"""Stemmen inschrijven en herkennen."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_confirmation, require_permission
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.security import create_token
from app.integrations.voice import SpeakerEncoder, SpeakerEncoderUnavailableError
from app.models.activity import ActivityAction
from app.models.user import User
from app.models.voice import VoiceProfile
from app.schemas.voice import EnrollResponse, IdentifyResponse, VoiceProfileOut
from app.services import voice_service
from app.services.activity_service import log_activity
from app.utils.audio import AudioClip, AudioError, load_wav
from app.utils.embeddings import EmbeddingError

logger = logging.getLogger("ganz.voice")

# Starlette hernoemde HTTP_422_UNPROCESSABLE_ENTITY naar ..._CONTENT. Het nummer blijft
# hetzelfde, dus dat gebruiken we: zo werkt dit op oude en nieuwe versies zonder waarschuwing.
HTTP_422 = 422

router = APIRouter(prefix="/voice", tags=["voice"])

AudioUpload = Annotated[UploadFile, File(description="Een WAV-opname van de stem")]


def get_encoder(request: Request) -> SpeakerEncoder:
    """Het herkenmodel staat klaar in app.state, net als de database."""
    return request.app.state.speaker_encoder


EncoderDep = Annotated[SpeakerEncoder, Depends(get_encoder)]


async def read_clip(audio: UploadFile, settings: Settings) -> AudioClip:
    data = await audio.read()
    if len(data) > settings.voice_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"De opname is groter dan {settings.voice_max_upload_bytes // (1024 * 1024)} MB.",
        )
    try:
        return load_wav(
            data, min_seconds=settings.voice_min_seconds, max_seconds=settings.voice_max_seconds
        )
    except AudioError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc


def _model_niet_beschikbaar(exc: SpeakerEncoderUnavailableError) -> HTTPException:
    logger.warning("Herkenmodel niet beschikbaar: %s", exc)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


async def guard_enrollment(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Wie mag er iemand inschrijven?

    Normaal alleen wie het recht `voice.enroll` heeft — inschrijven is immers hoe je toegang
    uitdeelt. Maar zolang er nog geen enkele stem bekend is, kan niemand herkend worden en
    zou niemand ooit kunnen beginnen. Daarom staat de allereerste inschrijving open. Zet
    GANZ_VOICE_ENROLLMENT_OPEN_WHEN_EMPTY op false zodra iedereen erin staat, dan valt dat
    gat dicht.

    Let op: gooi je later alle stemprofielen weg terwijl die instelling nog op true staat,
    dan gaat de deur weer open.
    """
    if settings.voice_enrollment_open_when_empty and not await voice_service.has_any_enrollment(
        session
    ):
        logger.warning(
            "Eerste inschrijving zonder controle: er is nog geen enkele stem bekend. Zet "
            "GANZ_VOICE_ENROLLMENT_OPEN_WHEN_EMPTY op false zodra dat wel zo is."
        )
        return None

    # Pas hier de gewone controle, zodat de bootstrap er niet op stukloopt. Let op dat
    # hier ook de tweede bevestiging langskomt: `voice.enroll` staat als gevoelig in het
    # register, en inschrijven ís de handeling waarmee je toegang uitdeelt. Alleen het
    # recht controleren zou precies dat gat openlaten.
    gebruiker = await get_current_user(
        request=request, credentials=_bearer(request), session=session
    )
    gecontroleerd = await require_permission("voice.enroll")(user=gebruiker)
    return await require_confirmation("voice.enroll")(
        request=request,
        user=gecontroleerd,
        session=session,
        x_ganz_confirmation=request.headers.get("X-Ganz-Confirmation"),
    )


def _bearer(request: Request) -> HTTPAuthorizationCredentials | None:
    """De Authorization-header met de hand uitlezen.

    Normaal doet FastAPI dat, maar deze controle draait pas ná de bootstrap-vraag en kan
    dus geen gewone dependency zijn.
    """
    kop = request.headers.get("Authorization", "")
    schema, _, waarde = kop.partition(" ")
    if schema.lower() != "bearer" or not waarde:
        return None
    return HTTPAuthorizationCredentials(scheme=schema, credentials=waarde)


@router.post("/enroll", response_model=EnrollResponse, status_code=status.HTTP_201_CREATED)
async def enroll(
    audio: AudioUpload,
    user_id: Annotated[int, Form(description="Wiens stem dit is")],
    _toegang: Annotated[User | None, Depends(guard_enrollment)],
    label: Annotated[str | None, Form(description="Naam van deze opname")] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    encoder: SpeakerEncoder = Depends(get_encoder),
) -> EnrollResponse:
    clip = await read_clip(audio, settings)
    try:
        profiel = await voice_service.enroll(
            session, user_id=user_id, clip=clip, encoder=encoder, label=label
        )
    except voice_service.UnknownUserError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Er bestaat geen gebruiker met id {user_id}. Maak hem eerst aan met "
            "scripts/create_user.py.",
        ) from exc
    except SpeakerEncoderUnavailableError as exc:
        raise _model_niet_beschikbaar(exc) from exc
    except EmbeddingError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    await log_activity(
        session,
        action=ActivityAction.VOICE_ENROLLED,
        user_id=user_id,
        message=f"Stem ingeschreven als '{profiel.label}'.",
    )
    await session.commit()
    return EnrollResponse(
        profile_id=profiel.id,
        profile=VoiceProfileOut.model_validate(profiel, from_attributes=True),
        message=f"Opname van {clip.seconds:.1f} seconde opgeslagen als '{profiel.label}'.",
    )


@router.post("/identify", response_model=IdentifyResponse)
async def identify(
    audio: AudioUpload,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    encoder: SpeakerEncoder = Depends(get_encoder),
) -> IdentifyResponse:
    # Dit endpoint kan per definitie niet achter een rechtencontrole staan: het ís de controle.
    clip = await read_clip(audio, settings)
    try:
        uitslag, gebruiker = await voice_service.identify(
            session, clip=clip, encoder=encoder, threshold=settings.voice_match_threshold
        )
    except SpeakerEncoderUnavailableError as exc:
        raise _model_niet_beschikbaar(exc) from exc
    except EmbeddingError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    if gebruiker is None:
        return IdentifyResponse(
            result="unknown",
            confidence=round(uitslag.confidence, 4),
            threshold=uitslag.threshold,
            runner_up_confidence=_afgerond(uitslag.runner_up_confidence),
            message="Deze stem ken ik niet.",
        )

    sterk = uitslag.confidence >= settings.voice_strong_threshold
    await log_activity(
        session,
        action=ActivityAction.VOICE_IDENTIFIED,
        user_id=gebruiker.id,
        message=f"{gebruiker.display_name} herkend aan zijn stem.",
        context={"confidence": round(uitslag.confidence, 4), "strong": sterk},
    )
    await session.commit()

    if gebruiker.tier is None:
        bericht = f"Hallo {gebruiker.display_name}. Je bent bekend, maar hebt geen toegang."
    elif sterk:
        bericht = f"Hallo {gebruiker.display_name}."
    else:
        bericht = (
            f"Hallo {gebruiker.display_name}. Ik herken je, maar niet zeker genoeg voor "
            "gevoelige dingen — daarvoor is je wachtwoord nodig."
        )

    return IdentifyResponse(
        result="identified",
        user_id=gebruiker.id,
        display_name=gebruiker.display_name,
        tier=gebruiker.tier,
        confidence=round(uitslag.confidence, 4),
        threshold=uitslag.threshold,
        runner_up_confidence=_afgerond(uitslag.runner_up_confidence),
        strong=sterk,
        access_token=create_token(
            gebruiker.id, "access", origin="voice", confidence=round(uitslag.confidence, 4)
        ),
        expires_in_minutes=settings.access_token_minutes,
        message=bericht,
    )


@router.get("/profiles", response_model=list[VoiceProfileOut])
async def list_profiles(
    _user: User = Depends(require_permission("voice.read")),
    session: AsyncSession = Depends(get_session),
) -> list[VoiceProfileOut]:
    profielen = await session.scalars(select(VoiceProfile).order_by(VoiceProfile.created_at))
    return [VoiceProfileOut.model_validate(p, from_attributes=True) for p in profielen]


def _afgerond(waarde: float | None) -> float | None:
    return None if waarde is None else round(waarde, 4)
