"""De endpoints waar het Command Center op draait."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.activity import ActivityAction, ActivityLogEntry
from app.models.platform import Conversation, MemoryEntry, MissionStatus, MissionTask, Skill
from app.models.social import ChannelStatus, SocialChannel, SocialPlatform
from app.models.upload import ContentType, UploadSchedule, UploadStatus
from app.models.user import User
from app.models.voice import VoiceProfile
from app.services import schedule_service
from tests.conftest import auth_headers

VANDAAG = datetime.now(timezone.utc)


# --- /status -----------------------------------------------------------------


async def test_status_geeft_de_vijf_regels(client: AsyncClient, owner: User) -> None:
    body = (await client.get("/status", headers=auth_headers(owner))).json()

    assert body["core_status"] == "active"
    assert body["voice_status"] == "not_configured"
    assert body["active_skills"] == 0
    assert body["integrations_count"] == 0
    assert body["system_status"] in {"optimal", "warning"}


async def test_status_telt_alleen_skills_die_aanstaan(
    client: AsyncClient, owner: User, session
) -> None:
    session.add_all(
        [
            Skill(user_id=owner.id, name="Aan", enabled=True),
            Skill(user_id=owner.id, name="Uit", enabled=False),
        ]
    )
    await session.commit()

    body = (await client.get("/status", headers=auth_headers(owner))).json()

    assert body["active_skills"] == 1


async def test_de_stem_staat_pas_op_luisterend_als_er_een_stem_is(
    client: AsyncClient, owner: User, session
) -> None:
    """Keek eerder naar een integratie met categorie 'voice'.

    Sinds fase 2 zit de stemherkenning in Ganz zelf: er stond 'not_configured' terwijl er
    wél stemmen ingeschreven waren. Nu wordt geteld wat er echt is.
    """
    eerst = (await client.get("/status", headers=auth_headers(owner))).json()
    assert eerst["voice_status"] == "not_configured"

    session.add(
        VoiceProfile(user_id=owner.id, label="Opname 1", embedding=[0.1, 0.2], embedding_dim=2)
    )
    await session.commit()

    daarna = (await client.get("/status", headers=auth_headers(owner))).json()
    assert daarna["voice_status"] == "listening"
    assert "1 opname" in daarna["voice_detail"]


async def test_een_profiel_zonder_afdruk_telt_niet_mee(
    client: AsyncClient, owner: User, session
) -> None:
    """Een half ingeschreven profiel mag het stoplicht niet op groen zetten.

    Dit ging echt mis. SQLAlchemy schrijft een Python-None in een JSON-kolom weg als de
    JSON-waarde `null`, niet als SQL NULL — en dan is `IS NOT NULL` gewoon waar. Het stond
    op "listening" zonder dat er één afdruk was. Erger: `has_any_enrollment()` uit fase 2
    gebruikt dezelfde filter, dus één zo'n rij zou de "eerste inschrijving is open"-deur
    dichtgooien en je buitensluiten. De kolom gebruikt nu NullableJSON.
    """
    session.add(VoiceProfile(user_id=owner.id, label="Half", embedding=None))
    await session.commit()

    body = (await client.get("/status", headers=auth_headers(owner))).json()

    assert body["voice_status"] == "not_configured"


async def test_een_profiel_zonder_afdruk_sluit_de_eerste_inschrijving_niet(
    database, owner: User, session
) -> None:
    """De keerzijde van dezelfde bug, en de vervelendste: buitengesloten raken."""
    from app.services.voice_service import has_any_enrollment

    session.add(VoiceProfile(user_id=owner.id, label="Half", embedding=None))
    await session.commit()

    async with database.session() as verse:
        assert await has_any_enrollment(verse) is False

        verse.add(
            VoiceProfile(user_id=owner.id, label="Echt", embedding=[0.1, 0.2], embedding_dim=2)
        )
        await verse.commit()
        assert await has_any_enrollment(verse) is True


# --- /activity ---------------------------------------------------------------


async def _log(session, owner: User, aantal: int) -> None:
    for nummer in range(aantal):
        session.add(
            ActivityLogEntry(
                user_id=owner.id,
                action=ActivityAction.TASK_CREATED,
                message=f"Regel {nummer}",
            )
        )
    await session.commit()


async def test_activity_levert_paginas_met_het_totaal_erbij(
    client: AsyncClient, owner: User, session
) -> None:
    await _log(session, owner, 25)

    eerste = (await client.get("/activity?limit=10", headers=auth_headers(owner))).json()

    assert len(eerste["items"]) == 10
    assert eerste["total"] == 25
    assert eerste["has_more"] is True


async def test_de_laatste_pagina_zegt_dat_hij_de_laatste_is(
    client: AsyncClient, owner: User, session
) -> None:
    await _log(session, owner, 25)

    laatste = (
        await client.get("/activity?limit=10&offset=20", headers=auth_headers(owner))
    ).json()

    assert len(laatste["items"]) == 5
    assert laatste["has_more"] is False


async def test_pagineren_laat_niets_dubbel_of_weg(
    client: AsyncClient, owner: User, session
) -> None:
    """Regels in dezelfde milliseconde zouden anders van volgorde kunnen wisselen.

    Dan zie je er één dubbel op pagina 1 en mis je er één op pagina 2. Daarom wordt er ook
    op id gesorteerd, niet alleen op tijd.
    """
    await _log(session, owner, 30)

    gezien = []
    for offset in (0, 10, 20):
        pagina = (
            await client.get(f"/activity?limit=10&offset={offset}", headers=auth_headers(owner))
        ).json()
        gezien.extend(regel["id"] for regel in pagina["items"])

    assert len(gezien) == 30
    assert len(set(gezien)) == 30


async def test_filteren_op_soort_gebeurtenis(client: AsyncClient, owner: User, session) -> None:
    await _log(session, owner, 3)
    session.add(
        ActivityLogEntry(user_id=owner.id, action=ActivityAction.SKILL_CREATED, message="Skill")
    )
    await session.commit()

    body = (
        await client.get("/activity?action=SKILL_CREATED", headers=auth_headers(owner))
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["action"] == "SKILL_CREATED"


async def test_je_ziet_andermans_logboek_niet(
    client: AsyncClient, owner: User, trusted: User, session
) -> None:
    await _log(session, owner, 5)

    body = (await client.get("/activity", headers=auth_headers(trusted))).json()

    assert body["total"] == 0


# --- /schedule/today ---------------------------------------------------------


async def test_schedule_today_zet_uploads_en_taken_op_een_lijst(
    client: AsyncClient, owner: User, session
) -> None:
    kanaal = SocialChannel(
        user_id=owner.id,
        platform=SocialPlatform.YOUTUBE,
        channel_name="Mijn kanaal",
        status=ChannelStatus.CONNECTED,
    )
    session.add(kanaal)
    await session.flush()
    session.add(
        UploadSchedule(
            channel_id=kanaal.id,
            title="Aflevering 12",
            content_type=ContentType.VIDEO,
            scheduled_at=VANDAAG.replace(hour=9, minute=0),
            status=UploadStatus.SCHEDULED,
        )
    )
    session.add(
        MissionTask(
            user_id=owner.id,
            title="Bank bijwerken",
            status=MissionStatus.PLANNED,
            scheduled_for=VANDAAG.replace(hour=7, minute=0),
        )
    )
    await session.commit()

    body = (await client.get("/schedule/today", headers=auth_headers(owner))).json()

    assert body["total"] == 2
    assert body["open"] == 2
    # Op tijd gesorteerd, ongeacht uit welke tabel ze komen.
    assert [regel["kind"] for regel in body["items"]] == ["task", "upload"]


async def test_morgen_staat_niet_op_de_lijst_van_vandaag(
    client: AsyncClient, owner: User, session
) -> None:
    session.add(
        MissionTask(
            user_id=owner.id,
            title="Morgen",
            status=MissionStatus.PLANNED,
            scheduled_for=VANDAAG + timedelta(days=1),
        )
    )
    await session.commit()

    body = (await client.get("/schedule/today", headers=auth_headers(owner))).json()

    assert body["total"] == 0


async def test_een_afgeronde_taak_telt_niet_meer_als_open(
    client: AsyncClient, owner: User, session
) -> None:
    session.add(
        MissionTask(
            user_id=owner.id,
            title="Al klaar",
            status=MissionStatus.DONE,
            scheduled_for=VANDAAG.replace(hour=8),
        )
    )
    await session.commit()

    body = (await client.get("/schedule/today", headers=auth_headers(owner))).json()

    assert body["total"] == 1
    assert body["open"] == 0


async def test_uploads_van_andermans_kanaal_staan_er_niet_bij(
    client: AsyncClient, owner: User, trusted: User, session
) -> None:
    """Een upload hangt aan een kanaal, niet aan een gebruiker.

    Zonder de join op het kanaal zie je die van iemand anders.
    """
    kanaal = SocialChannel(
        user_id=trusted.id,
        platform=SocialPlatform.YOUTUBE,
        channel_name="Van iemand anders",
        status=ChannelStatus.CONNECTED,
    )
    session.add(kanaal)
    await session.flush()
    session.add(
        UploadSchedule(
            channel_id=kanaal.id,
            title="Niet van jou",
            content_type=ContentType.VIDEO,
            scheduled_at=VANDAAG.replace(hour=9),
            status=UploadStatus.SCHEDULED,
        )
    )
    await session.commit()

    body = (await client.get("/schedule/today", headers=auth_headers(owner))).json()

    assert body["total"] == 0


def test_de_daggrenzen_liggen_in_utc() -> None:
    begin, eind = schedule_service.day_bounds(VANDAAG.date())

    assert begin.tzinfo is not None
    assert begin.hour == 0 and begin.minute == 0
    assert eind - begin == timedelta(days=1)


# --- /system/metrics ---------------------------------------------------------


async def test_systeemmetingen_zijn_alleen_voor_tier_1(
    client: AsyncClient, owner: User, trusted: User, limited: User
) -> None:
    assert (await client.get("/system/metrics", headers=auth_headers(owner))).status_code == 200
    assert (await client.get("/system/metrics", headers=auth_headers(trusted))).status_code == 403
    assert (await client.get("/system/metrics", headers=auth_headers(limited))).status_code == 403


async def test_de_metingen_zijn_echt(client: AsyncClient, owner: User) -> None:
    body = (await client.get("/system/metrics", headers=auth_headers(owner))).json()

    for veld in ("cpu_pct", "ram_pct", "disk_pct"):
        assert 0.0 <= body[veld] <= 100.0
    assert body["status"] in {"optimal", "warning"}
    assert body["boot_time"]


async def test_het_stoplicht_blijft_wel_voor_iedereen(
    client: AsyncClient, limited: User
) -> None:
    # /system is het paneel op het dashboard; /system/metrics gaat over de computer zelf.
    assert (await client.get("/system", headers=auth_headers(limited))).status_code == 200


# --- /memory/overview --------------------------------------------------------


async def test_memory_overview_telt_wat_ganz_onthoudt(
    client: AsyncClient, owner: User, session
) -> None:
    session.add_all(
        [
            MemoryEntry(user_id=owner.id, title="Koffie", content="Zonder suiker"),
            MemoryEntry(user_id=owner.id, title="Broer", content="Heet ook Ganz"),
            Conversation(user_id=owner.id, title="Eerste gesprek"),
        ]
    )
    await _log(session, owner, 3)

    body = (await client.get("/memory/overview", headers=auth_headers(owner))).json()

    assert body["memory_count"] == 2
    assert body["session_count"] == 1
    assert body["activity_count"] == 3
    assert len(body["recent_activity"]) == 3


async def test_memory_overview_vraagt_om_het_juiste_recht(
    client: AsyncClient, limited: User
) -> None:
    # memory.read is TIER_TRUSTED; limited is tier 3.
    assert (
        await client.get("/memory/overview", headers=auth_headers(limited))
    ).status_code == 403


# --- /skills/active ----------------------------------------------------------


async def test_skills_active_laat_alleen_de_actieve_zien(
    client: AsyncClient, owner: User, session
) -> None:
    session.add_all(
        [
            Skill(user_id=owner.id, name="Veel gebruikt", enabled=True, run_count=9),
            Skill(user_id=owner.id, name="Amper gebruikt", enabled=True, run_count=1),
            Skill(user_id=owner.id, name="Staat uit", enabled=False, run_count=99),
        ]
    )
    await session.commit()

    rijen = (await client.get("/skills/active", headers=auth_headers(owner))).json()

    assert [rij["name"] for rij in rijen] == ["Veel gebruikt", "Amper gebruikt"]


async def test_active_wordt_niet_als_skill_id_gelezen(
    client: AsyncClient, owner: User
) -> None:
    """FastAPI kijkt op volgorde. Stond /skills/{skill_id} eerder, dan was dit een 422."""
    antwoord = await client.get("/skills/active", headers=auth_headers(owner))

    assert antwoord.status_code == 200
    assert isinstance(antwoord.json(), list)


# --- Alles bij elkaar --------------------------------------------------------


@pytest.mark.parametrize(
    "pad",
    ["/status", "/activity", "/schedule/today", "/system/metrics", "/memory/overview",
     "/skills/active"],
)
async def test_geen_van_de_dashboard_endpoints_is_open(client: AsyncClient, pad: str) -> None:
    assert (await client.get(pad)).status_code == 401


async def test_de_cijfers_lekken_niet_via_het_stoplicht(
    client: AsyncClient, owner: User, limited: User
) -> None:
    """De tier-1-eis op /system/metrics stelt niets voor als /system dezelfde getallen geeft.

    Tier 3 hoort te zien dát alles draait, niet hoe zwaar de machine belast is.
    """
    volledig = (await client.get("/system", headers=auth_headers(owner))).json()
    beperkt = (await client.get("/system", headers=auth_headers(limited))).json()

    assert volledig["cpu_pct"] is not None
    assert volledig["boot_time"]

    assert beperkt["status"] in {"optimal", "warning"}
    assert "cpu_pct" not in beperkt
    assert "boot_time" not in beperkt


async def test_het_dashboardpaneel_maakt_hetzelfde_onderscheid(
    client: AsyncClient, owner: User, limited: User
) -> None:
    volledig = (await client.get("/dashboard", headers=auth_headers(owner))).json()["system"]
    beperkt = (await client.get("/dashboard", headers=auth_headers(limited))).json()["system"]

    assert volledig["cpu_pct"] is not None
    assert beperkt is not None  # het stoplicht blijft
    assert beperkt["cpu_pct"] is None
