"""De datalaag en de replay van het Quant Lab (sectie 11 van de opdracht).

Weer de tests eerst, en hier is dat extra belangrijk: een replay-corpus dat niet exact
herhaalbaar is, merk je pas als je een resultaat probeert na te rekenen — en dan is de data
al weken oud en niet meer te repareren.

De acceptatie-eis van fase 2 staat in `test_een_opgenomen_uur_is_bit_voor_bit_herhaalbaar`:
een opgenomen uur moet bit-voor-bit herhaalbaar zijn met een identiek resultaat.
"""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.quantlab.dataquality import (
    CHECK_UITLEG,
    DataCheck,
    QualityVerdict,
    quality_report,
)
from app.quantlab.feed import RawEvent, canonical_hash, chain_step
from app.quantlab.normalize import TickKind, tick_digest
from app.quantlab.synthetic import SyntheticDefect, SyntheticPoolSource

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Een vast startmoment: een uur dat elke keer hetzelfde uur is.
START = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
UUR = timedelta(hours=1)


def bron(**kwargs) -> SyntheticPoolSource:
    """Drie pools, een tick per tien seconden. Een uur is dan ruim duizend events."""
    opties = dict(
        seed=20261007, start_at=START, duration=UUR, pools=3, cadence_seconds=10
    )
    opties.update(kwargs)
    return SyntheticPoolSource(**opties)


# --- De synthetische bron ----------------------------------------------------


async def test_de_synthetische_bron_is_reproduceerbaar() -> None:
    """Zonder een bron die zich exact herhaalt, is er niets om replay tegen af te meten."""
    eerst = [event.payload_raw async for event in bron().events()]
    nogmaals = [event.payload_raw async for event in bron().events()]
    assert eerst == nogmaals
    assert len(eerst) > 1000, f"een uur hoort meer dan duizend events te geven, niet {len(eerst)}"


async def test_een_andere_seed_geeft_andere_data() -> None:
    assert [e.payload_raw async for e in bron().events()] != [
        e.payload_raw async for e in bron(seed=1).events()
    ]


async def test_de_synthetische_bron_heeft_geen_drift() -> None:
    """De prijzen mogen niet systematisch oplopen, en dit is geen smaakkwestie.

    Dit stond eerst fout: met een factor (1 + u) en u uit uniform(-0,04, +0,045) liep de
    prijs over een etmaal een factor 15.800 op. De controlegroep H0 — die willekeurig
    instapt — kwam daardoor uit op +8R met een winrate van 100%. Dat ziet er geloofwaardig
    uit en berust op niets. Een ruisvloer die geld verdient, is geen ruisvloer.
    """
    import json
    import math

    prijzen: dict[str, list[float]] = {}
    async for event in bron(duration=timedelta(hours=6)).events():
        payload = json.loads(event.payload_raw)
        if payload.get("type") != "tick":
            continue
        prijzen.setdefault(payload["pool"], []).append(float(payload["price_usd"]))

    for pool, reeks in prijzen.items():
        stappen = [
            math.log(reeks[i] / reeks[i - 1])
            for i in range(1, len(reeks))
            if reeks[i] > 0 and reeks[i - 1] > 0
        ]
        gemiddeld = sum(stappen) / len(stappen)
        # Ruim binnen wat je bij een drift van nul verwacht; bij de oude bron was dit
        # +0,0022 en viel deze test dus om.
        assert abs(gemiddeld) < 0.0005, f"{pool} heeft een drift van {gemiddeld:+.6f} per stap"


async def test_de_synthetische_bron_noemt_zichzelf_synthetisch() -> None:
    """Niemand mag deze data ooit voor echte marktdata kunnen aanzien."""
    assert bron().name == "synthetic"
    async for event in bron().events():
        assert event.source == "synthetic"
        break


# --- Ruwe opslag en de ketting -----------------------------------------------


def test_de_hash_gaat_over_de_tekst_en_niet_over_de_betekenis() -> None:
    """Twee JSON-documenten met dezelfde betekenis maar andere tekst zijn niet hetzelfde
    event. De ruwe opslag bewaart tekst, niet een geparste structuur — anders is
    "bit-voor-bit" een woord zonder inhoud."""
    a = '{"a":1,"b":2}'
    b = '{"b": 2, "a": 1}'
    assert json.loads(a) == json.loads(b)
    assert canonical_hash(a) != canonical_hash(b)


def test_de_ketting_sluit_aan() -> None:
    eerste = chain_step(None, canonical_hash("{}"))
    tweede = chain_step(eerste, canonical_hash('{"x":1}'))
    assert len(eerste) == 64 and len(tweede) == 64
    assert tweede != eerste
    # Dezelfde stap geeft dezelfde uitkomst; dat is wat hem narekenbaar maakt.
    assert chain_step(eerste, canonical_hash('{"x":1}')) == tweede


async def test_een_ruw_event_wordt_opgeslagen_zoals_het_binnenkwam(session) -> None:
    from app.models.quantlab import QuantRawEvent
    from app.services import quant_data_service

    tekst = '{"b": 2, "a": 1,   "spaties": "blijven staan"}'
    event = RawEvent(
        source="synthetic", stream="pairs", payload_raw=tekst, received_at=START
    )
    await quant_data_service.store_events(session, [event])
    await session.commit()

    rij = (await session.execute(select(QuantRawEvent))).scalar_one()
    assert rij.payload_raw == tekst, "de tekst is onderweg veranderd"
    assert rij.payload_hash == canonical_hash(tekst)
    assert rij.chain_hash == chain_step(None, rij.payload_hash)


async def test_de_volgorde_van_opslag_is_de_volgorde_van_binnenkomst(session) -> None:
    from app.models.quantlab import QuantRawEvent
    from app.services import quant_data_service

    events = [
        RawEvent(
            source="synthetic",
            stream="pairs",
            payload_raw=json.dumps({"n": n}),
            received_at=START + timedelta(seconds=n),
        )
        for n in range(5)
    ]
    await quant_data_service.store_events(session, events)
    await session.commit()

    rijen = (
        (await session.execute(select(QuantRawEvent).order_by(QuantRawEvent.seq)))
        .scalars()
        .all()
    )
    assert [json.loads(r.payload_raw)["n"] for r in rijen] == [0, 1, 2, 3, 4]
    assert [r.seq for r in rijen] == sorted(r.seq for r in rijen)


async def test_een_dubbel_event_wordt_bewaard_en_gemarkeerd(session) -> None:
    """Niet weggooien: de opslag is append-only. Wel markeren, zodat je het kunt tellen."""
    from app.models.quantlab import QuantRawEvent
    from app.services import quant_data_service

    tekst = '{"zelfde": true}'
    for seconde in (0, 1):
        await quant_data_service.store_events(
            session,
            [
                RawEvent(
                    source="synthetic",
                    stream="pairs",
                    payload_raw=tekst,
                    received_at=START + timedelta(seconds=seconde),
                )
            ],
        )
    await session.commit()

    rijen = (
        (await session.execute(select(QuantRawEvent).order_by(QuantRawEvent.seq)))
        .scalars()
        .all()
    )
    assert len(rijen) == 2, "een dubbel event mag niet verdwijnen"
    assert rijen[0].duplicate_of_id is None
    assert rijen[1].duplicate_of_id == rijen[0].id


async def test_een_aangepaste_rij_valt_door_de_mand(session) -> None:
    """De ketting is er om te zien dát iemand in de data heeft gezeten."""
    from app.models.quantlab import QuantRawEvent
    from app.services import quant_data_service

    await quant_data_service.store_events(
        session,
        [
            RawEvent(
                source="synthetic",
                stream="pairs",
                payload_raw=json.dumps({"n": n}),
                received_at=START + timedelta(seconds=n),
            )
            for n in range(4)
        ],
    )
    await session.commit()
    assert (await quant_data_service.verify_chain(session)).ok is True

    tweede = (
        await session.execute(
            select(QuantRawEvent).order_by(QuantRawEvent.seq).offset(1).limit(1)
        )
    ).scalar_one()
    await session.execute(
        update(QuantRawEvent)
        .where(QuantRawEvent.id == tweede.id)
        .values(payload_raw='{"n": 99}')
    )
    await session.commit()

    uitslag = await quant_data_service.verify_chain(session)
    assert uitslag.ok is False
    assert uitslag.first_bad_seq == tweede.seq
    assert "aangepast" in uitslag.explanation.lower() or "veranderd" in uitslag.explanation.lower()


# --- Normaliseren -------------------------------------------------------------


async def test_een_event_wordt_omgezet_naar_een_tick(session) -> None:
    from app.models.quantlab import QuantMarketTick
    from app.services import quant_data_service

    opname = await quant_data_service.record(session, source=bron())
    await session.commit()

    assert opname.events > 1000
    assert opname.ticks > 0
    ticks = (await session.execute(select(QuantMarketTick).limit(5))).scalars().all()
    assert ticks
    for tick in ticks:
        assert tick.pool_address
        assert tick.observed_at.tzinfo is not None
        assert tick.raw_event_id is not None


async def test_een_onleesbaar_event_wordt_niet_gerepareerd(session) -> None:
    """Sectie 10: nooit repareren. Het ruwe event blijft staan, er komt geen tick, en het
    wordt geteld — zodat een stukgelopen feed zichtbaar is in plaats van stil."""
    from app.models.quantlab import QuantMarketTick, QuantRawEvent
    from app.services import quant_data_service

    opname = await quant_data_service.record(
        session,
        source=bron(duration=timedelta(minutes=2), defects={SyntheticDefect.BROKEN_JSON}),
    )
    await session.commit()

    assert opname.parse_failures > 0
    rijen = (await session.execute(select(QuantRawEvent))).scalars().all()
    assert len(rijen) == opname.events, "ook een onleesbaar event hoort in de ruwe opslag"
    ticks = (await session.execute(select(QuantMarketTick))).scalars().all()
    assert len(ticks) == opname.ticks < opname.events


async def test_prijzen_gaan_niet_door_een_float(session) -> None:
    """Een prijs van 0,000000123 die door een float gaat, komt er anders uit. Daarom wordt
    JSON geparsed met Decimal en niet met float."""
    from app.models.quantlab import QuantMarketTick
    from app.services import quant_data_service

    tekst = json.dumps(
        {
            "type": "tick",
            "pool": "pool-1",
            "token": "token-1",
            "venue": "synthetic-dex",
            "chain": "synthetic",
            "observed_at": START.isoformat(),
            "price_usd": "0.000000123456",
            "liquidity_usd": "12345.67",
            "volume_usd": "100.00",
            "volume_window_seconds": 60,
        }
    )
    await quant_data_service.store_events(
        session,
        [RawEvent(source="synthetic", stream="ticks", payload_raw=tekst, received_at=START)],
    )
    await quant_data_service.normalize_pending(session)
    await session.commit()

    tick = (await session.execute(select(QuantMarketTick))).scalar_one()
    assert tick.price_usd == Decimal("0.000000123456")


# --- Replay: de acceptatie-eis van fase 2 ------------------------------------


async def test_een_opgenomen_uur_is_bit_voor_bit_herhaalbaar(session) -> None:
    """De eis uit sectie 14: een opgenomen uur data is bit-voor-bit replaybaar met een
    identiek resultaat.

    "Identiek" wordt hier niet met het oog vastgesteld maar met een afdruk over alle
    genormaliseerde ticks. De ruwe tabel blijft onaangeroerd; alleen het afgeleide deel
    wordt weggegooid en opnieuw opgebouwd.
    """
    from app.models.quantlab import QuantMarketTick, QuantRawEvent
    from app.services import quant_data_service

    opname = await quant_data_service.record(session, source=bron())
    await session.commit()
    eerste_afdruk = await quant_data_service.normalized_digest(session)
    ruwe_afdruk = (await quant_data_service.verify_chain(session)).digest
    aantal_ruw = len((await session.execute(select(QuantRawEvent))).scalars().all())
    aantal_ticks = len((await session.execute(select(QuantMarketTick))).scalars().all())

    herhaling = await quant_data_service.replay(session)
    await session.commit()

    assert herhaling.events == opname.events
    assert herhaling.ticks == opname.ticks
    assert herhaling.digest == eerste_afdruk, "de replay gaf een ander resultaat"
    assert (await quant_data_service.verify_chain(session)).digest == ruwe_afdruk
    assert len((await session.execute(select(QuantRawEvent))).scalars().all()) == aantal_ruw
    assert (
        len((await session.execute(select(QuantMarketTick))).scalars().all()) == aantal_ticks
    )


async def test_de_afdruk_verandert_als_er_een_tick_anders_is(session) -> None:
    """Een afdruk die bij elke data hetzelfde blijft, bewijst niets. Deze test is er om de
    vorige te laten gelden."""
    from app.models.quantlab import QuantMarketTick
    from app.services import quant_data_service

    await quant_data_service.record(
        session, source=bron(duration=timedelta(minutes=5))
    )
    await session.commit()
    voor = await quant_data_service.normalized_digest(session)

    eerste = (
        await session.execute(select(QuantMarketTick).order_by(QuantMarketTick.id).limit(1))
    ).scalar_one()
    await session.execute(
        update(QuantMarketTick)
        .where(QuantMarketTick.id == eerste.id)
        .values(price_usd=Decimal("1.5"))
    )
    await session.commit()

    assert await quant_data_service.normalized_digest(session) != voor


async def test_replay_van_een_tijdvenster_geeft_alleen_dat_venster(session) -> None:
    from app.services import quant_data_service

    await quant_data_service.record(session, source=bron())
    await session.commit()

    half = await quant_data_service.replay(
        session, since=START, until=START + timedelta(minutes=30)
    )
    await session.commit()
    heel = await quant_data_service.replay(session)
    await session.commit()

    assert 0 < half.events < heel.events


async def test_een_gat_in_de_ketting_stopt_de_replay(session) -> None:
    """Replayen van data waarvan je niet weet of hij nog klopt, levert een getal op waar je
    niets aan hebt. Dus: eerst de ketting, dan de replay."""
    from app.models.quantlab import QuantRawEvent
    from app.services import quant_data_service

    await quant_data_service.record(
        session, source=bron(duration=timedelta(minutes=2))
    )
    await session.commit()

    eerste = (
        await session.execute(select(QuantRawEvent).order_by(QuantRawEvent.seq).limit(1))
    ).scalar_one()
    await session.execute(
        update(QuantRawEvent).where(QuantRawEvent.id == eerste.id).values(payload_raw="{}")
    )
    await session.commit()

    with pytest.raises(quant_data_service.CorpusBroken):
        await quant_data_service.replay(session)


# --- Datakwaliteit ------------------------------------------------------------


@pytest.mark.parametrize(
    ("defect", "check"),
    [
        (SyntheticDefect.GAP, DataCheck.GAP),
        (SyntheticDefect.ZERO_PRICE, DataCheck.ZERO_OR_NEGATIVE_PRICE),
        (SyntheticDefect.NEGATIVE_PRICE, DataCheck.ZERO_OR_NEGATIVE_PRICE),
        (SyntheticDefect.ROUNDED_PRICE, DataCheck.ROUNDED_PRICE),
        (SyntheticDefect.OUT_OF_ORDER, DataCheck.OUT_OF_ORDER),
        (SyntheticDefect.FUTURE_TIMESTAMP, DataCheck.FUTURE_TIMESTAMP),
        (SyntheticDefect.DUPLICATE, DataCheck.DUPLICATE),
        (SyntheticDefect.BROKEN_JSON, DataCheck.PARSE_FAILURE),
    ],
)
async def test_elk_ingebouwd_gebrek_wordt_gemeld(session, defect, check) -> None:
    """Per gebrek één test, en de bron maakt het gebrek met opzet. Een controle die nooit
    iets vindt, is niet te onderscheiden van een controle die niet werkt."""
    from app.services import quant_data_service

    await quant_data_service.record(
        session, source=bron(duration=timedelta(minutes=20), defects={defect})
    )
    await session.commit()

    rapport = await quant_data_service.quality(session, now=START + UUR)
    bevinding = {b.check: b for b in rapport.findings}
    assert check in bevinding, f"{defect.value} is niet gemeld; gevonden: {list(bevinding)}"
    assert bevinding[check].count > 0
    assert bevinding[check].examples


async def test_een_schoon_uur_geeft_geen_alarm(session) -> None:
    from app.services import quant_data_service

    await quant_data_service.record(session, source=bron())
    await session.commit()

    rapport = await quant_data_service.quality(session, now=START + UUR)
    alarmen = [b for b in rapport.findings if b.severity is QualityVerdict.ALARM]
    assert alarmen == [], f"onverwacht alarm: {[b.check.value for b in alarmen]}"
    assert rapport.verdict is not QualityVerdict.ALARM


async def test_synthetische_data_wordt_altijd_gemeld(session) -> None:
    """Een corpus met verzonnen data mag nooit per ongeluk voor een resultaat doorgaan."""
    from app.services import quant_data_service

    await quant_data_service.record(
        session, source=bron(duration=timedelta(minutes=5))
    )
    await session.commit()

    rapport = await quant_data_service.quality(session, now=START + UUR)
    assert rapport.synthetic_events > 0
    assert "synthetisch" in rapport.explanation.lower()


def test_elke_controle_heeft_een_uitleg_in_gewone_taal() -> None:
    for check in DataCheck:
        assert len(CHECK_UITLEG[check]) > 20, check


def test_een_rapport_zonder_data_zegt_dat_er_geen_data_is() -> None:
    rapport = quality_report(ticks=[], raw_count=0, duplicates=0, parse_failures=0,
                             synthetic_events=0, now=START)
    assert rapport.verdict is QualityVerdict.NO_DATA
    assert "geen data" in rapport.explanation.lower()


# --- De Scout ----------------------------------------------------------------


async def test_de_scout_klopt_terwijl_hij_draait(database) -> None:
    """De hartslag uit fase 1 komt hiervandaan. Zonder kloppende Scout houdt de
    dead-man switch elke instap tegen, en dat is precies de bedoeling."""
    from app.models.quantlab import QuantHeartbeat
    from app.quantlab.scout import Scout

    scout = Scout(database, source=bron(duration=timedelta(minutes=2)), heartbeat_seconds=0)
    uitslag = await scout.run()

    async with database.session() as session:
        hartslag = (await session.execute(select(QuantHeartbeat))).scalar_one()
    assert hartslag.component == "scout"
    assert uitslag.events > 0


async def test_de_scout_schrijft_een_run_op(database) -> None:
    """Zonder runs is "hoeveel data hebben we" een vraag die je niet kunt beantwoorden."""
    from app.models.quantlab import QuantIngestRun
    from app.quantlab.scout import Scout

    uitslag = await Scout(
        database, source=bron(duration=timedelta(minutes=2)), heartbeat_seconds=0
    ).run()

    async with database.session() as session:
        run = (await session.execute(select(QuantIngestRun))).scalar_one()
    assert run.source == "synthetic"
    assert run.events == uitslag.events
    assert run.bytes_stored == uitslag.bytes_stored > 0
    assert run.stopped_at is not None
    assert run.stop_reason == "source_exhausted"


async def test_de_scout_stopt_als_je_hem_vraagt_te_stoppen(database) -> None:
    from app.models.quantlab import QuantIngestRun
    from app.quantlab.scout import Scout

    stop = asyncio.Event()
    scout = Scout(
        database,
        source=bron(duration=timedelta(hours=24)),
        heartbeat_seconds=0,
        batch_size=20,
    )

    async def even_laten_lopen() -> None:
        while scout.events_stored < 40:
            await asyncio.sleep(0)
        stop.set()

    uitslag, _ = await asyncio.gather(scout.run(stop=stop), even_laten_lopen())

    assert uitslag.stop_reason == "asked_to_stop"
    assert uitslag.events >= 40
    async with database.session() as session:
        run = (await session.execute(select(QuantIngestRun))).scalar_one()
    assert run.stop_reason == "asked_to_stop"


async def test_een_klapper_in_de_bron_sluit_de_run_netjes_af(database) -> None:
    """Een run die openblijft, is een gat in de boekhouding van het corpus."""
    from app.models.quantlab import QuantIngestRun
    from app.quantlab.scout import Scout

    class KapotteBron:
        name = "synthetic"

        def streams(self):
            return ("ticks",)

        async def events(self):
            yield RawEvent(
                source="synthetic",
                stream="ticks",
                payload_raw='{"type":"heartbeat"}',
                received_at=START,
            )
            raise RuntimeError("verbinding weg")

    with pytest.raises(RuntimeError):
        await Scout(database, source=KapotteBron(), heartbeat_seconds=0).run()

    async with database.session() as session:
        run = (await session.execute(select(QuantIngestRun))).scalar_one()
    assert run.stopped_at is not None
    assert run.stop_reason == "source_failed"


def test_de_scout_draait_niet_in_het_api_proces() -> None:
    """Advies uit fase 0: de datalaag hoort in een eigen proces.

    De scheduler in de API draait in hetzelfde proces als de verzoeken en heeft een
    jobstore in het geheugen. Een ingest die daar in hangt, concurreert met het bedienen
    van de app en laat na een herstart een gat achter dat je nooit meer kunt vullen.
    """
    bron_tekst = (APP_DIR / "workers" / "scheduler.py").read_text()
    boom = ast.parse(bron_tekst)
    modules = [
        naam
        for knoop in ast.walk(boom)
        if isinstance(knoop, (ast.Import, ast.ImportFrom))
        for naam in (
            [knoop.module or ""]
            if isinstance(knoop, ast.ImportFrom)
            else [a.name for a in knoop.names]
        )
    ]
    for module in modules:
        assert "quant" not in module, (
            f"de scheduler van de API importeert {module}; de datalaag hoort in een eigen "
            "proces (zie scripts/quant_scout.py)"
        )


# --- Opslag en groei ----------------------------------------------------------


async def test_de_opslaggroei_wordt_gemeten_en_niet_geschat(session) -> None:
    from app.services import quant_data_service

    opname = await quant_data_service.record(session, source=bron())
    await session.commit()

    stand = await quant_data_service.storage_report(session, now=START + UUR)
    assert stand.events == opname.events
    assert stand.bytes_stored == opname.bytes_stored
    assert stand.bytes_per_event > 0
    # Een uur opgenomen, dus de projectie per dag is 24 keer zoveel.
    assert stand.measured_seconds == pytest.approx(3600, rel=0.05)
    assert stand.projected_bytes_per_day > stand.bytes_stored


async def test_opruimen_vraagt_een_expliciete_grens(session) -> None:
    """Een replay-corpus dat zichzelf opruimt, is een corpus dat je niet kunt replayen."""
    from app.services import quant_data_service

    with pytest.raises(ValueError):
        await quant_data_service.prune_raw_events(session, older_than=None)


async def test_opruimen_haalt_alleen_weg_wat_ouder_is(session) -> None:
    from app.models.quantlab import QuantRawEvent
    from app.services import quant_data_service

    await quant_data_service.record(session, source=bron())
    await session.commit()
    voor = len((await session.execute(select(QuantRawEvent))).scalars().all())

    weg = await quant_data_service.prune_raw_events(
        session, older_than=START + timedelta(minutes=30)
    )
    await session.commit()
    na = len((await session.execute(select(QuantRawEvent))).scalars().all())
    assert 0 < weg < voor
    assert na == voor - weg


# --- Over HTTP ---------------------------------------------------------------


async def test_het_datakwaliteitsrapport_is_zichtbaar_vanaf_tier_2(client, trusted) -> None:
    from tests.conftest import auth_headers

    antwoord = await client.get("/quant/data/quality", headers=auth_headers(trusted))
    assert antwoord.status_code == 200, antwoord.text
    body = antwoord.json()
    assert body["verdict"] == QualityVerdict.NO_DATA.value
    assert body["checks"]


async def test_de_opslagstand_is_zichtbaar_vanaf_tier_2(client, trusted) -> None:
    from tests.conftest import auth_headers

    antwoord = await client.get("/quant/data/storage", headers=auth_headers(trusted))
    assert antwoord.status_code == 200, antwoord.text
    assert antwoord.json()["events"] == 0


async def test_een_gast_mag_de_datalaag_niet_zien(client, session) -> None:
    from app.core.security import hash_password
    from app.models.user import TIER_GUEST, User
    from tests.conftest import auth_headers

    gast = User(
        email="gast-data@example.com",
        display_name="Gast",
        password_hash=hash_password("geheim123"),
        tier=TIER_GUEST,
    )
    session.add(gast)
    await session.commit()

    for pad in ("/quant/data/quality", "/quant/data/storage", "/quant/data/runs"):
        assert (await client.get(pad, headers=auth_headers(gast))).status_code == 403, pad


def test_de_afdruk_van_een_tick_is_stabiel() -> None:
    """Dezelfde tick geeft dezelfde afdruk, ook na een rondje door de database.

    Daar zit de valkuil: PostgreSQL geeft een Numeric(30,12) terug met twaalf decimalen,
    dus 1,5 komt terug als 1,500000000000. Zou de afdruk de tekst van het getal gebruiken
    zoals hij toevallig is, dan verschilt hij voor en na het opslaan."""
    velden = dict(
        kind=TickKind.TICK,
        venue="synthetic-dex",
        chain="synthetic",
        pool_address="pool-1",
        token_address="token-1",
        observed_at=START,
        price_usd=Decimal("1.5"),
        liquidity_usd=Decimal("1000"),
        volume_usd=Decimal("10"),
        volume_window_seconds=60,
    )
    uit_geheugen = tick_digest([velden])
    uit_database = tick_digest([{**velden, "price_usd": Decimal("1.500000000000"),
                                 "liquidity_usd": Decimal("1000.00")}])
    assert uit_geheugen == uit_database
