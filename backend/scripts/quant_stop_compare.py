"""Vergelijk een vaste stop van 25% met een stop die per trade uit de structuur volgt.

Een structurele stop is alleen beter als je kunt laten zien dát hij beter is. Daarom draaien
beide vormen hier over hetzelfde corpus met hetzelfde zaad: dan proberen ze exact dezelfde
instappen en is het enige verschil waar de stop komt te liggen.

    GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \\
      python -m scripts.quant_stop_compare

**De data is synthetisch en geen kostenparameter is geverifieerd.** Wat hieronder staat zegt
dus niets over de markt. Wat het wel laat zien: hoe de twee vormen zich tegenover elkaar
gedragen, en of de afgeleide ondergrens van 20% vaak bindt.
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
from app.quantlab.safety import SyntheticSafetyOracle
from app.quantlab.synthetic import SyntheticPoolSource
from app.services import quant_data_service, quant_paper_service

HYPOTHESES = Path(__file__).resolve().parents[2] / "hypotheses"
START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
DUUR = timedelta(hours=48)
SEED = 20261006


def kop(tekst: str) -> None:
    print(f"\n{tekst}\n{'-' * len(tekst)}")


async def leegmaken(session) -> None:
    for tabel in (
        QuantPaperFill, QuantPaperTrade, QuantSignal, QuantStrategyRun,
        QuantHypothesis, QuantMarketTick, QuantRawEvent, QuantIngestRun,
    ):
        await session.execute(delete(tabel))
    await session.commit()


async def main() -> None:
    instellingen = get_settings()
    if instellingen.is_production:
        raise SystemExit("Dit script schrijft rijen en draait niet in productie.")
    url = os.environ.get("GANZ_DATABASE_URL", instellingen.database_url)
    print(f"Database: {url.rsplit('@', 1)[-1]}")
    print("Data: synthetisch. Kostenparameters: geen geverifieerd.")
    print(f"Papieren rekening: $ {instellingen.quant_paper_equity_usd} "
          f"(1R = $ {instellingen.quant_paper_equity_usd * Decimal('0.0075')})")

    database = Database.from_url(url)
    try:
        async with database.session() as session:
            await leegmaken(session)

            kop("1. Twee dagen opnemen")
            opname = await quant_data_service.record(
                session,
                source=SyntheticPoolSource(
                    seed=SEED, start_at=START, duration=DUUR, pools=3,
                    cadence_seconds=20, new_pool_every_minutes=5,
                    pool_lifetime_minutes=60,
                ),
            )
            await session.commit()
            print(f"  {opname.events} events, {opname.ticks} ticks")

            kop("2. Dezelfde instappen, twee manieren om de stop te zetten")
            uitslagen = {}
            for naam in ("H0_v1", "H0_v2"):
                uitslagen[naam] = await quant_paper_service.run_hypothesis(
                    session,
                    hypothesis=load_hypothesis(HYPOTHESES / f"{naam}.yaml"),
                    seed=SEED,
                    safety=SyntheticSafetyOracle(seed=SEED),
                    attempts_per_hour_override=30,
                )
                await session.commit()

            print(f"  {'hypothese':<10} | {'stop':<22} | {'signalen':>8} | {'trades':>6}"
                  f" | {'R':>9} | {'drawdown':>9} | {'slip $':>10}")
            for naam, uitslag in uitslagen.items():
                soort = "vast 25%" if naam.endswith("v1") else "per trade (structuur)"
                print(f"  {naam:<10} | {soort:<22} | {uitslag.signals_proposed:>8}"
                      f" | {uitslag.trades_opened:>6} | {str(uitslag.realized_r):>9}"
                      f" | {str(uitslag.max_drawdown_r):>9}"
                      f" | {str(uitslag.total_slippage_usd):>10}")

            kop("3. Hoe de stop per trade uitpakt")
            runs = (
                await session.execute(select(QuantStrategyRun).order_by(QuantStrategyRun.id))
            ).scalars().all()
            for run in runs:
                hyp = await session.get(QuantHypothesis, run.hypothesis_id)
                rij = (
                    await session.execute(
                        select(
                            func.min(QuantPaperTrade.stop_distance_pct),
                            func.avg(QuantPaperTrade.stop_distance_pct),
                            func.max(QuantPaperTrade.stop_distance_pct),
                            func.count(),
                        ).where(QuantPaperTrade.run_id == run.id)
                    )
                ).one()
                laagste, gemiddeld, hoogste, aantal = rij
                vast = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(QuantPaperTrade)
                        .where(
                            QuantPaperTrade.run_id == run.id,
                            QuantPaperTrade.stop_clamped.is_not(None),
                        )
                    ) or 0
                )
                print(
                    f"\n  {hyp.name}_{hyp.version}: {aantal} trades, stopafstand "
                    f"{laagste}-{hoogste} (gemiddeld "
                    f"{Decimal(str(gemiddeld)).quantize(Decimal('0.0001'))})"
                )
                print(f"    tegen een grens aangelopen: {vast} van {aantal}")

                voorbeeld = (
                    await session.execute(
                        select(QuantPaperTrade)
                        .where(QuantPaperTrade.run_id == run.id)
                        .order_by(QuantPaperTrade.id)
                        .limit(2)
                    )
                ).scalars().all()
                for trade in voorbeeld:
                    print(f"    trade {trade.id}: {trade.stop_distance_pct} "
                          f"({trade.stop_clamped or 'niet begrensd'}) — {trade.stop_basis}")

            kop("4. Expectancy van beide vormen")
            for run in runs:
                hyp = await session.get(QuantHypothesis, run.hypothesis_id)
                uit = await quant_paper_service.run_expectancy(
                    session, run_id=run.id, seed=SEED
                )
                kosten = run.total_fees_usd + run.total_slippage_usd
                print(
                    f"\n  {hyp.name}_{hyp.version}: N={uit.n}, expectancy {uit.expectancy_r}R, "
                    f"90%-interval [{uit.ci_low}, {uit.ci_high}], kosten $ {kosten}"
                )
                print(f"    {uit.verdict}")
            print(
                "\n  Beide vormen horen rond nul uit te komen: H0 stapt willekeurig in. Een\n"
                "  verschil hier zegt iets over de sizing, niet over een edge — en over\n"
                "  synthetische data, dus niet over de markt."
            )

            await leegmaken(session)
            print("\nTabellen weer leeggemaakt.")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
