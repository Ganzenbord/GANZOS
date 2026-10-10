"""De rem op het raden van wachtwoorden.

Dit was het enige gat dat overbleef na een ronde langs alle plekken waar een geheim wordt
gecontroleerd: de bevestigingslaag telt mispogingen over een tijdvenster, inloggen deed dat
niet. Onbeperkt wachtwoorden proberen is voor een computer geen werk.

De belangrijkste test is niet dat de rem werkt, maar dat hij niet verraadt of een account
bestaat — en dat hij niet te gebruiken is om de eigenaar buiten te sluiten.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.access import LoginAttempt
from app.models.activity import ActivityAction, ActivityLogEntry
from app.models.user import User
from app.services import login_guard

GOED = "geheim123"
FOUT = "dit-is-het-niet"


async def _mis(client: AsyncClient, email: str, *, keer: int = 1):
    antwoord = None
    for _ in range(keer):
        antwoord = await client.post(
            "/auth/login", json={"email": email, "password": FOUT, "device_name": "test"}
        )
    return antwoord


async def test_na_vijf_keer_mis_gaat_de_deur_dicht(client: AsyncClient, owner: User) -> None:
    for _ in range(5):
        antwoord = await _mis(client, owner.email)
        assert antwoord.status_code == 401

    zesde = await _mis(client, owner.email)
    assert zesde.status_code == 429
    assert "Retry-After" in zesde.headers
    assert "minuten" in zesde.json()["detail"]


async def test_het_goede_wachtwoord_werkt_ook_niet_meer_zolang_de_rem_staat(
    client: AsyncClient, owner: User
) -> None:
    """Anders is de rem geen rem: wie het wachtwoord raadt, komt er alsnog in."""
    await _mis(client, owner.email, keer=5)
    antwoord = await client.post(
        "/auth/login", json={"email": owner.email, "password": GOED, "device_name": "test"}
    )
    assert antwoord.status_code == 429


async def test_de_rem_verraadt_niet_of_een_account_bestaat(client: AsyncClient) -> None:
    """Een onbekend adres moet exact hetzelfde gedrag geven als een bekend adres. Zou de rem
    alleen bij bestaande accounts aangaan, dan is hij zelf een manier om te ontdekken welke
    adressen hier een account hebben."""
    onbekend = "bestaat.niet@example.com"
    for _ in range(5):
        assert (await _mis(client, onbekend)).status_code == 401
    geblokkeerd = await _mis(client, onbekend)
    assert geblokkeerd.status_code == 429


async def test_een_geslaagde_inlog_zet_de_teller_terug(
    client: AsyncClient, owner: User, session
) -> None:
    await _mis(client, owner.email, keer=4)
    goed = await client.post(
        "/auth/login", json={"email": owner.email, "password": GOED, "device_name": "test"}
    )
    assert goed.status_code == 200

    # En daarna mag er weer vijf keer mis getikt worden zonder dat de deur dichtgaat.
    for _ in range(5):
        assert (await _mis(client, owner.email)).status_code == 401


async def test_de_strenge_grens_geldt_per_adres_en_ip_samen(session) -> None:
    """Zou vijf keer mis een account dichtzetten ongeacht de bron, dan kan iedereen die jouw
    e-mailadres kent jou een kwartier buitensluiten. Daarom telt de strenge grens het paar."""
    settings = get_settings()
    for _ in range(settings.login_max_failures_per_pair):
        await login_guard.record_failure(
            session, email="stef@example.com", ip="10.0.0.99", settings=settings
        )
    await session.commit()

    # Vanaf het IP van de aanvaller: dicht.
    aanvaller = await login_guard.check(
        session, email="stef@example.com", ip="10.0.0.99", settings=settings
    )
    assert aanvaller.allowed is False

    # Vanaf het eigen apparaat van Stef: open.
    eigenaar = await login_guard.check(
        session, email="stef@example.com", ip="192.168.1.5", settings=settings
    )
    assert eigenaar.allowed is True


async def test_een_verdeelde_aanval_wordt_alsnog_gestopt(session) -> None:
    """Veel bronnen, één account: dan loopt geen enkel paar vol, maar de ruime grens per
    adres wel."""
    settings = get_settings()
    for n in range(settings.login_max_failures_per_account):
        await login_guard.record_failure(
            session, email="stef@example.com", ip=f"10.1.{n // 256}.{n % 256}", settings=settings
        )
    await session.commit()

    oordeel = await login_guard.check(
        session, email="stef@example.com", ip="10.9.9.9", settings=settings
    )
    assert oordeel.allowed is False
    assert oordeel.reason == "account"


async def test_een_bron_die_adressen_afgaat_loopt_tegen_de_ip_grens(session) -> None:
    settings = get_settings()
    for n in range(settings.login_max_failures_per_ip):
        await login_guard.record_failure(
            session, email=f"iemand{n}@example.com", ip="10.0.0.7", settings=settings
        )
    await session.commit()

    oordeel = await login_guard.check(
        session, email="weer.een.ander@example.com", ip="10.0.0.7", settings=settings
    )
    assert oordeel.allowed is False
    assert oordeel.reason == "ip"


async def test_het_adres_staat_niet_in_de_database(
    client: AsyncClient, owner: User, session
) -> None:
    """Wie aan het proberen is, vult adressen in van mensen die hier geen gebruiker zijn.
    Die adressen bewaren zou betekenen dat Ganz gegevens verzamelt over mensen die er niets
    te zoeken hebben."""
    await _mis(client, "iemand.anders@example.com")

    rijen = (await session.execute(select(LoginAttempt))).scalars().all()
    assert len(rijen) == 1
    assert "iemand.anders" not in rijen[0].email_hash
    assert "@" not in rijen[0].email_hash
    assert len(rijen[0].email_hash) == 64


async def test_het_logboek_houdt_een_spoor_zonder_het_adres(
    client: AsyncClient, owner: User, session
) -> None:
    """Dit is het spoor waar een beveiligingscontrole straks naar kijkt. Losse missers horen
    erbij, een reeks niet."""
    await _mis(client, owner.email, keer=6)

    rijen = (
        (await session.execute(select(ActivityLogEntry).order_by(ActivityLogEntry.id)))
        .scalars()
        .all()
    )
    acties = [rij.action for rij in rijen]
    assert ActivityAction.USER_LOGIN_FAILED.value in acties
    assert ActivityAction.USER_LOGIN_BLOCKED.value in acties
    for rij in rijen:
        assert owner.email not in (rij.message or "")
        assert owner.email not in str(rij.context or {})


async def test_oude_pogingen_worden_opgeruimd(session) -> None:
    """Deze rijen zijn bedoeld om te verdwijnen: een langer bewaarde lijst IP-adressen is
    een archief en geen rem."""
    settings = get_settings()
    session.add(
        LoginAttempt(
            email_hash=login_guard.email_hash("oud@example.com", settings),
            ip_address="10.0.0.1",
            created_at=datetime.now(timezone.utc) - timedelta(hours=48),
        )
    )
    await login_guard.record_failure(
        session, email="nieuw@example.com", ip="10.0.0.2", settings=settings
    )
    await session.commit()

    weg = await login_guard.prune_attempts(session)
    await session.commit()

    assert weg == 1
    over = (await session.execute(select(LoginAttempt))).scalars().all()
    assert len(over) == 1
    assert over[0].email_hash == login_guard.email_hash("nieuw@example.com", settings)


async def test_een_afdruk_is_niet_terug_te_rekenen_zonder_het_servergeheim() -> None:
    """Zonder het geheim ervoor is een lijst van adressen zo nagerekend — dan had je het
    adres net zo goed kunnen bewaren."""
    settings = get_settings()
    afdruk = login_guard.email_hash("stef@example.com", settings)

    import hashlib

    naakt = hashlib.sha256(b"stef@example.com").hexdigest()
    assert afdruk != naakt
    # En hetzelfde adres geeft wél steeds dezelfde afdruk, anders valt er niets te tellen.
    assert afdruk == login_guard.email_hash("STEF@example.com ", settings)
