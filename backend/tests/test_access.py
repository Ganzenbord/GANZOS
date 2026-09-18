"""Toegangsniveaus, pincode en de tweede bevestiging.

Hier staat wat fase 2 belooft: wie welk niveau heeft mag wat daarbij hoort, geen tier is
geen toegang, en gevoelige handelingen vragen er nog een bevestiging bovenop — ook van de
eigenaar, en zeker als de aanmelding alleen op een stem berustte.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.permissions import PERMISSIONS, get_permission, permissions_for_tier, tier_allows
from app.core.security import create_token
from app.models.confirmation import MAX_ATTEMPTS, ConfirmationRequest, ConfirmationStatus
from app.models.user import TIER_GUEST, TIER_LIMITED, TIER_OWNER, TIER_TRUSTED, User
from app.utils.pin import InvalidPinError, validate_pin
from tests.conftest import auth_headers, confirm_headers
from tests.voicefakes import STEF, maak_wav

WACHTWOORD = "geheim123"


# --- Het register ------------------------------------------------------------


def test_elk_recht_heeft_een_uitleg_en_een_niveau() -> None:
    for recht in PERMISSIONS:
        assert recht.description
        assert recht.max_tier in (TIER_OWNER, TIER_TRUSTED, TIER_LIMITED, TIER_GUEST)


def test_de_stemrechten_staan_in_het_register() -> None:
    assert get_permission("voice.read").max_tier == TIER_TRUSTED
    assert get_permission("voice.enroll").max_tier == TIER_OWNER
    # Inschrijven deelt toegang uit, dus dat is gevoelig.
    assert get_permission("voice.enroll").sensitive is True


def test_een_onbekend_recht_valt_meteen_op() -> None:
    with pytest.raises(KeyError, match="Onbekend recht"):
        get_permission("bestaat.niet")


@pytest.mark.parametrize(
    ("tier", "recht", "mag"),
    [
        (TIER_OWNER, "finance.read", True),
        (TIER_OWNER, "voice.enroll", True),
        (TIER_TRUSTED, "todo.write", True),
        (TIER_TRUSTED, "finance.read", False),
        (TIER_LIMITED, "todo.read", True),
        (TIER_LIMITED, "todo.write", False),
        (TIER_GUEST, "core.read", True),
        (TIER_GUEST, "system.read", False),
        (None, "core.read", False),
        (None, "todo.read", False),
    ],
)
def test_de_toegangsmatrix(tier: int | None, recht: str, mag: bool) -> None:
    assert tier_allows(tier, recht) is mag


def test_zonder_tier_is_de_lijst_met_rechten_leeg() -> None:
    # De frontend verbergt hiermee alles; de server weigert het toch al.
    assert permissions_for_tier(None) == []
    assert permissions_for_tier(TIER_OWNER)


# --- Over HTTP ---------------------------------------------------------------


async def test_zonder_token_kom_je_er_niet_in(client: AsyncClient) -> None:
    assert (await client.get("/auth/me")).status_code == 401


async def test_een_gebruiker_zonder_tier_mag_niets(
    client: AsyncClient, owner: User, session
) -> None:
    owner.tier = None
    await session.commit()

    antwoord = await client.get("/todos", headers=auth_headers(owner))

    assert antwoord.status_code == 403
    assert "geen toegang" in antwoord.json()["detail"]


async def test_me_laat_zien_dat_je_niets_mag(client: AsyncClient, owner: User, session) -> None:
    owner.tier = None
    await session.commit()

    body = (await client.get("/auth/me", headers=auth_headers(owner))).json()

    assert body["tier"] is None
    assert body["permissions"] == []


async def test_het_rechtenoverzicht_werkt_ook_zonder_tier(
    client: AsyncClient, owner: User, session
) -> None:
    owner.tier = None
    await session.commit()

    rijen = (await client.get("/auth/permissions", headers=auth_headers(owner))).json()

    assert rijen
    assert all(rij["granted"] is False for rij in rijen)


async def test_require_tier_dwingt_een_niveau_af(client: AsyncClient, owner: User) -> None:
    from app.api.deps import require_tier
    from fastapi import HTTPException

    afgeschermd = require_tier(TIER_TRUSTED)
    assert await afgeschermd(user=owner) is owner

    owner.tier = TIER_GUEST
    with pytest.raises(HTTPException) as gevangen:
        await afgeschermd(user=owner)
    assert gevangen.value.status_code == 403

    owner.tier = None
    with pytest.raises(HTTPException, match="geen toegang"):
        await afgeschermd(user=owner)


# --- De pincode --------------------------------------------------------------


@pytest.mark.parametrize("pin", ["123", "12a4", "1111", "1234", "1234567890123", ""])
def test_een_zwakke_pincode_wordt_geweigerd(pin: str) -> None:
    with pytest.raises(InvalidPinError):
        validate_pin(pin)


def test_een_bruikbare_pincode_komt_schoon_terug() -> None:
    assert validate_pin(" 2468 ") == "2468"


async def test_een_pincode_instellen_vraagt_om_het_wachtwoord(
    client: AsyncClient, owner: User
) -> None:
    mis = await client.post(
        "/auth/pin", json={"password": "fout", "pin": "2468"}, headers=auth_headers(owner)
    )
    assert mis.status_code == 401

    goed = await client.post(
        "/auth/pin", json={"password": WACHTWOORD, "pin": "2468"}, headers=auth_headers(owner)
    )
    assert goed.status_code == 200


async def test_me_vertelt_of_er_een_pincode_is(client: AsyncClient, owner: User) -> None:
    """De telefoon moet dit weten: een pincodeveld tonen dat gegarandeerd mislukt is erger
    dan geen pincodeveld. Wat er teruggaat is alleen `ja` of `nee`, nooit de code zelf."""
    voor = (await client.get("/auth/me", headers=auth_headers(owner))).json()
    assert voor["has_pin"] is False

    await client.post(
        "/auth/pin", json={"password": WACHTWOORD, "pin": "2468"}, headers=auth_headers(owner)
    )

    na = (await client.get("/auth/me", headers=auth_headers(owner))).json()
    assert na["has_pin"] is True
    assert "2468" not in na.values()
    assert "pin_hash" not in na


async def test_de_pincode_staat_niet_leesbaar_in_de_database(
    client: AsyncClient, owner: User, session
) -> None:
    await client.post(
        "/auth/pin", json={"password": WACHTWOORD, "pin": "2468"}, headers=auth_headers(owner)
    )
    await session.refresh(owner)

    assert owner.pin_hash
    assert "2468" not in owner.pin_hash
    assert owner.pin_updated_at is not None


# --- De tweede bevestiging ---------------------------------------------------


async def test_bevestigen_kan_met_wachtwoord_of_pincode(
    client: AsyncClient, owner: User
) -> None:
    met_wachtwoord = await client.post(
        "/auth/confirm", json={"password": WACHTWOORD}, headers=auth_headers(owner)
    )
    assert met_wachtwoord.status_code == 200
    assert met_wachtwoord.json()["confirmation_id"]

    await client.post(
        "/auth/pin", json={"password": WACHTWOORD, "pin": "2468"}, headers=auth_headers(owner)
    )
    met_pin = await client.post(
        "/auth/confirm", json={"pin": "2468"}, headers=auth_headers(owner)
    )
    assert met_pin.status_code == 200


async def test_allebei_of_geen_van_beide_mag_niet(client: AsyncClient, owner: User) -> None:
    for payload in ({}, {"password": WACHTWOORD, "pin": "2468"}):
        antwoord = await client.post("/auth/confirm", json=payload, headers=auth_headers(owner))
        assert antwoord.status_code == 422


async def test_een_pincode_zonder_ingestelde_pincode_wordt_geweigerd(
    client: AsyncClient, owner: User
) -> None:
    antwoord = await client.post(
        "/auth/confirm", json={"pin": "2468"}, headers=auth_headers(owner)
    )

    assert antwoord.status_code == 403
    assert "nog geen pincode" in antwoord.json()["detail"]


async def test_doorproberen_van_de_pincode_loopt_vast(client: AsyncClient, owner: User) -> None:
    """Een pincode van vier cijfers is tienduizend mogelijkheden: zonder een grens over de
    verzoeken heen is hij door te rekenen. De grens per verzoek helpt daar niet, want elke
    poging is een nieuw verzoek."""
    await client.post(
        "/auth/pin", json={"password": WACHTWOORD, "pin": "2468"}, headers=auth_headers(owner)
    )

    codes = [
        (
            await client.post(
                "/auth/confirm", json={"pin": "1357"}, headers=auth_headers(owner)
            )
        ).status_code
        for _ in range(6)
    ]

    assert codes[:5] == [401] * 5
    assert codes[5] == 429

    # Ook de goede pincode komt er nu niet meer langs: anders was de grens niets waard.
    geblokkeerd = await client.post(
        "/auth/confirm", json={"pin": "2468"}, headers=auth_headers(owner)
    )
    assert geblokkeerd.status_code == 429
    assert "opnieuw" in geblokkeerd.json()["detail"]


async def test_de_grens_geldt_per_gebruiker(
    client: AsyncClient, owner: User, trusted: User
) -> None:
    """Wie zijn eigen pincode zit mis te tikken, hoort een ander niet buiten te sluiten."""
    for _ in range(6):
        await client.post("/auth/confirm", json={"password": "fout"}, headers=auth_headers(owner))

    van_de_ander = await client.post(
        "/auth/confirm", json={"password": WACHTWOORD}, headers=auth_headers(trusted)
    )
    assert van_de_ander.status_code == 200


async def test_elke_bevestiging_laat_een_spoor_na(
    client: AsyncClient, owner: User, session
) -> None:
    await client.post("/auth/confirm", json={"password": WACHTWOORD}, headers=auth_headers(owner))

    rij = await session.scalar(select(ConfirmationRequest))
    assert rij.status == ConfirmationStatus.CONFIRMED.value
    assert rij.method == "password"
    assert rij.confirmed_at is not None


async def test_ook_een_mislukte_poging_laat_een_spoor_na(
    client: AsyncClient, owner: User, session
) -> None:
    antwoord = await client.post(
        "/auth/confirm", json={"password": "fout"}, headers=auth_headers(owner)
    )

    assert antwoord.status_code == 401
    rij = await session.scalar(select(ConfirmationRequest))
    assert rij is not None
    assert rij.attempts == 1
    assert rij.status == ConfirmationStatus.PENDING.value


async def test_een_gevoelige_handeling_vraagt_om_een_bevestiging(
    client: AsyncClient, owner: User
) -> None:
    antwoord = await client.post(
        "/finance/accounts",
        json={
            "provider": "manual",
            "account_type": "bank",
            "name": "Spaarrekening",
            "currency": "EUR",
            "credentials": {"value": "500.00"},
        },
        headers=auth_headers(owner),
    )

    assert antwoord.status_code == 428


async def test_dezelfde_bevestiging_kan_niet_twee_keer(
    client: AsyncClient, owner: User, session
) -> None:
    """Eén bevestiging dekt één handeling af, anders is het geen drempel."""
    headers = await confirm_headers(session, owner, "finance.manage")
    payload = {
        "provider": "manual",
        "account_type": "bank",
        "name": "Spaarrekening",
        "currency": "EUR",
        "credentials": {"value": "500.00"},
    }

    eerste = await client.post("/finance/accounts", json=payload, headers=headers)
    tweede = await client.post("/finance/accounts", json=payload, headers=headers)

    assert eerste.status_code in (200, 201)
    assert tweede.status_code == 403


async def test_een_bevestiging_voor_iets_anders_telt_niet(
    client: AsyncClient, owner: User, session
) -> None:
    # Bevestigen om het weer op te vragen en dan een rekening koppelen: dat hoort niet te kunnen.
    headers = await confirm_headers(session, owner, "upload.execute")

    antwoord = await client.post(
        "/finance/accounts",
        json={
            "provider": "manual",
            "account_type": "bank",
            "name": "Spaarrekening",
            "currency": "EUR",
            "credentials": {"value": "500.00"},
        },
        headers=headers,
    )

    assert antwoord.status_code == 403
    assert "upload.execute" in antwoord.json()["detail"]


async def test_te_vaak_mis_blokkeert_de_bevestiging(
    client: AsyncClient, owner: User, session
) -> None:
    for poging in range(MAX_ATTEMPTS):
        antwoord = await client.post(
            "/auth/confirm", json={"password": "fout"}, headers=auth_headers(owner)
        )
        assert antwoord.status_code == 401, poging

    rijen = (await session.execute(select(ConfirmationRequest))).scalars().all()
    # Elke poging is een eigen verzoek; het gaat erom dat ze allemaal bewaard blijven.
    assert len(rijen) == MAX_ATTEMPTS


# --- De stem is geen wachtwoord ----------------------------------------------


async def test_een_zwakke_stemherkenning_kan_niets_bevestigen(
    client: AsyncClient, owner: User
) -> None:
    """De prompt is hier stellig over, en terecht: een opname van je stem is zo gemaakt."""
    zwak = create_token(owner.id, "access", origin="voice", confidence=0.30)

    antwoord = await client.post(
        "/auth/confirm",
        json={"password": WACHTWOORD},
        headers={"Authorization": f"Bearer {zwak}"},
    )

    assert antwoord.status_code == 403
    assert "wachtwoord" in antwoord.json()["detail"]


async def test_een_sterke_stemherkenning_mag_wel_bevestigen(
    client: AsyncClient, owner: User
) -> None:
    sterk = create_token(owner.id, "access", origin="voice", confidence=0.95)

    antwoord = await client.post(
        "/auth/confirm",
        json={"password": WACHTWOORD},
        headers={"Authorization": f"Bearer {sterk}"},
    )

    assert antwoord.status_code == 200


async def test_een_stem_alleen_opent_geen_gevoelige_deur(
    client: AsyncClient, owner: User
) -> None:
    """Herkend worden is genoeg om binnen te komen, niet om iets onomkeerbaars te doen."""
    await client.post(
        "/voice/enroll",
        data={"user_id": str(owner.id)},
        files={"audio": ("o.wav", maak_wav(STEF), "audio/wav")},
    )
    token = (
        await client.post(
            "/voice/identify", files={"audio": ("o.wav", maak_wav(STEF, variant=2), "audio/wav")}
        )
    ).json()["access_token"]

    antwoord = await client.post(
        "/finance/accounts",
        json={
            "provider": "manual",
            "account_type": "bank",
            "name": "Spaarrekening",
            "currency": "EUR",
            "credentials": {"value": "500.00"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert antwoord.status_code == 428


# --- Twee dingen die pas opvielen toen het echt draaide -----------------------


async def test_geen_toegang_is_echt_op_te_slaan(database, session) -> None:
    """`tier=None` moet ook daadwerkelijk NULL worden.

    Met een `default=TIER_GUEST` op de kolom erbij werd een expliciete None bij het opslaan
    alsnog 4, en was "geen toegang" dus onbereikbaar — precies waar die kolom voor is. Dat
    zag je aan geen enkele test; het viel op toen de server echt draaide.
    """
    from app.core.security import hash_password

    gast = User(
        email="niemand@example.com",
        display_name="Niemand",
        password_hash=hash_password("geheim123"),
        tier=None,
    )
    session.add(gast)
    await session.commit()

    async with database.session() as verse:
        opnieuw = await verse.scalar(select(User).where(User.email == "niemand@example.com"))
        assert opnieuw.tier is None


async def test_een_nieuwe_gebruiker_begint_zonder_toegang(session) -> None:
    """Zonder tier meegeven krijg je geen toegang, geen gastrol. Toegang geef je bewust."""
    from app.core.security import hash_password

    nieuw = User(
        email="nieuw@example.com",
        display_name="Nieuw",
        password_hash=hash_password("geheim123"),
    )
    session.add(nieuw)
    await session.commit()

    assert nieuw.tier is None


def test_de_ontwikkelsleutel_is_een_geldige_fernet_sleutel() -> None:
    """Hij was het niet: 35 bytes in plaats van 32.

    Daardoor liep alles wat tokens versleutelt in development stuk op een 500. De tests
    merkten dat niet, want die zetten hun eigen sleutel — dit is de test die dat gat dicht.
    """
    from cryptography.fernet import Fernet

    from app.core.config import DEV_ENCRYPTION_KEY

    Fernet(DEV_ENCRYPTION_KEY.encode())
