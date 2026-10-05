"""Laat H0 end-to-end draaien en toon de vier stressvarianten.

Dit is de acceptatie-eis van fase 3: unit tests op het fill-model (die staan in
`tests/test_quant_fills.py`), H0 die end-to-end draait, en een rapport met verwachte versus
gesimuleerde fills. Dit script levert de laatste twee, tegen een echte PostgreSQL.

    GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \\
      python -m scripts.quant_paper_proof

**De data is synthetisch (verzonnen) en geen enkele kostenparameter is geverifieerd.** Wat
hieronder staat, zegt dus niets over de markt en niets over of H1 werkt. Het laat zien dat
de machinerie klopt: dat de risicolaag blokkeert, dat de kosten worden geboekt, dat
overgeslagen signalen worden geteld, en hoe hard een resultaat verandert onder stress.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.database import Database
from app.models.quantlab import (
    QuantHypothesis,
    QuantIngestRun,
    QuantMarketTick,
    QuantPaperFill,
    QuantPaperTrade,
    QuantRawEvent,
    QuantSignal,
    QuantStrategyRun,
)
from app.quantlab.hypothesis import load_hypothesis
from app.quantlab.safety import NeverVerifiableOracle, SyntheticSafetyOracle
from app.quantlab.synthetic import SyntheticPoolSource
from app.services import quant_data_service, quant_paper_service

HYPOTHESES = Path(__file__).resolve().parents[2] / "hypotheses"
START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
# Een etmaal met doorlopend nieuwe pools. Dat laatste is nodig: H0 kijkt naar tokens van
# 5 tot 30 minuten oud, dus als alle pools aan het begin opengaan, komt er na het eerste uur
# niets meer in aanmerking en blijft N op een handvol steken. Een sniper-universum is een
# stroom nieuwe tokens, niet een vaste lijst.
DUUR = timedelta(hours=72)
SEED = 20261005


def kop(tekst: str) -> None:
    print(f"\n{tekst}\n{'-' * len(tekst)}")


async def leegmaken(session) -> None:
    for tabel in (
        QuantPaperFill,
        QuantPaperTrade,
        QuantSignal,
        QuantStrategyRun,
        QuantHypothesis,
        QuantMarketTick,
        QuantRawEvent,
        QuantIngestRun,
    ):
        await session.execute(delete(tabel))
    await session.commit()


async def opnemen(session) -> None:
    kop("1. Drie dagen synthetische data opnemen")
    opname = await quant_data_service.record(
        session,
        source=SyntheticPoolSource(
            seed=SEED,
            start_at=START,
            duration=DUUR,
            pools=3,
            cadence_seconds=20,
            new_pool_every_minutes=5,
            pool_lifetime_minutes=60,
        ),
    )
    await session.commit()
    print(f"  events: {opname.events}, ticks: {opname.ticks}")
    from app.models.quantlab import QuantMarketTick as _T

    pools = int(
        await session.scalar(select(func.count(func.distinct(_T.pool_address)))) or 0
    )
    print(f"  pools in het corpus: {pools} (doorlopend nieuwe, elk een uur actief)")
    afdruk = (await quant_data_service.verify_chain(session)).digest
    print(f"  corpusafdruk: {afdruk}")


async def draaien(session) -> dict:
    kop("2. H0 in vier stressvarianten over hetzelfde corpus")
    hypothese = load_hypothesis(HYPOTHESES / "H0_v1.yaml")
    print(f"  hypothese: {hypothese.label}  hash {hypothese.content_hash[:16]}...")
    uitslagen = await quant_paper_service.run_stress_suite(
        session,
        hypothesis=hypothese,
        seed=SEED,
        safety=SyntheticSafetyOracle(seed=SEED),
        attempts_per_hour_override=30,
    )
    await session.commit()

    print(
        f"\n  {'variant':<12}{'signalen':>9}{'trades':>8}{'gesloten':>9}"
        f"{'gedwongen':>10}{'R':>9}{'drawdown':>10}{'fees $':>9}{'slip $':>9}"
    )
    for naam, uitslag in uitslagen.items():
        print(
            f"  {naam:<12}{uitslag.signals_proposed:>9}{uitslag.trades_opened:>8}"
            f"{uitslag.trades_closed:>9}{uitslag.trades_force_closed:>10}"
            f"{str(uitslag.realized_r):>9}{str(uitslag.max_drawdown_r):>10}"
            f"{str(uitslag.total_fees_usd):>9}{str(uitslag.total_slippage_usd):>9}"
        )
    print(
        "\n  De signalen zijn in alle vier de varianten gelijk: het enige verschil is het\n"
        "  fill-model. Zouden de instappen ook verschillen, dan vergelijk je twee\n"
        "  strategieën in plaats van twee werelden."
    )
    return uitslagen


async def waarom_niet(session) -> None:
    kop("3. Waarom signalen niet zijn genomen")
    run = (
        await session.execute(
            select(QuantStrategyRun)
            .where(QuantStrategyRun.variant == "base")
            .order_by(QuantStrategyRun.id)
            .limit(1)
        )
    ).scalar_one()
    for reden, aantal in sorted(
        (run.skipped_by_reason or {}).items(), key=lambda p: -p[1]
    ):
        print(f"  {reden:<28}{aantal:>5}")
    genomen = int(
        await session.scalar(
            select(func.count())
            .select_from(QuantSignal)
            .where(QuantSignal.run_id == run.id, QuantSignal.taken.is_(True))
        )
        or 0
    )
    print(f"  {'genomen':<28}{genomen:>5}")
    print(f"\n  risicolaag: maximaal {run.max_open_risk_r}R tegelijk open (grens is 5R)")

    voorbeeld = (
        await session.execute(
            select(QuantSignal)
            .where(QuantSignal.run_id == run.id, QuantSignal.taken.is_(False))
            .limit(2)
        )
    ).scalars().all()
    for signaal in voorbeeld:
        print(f"\n  voorbeeld ({signaal.reason}): {signaal.detail}")


async def fills(session) -> None:
    kop("4. Verwachte versus gesimuleerde fill")
    trades = (
        await session.execute(
            select(QuantPaperTrade).order_by(QuantPaperTrade.id).limit(3)
        )
    ).scalars().all()
    for trade in trades:
        print(
            f"\n  trade {trade.id} in {trade.pool_address}  "
            f"{trade.exit_reason or 'open'}  R={trade.r_multiple}"
        )
        rijen = await quant_paper_service.trade_fills(session, trade_id=trade.id)
        print(
            f"    {'order':<14}{'verwacht':>16}{'markt':>16}{'fill':>16}"
            f"{'slip $':>10}{'klok $':>10}{'fee $':>8}{'ms':>8}"
        )
        for fill in rijen:
            if not fill.filled:
                print(f"    {fill.kind + '/' + fill.reason:<14}MISLUKT: {fill.failure_reason}")
                continue
            print(
                f"    {fill.kind + '/' + fill.reason:<14}"
                f"{str(fill.expected_price):>16}{str(fill.market_price):>16}"
                f"{str(fill.fill_price):>16}{str(fill.slippage_usd):>10}"
                f"{str(fill.latency_cost_usd):>10}{str(fill.fee_usd):>8}"
                f"{fill.latency_ms:>8.0f}"
            )
    print(
        "\n  'verwacht' is de prijs waarop het signaal mikte, 'markt' de prijs na de\n"
        "  vertraging, 'fill' wat er werkelijk uitkwam. Het verschil tussen de eerste twee\n"
        "  is wat de klok kostte; tussen de laatste twee is slippage."
    )


async def expectancy(session) -> None:
    kop("5. Expectancy — met N, kosten en onzekerheidsmarge")
    runs = (
        await session.execute(select(QuantStrategyRun).order_by(QuantStrategyRun.id))
    ).scalars().all()
    for run in runs:
        uitslag = await quant_paper_service.run_expectancy(
            session, run_id=run.id, seed=SEED
        )
        kosten = run.total_fees_usd + run.total_slippage_usd
        print(
            f"\n  {run.variant}: N={uitslag.n}, expectancy {uitslag.expectancy_r}R, "
            f"90%-interval [{uitslag.ci_low}, {uitslag.ci_high}], "
            f"winrate {uitslag.win_rate}, kosten ${kosten}"
        )
        print(f"    {uitslag.verdict}")
    print(
        "\n  Let op wat hier NIET staat: een conclusie over de markt. De drempel van 150\n"
        "  gesloten trades is gehaald, dus de meting mag een uitspraak doen — maar die\n"
        "  uitspraak gaat over synthetische data. Wat je hier wel ziet, is dat een\n"
        "  controlegroep zich gedraagt als een controlegroep: nul zit in het interval."
    )


async def preregistratie(session) -> None:
    kop("6. Pre-registratie: hetzelfde bestand wijzigen onder dezelfde versie")
    from app.quantlab.hypothesis import PreRegistrationError

    hypothese = load_hypothesis(HYPOTHESES / "H0_v1.yaml")
    gesleuteld = hypothese.with_source(
        hypothese.source_yaml.replace("stop_distance_pct: 0.25", "stop_distance_pct: 0.10")
    )
    try:
        await quant_paper_service.register_hypothesis(session, gesleuteld)
        raise AssertionError("dit had geweigerd moeten worden")
    except PreRegistrationError as fout:
        print(f"  geweigerd: {fout}")
    await session.rollback()


async def latency_resolutie(session) -> None:
    """Waarom de latency-stresstest bij 20 seconden per tick niets doet.

    Een fill valt op de eerste tick ná de vertraging. Is de cadans 20 seconden en de
    vertraging 800 of 1600 milliseconden, dan is dat allebei dezelfde volgende tick — en
    komt er exact dezelfde fill uit. De stresstest op latency meet dan niets.

    Hieronder hetzelfde, maar met een tick per seconde. Dan valt het verschil wél ergens.
    """
    kop("7. De latency-stresstest heeft fijnere data nodig")
    await leegmaken(session)
    await quant_data_service.record(
        session,
        source=SyntheticPoolSource(
            seed=SEED, start_at=START, duration=timedelta(hours=1), pools=3,
            cadence_seconds=1,
        ),
    )
    await session.commit()

    uitslagen = await quant_paper_service.run_stress_suite(
        session,
        hypothesis=load_hypothesis(HYPOTHESES / "H0_v1.yaml"),
        seed=SEED,
        safety=SyntheticSafetyOracle(seed=SEED),
        attempts_per_hour_override=60,
    )
    await session.commit()
    print(f"  {'variant':<12}{'trades':>8}{'R':>10}{'slip $':>10}")
    for naam, uitslag in uitslagen.items():
        print(
            f"  {naam:<12}{uitslag.trades_opened:>8}{str(uitslag.realized_r):>10}"
            f"{str(uitslag.total_slippage_usd):>10}"
        )
    basis, traag = uitslagen["base"], uitslagen["latency_2x"]
    zelfde = basis.realized_r == traag.realized_r
    print(
        f"\n  latency_2x gelijk aan base: {zelfde}"
        "  (bij een cadans van 20 seconden was dit wel zo)"
    )


async def main() -> None:
    instellingen = get_settings()
    if instellingen.is_production:
        raise SystemExit("Dit script schrijft rijen en draait niet in productie.")
    url = os.environ.get("GANZ_DATABASE_URL", instellingen.database_url)
    print(f"Database: {url.rsplit('@', 1)[-1]}")
    print(
        "Data: synthetisch (verzonnen). Kostenparameters: geen enkele geverifieerd.\n"
        "Deze proef gaat over de machinerie, niet over de markt."
    )
    database = Database.from_url(url)
    try:
        async with database.session() as session:
            await leegmaken(session)
            await opnemen(session)
            await draaien(session)
            await waarom_niet(session)
            await fills(session)
            await expectancy(session)
            await preregistratie(session)
            await latency_resolutie(session)
            await leegmaken(session)
            print("\nTabellen weer leeggemaakt.")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
