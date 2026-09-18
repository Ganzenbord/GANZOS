"""Inloggen per apparaat: vernieuwen, intrekken, en diefstal van een token zien.

Wat hier bewezen wordt is het verschil tussen "het token is verlopen" en "iemand anders
heeft het". Het eerste is dagelijkse kost, het tweede hoort de sessie te sluiten.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import decode_token
from app.models.access import UserSession
from app.models.activity import ActivityAction, ActivityLogEntry
from app.models.user import User
from app.services import session_service
from tests.conftest import auth_headers

WACHTWOORD = "geheim123"


async def inloggen(client: AsyncClient, user: User, apparaat: str = "Telefoon") -> dict:
    antwoord = await client.post(
        "/auth/login",
        json={"email": user.email, "password": WACHTWOORD, "device_name": apparaat},
    )
    assert antwoord.status_code == 200, antwoord.text
    return antwoord.json()


async def test_inloggen_levert_een_sessie_op(client: AsyncClient, owner: User, session) -> None:
    lichaam = await inloggen(client, owner, "Laptop van Stef")

    assert lichaam["refresh_token"]
    assert lichaam["session_id"]
    # Het inlogtoken weet bij welke sessie het hoort; zonder dat weet "log dit apparaat uit"
    # niet welk apparaat dat is.
    assert decode_token(lichaam["access_token"], "access")["sid"] == lichaam["session_id"]

    rij = await session.get(UserSession, lichaam["session_id"])
    assert rij.device_name == "Laptop van Stef"
    # Alleen de afdruk, nooit het token zelf: wie de database leest kan er niet mee inloggen.
    assert lichaam["refresh_token"] not in rij.refresh_hash
    assert len(rij.refresh_hash) == 64


async def test_vernieuwen_geeft_elke_keer_een_nieuw_token(
    client: AsyncClient, owner: User
) -> None:
    eerste = await inloggen(client, owner)

    tweede = await client.post("/auth/refresh", json={"refresh_token": eerste["refresh_token"]})

    assert tweede.status_code == 200
    body = tweede.json()
    assert body["refresh_token"] != eerste["refresh_token"]
    assert body["session_id"] == eerste["session_id"]
    # Het nieuwe inlogtoken werkt meteen.
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


async def test_een_token_dat_al_gebruikt_is_sluit_de_sessie(
    client: AsyncClient, owner: User, session
) -> None:
    """Dit is het enige moment waarop je diefstal van een token kunt zien.

    Twee partijen met hetzelfde token: wie de echte is valt niet te zeggen, dus gaan ze er
    allebei uit."""
    eerste = await inloggen(client, owner)
    tweede = await client.post("/auth/refresh", json={"refresh_token": eerste["refresh_token"]})
    assert tweede.status_code == 200

    opnieuw = await client.post("/auth/refresh", json={"refresh_token": eerste["refresh_token"]})

    assert opnieuw.status_code == 401
    assert "voorzorg" in opnieuw.json()["detail"]

    # En het nieuwe token doet het nu ook niet meer: de hele sessie is dicht.
    daarna = await client.post(
        "/auth/refresh", json={"refresh_token": tweede.json()["refresh_token"]}
    )
    assert daarna.status_code == 401

    rij = await session.get(UserSession, eerste["session_id"])
    await session.refresh(rij)
    assert rij.revoked_reason == "hergebruikt"

    acties = (await session.execute(select(ActivityLogEntry.action))).scalars().all()
    assert ActivityAction.SESSION_REUSE_DETECTED in acties


async def test_een_verzonnen_token_werkt_niet(client: AsyncClient) -> None:
    antwoord = await client.post("/auth/refresh", json={"refresh_token": "zelf-verzonnen"})

    assert antwoord.status_code == 401
    assert "opnieuw in" in antwoord.json()["detail"]


async def test_een_verlopen_sessie_wordt_geweigerd(
    client: AsyncClient, owner: User, session
) -> None:
    lichaam = await inloggen(client, owner)
    rij = await session.get(UserSession, lichaam["session_id"])
    rij.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()

    antwoord = await client.post("/auth/refresh", json={"refresh_token": lichaam["refresh_token"]})

    assert antwoord.status_code == 401
    assert "verlopen" in antwoord.json()["detail"]


async def test_de_lijst_met_apparaten_bevat_geen_tokens(
    client: AsyncClient, owner: User
) -> None:
    eerste = await inloggen(client, owner, "Telefoon")
    await inloggen(client, owner, "Laptop")

    lijst = await client.get(
        "/auth/sessions", headers={"Authorization": f"Bearer {eerste['access_token']}"}
    )

    assert lijst.status_code == 200
    rijen = lijst.json()
    namen = {rij["device_name"] for rij in rijen}
    assert namen == {"Telefoon", "Laptop"}
    # Precies één is het apparaat waar je nu op kijkt.
    assert [rij["current"] for rij in rijen].count(True) == 1
    assert eerste["refresh_token"] not in str(rijen)
    assert "refresh_hash" not in str(rijen)


async def test_een_apparaat_eruit_gooien_laat_de_rest_staan(
    client: AsyncClient, owner: User
) -> None:
    telefoon = await inloggen(client, owner, "Telefoon")
    laptop = await inloggen(client, owner, "Laptop")

    weg = await client.delete(
        f"/auth/sessions/{telefoon['session_id']}",
        headers={"Authorization": f"Bearer {laptop['access_token']}"},
    )

    assert weg.status_code == 200
    assert weg.json()["revoked"] == 1
    # De telefoon kan niet meer vernieuwen...
    assert (
        await client.post("/auth/refresh", json={"refresh_token": telefoon["refresh_token"]})
    ).status_code == 401
    # ...en de laptop wel.
    assert (
        await client.post("/auth/refresh", json={"refresh_token": laptop["refresh_token"]})
    ).status_code == 200


async def test_je_kunt_het_apparaat_van_een_ander_niet_uitloggen(
    client: AsyncClient, owner: User, trusted: User
) -> None:
    van_de_ander = await inloggen(client, trusted, "Telefoon van Bram")

    antwoord = await client.delete(
        f"/auth/sessions/{van_de_ander['session_id']}", headers=auth_headers(owner)
    )

    # Geen 403 met "die is niet van jou": dat verklapt dat de sessie bestaat.
    assert antwoord.status_code == 200
    assert antwoord.json()["revoked"] == 0
    assert (
        await client.post("/auth/refresh", json={"refresh_token": van_de_ander["refresh_token"]})
    ).status_code == 200


async def test_overal_uitloggen_gooit_alles_eruit(client: AsyncClient, owner: User) -> None:
    telefoon = await inloggen(client, owner, "Telefoon")
    laptop = await inloggen(client, owner, "Laptop")

    antwoord = await client.post(
        "/auth/logout?alles=true",
        headers={"Authorization": f"Bearer {laptop['access_token']}"},
    )

    assert antwoord.status_code == 200
    assert antwoord.json()["revoked"] == 2
    for token in (telefoon["refresh_token"], laptop["refresh_token"]):
        assert (await client.post("/auth/refresh", json={"refresh_token": token})).status_code == 401


async def test_een_geblokkeerd_account_kan_niet_meer_vernieuwen(
    client: AsyncClient, owner: User, session
) -> None:
    """Uitzetten moet meteen werken, ook op een apparaat dat al ingelogd was."""
    lichaam = await inloggen(client, owner)
    owner.active = False
    await session.commit()

    antwoord = await client.post("/auth/refresh", json={"refresh_token": lichaam["refresh_token"]})

    assert antwoord.status_code == 401
    assert "geblokkeerd" in antwoord.json()["detail"]


async def test_opruimen_laat_verse_sessies_staan(session, owner: User) -> None:
    settings = get_settings()
    rij, _ = await session_service.create(session, user=owner, settings=settings)
    oud, _ = await session_service.create(session, user=owner, settings=settings)
    oud.expires_at = datetime.now(timezone.utc) - timedelta(days=90)
    await session.flush()

    aantal = await session_service.purge(session, ouder_dan_dagen=30)

    assert aantal == 1
    over = (await session.scalars(select(UserSession.id))).all()
    assert list(over) == [rij.id]
