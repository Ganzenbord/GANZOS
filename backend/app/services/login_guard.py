"""De rem op het raden van wachtwoorden.

De bevestigingslaag had dit al goed geregeld (`confirmation_service.recent_failures`), met
precies de valkuil erin benoemd: een grens per poging houdt niemand tegen, want elke poging
is een nieuw verzoek. **Bij inloggen stond die rem er niet.** Onbeperkt wachtwoorden
proberen is voor een computer geen werk, en wat erachter zit zijn de sleutels van twintig
kanalen, straks de mail en misschien de telefoon.

Drie grenzen in plaats van één, en dat heeft een reden:

| Grens | Waarom niet alleen deze |
| --- | --- |
| per adres **én** IP, streng | houdt de gewone aanval tegen: één bron die doorprobeert |
| per IP, ruimer | houdt één bron tegen die veel adressen langsgaat |
| per adres, ruim | houdt een verdeelde aanval tegen: veel bronnen, één account |

Waarom de strenge grens per *paar* geldt en niet per adres: zou vijf keer mis een account
voor een kwartier dichtzetten, dan kan iedereen die jouw e-mailadres kent jou buitensluiten
wanneer hij wil. De ruime grens per adres vangt het verdeelde geval alsnog, zonder dat een
kwartier buitensluiten gratis is.

Wat er nooit uit deze laag komt: of een adres bestaat. De melding is dezelfde voor een
onbekend adres en een fout wachtwoord, en dat geldt ook voor de melding dat je te vaak mis
hebt getikt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.access import LoginAttempt

# Hoe lang mislukte pogingen blijven staan voordat ze worden opgeruimd. Veel langer dan het
# tijdvenster waarin ze meetellen, zodat er iets te zien is als je wil weten of iemand aan
# het proberen is geweest — maar geen maanden, want dan is het een archief van IP-adressen.
RETENTION_HOURS = 24


@dataclass(frozen=True, slots=True)
class Verdict:
    """Mag deze poging door, en zo niet: hoe lang niet.

    `reason` is voor het logboek en niet voor de gebruiker. Die krijgt één en dezelfde
    melding, hoe hij ook geblokkeerd is.
    """

    allowed: bool
    retry_after_minutes: int = 0
    reason: str = ""


def email_hash(email: str, settings: Settings) -> str:
    """De afdruk waaronder een poging wordt geteld.

    Met het geheim van de server ervoor: anders is een lijst van adressen zo nagerekend, en
    dan had je het adres net zo goed kunnen bewaren.
    """
    basis = f"{settings.secret_key}:{email.strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


async def _tel(
    session: AsyncSession,
    *,
    sinds: datetime,
    afdruk: str | None = None,
    ip: str | None = None,
) -> int:
    vraag = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.created_at >= sinds
    )
    if afdruk is not None:
        vraag = vraag.where(LoginAttempt.email_hash == afdruk)
    if ip is not None:
        vraag = vraag.where(LoginAttempt.ip_address == ip)
    return int(await session.scalar(vraag) or 0)


async def check(
    session: AsyncSession,
    *,
    email: str,
    ip: str | None,
    settings: Settings,
) -> Verdict:
    """Mag er nog een poging gedaan worden vanaf dit adres en dit IP?"""
    minuten = settings.login_lockout_minutes
    sinds = datetime.now(timezone.utc) - timedelta(minutes=minuten)
    afdruk = email_hash(email, settings)

    if ip is not None:
        paar = await _tel(session, sinds=sinds, afdruk=afdruk, ip=ip)
        if paar >= settings.login_max_failures_per_pair:
            return Verdict(False, minuten, "paar")

        per_ip = await _tel(session, sinds=sinds, ip=ip)
        if per_ip >= settings.login_max_failures_per_ip:
            return Verdict(False, minuten, "ip")

    per_adres = await _tel(session, sinds=sinds, afdruk=afdruk)
    if per_adres >= settings.login_max_failures_per_account:
        return Verdict(False, minuten, "account")

    return Verdict(True)


async def record_failure(
    session: AsyncSession, *, email: str, ip: str | None, settings: Settings
) -> None:
    session.add(LoginAttempt(email_hash=email_hash(email, settings), ip_address=ip))


async def clear(
    session: AsyncSession, *, email: str, ip: str | None, settings: Settings
) -> None:
    """Na een geslaagde inlog: de teller van dit adres vanaf dit IP op nul.

    Alleen van dit IP, niet van het hele adres. Zou een geslaagde inlog van de eigenaar ook
    de pogingen van een onbekende bron wissen, dan kan iemand blijven proberen zolang de
    eigenaar af en toe zelf inlogt.
    """
    vraag = delete(LoginAttempt).where(
        LoginAttempt.email_hash == email_hash(email, settings)
    )
    if ip is not None:
        vraag = vraag.where(LoginAttempt.ip_address == ip)
    await session.execute(vraag)


async def prune_attempts(session: AsyncSession, *, hours: int = RETENTION_HOURS) -> int:
    """Oude pogingen weggooien. Hoort in de planner, niet in het inlogpad."""
    grens = datetime.now(timezone.utc) - timedelta(hours=hours)
    uitkomst = await session.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < grens)
    )
    return int(uitkomst.rowcount or 0)
