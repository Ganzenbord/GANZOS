"""Stemmen inschrijven en herkennen.

De endpoints blijven hierdoor kort: zij gaan over HTTP, dit gaat over stemmen. De
herkenner komt als `SpeakerEncoder` binnen, zodat er een namaakversie in kan bij de tests
en er later een ander model naast kan zonder dat hier iets verandert.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.voice import SpeakerEncoder
from app.models.user import User
from app.models.voice import VoiceProfile
from app.utils.audio import AudioClip
from app.utils.embeddings import Candidate, MatchResult, best_match


class UnknownUserError(LookupError):
    """Er wordt ingeschreven op een gebruiker die niet bestaat."""


async def has_any_enrollment(session: AsyncSession) -> bool:
    """Is er al iemand ingeschreven? Bepaalt of de eerste inschrijving nog open mag staan."""
    aantal = await session.scalar(
        select(func.count()).select_from(VoiceProfile).where(VoiceProfile.embedding.is_not(None))
    )
    return bool(aantal)


async def load_candidates(session: AsyncSession) -> list[Candidate]:
    """Alle stemmen waarmee vergeleken kan worden.

    Profielen zonder afdruk, uitgezette profielen en mensen die op non-actief staan doen
    niet mee: die horen niet herkend te worden. Iemand zónder tier doet wél mee — hij is
    bekend, hij mag alleen niets. Dat verschil moet Ganz kunnen uitspreken.
    """
    rijen = await session.execute(
        select(VoiceProfile.id, VoiceProfile.user_id, VoiceProfile.embedding)
        .join(User, User.id == VoiceProfile.user_id)
        .where(
            VoiceProfile.embedding.is_not(None),
            VoiceProfile.active.is_(True),
            User.active.is_(True),
        )
    )
    return [
        Candidate(profile_id=profile_id, user_id=user_id, embedding=embedding)
        for profile_id, user_id, embedding in rijen
        if embedding
    ]


async def enroll(
    session: AsyncSession,
    *,
    user_id: int,
    clip: AudioClip,
    encoder: SpeakerEncoder,
    label: str | None = None,
) -> VoiceProfile:
    """Maak een afdruk van dit fragment en bewaar hem bij deze gebruiker."""
    gebruiker = await session.get(User, user_id)
    if gebruiker is None:
        raise UnknownUserError(str(user_id))

    afdruk = await encoder.embed(clip)

    if not label:
        eerder = await session.scalar(
            select(func.count()).select_from(VoiceProfile).where(VoiceProfile.user_id == user_id)
        )
        label = f"Opname {int(eerder or 0) + 1}"

    profiel = VoiceProfile(
        user_id=user_id,
        label=label,
        embedding=afdruk,
        embedding_model=encoder.model_name,
        embedding_dim=len(afdruk),
        sample_seconds=round(clip.seconds, 2),
        enrolled_at=datetime.now(timezone.utc),
    )
    session.add(profiel)
    await session.flush()
    return profiel


async def identify(
    session: AsyncSession,
    *,
    clip: AudioClip,
    encoder: SpeakerEncoder,
    threshold: float,
) -> tuple[MatchResult, User | None]:
    """Wie is dit? Geeft de uitslag terug, plus de gebruiker als die herkend is."""
    afdruk = await encoder.embed(clip)
    uitslag = best_match(afdruk, await load_candidates(session), threshold=threshold)
    if not uitslag.matched or uitslag.user_id is None:
        return uitslag, None
    return uitslag, await session.get(User, uitslag.user_id)
