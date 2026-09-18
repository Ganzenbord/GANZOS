"""De tweede bevestiging voor gevoelige handelingen.

Waarom dit meer is dan een wachtwoordcontrole: een stem is na te maken en een gestolen
inlogtoken kan meekijken. Voor alles wat geld kost, naar buiten gaat of iets vernietigt,
moet er nog één keer bewust "ja" gezegd worden — met iets wat niet in dat token zit.

Elke bevestiging staat als rij in `confirmation_requests`. Zo is achteraf te zien dát er
bevestigd is, waarvoor, en hoe vaak het misging. Het token dat de client meekrijgt verwijst
naar die rij; is die verlopen of al gebruikt, dan telt het token niet meer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import verify_password
from app.models.confirmation import (
    MAX_ATTEMPTS,
    ConfirmationMethod,
    ConfirmationRequest,
    ConfirmationStatus,
)
from app.models.user import User


class ConfirmationError(Exception):
    """Gaat mis op een manier die de gebruiker moet weten. `code` is voor de app."""

    def __init__(self, code: str, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def recent_failures(
    session: AsyncSession, *, user_id: int, minutes: int
) -> int:
    """Hoeveel mispogingen deze gebruiker de afgelopen minuten bij elkaar heeft."""
    grens = _now() - timedelta(minutes=minutes)
    resultaat = await session.execute(
        select(func.coalesce(func.sum(ConfirmationRequest.attempts), 0)).where(
            ConfirmationRequest.user_id == user_id,
            ConfirmationRequest.created_at >= grens,
        )
    )
    return int(resultaat.scalar_one())


async def create(
    session: AsyncSession,
    *,
    user: User,
    method: ConfirmationMethod,
    settings: Settings,
    permission_key: str | None = None,
    origin: str | None = None,
    origin_confidence: float | None = None,
) -> ConfirmationRequest:
    # Elke poging is een nieuw verzoek, dus de grens per verzoek (MAX_ATTEMPTS) houdt in zijn
    # eentje niemand tegen: wie mis tikt begint gewoon opnieuw. Daarom telt hier het totaal
    # over een tijdvenster mee. Zonder dit is een pincode van vier cijfers in tienduizend
    # verzoeken te raden, en dat is voor een computer geen werk.
    mis = await recent_failures(
        session, user_id=user.id, minutes=settings.confirmation_lockout_minutes
    )
    if mis >= settings.confirmation_max_failures:
        raise ConfirmationError(
            "te_vaak_mis",
            f"Te vaak mis. Probeer het over {settings.confirmation_lockout_minutes} "
            "minuten opnieuw.",
            status_code=429,
        )

    verzoek = ConfirmationRequest(
        user_id=user.id,
        permission_key=permission_key,
        method=method.value,
        origin=origin,
        origin_confidence=origin_confidence,
        expires_at=_now() + timedelta(minutes=settings.confirmation_token_minutes),
    )
    session.add(verzoek)
    await session.flush()
    return verzoek


async def verify(
    session: AsyncSession,
    *,
    verzoek: ConfirmationRequest,
    user: User,
    secret: str,
    settings: Settings,
) -> ConfirmationRequest:
    """Controleer wachtwoord of pincode en zet de bevestiging op 'confirmed'."""
    if verzoek.status != ConfirmationStatus.PENDING.value:
        raise ConfirmationError(
            "bevestiging_niet_open", "Deze bevestiging is al afgehandeld of vervallen."
        )
    if verzoek.expires_at <= _now():
        verzoek.status = ConfirmationStatus.FAILED.value
        raise ConfirmationError("bevestiging_verlopen", "Deze bevestiging is verlopen.")
    if verzoek.attempts >= MAX_ATTEMPTS:
        verzoek.status = ConfirmationStatus.FAILED.value
        raise ConfirmationError(
            "te_vaak_mis", "Te vaak mis. Begin opnieuw.", status_code=429
        )

    # Een aanmelding die alleen op een stem berust, is te zwak voor dit soort handelingen.
    # De prompt is daar stellig over, en terecht: een opname van je stem is zo gemaakt.
    if verzoek.origin == "voice" and not _stem_sterk_genoeg(verzoek, settings):
        raise ConfirmationError(
            "stem_te_zwak",
            "De stemherkenning was hiervoor niet zeker genoeg. Log in met je wachtwoord.",
        )

    afdruk = user.pin_hash if verzoek.method == ConfirmationMethod.PIN.value else user.password_hash
    if verzoek.method == ConfirmationMethod.PIN.value and not user.pin_hash:
        raise ConfirmationError(
            "pin_niet_ingesteld",
            "Er is nog geen pincode ingesteld. Dat doe je bij Instellingen.",
        )

    if not afdruk or not verify_password(secret, afdruk):
        verzoek.attempts += 1
        resterend = MAX_ATTEMPTS - verzoek.attempts
        if resterend <= 0:
            verzoek.status = ConfirmationStatus.FAILED.value
        is_pin = verzoek.method == ConfirmationMethod.PIN.value
        woord = "Die pincode" if is_pin else "Dat wachtwoord"
        raise ConfirmationError(
            "onjuist",
            f"{woord} klopt niet. Nog {max(resterend, 0)} poging(en) over.",
            status_code=401,
        )

    verzoek.status = ConfirmationStatus.CONFIRMED.value
    verzoek.confirmed_at = _now()
    return verzoek


async def consume(
    session: AsyncSession, *, verzoek_id: int, user_id: int, permission_key: str | None
) -> ConfirmationRequest:
    """Gebruik een bevestiging op bij een gevoelige handeling.

    Eén bevestiging dekt één handeling af. Daarna gaat hij op `used`, zodat hetzelfde token
    niet een tweede keer langs de kassa kan.
    """
    verzoek = await session.get(ConfirmationRequest, verzoek_id)
    if verzoek is None or verzoek.user_id != user_id:
        raise ConfirmationError("bevestiging_onbekend", "Deze bevestiging bestaat niet.")
    if verzoek.status != ConfirmationStatus.CONFIRMED.value:
        raise ConfirmationError(
            "bevestiging_niet_gegeven", "Deze bevestiging is niet (meer) geldig."
        )
    if verzoek.expires_at <= _now():
        verzoek.status = ConfirmationStatus.FAILED.value
        raise ConfirmationError("bevestiging_verlopen", "Deze bevestiging is verlopen.")
    if verzoek.permission_key and verzoek.permission_key != permission_key:
        # Bevestigen voor het weer en dan een upload doen: dat hoort niet te kunnen.
        raise ConfirmationError(
            "bevestiging_ander_recht",
            f"Deze bevestiging was voor '{verzoek.permission_key}', niet voor "
            f"'{permission_key}'.",
        )

    verzoek.status = ConfirmationStatus.USED.value
    return verzoek


def _stem_sterk_genoeg(verzoek: ConfirmationRequest, settings: Settings) -> bool:
    """Zonder gelijkenis is het niet sterk: dan weten we het niet, en dan is het nee."""
    if verzoek.origin_confidence is None:
        return False
    return verzoek.origin_confidence >= settings.voice_strong_threshold
