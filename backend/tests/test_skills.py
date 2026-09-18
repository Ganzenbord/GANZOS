"""De skill-engine: matchen, uitvoeren, en waarom het ging zoals het ging."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.platform import MissionStatus, MissionTask, Skill
from app.models.user import User
from app.services.skill_executor import (
    ExecutionResult,
    SkillExecutor,
    StepContext,
    StepError,
    Tool,
    ToolRegistry,
)
from app.services.skill_matcher import LexicalMatcher, SkillMatch, tokenize
from tests.conftest import auth_headers, confirm_headers

UPLOAD_SKILL = {
    "name": "Video uploaden",
    "description": "Een afgeronde video publiceren naar YouTube",
    "trigger_pattern": "upload|publiceer|zet online",
    "steps": [
        {"tool": "youtube.upload", "action": "upload"},
        {"tool": "activity.log", "action": "success"},
    ],
}
WEER_SKILL = {
    "name": "Weerbericht",
    "description": "Vertel hoe het weer wordt",
    "trigger_pattern": "weer|regen|temperatuur",
    "steps": [{"tool": "weather.read", "action": "read"}],
}


async def maak_skill(client: AsyncClient, user: User, payload: dict) -> dict:
    antwoord = await client.post("/skills", json=payload, headers=auth_headers(user))
    assert antwoord.status_code == 201, antwoord.text
    return antwoord.json()


async def maak_taak(client: AsyncClient, user: User, titel: str) -> dict:
    antwoord = await client.post("/tasks", json={"title": titel}, headers=auth_headers(user))
    assert antwoord.status_code == 201, antwoord.text
    return antwoord.json()


# --- Het matchen, los van alles ----------------------------------------------


def test_stopwoorden_tellen_niet_mee() -> None:
    # Anders matcht "kun je even het weer opzoeken" op alles wat "je" en "even" bevat.
    assert tokenize("Kun je even het weer opzoeken?") == {"weer", "opzoeken"}


def test_korte_woorden_vallen_af() -> None:
    assert "de" not in tokenize("de video")
    assert "video" in tokenize("de video")


async def test_de_matcher_kiest_de_skill_met_de_meeste_overlap(session, owner: User) -> None:
    upload = Skill(user_id=owner.id, **UPLOAD_SKILL)
    weer = Skill(user_id=owner.id, **WEER_SKILL)
    session.add_all([upload, weer])
    await session.commit()

    uitslag = await LexicalMatcher().match(
        "Publiceer de nieuwe video op YouTube", [upload, weer], threshold=0.2
    )

    assert uitslag.matched is True
    assert uitslag.skill is upload
    assert uitslag.backend == "woorden"


async def test_de_matcher_legt_uit_waarom_er_niets_paste(session, owner: User) -> None:
    """Zonder uitleg is 'Ganz deed niets' het vervelendste soort stilte."""
    weer = Skill(user_id=owner.id, **WEER_SKILL)
    session.add(weer)
    await session.commit()

    uitslag = await LexicalMatcher().match("Bestel een pizza", [weer], threshold=0.45)

    assert uitslag.matched is False
    assert "onder de drempel" in uitslag.reason
    assert "Weerbericht" in uitslag.reason


async def test_zonder_skills_zegt_de_matcher_dat_ook() -> None:
    uitslag = await LexicalMatcher().match("Wat dan ook", [], threshold=0.45)

    assert uitslag.matched is False
    assert "nog geen skills" in uitslag.reason


async def test_een_lege_opdracht_levert_geen_match() -> None:
    uitslag = await LexicalMatcher().match("de en het", [], threshold=0.45)

    assert uitslag.matched is False
    assert "geen woorden" in uitslag.reason


# --- De uitvoering, los van alles --------------------------------------------


def test_een_onbekend_gereedschap_wordt_vooraf_afgevangen() -> None:
    """Liever hier struikelen dan halverwege: een halve skill is niet terug te draaien."""
    with pytest.raises(StepError, match="Onbekend gereedschap"):
        SkillExecutor().validate([{"tool": "bestaat.niet"}])


def test_een_skill_zonder_stappen_wordt_afgevangen() -> None:
    with pytest.raises(StepError, match="geen stappen"):
        SkillExecutor().validate([])


def test_een_stap_zonder_gereedschap_wordt_afgevangen() -> None:
    with pytest.raises(StepError, match="noemt geen gereedschap"):
        SkillExecutor().validate([{"action": "doe iets"}])


async def test_de_stappen_worden_op_volgorde_gedaan() -> None:
    uitkomst = await SkillExecutor().run(
        [{"tool": "weather.read"}, {"tool": "activity.log"}],
        StepContext(user_id=1, task_id=1, skill_name="Test", step_index=0, confirmed=False),
    )

    assert uitkomst.ok is True
    assert [stap["tool"] for stap in uitkomst.steps] == ["weather.read", "activity.log"]
    assert all(stap["simulated"] for stap in uitkomst.steps)


async def test_gevoelig_gereedschap_weigert_zonder_bevestiging() -> None:
    uitkomst = await SkillExecutor().run(
        [{"tool": "youtube.upload"}],
        StepContext(user_id=1, task_id=1, skill_name="Test", step_index=0, confirmed=False),
    )

    assert uitkomst.ok is False
    assert "bevestiging" in uitkomst.error
    assert uitkomst.failed_step == 1


async def test_de_uitvoering_stopt_bij_de_eerste_fout() -> None:
    async def stuk(step, context):
        raise StepError("Dit ging mis.")

    register = ToolRegistry(
        [
            Tool("goed", "Doet het", lambda s, c: _ok()),
            Tool("stuk", "Gaat mis", stuk),
            Tool("nooit", "Komt niet aan de beurt", lambda s, c: _ok()),
        ]
    )
    uitkomst = await SkillExecutor(register).run(
        [{"tool": "goed"}, {"tool": "stuk"}, {"tool": "nooit"}],
        StepContext(user_id=1, task_id=1, skill_name="Test", step_index=0, confirmed=True),
    )

    assert uitkomst.ok is False
    assert uitkomst.failed_step == 2
    # De stap die wél lukte blijft zichtbaar: dat is wat je moet weten om op te ruimen.
    assert [stap["tool"] for stap in uitkomst.steps] == ["goed"]


async def test_een_gereedschap_dat_klapt_sloopt_ganz_niet() -> None:
    async def klapt(step, context):
        raise ValueError("onverwacht")

    register = ToolRegistry([Tool("klapt", "Gaat onverwacht mis", klapt)])
    uitkomst = await SkillExecutor(register).run(
        [{"tool": "klapt"}],
        StepContext(user_id=1, task_id=1, skill_name="Test", step_index=0, confirmed=True),
    )

    assert uitkomst.ok is False
    assert "onverwacht" in uitkomst.error


async def _ok() -> dict:
    return {"ok": True}


def test_er_kunnen_echte_gereedschappen_bij_zonder_de_rest_te_veranderen() -> None:
    """Dit is waar het koppelvlak voor bedoeld is: één register() erbij, verder niets."""
    register = SkillExecutor().registry
    assert "youtube.upload" in register
    assert register.get("youtube.upload").simulated is True

    register.register(Tool("eigen.iets", "Zelf toegevoegd", lambda s, c: _ok()))
    assert "eigen.iets" in register

    with pytest.raises(ValueError, match="staat al in het register"):
        register.register(Tool("eigen.iets", "Nog een keer", lambda s, c: _ok()))


# --- Over HTTP ---------------------------------------------------------------


async def test_een_skill_met_een_onbekend_gereedschap_wordt_niet_opgeslagen(
    client: AsyncClient, owner: User
) -> None:
    antwoord = await client.post(
        "/skills",
        json={"name": "Onzin", "steps": [{"tool": "bestaat.niet"}]},
        headers=auth_headers(owner),
    )

    assert antwoord.status_code == 422
    assert "Onbekend gereedschap" in antwoord.json()["detail"]


async def test_de_lijst_met_gereedschappen_zegt_wat_echt_is(
    client: AsyncClient, owner: User
) -> None:
    rijen = (await client.get("/skills/tools", headers=auth_headers(owner))).json()
    per_naam = {rij["name"]: rij for rij in rijen}

    assert per_naam["youtube.upload"]["sensitive"] is True
    assert per_naam["weather.read"]["sensitive"] is False
    # Zolang dit true is heeft Ganz niets in de buitenwereld gedaan. Dat hoort zichtbaar te zijn.
    assert all(rij["simulated"] for rij in rijen)


async def test_de_hele_loop_van_opdracht_tot_uitgevoerd(
    client: AsyncClient, owner: User, session
) -> None:
    await maak_skill(client, owner, WEER_SKILL)
    taak = await maak_taak(client, owner, "Vertel me het weer van morgen")

    match = await client.post(f"/tasks/{taak['id']}/match", headers=auth_headers(owner))
    assert match.status_code == 200
    body = match.json()
    assert body["matched"] is True
    assert body["skill"]["name"] == "Weerbericht"
    assert body["backend"] == "woorden"
    assert body["task"]["match_reason"].startswith("[woorden]")

    uitvoeren = await client.post(f"/tasks/{taak['id']}/execute", headers=auth_headers(owner))
    assert uitvoeren.status_code == 200
    resultaat = uitvoeren.json()
    assert resultaat["ok"] is True
    assert resultaat["task"]["status"] == MissionStatus.DONE
    assert resultaat["task"]["completed_at"]
    assert resultaat["simulated"] is True

    opnieuw = await session.get(Skill, body["skill"]["id"])
    await session.refresh(opnieuw)
    assert opnieuw.success_count == 1
    assert opnieuw.run_count == 1
    assert opnieuw.last_used_at is not None


async def test_zonder_passende_skill_blijft_de_taak_staan_met_uitleg(
    client: AsyncClient, owner: User
) -> None:
    await maak_skill(client, owner, WEER_SKILL)
    taak = await maak_taak(client, owner, "Bestel een pizza met extra kaas")

    body = (await client.post(f"/tasks/{taak['id']}/match", headers=auth_headers(owner))).json()

    assert body["matched"] is False
    assert body["skill"] is None
    assert body["task"]["status"] == MissionStatus.PLANNED
    assert body["task"]["match_reason"]


async def test_uitvoeren_zonder_gematchte_skill_zegt_wat_je_moet_doen(
    client: AsyncClient, owner: User
) -> None:
    taak = await maak_taak(client, owner, "Iets doen")

    antwoord = await client.post(f"/tasks/{taak['id']}/execute", headers=auth_headers(owner))

    assert antwoord.status_code == 409
    assert "match" in antwoord.json()["detail"]


async def test_een_gevoelige_skill_vraagt_om_een_bevestiging(
    client: AsyncClient, owner: User, session
) -> None:
    await maak_skill(client, owner, UPLOAD_SKILL)
    taak = await maak_taak(client, owner, "Upload de nieuwe video naar YouTube")
    await client.post(f"/tasks/{taak['id']}/match", headers=auth_headers(owner))

    zonder = await client.post(f"/tasks/{taak['id']}/execute", headers=auth_headers(owner))
    assert zonder.status_code == 428

    headers = await confirm_headers(session, owner, "tasks.execute")
    met = await client.post(f"/tasks/{taak['id']}/execute", headers=headers)
    assert met.status_code == 200, met.text
    assert met.json()["ok"] is True


async def test_een_mislukte_uitvoering_telt_mee_als_mislukking(
    client: AsyncClient, owner: User, database, encoder
) -> None:
    """Een skill die faalt hoort dat in zijn teller terug te zien."""
    from app.core.config import get_settings
    from app.main import create_app
    from httpx import ASGITransport

    async def stuk(step, context):
        raise StepError("Het weerstation antwoordt niet.")

    register = ToolRegistry([Tool("weather.read", "Weer", stuk)])
    app = create_app(
        settings=get_settings(),
        database=database,
        speaker_encoder=encoder,
        skill_executor=SkillExecutor(register),
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test/api") as http:
            skill = await maak_skill(http, owner, WEER_SKILL)
            taak = await maak_taak(http, owner, "Vertel me het weer")
            await http.post(f"/tasks/{taak['id']}/match", headers=auth_headers(owner))
            antwoord = await http.post(f"/tasks/{taak['id']}/execute", headers=auth_headers(owner))

    assert antwoord.status_code == 200
    body = antwoord.json()
    assert body["ok"] is False
    assert body["task"]["status"] == MissionStatus.FAILED
    assert "weerstation" in body["task"]["error"]

    async with database.session() as verse:
        opnieuw = await verse.get(Skill, skill["id"])
        assert opnieuw.failure_count == 1
        assert opnieuw.success_count == 0


async def test_een_taak_annuleren_kan_maar_een_keer(client: AsyncClient, owner: User) -> None:
    taak = await maak_taak(client, owner, "Toch maar niet")

    eerste = await client.post(f"/tasks/{taak['id']}/cancel", headers=auth_headers(owner))
    assert eerste.status_code == 200
    assert eerste.json()["status"] == MissionStatus.CANCELLED

    tweede = await client.post(f"/tasks/{taak['id']}/cancel", headers=auth_headers(owner))
    assert tweede.status_code == 409


async def test_de_versie_loopt_op_bij_andere_stappen_maar_niet_bij_een_naam(
    client: AsyncClient, owner: User
) -> None:
    skill = await maak_skill(client, owner, WEER_SKILL)
    assert skill["version"] == 1

    naam = await client.patch(
        f"/skills/{skill['id']}", json={"name": "Het weer"}, headers=auth_headers(owner)
    )
    assert naam.json()["version"] == 1

    stappen = await client.patch(
        f"/skills/{skill['id']}",
        json={"steps": [{"tool": "weather.read"}, {"tool": "activity.log"}]},
        headers=auth_headers(owner),
    )
    assert stappen.json()["version"] == 2


async def test_skills_van_iemand_anders_zijn_onzichtbaar(
    client: AsyncClient, owner: User, trusted: User
) -> None:
    skill = await maak_skill(client, owner, WEER_SKILL)

    lijst = (await client.get("/skills", headers=auth_headers(trusted))).json()
    assert lijst == []

    weg = await client.delete(f"/skills/{skill['id']}", headers=auth_headers(trusted))
    assert weg.status_code == 404


async def test_alles_wat_er_gebeurt_komt_in_het_logboek(
    client: AsyncClient, owner: User, session
) -> None:
    from app.models.activity import ActivityLogEntry

    await maak_skill(client, owner, WEER_SKILL)
    taak = await maak_taak(client, owner, "Vertel me het weer")
    await client.post(f"/tasks/{taak['id']}/match", headers=auth_headers(owner))
    await client.post(f"/tasks/{taak['id']}/execute", headers=auth_headers(owner))

    acties = (await session.execute(select(ActivityLogEntry.action))).scalars().all()

    assert "SKILL_CREATED" in acties
    assert "TASK_CREATED" in acties
    assert "TASK_MATCHED" in acties
    assert "TASK_COMPLETED" in acties


async def test_skills_beheren_vraagt_om_het_juiste_recht(
    client: AsyncClient, limited: User
) -> None:
    # skills.write is TIER_TRUSTED; limited is tier 3.
    lezen = await client.get("/skills", headers=auth_headers(limited))
    schrijven = await client.post("/skills", json=WEER_SKILL, headers=auth_headers(limited))

    assert lezen.status_code == 200
    assert schrijven.status_code == 403


async def test_een_taak_van_iemand_anders_is_niet_uit_te_voeren(
    client: AsyncClient, owner: User, trusted: User
) -> None:
    taak = await maak_taak(client, owner, "Van mij")

    antwoord = await client.post(f"/tasks/{taak['id']}/execute", headers=auth_headers(trusted))

    assert antwoord.status_code == 404


def test_geen_twee_endpoints_op_hetzelfde_pad() -> None:
    """Twee routers op hetzelfde pad is stil kapot.

    `platform.py` bediende ook GET /skills. FastAPI kiest dan de eerste van de twee, dus de
    versie met stappen en versienummer erin was onbereikbaar — zonder dat iets dat zei. Dit
    vangt af dat er ooit weer zo'n paar ontstaat.
    """
    from collections import Counter

    from app.core.config import get_settings
    from app.main import create_app

    app = create_app(settings=get_settings())
    paren = [
        (methode, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for methode in route.methods
        if methode != "HEAD"
    ]
    dubbel = {paar: aantal for paar, aantal in Counter(paren).items() if aantal > 1}

    assert dubbel == {}, f"Deze endpoints botsen: {dubbel}"
