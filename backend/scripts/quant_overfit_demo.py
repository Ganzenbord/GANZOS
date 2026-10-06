"""Waarom "een AI die aldoende leert" in traden bijna altijd zelfbedrog is.

Deze proef is er niet om iets te bouwen maar om iets te laten zien, en ze is bedoeld voor
iemand die geen trader is.

De opzet:

1. Twee corpora met **dezelfde** generator, alleen een ander zaad. Noem ze A en B.
2. Zes varianten van H0 — willekeurig instappen — met alleen een andere stopafstand.
3. Alle zes draaien op A. We kiezen de beste. Dat is precies wat "leren van de resultaten"
   doet.
4. Diezelfde zes draaien op B. We kijken waar de winnaar van A terechtkomt.

Het beslissende punt: **H0 stapt willekeurig in, dus er is per constructie geen edge.** Elk
verschil tussen de zes varianten is dus ruis — dat weten we hier zeker, en dat is precies
wat deze proef bruikbaar maakt. Als het "leren" op A toch een duidelijke winnaar vindt, dan
weten we dat die winnaar niets betekent.

    GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_proef \\
      python -m scripts.quant_overfit_demo
"""

from __future__ import annotations

import asyncio
import os
import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

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
from app.quantlab.safety import AlwaysSafeOracle
from app.quantlab.synthetic import SyntheticPoolSource
from app.services import quant_data_service, quant_paper_service

HYPOTHESES = Path(__file__).resolve().parents[2] / "hypotheses"
START = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
DUUR = timedelta(hours=18)
STOPS = ("0.15", "0.20", "0.25", "0.30", "0.35", "0.40")
TABELLEN = (
    QuantPaperFill, QuantPaperTrade, QuantSignal, QuantStrategyRun,
    QuantHypothesis, QuantMarketTick, QuantRawEvent, QuantIngestRun,
)


def kop(tekst: str) -> None:
    print(f"\n{tekst}\n{'-' * len(tekst)}")


def variant(stop: str):
    """H0 met een andere stopafstand, als eigen versie.

    Eigen versie omdat de pre-registratie dat eist: hetzelfde label met andere inhoud wordt
    geweigerd. Dat is hier geen hinder maar precies de discipline die wordt gedemonstreerd —
    elk experiment moet een naam hebben voordat het draait.
    """
    basis = load_hypothesis(HYPOTHESES / "H0_v1.yaml")
    tekst = basis.source_yaml.replace(
        "stop_distance_pct: 0.25", f"stop_distance_pct: {stop}"
    ).replace("name: H0", "name: H0SWEEP").replace(
        "version: v1", f"version: s{stop.replace('.', '')}"
    )
    return basis.with_source(tekst)


async def corpus(session, *, seed: int) -> None:
    for tabel in TABELLEN:
        await session.execute(delete(tabel))
    await session.commit()
    await quant_data_service.record(
        session,
        source=SyntheticPoolSource(
            seed=seed, start_at=START, duration=DUUR, pools=3, cadence_seconds=20,
            new_pool_every_minutes=5, pool_lifetime_minutes=60,
        ),
    )
    await session.commit()


async def sweep(session, *, label: str) -> dict[str, tuple]:
    uit: dict[str, tuple] = {}
    for stop in STOPS:
        uitslag = await quant_paper_service.run_hypothesis(
            session,
            hypothesis=variant(stop),
            seed=777,
            safety=AlwaysSafeOracle(),
            attempts_per_hour_override=60,
        )
        await session.commit()
        run = (
            await session.execute(
                select(QuantStrategyRun).order_by(QuantStrategyRun.id.desc()).limit(1)
            )
        ).scalar_one()
        meting = await quant_paper_service.run_expectancy(session, run_id=run.id, seed=1)
        geblokkeerd = (uitslag.skipped_by_reason or {}).get("risk_veto", 0)
        uit[stop] = (
            meting.n,
            meting.expectancy_r or Decimal("0"),
            uitslag.realized_r,
            geblokkeerd,
        )
    return uit


def tabel(label: str, resultaten: dict[str, tuple]) -> None:
    print(f"\n  {label}")
    print(
        f"    {'stop':>6} | {'trades':>6} | {'expectancy':>11} | {'totaal R':>9}"
        f" | {'door risicolaag geblokkeerd':>27}"
    )
    for stop, (n, exp, totaal, geblokkeerd) in resultaten.items():
        print(
            f"    {stop:>6} | {n:>6} | {str(exp):>11} | {str(totaal):>9}"
            f" | {geblokkeerd:>27}"
        )


async def main() -> None:
    instellingen = get_settings()
    if instellingen.is_production:
        raise SystemExit("Dit script schrijft rijen en draait niet in productie.")
    url = os.environ.get("GANZ_DATABASE_URL", instellingen.database_url)
    print(f"Database: {url.rsplit('@', 1)[-1]}")
    print(
        "H0 stapt willekeurig in, dus er is per constructie GEEN edge.\n"
        "Elk verschil tussen de varianten hieronder is dus ruis. Dat weten we zeker."
    )

    database = Database.from_url(url)
    try:
        async with database.session() as session:
            kop("1. Zes stopafstanden op corpus A")
            await corpus(session, seed=1111)
            a = await sweep(session, label="A")
            tabel("corpus A", a)

            beste = max(a, key=lambda s: a[s][1])
            slechtste = min(a, key=lambda s: a[s][1])
            print(
                f"\n  'Leren' zou nu kiezen: stop {beste} "
                f"(expectancy {a[beste][1]}R, de beste van de zes)."
            )
            print(
                f"  Het verschil met de slechtste ({slechtste}, {a[slechtste][1]}R) is "
                f"{a[beste][1] - a[slechtste][1]}R per trade."
            )
            print("  Dat lijkt een echt verschil. Het is het niet.")
            print(
                "\n  Kijk ook naar de laatste kolom. De varianten met weinig trades zijn\n"
                "  vroeg op een slechte dag tegen de dagstop van -3R aangelopen en daarna\n"
                "  voor de rest van het corpus op slot gezet. Ze kregen dus niet alleen\n"
                "  pech, ze kregen ook geen kans meer om die pech uit te vlakken. Een 'AI\n"
                "  die leert' zou dat lezen als 'die stopafstand is slecht'."
            )

            kop("2. Dezelfde zes op corpus B — alleen een ander zaad")
            await corpus(session, seed=2222)
            b = await sweep(session, label="B")
            tabel("corpus B", b)

            rang_b = sorted(b, key=lambda s: b[s][1], reverse=True)
            plek = rang_b.index(beste) + 1
            print(
                f"\n  De winnaar van A (stop {beste}) staat op corpus B op plek "
                f"{plek} van {len(STOPS)}, met {b[beste][1]}R."
            )
            print(f"  De winnaar op B is stop {rang_b[0]} met {b[rang_b[0]][1]}R.")

            kop("3. Wat dit betekent")
            spreiding_a = statistics.pstdev([float(a[s][1]) for s in STOPS])
            spreiding_b = statistics.pstdev([float(b[s][1]) for s in STOPS])
            print(
                f"  De spreiding tussen de varianten is op A {spreiding_a:.4f}R en op B "
                f"{spreiding_b:.4f}R."
            )
            print(
                "  Die spreiding is er terwijl er geen edge is. Hij komt dus volledig uit\n"
                "  het toeval van welke trades er net wel en net niet in vielen."
            )

            alle_r = [float(a[s][1]) for s in STOPS] + [float(b[s][1]) for s in STOPS]
            print(
                f"\n  Over alle twaalf runs samen: gemiddelde expectancy "
                f"{statistics.fmean(alle_r):+.4f}R. Dat is waar H0 hoort uit te komen: nul."
            )

            kop("4. Hoeveel trades heb je nodig om een echte edge te zien?")
            rijen = (
                await session.execute(
                    select(QuantPaperTrade.r_multiple).where(
                        QuantPaperTrade.r_multiple.is_not(None)
                    )
                )
            ).scalars().all()
            sd = statistics.pstdev([float(r) for r in rijen])
            print(f"  Gemeten spreiding van de uitkomsten: {sd:.3f}R per trade (N={len(rijen)}).")
            print(f"\n    {'edge per trade':>15} | {'trades nodig':>13}")
            for edge in (0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
                nodig = (1.645 * sd / edge) ** 2
                print(f"    {edge:>14.2f}R | {nodig:>13.0f}")
            bij_150 = 1.645 * sd / (150 ** 0.5)
            print(
                f"\n  Bij de drempel van 150 trades uit je eigen opdracht kun je een edge\n"
                f"  van ongeveer {bij_150:.2f}R per trade zien. Alles wat kleiner is, is op\n"
                f"  dat moment niet te onderscheiden van nul."
            )

            for tabel_naam in TABELLEN:
                await session.execute(delete(tabel_naam))
            await session.commit()
            print("\nTabellen weer leeggemaakt.")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
