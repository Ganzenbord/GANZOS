"""De afspraak dat er nooit een geheim of een ruwe rij naar buiten gaat.

Dit bestand controleert geen enkel los eindpunt maar een régel, en dat is met opzet. Een
opruimactie is over een half jaar weer vervuild; een test die faalt op het moment dat
iemand een eindpunt zonder responsemodel toevoegt, houdt stand.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.main import create_app
from app.models.social import SocialChannel
from app.models.user import User
from app.utils.crypto import get_vault
from app.utils.redact import redact_text, scrub
from tests.conftest import auth_headers, confirm_headers

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Eindpunten die met opzet geen responsemodel hebben, met de reden erbij. Een lege lijst is
# niet het doel — het doel is dat elke uitzondering een reden heeft die je kunt nalezen.
ZONDER_MODEL_TOEGESTAAN = {
    # 204: geen inhoud, dus ook niets om te lekken.
    ("POST", "/api/todos/reorder"),
    ("DELETE", "/api/todos/subtasks/{subtask_id}"),
    ("DELETE", "/api/todos/{task_id}"),
    ("DELETE", "/api/finance/accounts/{account_id}"),
    ("DELETE", "/api/social/channels/{channel_id}"),
    ("DELETE", "/api/uploads/{upload_id}"),
    ("DELETE", "/api/integrations/{integration_id}"),
    ("DELETE", "/api/skills/{skill_id}"),
    # Geen JSON maar een pagina in de browser van de gebruiker; er staat één zin op.
    ("GET", "/api/youtube/oauth/callback"),
}


def test_elk_eindpunt_heeft_een_expliciete_lijst_met_velden() -> None:
    """Geen responsemodel betekent: wat de functie toevallig teruggeeft, gaat de deur uit.

    Dat werkt tot iemand een kolom toevoegt aan het model dat eronder ligt. Met een
    responsemodel staat er een lijst met toegestane velden tussen, en valt zo'n kolom er
    vanzelf buiten."""
    app = create_app()
    zonder = set()
    for route in app.routes:
        pad = getattr(route, "path", "")
        if not pad.startswith("/api"):
            continue
        if getattr(route, "response_model", None) is None:
            for methode in sorted(getattr(route, "methods", set()) or set()):
                zonder.add((methode, pad))

    onverwacht = zonder - ZONDER_MODEL_TOEGESTAAN
    assert not onverwacht, (
        "Deze eindpunten hebben geen responsemodel. Geef ze er een, of zet ze met een reden "
        f"in ZONDER_MODEL_TOEGESTAAN: {sorted(onverwacht)}"
    )


def test_de_lijst_met_uitzonderingen_bevat_geen_dode_regels() -> None:
    """Een uitzondering voor een eindpunt dat niet meer bestaat, verbergt de volgende."""
    app = create_app()
    bestaand = {
        (methode, getattr(route, "path", ""))
        for route in app.routes
        for methode in (getattr(route, "methods", set()) or set())
    }
    verdwenen = ZONDER_MODEL_TOEGESTAAN - bestaand
    assert not verdwenen, f"Deze uitzonderingen slaan nergens meer op: {sorted(verdwenen)}"


def test_geen_enkele_module_serialiseert_een_ruwe_rij() -> None:
    """`**rij.__dict__` en `model_dump()` op een databaserij nemen alles mee wat er staat.

    Inclusief de kolom die er volgende maand bij komt. Dat is precies de kortsluiting die
    dit project niet wil, dus die vorm hoort nergens in de API-laag te staan."""
    verboden = re.compile(r"\*\*\s*\w+\.__dict__|\*\*\s*\w+\.dict\(\)|jsonable_encoder\(\s*\w+\s*\)")
    gevonden = []
    for pad in (APP_DIR / "api").rglob("*.py"):
        for nummer, regel in enumerate(pad.read_text().splitlines(), start=1):
            if verboden.search(regel):
                gevonden.append(f"{pad.name}:{nummer}: {regel.strip()}")
    assert not gevonden, "Ruwe serialisatie gevonden:\n" + "\n".join(gevonden)


def _modellen_die_de_client_krijgt() -> dict[str, type]:
    """Elk responsemodel van elke route, inclusief de modellen die daarin genest zitten.

    Kijken naar álle schema's zou ook de invoermodellen meenemen, en die horen juist een
    wachtwoord te bevatten — daar gaat het de andere kant op."""
    app = create_app()
    gevonden: dict[str, type] = {}

    def loop(model: object) -> None:
        velden = getattr(model, "model_fields", None)
        if not isinstance(velden, dict) or model.__name__ in gevonden:
            return
        gevonden[model.__name__] = model  # type: ignore[assignment]
        for veld in velden.values():
            for genest in _uitpakken(veld.annotation):
                loop(genest)

    for route in app.routes:
        model = getattr(route, "response_model", None)
        if model is None:
            continue
        for stuk in _uitpakken(model):
            loop(stuk)
    return gevonden


def _uitpakken(annotatie: object) -> list[type]:
    """Haalt de modellen uit `list[X]`, `X | None` en dergelijke."""
    import typing

    argumenten = typing.get_args(annotatie)
    if not argumenten:
        return [annotatie] if inspect.isclass(annotatie) else []
    uit: list[type] = []
    for arg in argumenten:
        uit.extend(_uitpakken(arg))
    return uit


def test_geen_enkel_responsemodel_heeft_een_veld_dat_naar_een_geheim_ruikt() -> None:
    """Een veld dat `credentials` of `token` heet, hoort niet in iets dat de client krijgt.

    Uitgezonderd: de velden waar een token juist de bedoeling is — het inlogtoken, het
    vernieuwingstoken en het bevestigingstoken, die de client nodig heeft om er iets mee te
    doen."""
    toegestaan = {
        ("TokenResponse", "access_token"),
        ("TokenResponse", "refresh_token"),
        ("TokenResponse", "token_type"),
        ("ConfirmationResponse", "confirmation_token"),
        ("IdentifyResponse", "access_token"),
        # Zegt óf er gegevens zijn, niet welke.
        ("IntegrationOut", "has_credentials"),
    }
    verdacht = re.compile(
        r"(secret|password|credential|api_key|_hash|token|embedding$)", re.IGNORECASE
    )

    gevonden = []
    for naam, model in _modellen_die_de_client_krijgt().items():
        for veld in model.model_fields:
            if (naam, veld) in toegestaan:
                continue
            if verdacht.search(veld):
                gevonden.append(f"{naam}.{veld}")
    assert not gevonden, f"Deze velden gaan naar de client: {sorted(set(gevonden))}"


# --- Wat er werkelijk over de lijn gaat --------------------------------------


async def test_de_gegevens_van_een_kanaal_komen_nergens_terug(
    client: AsyncClient, owner: User, session
) -> None:
    """Niet de schema's maar het echte antwoord, met een echte sleutel erin."""
    session.add(
        SocialChannel(
            user_id=owner.id,
            platform="youtube",
            channel_name="Testkanaal",
            credentials_encrypted=get_vault().encrypt(
                {"api_key": "AIzaGEHEIMEsleutel", "oauth_refresh_token": "rt-geheim"}
            ),
        )
    )
    await session.commit()

    for pad in ("/social/channels", "/social/overview", "/dashboard", "/integrations"):
        antwoord = await client.get(pad, headers=auth_headers(owner))
        assert antwoord.status_code == 200, pad
        tekst = antwoord.text
        for geheim in ("AIzaGEHEIMEsleutel", "rt-geheim", "credentials_encrypted"):
            assert geheim not in tekst, f"{geheim} kwam terug via {pad}"


async def test_een_onverwachte_fout_vertelt_de_client_niets(
    app, owner: User, monkeypatch
) -> None:
    """Een stack trace zegt welke bibliotheken je draait en wat er in een variabele stond.

    Wat de client krijgt is een kenmerk waarmee jij de regel in het logboek terugvindt.

    Met een eigen client: de gewone testclient gooit een fout uit de app opnieuw op, zodat
    je hem in je test ziet. Hier gaat het juist om wat er over de lijn gaat."""
    from httpx import ASGITransport

    from app.services import core_service

    async def klapt(*args, **kwargs):
        raise RuntimeError("wachtwoord=superheim123 in de melding")

    monkeypatch.setattr(core_service, "core_overview", klapt)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test/api") as echt:
        antwoord = await echt.get("/core", headers=auth_headers(owner))

    assert antwoord.status_code == 500
    tekst = antwoord.text
    assert "superheim123" not in tekst
    assert "RuntimeError" not in tekst
    assert "Traceback" not in tekst
    assert antwoord.json()["reference"]


# --- Het schoonmaken zelf ----------------------------------------------------


@pytest.mark.parametrize(
    "ingang, verwacht_weg",
    [
        ({"api_key": "AIzaGEHEIM"}, "AIzaGEHEIM"),
        ({"nested": {"client_secret": "GOCSPX-geheim"}}, "GOCSPX-geheim"),
        ({"lijst": [{"refresh_token": "rt-1"}]}, "rt-1"),
    ],
)
def test_schoonmaken_haalt_geheimen_uit_een_structuur(ingang: dict, verwacht_weg: str) -> None:
    assert verwacht_weg not in str(scrub(ingang))


@pytest.mark.parametrize(
    "regel, verwacht_weg",
    [
        ("connect postgresql://ganz:wachtwoord123@db:5432/ganz", "wachtwoord123"),
        (
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        ),
        ("key=AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q", "AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"),
    ],
)
def test_schoonmaken_haalt_geheimen_uit_vrije_tekst(regel: str, verwacht_weg: str) -> None:
    assert verwacht_weg not in redact_text(regel)


def test_de_logfilter_hangt_aan_de_handlers() -> None:
    """Aan de handlers en niet aan de loggers: anders glipt alles wat van sqlalchemy of
    uvicorn doorheen komt er ongefilterd langs."""
    import logging

    from app.utils.redact import SecretFilter

    logging.basicConfig()
    create_app()

    handlers = logging.getLogger().handlers
    assert handlers, "geen handler om aan te hangen"
    assert all(any(isinstance(f, SecretFilter) for f in h.filters) for h in handlers)


# --- Eigen sleutels toevoegen -------------------------------------------------


async def test_een_eigen_sleutel_gaat_erin_en_komt_er_nooit_uit(
    client: AsyncClient, owner: User, session
) -> None:
    """De kern van "server-side versleuteld, nooit client-side": je kunt hem invullen en
    vervangen, maar niet uitlezen — ook niet als jij het zelf bent."""
    from app.models.platform import Integration

    headers = await confirm_headers(session, owner, "integrations.manage")
    aangemaakt = await client.post(
        "/integrations",
        json={
            "key": "higgsfield",
            "name": "Higgsfield",
            "category": "video",
            "credentials": {"api_key": "hf-GEHEIM-12345"},
        },
        headers=headers,
    )

    assert aangemaakt.status_code == 201, aangemaakt.text
    body = aangemaakt.json()
    assert body["has_credentials"] is True
    assert "hf-GEHEIM-12345" not in aangemaakt.text
    assert "credentials" not in body

    # Ook niet via de lijst, en ook niet via het dashboard.
    for pad in ("/integrations", "/dashboard"):
        antwoord = await client.get(pad, headers=auth_headers(owner))
        assert "hf-GEHEIM-12345" not in antwoord.text

    # In de database staat hij versleuteld.
    rij = await session.scalar(select(Integration).where(Integration.key == "higgsfield"))
    assert rij.credentials_encrypted
    assert "hf-GEHEIM-12345" not in rij.credentials_encrypted
    assert get_vault().decrypt(rij.credentials_encrypted)["api_key"] == "hf-GEHEIM-12345"


async def test_alleen_de_naam_wijzigen_laat_de_sleutel_staan(
    client: AsyncClient, owner: User, session
) -> None:
    """De client heeft de sleutel nooit gezien, dus kan hem ook niet meesturen. Zou een
    wijziging zonder sleutel hem wissen, dan raak je hem kwijt door je koppeling te
    hernoemen."""
    from app.models.platform import Integration

    headers = await confirm_headers(session, owner, "integrations.manage")
    gemaakt = (
        await client.post(
            "/integrations",
            json={"key": "hf", "name": "Higgsfield", "credentials": {"api_key": "blijf-staan"}},
            headers=headers,
        )
    ).json()

    headers = await confirm_headers(session, owner, "integrations.manage")
    gewijzigd = await client.patch(
        f"/integrations/{gemaakt['id']}", json={"name": "Higgsfield AI"}, headers=headers
    )

    assert gewijzigd.status_code == 200
    assert gewijzigd.json()["name"] == "Higgsfield AI"
    rij = await session.get(Integration, gemaakt["id"])
    await session.refresh(rij)
    assert get_vault().decrypt(rij.credentials_encrypted)["api_key"] == "blijf-staan"


async def test_een_sleutel_toevoegen_vraagt_om_een_bevestiging(
    client: AsyncClient, owner: User
) -> None:
    antwoord = await client.post(
        "/integrations",
        json={"key": "hf", "name": "Higgsfield", "credentials": {"api_key": "x"}},
        headers=auth_headers(owner),
    )

    assert antwoord.status_code == 428


async def test_de_koppeling_van_een_ander_is_onzichtbaar(
    client: AsyncClient, owner: User, trusted: User, session
) -> None:
    headers = await confirm_headers(session, owner, "integrations.manage")
    van_mij = (
        await client.post(
            "/integrations", json={"key": "hf", "name": "Van Stef"}, headers=headers
        )
    ).json()

    # Dezelfde 404 voor "bestaat niet" en "is niet van jou".
    headers = await confirm_headers(session, trusted, "integrations.manage")
    antwoord = await client.patch(
        f"/integrations/{van_mij['id']}", json={"name": "Gekaapt"}, headers=headers
    )
    assert antwoord.status_code in (403, 404)
