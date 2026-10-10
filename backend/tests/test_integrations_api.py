"""Koppelingen: de kluis, en het overzicht dat zegt welke functie nog een sleutel mist.

Dit bestand bestond nog niet, en dat was een gat op de gevoeligste plek van Ganz: hier
komen de sleutels binnen waarmee hij daarna namens jou mag handelen. De belangrijkste test
is daarom niet of het overzicht klopt, maar of er nooit een sleutel uit komt.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.integrations.base import ProviderNotConfigured
from app.integrations.catalog import CATALOG
from app.models.user import User
from app.services import integration_service
from tests.conftest import auth_headers, confirm_headers

GEHEIM = "xoxb-dit-is-een-geheim-token"


async def _koppel(client: AsyncClient, session, user: User, **payload) -> dict:
    headers = await confirm_headers(session, user, "integrations.manage")
    antwoord = await client.post("/integrations", json=payload, headers=headers)
    assert antwoord.status_code == 201, antwoord.text
    return antwoord.json()


# --- De kluis ----------------------------------------------------------------


async def test_een_sleutel_komt_er_nooit_meer_uit(
    client: AsyncClient, owner: User, session
) -> None:
    """De kern van 'server-side versleuteld, nooit client-side'.

    Deze test zoekt het geheim in élk antwoord dat de koppeling aanraakt. Een nieuw veld
    toevoegen dat de sleutel per ongeluk meestuurt, laat hem dus omvallen."""
    gemaakt = await _koppel(
        client, session, owner,
        key="slack", name="Slack", category="assistent",
        credentials={"bot_token": GEHEIM, "signing_secret": "ook-geheim"},
    )
    assert GEHEIM not in str(gemaakt)
    assert gemaakt["has_credentials"] is True

    for pad in ("/integrations", "/integrations/catalog"):
        antwoord = await client.get(pad, headers=auth_headers(owner))
        assert antwoord.status_code == 200
        assert GEHEIM not in antwoord.text
        assert "signing_secret" not in antwoord.text or "ook-geheim" not in antwoord.text


async def test_wijzigen_zonder_sleutel_laat_de_oude_staan(
    client: AsyncClient, owner: User, session
) -> None:
    """Zonder deze regel raakt iemand die alleen de naam wijzigt zijn sleutel kwijt — en
    dat merkt hij pas als er iets niet meer werkt."""
    gemaakt = await _koppel(
        client, session, owner, key="telegram", name="Telegram",
        credentials={"bot_token": GEHEIM},
    )
    headers = await confirm_headers(session, owner, "integrations.manage")
    antwoord = await client.patch(
        f"/integrations/{gemaakt['id']}", json={"name": "Telegram (prive)"}, headers=headers
    )
    assert antwoord.status_code == 200
    assert antwoord.json()["has_credentials"] is True
    assert await integration_service.credentials_for(session, owner.id, "telegram") == {
        "bot_token": GEHEIM
    }


async def test_een_leeg_object_gooit_de_sleutel_wel_weg(
    client: AsyncClient, owner: User, session
) -> None:
    gemaakt = await _koppel(
        client, session, owner, key="telegram", name="Telegram",
        credentials={"bot_token": GEHEIM},
    )
    headers = await confirm_headers(session, owner, "integrations.manage")
    antwoord = await client.patch(
        f"/integrations/{gemaakt['id']}", json={"credentials": {}}, headers=headers
    )
    assert antwoord.status_code == 200
    assert antwoord.json()["status"] == "disconnected"


async def test_koppelen_is_alleen_voor_de_eigenaar(
    client: AsyncClient, trusted: User, session
) -> None:
    """`integrations.manage` is TIER_OWNER. Een vertrouwde gebruiker komt dus niet eens bij
    de eigendomscontrole — hij wordt een stap eerder geweigerd."""
    headers = await confirm_headers(session, trusted, "integrations.manage")
    antwoord = await client.post(
        "/integrations", json={"key": "slack", "name": "Slack"}, headers=headers
    )
    assert antwoord.status_code == 403


async def test_de_koppeling_van_iemand_anders_bestaat_niet(
    owner: User, trusted: User, session
) -> None:
    """Dezelfde fout voor 'bestaat niet' en 'is niet van jou': anders kun je via de
    foutmelding aftasten welke ID's bestaan. Op servicelaag getest, want via de API komt
    een niet-eigenaar hier nooit (zie de test hierboven)."""
    rij = await integration_service.create(
        session, owner.id,
        {"key": "slack", "name": "Slack", "credentials": {"bot_token": GEHEIM}},
    )
    await session.commit()

    with pytest.raises(integration_service.IntegrationNotFound):
        await integration_service.delete(session, trusted.id, rij.id)
    with pytest.raises(integration_service.IntegrationNotFound):
        await integration_service.update(session, trusted.id, rij.id, {"name": "Gekaapt"})
    # En een ID dat niet bestaat geeft exact dezelfde fout.
    with pytest.raises(integration_service.IntegrationNotFound):
        await integration_service.delete(session, owner.id, 9999)


# --- De catalogus ------------------------------------------------------------


async def test_de_catalogus_noemt_elke_functie(client: AsyncClient, owner: User) -> None:
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    assert len(body) == len(CATALOG)
    assert {regel["key"] for regel in body} == {plek.key for plek in CATALOG}
    # Elke regel zegt waar de sleutel hoort; een overzicht zonder dat stuurt mensen naar
    # het verkeerde formulier.
    assert all(regel["where"] for regel in body)


async def test_de_catalogus_zegt_eerlijk_wat_nog_niet_is_aangesloten(
    client: AsyncClient, owner: User
) -> None:
    """`wired` is een feit, geen belofte: invullen bij een functie die nog niets aanroept,
    hoort zichtbaar te zijn in plaats van stil niets te doen."""
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    per_key = {regel["key"]: regel for regel in body}

    assert per_key["youtube"]["wired"] is True
    assert per_key["anthropic"]["wired"] is False
    assert per_key["anthropic"]["note"]
    assert per_key["slack"]["wired"] is False


async def test_de_catalogus_laat_zien_welk_veld_nog_leeg_is(
    client: AsyncClient, owner: User, session
) -> None:
    """Een half ingevulde koppeling is erger dan geen: hij lijkt te werken."""
    voor = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    assert [r for r in voor if r["key"] == "slack"][0]["state"] == "missing"

    await _koppel(
        client, session, owner, key="slack", name="Slack",
        credentials={"bot_token": GEHEIM},  # signing_secret en app_token ontbreken
    )

    na = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    slack = [r for r in na if r["key"] == "slack"][0]
    assert slack["state"] == "incomplete"
    assert set(slack["missing_fields"]) == {"signing_secret", "app_token"}


async def test_een_complete_koppeling_staat_op_verbonden(
    client: AsyncClient, owner: User, session
) -> None:
    await _koppel(
        client, session, owner, key="telegram", name="Telegram",
        credentials={"bot_token": GEHEIM},
    )
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    assert [r for r in body if r["key"] == "telegram"][0]["state"] == "connected"
    assert [r for r in body if r["key"] == "telegram"][0]["missing_fields"] == []


async def test_sleutels_op_de_server_worden_bij_de_server_gezocht(
    client: AsyncClient, owner: User
) -> None:
    """Ganz heeft drie bewaarplaatsen. Een sleutel die als omgevingsvariabele hoort, mag
    niet als 'nog koppelen in het scherm' worden gemeld."""
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    per_key = {regel["key"]: regel for regel in body}

    # In de tests staat er geen YouTube-project ingesteld.
    assert per_key["youtube_oauth_app"]["store"] == "server"
    assert per_key["youtube_oauth_app"]["state"] == "missing"
    assert set(per_key["youtube_oauth_app"]["missing_fields"]) == {
        "youtube_client_id", "youtube_client_secret"
    }
    # En die van een kanaal horen bij het kanaal.
    assert per_key["youtube"]["store"] == "channel"
    assert per_key["youtube"]["state"] == "elsewhere"


async def test_de_catalogus_vraagt_om_het_juiste_recht(
    client: AsyncClient, limited: User
) -> None:
    antwoord = await client.get("/integrations/catalog", headers=auth_headers(limited))
    assert antwoord.status_code == 403


# --- require_credentials: wat een functie zelf aanroept ----------------------


async def test_een_functie_krijgt_een_bruikbare_weigering(owner: User, session) -> None:
    """De tekst is voor de gebruiker, niet voor een logboek: hij moet weten wát er mist en
    wáár hij het invult."""
    with pytest.raises(ProviderNotConfigured) as niet_gekoppeld:
        await integration_service.require_credentials(session, owner.id, "slack")
    assert "Slack" in str(niet_gekoppeld.value)
    assert "Koppelingen" in str(niet_gekoppeld.value)


async def test_een_halve_koppeling_wordt_niet_doorgelaten(owner: User, session) -> None:
    await integration_service.create(
        session, owner.id,
        {"key": "slack", "name": "Slack", "credentials": {"bot_token": GEHEIM}},
    )
    await session.commit()

    with pytest.raises(ProviderNotConfigured) as halve:
        await integration_service.require_credentials(session, owner.id, "slack")
    # De labels, niet de veldnamen: dit is tekst die een mens leest.
    assert "Signing secret" in str(halve.value)


async def test_een_complete_koppeling_komt_er_wel_door(owner: User, session) -> None:
    await integration_service.create(
        session, owner.id,
        {"key": "telegram", "name": "Telegram", "credentials": {"bot_token": GEHEIM}},
    )
    await session.commit()
    gegevens = await integration_service.require_credentials(session, owner.id, "telegram")
    assert gegevens == {"bot_token": GEHEIM}


async def test_een_sleutel_die_elders_hoort_wordt_doorverwezen(owner: User, session) -> None:
    """Zonder deze tak zou een functie zeggen 'niet gekoppeld' terwijl de sleutel wel
    bestaat, alleen op een andere plek."""
    with pytest.raises(ProviderNotConfigured) as elders:
        await integration_service.require_credentials(session, owner.id, "youtube")
    assert "kanaal" in str(elders.value).lower()


async def test_een_onleesbare_sleutel_breekt_het_overzicht_niet(
    client: AsyncClient, owner: User, session
) -> None:
    """Wisselt GANZ_ENCRYPTION_KEY, dan is elke opgeslagen sleutel onleesbaar.

    Eén zo'n rij mag niet het hele koppelscherm slopen: dan zie je niet eens meer wát je
    opnieuw moet invullen. De kluis geeft bij een onleesbare waarde niets terug in plaats
    van een fout, en het overzicht meldt het als 'niet compleet'."""
    from app.models.platform import Integration, IntegrationStatus

    session.add(
        Integration(
            user_id=owner.id,
            key="telegram",
            name="Telegram",
            status=IntegrationStatus.CONNECTED,
            credentials_encrypted="dit-is-geen-geldig-versleuteld-blok",
        )
    )
    await session.commit()

    antwoord = await client.get("/integrations/catalog", headers=auth_headers(owner))
    assert antwoord.status_code == 200
    telegram = [r for r in antwoord.json() if r["key"] == "telegram"][0]
    assert telegram["state"] == "incomplete"
    assert telegram["missing_fields"] == ["bot_token"]


async def test_een_functie_zonder_sleutel_zegt_dat_ook(
    client: AsyncClient, owner: User
) -> None:
    """Binance-bulkdata heeft geen sleutel nodig, alleen netwerktoegang. 'Ingevuld' melden
    zou suggereren dat er iets gedaan is wat niet nodig was."""
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    binance = [r for r in body if r["key"] == "binance_bulk"][0]
    assert binance["state"] == "no_key_needed"
    assert binance["fields"] == []
    assert binance["note"]


async def test_de_fabriek_staat_in_de_catalogus(client: AsyncClient, owner: User) -> None:
    """Elke stap van de videofabriek moet een plek hebben om een sleutel in te vullen,
    anders ontdek je pas halverwege dat er een ontbreekt."""
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    per_key = {regel["key"]: regel for regel in body}

    for sleutel in ("vidrush", "nexlev", "web_onderzoek", "stem_generatie", "thumbnails",
                    "muziek_licentie", "mail", "agenda", "slack", "telegram", "anthropic"):
        assert sleutel in per_key, sleutel
        assert per_key[sleutel]["purpose"], sleutel
        # Niets hiervan is aangesloten; dat hoort zichtbaar te zijn en niet verstopt.
        assert per_key[sleutel]["wired"] is False, sleutel
        assert per_key[sleutel]["note"], sleutel


async def test_vidrush_vraagt_om_meer_dan_een_sleutel(client: AsyncClient, owner: User) -> None:
    """Een werkruimte-ID is geen geheim en hoort dus niet als wachtwoordveld op het scherm.
    Zou alles gemaskeerd zijn, dan kun je niet zien of je het goed hebt getypt."""
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    vidrush = [r for r in body if r["key"] == "vidrush"][0]
    velden = {veld["name"]: veld for veld in vidrush["fields"]}
    assert velden["api_key"]["masked"] is True
    assert velden["workspace_id"]["masked"] is False


async def test_de_koppelingen_zijn_per_categorie_gegroepeerd(
    client: AsyncClient, owner: User
) -> None:
    """Het scherm zet een kop neer zodra de categorie verandert. Staan de regels door elkaar,
    dan krijg je dezelfde kop vijf keer."""
    body = (await client.get("/integrations/catalog", headers=auth_headers(owner))).json()
    volgorde = [regel["category"] for regel in body]
    gezien: list[str] = []
    for categorie in volgorde:
        if not gezien or gezien[-1] != categorie:
            assert categorie not in gezien, f"{categorie} komt twee keer los voor"
            gezien.append(categorie)
    assert gezien == ["kanalen", "productie", "assistent", "modellen", "geld", "lab"]
