"""Ingelogde apparaten.

Een inlogtoken is kort geldig en staat nergens; een vernieuwingstoken is lang geldig en
staat wél ergens. Dat is de hele afweging: het korte token hoeft niemand bij te houden, en
het lange moet je kunnen intrekken.

Drie dingen die hier met opzet zo zijn:

- **Het vernieuwingstoken staat als afdruk in de database.** Wie de database leest kan er
  niet mee inloggen. Het is 256 bits toeval, dus één ronde sha256 volstaat — een woordenboek
  helpt niemand tegen een getal dat niemand kan raden. Een wachtwoord is een ander verhaal
  en gaat daarom wél door pbkdf2.
- **Bij elk gebruik komt er een nieuw token en schuift het oude naar `previous_hash`.**
  Komt dat oude daarna alsnog langs, dan bestaat er een kopie — en gaat de sessie dicht.
  Dit is het enige moment waarop je diefstal van een token kunt zíen, dus dat pak je.
- **Een sessie hoort bij een aanmelding met een wachtwoord.** Een stem levert er geen op;
  zie `docs/server.md`. Een opname mag nooit een sessie van twee maanden worden.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.access import UserSession
from app.models.user import User

# 32 bytes toeval, url-safe. Niet korter: dit is het enige dat twee maanden geldig blijft.
TOKEN_BYTES = 32


class SessionError(Exception):
    """Het vernieuwen kan niet. De tekst is voor de gebruiker."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _afdruk(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _kort(tekst: str | None, lengte: int) -> str | None:
    if not tekst:
        return None
    tekst = tekst.strip()
    return tekst[:lengte] or None


async def create(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    device_name: str | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[UserSession, str]:
    """Maakt een sessie en geeft het vernieuwingstoken één keer terug."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    rij = UserSession(
        user_id=user.id,
        refresh_hash=_afdruk(token),
        device_name=_kort(device_name, 120),
        user_agent=_kort(user_agent, 300),
        ip_address=_kort(ip_address, 64),
        last_used_at=_now(),
        expires_at=_now() + timedelta(days=settings.refresh_token_days),
    )
    session.add(rij)
    await session.flush()
    return rij, token


async def _zoek(session: AsyncSession, token: str) -> tuple[UserSession | None, bool]:
    """Zoekt de sessie bij dit token. De tweede waarde zegt of het een oud token was."""
    afdruk = _afdruk(token)
    rij = await session.scalar(select(UserSession).where(UserSession.refresh_hash == afdruk))
    if rij is not None:
        return rij, False
    hergebruik = await session.scalar(
        select(UserSession).where(UserSession.previous_hash == afdruk)
    )
    return hergebruik, hergebruik is not None


async def rotate(
    session: AsyncSession, *, token: str, settings: Settings, ip_address: str | None = None
) -> tuple[UserSession, User, str]:
    """Wisselt een vernieuwingstoken om voor een nieuw stel."""
    rij, hergebruikt = await _zoek(session, token)
    if rij is None:
        raise SessionError("onbekend", "Deze sessie bestaat niet meer. Log opnieuw in.")

    if hergebruikt:
        # Het token is twee keer gebruikt. Er is dus een kopie in omloop, en welke van de
        # twee de echte gebruiker is, valt niet te zeggen. Allebei eruit dan maar.
        await _sluit(session, rij, "hergebruikt")
        raise SessionError(
            "hergebruikt",
            "Deze sessie is uit voorzorg gesloten: er werd een verlopen sleutel opnieuw "
            "gebruikt. Log opnieuw in.",
        )
    if rij.revoked_at is not None:
        raise SessionError("ingetrokken", "Deze sessie is ingetrokken. Log opnieuw in.")
    if rij.expires_at <= _now():
        await _sluit(session, rij, "verlopen")
        raise SessionError("verlopen", "Deze sessie is verlopen. Log opnieuw in.")

    gebruiker = await session.get(User, rij.user_id)
    if gebruiker is None or not gebruiker.active:
        await _sluit(session, rij, "ingetrokken")
        raise SessionError("geblokkeerd", "Dit account bestaat niet meer of is geblokkeerd.")

    nieuw = secrets.token_urlsafe(TOKEN_BYTES)
    rij.previous_hash = rij.refresh_hash
    rij.refresh_hash = _afdruk(nieuw)
    rij.last_used_at = _now()
    if ip_address:
        rij.ip_address = _kort(ip_address, 64)
    # De klok gaat opnieuw lopen: wie Ganz dagelijks gebruikt, hoeft nooit opnieuw in te
    # loggen; wie een apparaat twee maanden laat liggen wel.
    rij.expires_at = _now() + timedelta(days=settings.refresh_token_days)
    await session.flush()
    return rij, gebruiker, nieuw


async def _sluit(session: AsyncSession, rij: UserSession, reden: str) -> None:
    rij.revoked_at = _now()
    rij.revoked_reason = reden
    rij.refresh_hash = f"gesloten:{secrets.token_urlsafe(16)}"
    rij.previous_hash = None
    await session.flush()


async def revoke(session: AsyncSession, *, user_id: int, session_id: int) -> bool:
    """Trekt één apparaat in. Alleen je eigen sessies."""
    rij = await session.get(UserSession, session_id)
    if rij is None or rij.user_id != user_id or rij.revoked_at is not None:
        return False
    await _sluit(session, rij, "ingetrokken")
    return True


async def revoke_all(
    session: AsyncSession, *, user_id: int, behalve: int | None = None
) -> int:
    """Trekt alle apparaten in, eventueel op het huidige na."""
    rijen = (
        await session.scalars(
            select(UserSession).where(
                UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
            )
        )
    ).all()
    aantal = 0
    for rij in rijen:
        if behalve is not None and rij.id == behalve:
            continue
        await _sluit(session, rij, "ingetrokken")
        aantal += 1
    return aantal


async def list_for(session: AsyncSession, user_id: int) -> list[UserSession]:
    """De apparaten die nu toegang hebben, nieuwste eerst."""
    rijen = await session.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > _now(),
        )
        .order_by(UserSession.last_used_at.desc().nullslast(), UserSession.id.desc())
    )
    return list(rijen.all())


async def purge(session: AsyncSession, *, ouder_dan_dagen: int = 30) -> int:
    """Ruimt sessies op die al lang dicht of verlopen zijn.

    Niet meteen bij het sluiten: een dichte sessie is een spoor, en dat wil je nog even
    kunnen nalezen als er iets vreemds is gebeurd.
    """
    grens = _now() - timedelta(days=ouder_dan_dagen)
    rijen = (
        await session.scalars(
            select(UserSession).where(
                UserSession.expires_at < grens,
            )
        )
    ).all()
    for rij in rijen:
        await session.delete(rij)
    await session.flush()
    return len(rijen)
