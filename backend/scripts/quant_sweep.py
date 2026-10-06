"""Vijftig sessies met verschillende parameters, en een eerlijke selectie van de beste tien.

Wat dit doet, en waarom het in deze vorm staat:

1. Vijftig parameterstellen, elk een eigen voorgeregistreerde versie (de pre-registratie
   dwingt dat af: hetzelfde label met andere inhoud wordt geweigerd).
2. Alle vijftig op **corpus A**. Rangschikken op expectancy. De beste tien eruit.
3. Diezelfde vijftig ook op **corpus B** — andere data, zelfde generator.
4. Kijken waar de tien winnaars van A op B terechtkomen.

Stap 4 is het hele punt. "De beste tien van vijftig" is een keuze die altijd een antwoord
geeft, ook als er niets te kiezen valt. De vraag is niet welke tien bovenaan staan maar of
ze daar morgen nog staan.

Bij vijftig varianten is dat erger dan bij zes. Hoe meer je probeert, hoe extremer de
beste eruit ziet door toeval alleen — en dat is te berekenen. Zie stap 5.

**Alle data blijft staan.** Beide corpora staan naast elkaar in de database (verschillende
tijdvensters en pool-voorvoegsels), alle honderd runs blijven bewaard met hun trades,
fills en overgeslagen signalen, en er komt een CSV naast voor wie het in een
spreadsheet wil bekijken.

    GANZ_DATABASE_URL=postgresql+asyncpg://ganz:ganz@localhost:5432/ganz_sweep \\
      python -m scripts.quant_sweep

De data is synthetisch en geen kostenparameter is geverifieerd.
"""

from __future__ import annotations

import asyncio
import csv
import os
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import Database
from app.models.quantlab import QuantHypothesis, QuantPaperTrade, QuantStrategyRun
from app.quantlab.hypothesis import load_hypothesis
from app.quantlab.safety import AlwaysSafeOracle
from app.quantlab.synthetic import SyntheticPoolSource
from app.services import quant_data_service, quant_paper_service

HYPOTHESES = Path(__file__).resolve().parents[2] / "hypotheses"
UITVOER = Path(os.environ.get("GANZ_SWEEP_OUT", "/tmp/quant-sweep"))

# Twee corpora, naast elkaar in dezelfde tabellen: verschillende tijdvensters en
# verschillende pool-voorvoegsels, zodat ze niet in elkaar lopen en beide bewaard blijven.
CORPORA = {
    "A": dict(seed=1111, start=datetime(2026, 10, 5, tzinfo=timezone.utc), prefix="a"),
    "B": dict(seed=2222, start=datetime(2026, 11, 5, tzinfo=timezone.utc), prefix="b"),
}
DUUR = timedelta(hours=12)

# Het raster waaruit de vijftig stellen komen. Alle vier zijn exit-parameters; de
# risicogrenzen staan hardcoded en doen hier niet mee.
RASTER = {
    "stop_distance_pct": ["0.15", "0.20", "0.25", "0.30", "0.35", "0.40", "0.45"],
    "take_half_at_r": ["1.5", "2.0", "2.5", "3.0"],
    "trailing_stop_pct": ["0.15", "0.20", "0.25", "0.30"],
    "max_hold_minutes": ["60", "120", "240"],
}
AANTAL_SESSIES = 50
SWEEP_SEED = 20261006
TOP = 10


@dataclass(frozen=True)
class Sessie:
    nummer: int
    params: dict[str, str]

    @property
    def versie(self) -> str:
        return f"s{self.nummer:03d}"

    def hypothese(self):
        basis = load_hypothesis(HYPOTHESES / "H0_v1.yaml")
        tekst = basis.source_yaml
        for sleutel, waarde in self.params.items():
            # Elke regel staat één keer in het bestand, met twee spaties ervoor.
            oud = next(
                r for r in tekst.splitlines() if r.strip().startswith(f"{sleutel}:")
            )
            tekst = tekst.replace(oud, f"  {sleutel}: {waarde}")
        tekst = tekst.replace("name: H0", "name: H0SWEEP").replace(
            "version: v1", f"version: {self.versie}"
        )
        return basis.with_source(tekst)


def maak_sessies() -> list[Sessie]:
    """Vijftig stellen uit het raster, reproduceerbaar.

    Een steekproef en niet het hele raster van 336: met vijftig is het punt al gemaakt, en
    het hele raster zou de proef alleen langer maken zonder hem sterker te maken.
    """
    toeval = random.Random(SWEEP_SEED)
    gezien: set[tuple[str, ...]] = set()
    uit: list[Sessie] = []
    while len(uit) < AANTAL_SESSIES:
        keuze = {sleutel: toeval.choice(opties) for sleutel, opties in RASTER.items()}
        sleutel = tuple(keuze.values())
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        uit.append(Sessie(nummer=len(uit) + 1, params=keuze))
    return uit


def kop(tekst: str) -> None:
    print(f"\n{tekst}\n{'-' * len(tekst)}", flush=True)


async def corpus_opnemen(session, naam: str) -> str:
    opzet = CORPORA[naam]
    await quant_data_service.record(
        session,
        source=SyntheticPoolSource(
            seed=opzet["seed"], start_at=opzet["start"], duration=DUUR, pools=3,
            cadence_seconds=20, new_pool_every_minutes=5, pool_lifetime_minutes=60,
            pool_prefix=opzet["prefix"],
        ),
    )
    await session.commit()
    return (await quant_data_service.verify_chain(session)).digest or ""


async def draai(session, sessies: list[Sessie], naam: str) -> dict[int, dict]:
    opzet = CORPORA[naam]
    ticks = await quant_paper_service.load_ticks(
        session, since=opzet["start"], until=opzet["start"] + DUUR
    )
    print(f"  corpus {naam}: {len(ticks)} ticks", flush=True)

    uit: dict[int, dict] = {}
    for sessie in sessies:
        uitslag = await quant_paper_service.run_hypothesis(
            session,
            hypothesis=sessie.hypothese(),
            seed=777,
            safety=AlwaysSafeOracle(),
            attempts_per_hour_override=60,
            ticks=ticks,
        )
        await session.commit()
        run = (
            await session.execute(
                select(QuantStrategyRun).order_by(QuantStrategyRun.id.desc()).limit(1)
            )
        ).scalar_one()
        meting = await quant_paper_service.run_expectancy(session, run_id=run.id, seed=1)
        uit[sessie.nummer] = {
            "run_id": run.id,
            "n": meting.n,
            "expectancy": meting.expectancy_r or Decimal("0"),
            "ci_low": meting.ci_low,
            "ci_high": meting.ci_high,
            "realized_r": uitslag.realized_r,
            "drawdown_r": uitslag.max_drawdown_r,
            "fees_usd": uitslag.total_fees_usd,
            "slippage_usd": uitslag.total_slippage_usd,
            "risk_veto": (uitslag.skipped_by_reason or {}).get("risk_veto", 0),
        }
        if sessie.nummer % 10 == 0:
            print(f"    {sessie.nummer}/{len(sessies)} gedraaid", flush=True)
    return uit


def verwachte_beste(sd: float, n: int, varianten: int) -> float:
    """Hoe goed de beste van `varianten` eruit ziet als er GEEN edge is.

    De standaardfout van een gemiddelde is sd/sqrt(n). Het maximum van k normale
    trekkingen ligt gemiddeld ongeveer sqrt(2*ln(k)) standaardfouten boven nul. Bij vijftig
    varianten is dat een factor 2,8 — dus de beste van vijftig ziet er bijna drie
    standaardfouten goed uit, puur door te kiezen.
    """
    import math

    if n <= 0:
        return 0.0
    return sd / math.sqrt(n) * math.sqrt(2 * math.log(varianten))


async def main() -> None:
    instellingen = get_settings()
    if instellingen.is_production:
        raise SystemExit("Dit script schrijft rijen en draait niet in productie.")
    url = os.environ.get("GANZ_DATABASE_URL", instellingen.database_url)
    UITVOER.mkdir(parents=True, exist_ok=True)
    print(f"Database: {url.rsplit('@', 1)[-1]}")
    print(f"Uitvoer:  {UITVOER}")
    print("Data: synthetisch. Kostenparameters: geen geverifieerd.", flush=True)

    sessies = maak_sessies()
    database = Database.from_url(url)
    try:
        async with database.session() as session:
            kop("1. Twee corpora opnemen (beide blijven staan)")
            afdrukken = {}
            for naam in CORPORA:
                afdrukken[naam] = await corpus_opnemen(session, naam)
                print(f"  corpus {naam}: afdruk {afdrukken[naam][:16]}...", flush=True)

            kop(f"2. {AANTAL_SESSIES} sessies op corpus A")
            a = await draai(session, sessies, "A")

            kop(f"3. Dezelfde {AANTAL_SESSIES} sessies op corpus B")
            b = await draai(session, sessies, "B")

            # --- de gevraagde selectie ---
            kop(f"4. De beste {TOP} op corpus A — en waar ze op B staan")
            rang_a = sorted(a, key=lambda nr: a[nr]["expectancy"], reverse=True)
            rang_b = sorted(b, key=lambda nr: b[nr]["expectancy"], reverse=True)
            plek_b = {nr: i + 1 for i, nr in enumerate(rang_b)}

            print(
                f"  {'#':>3} | {'stop':>5} | {'half':>4} | {'trail':>5} | {'hold':>4}"
                f" | {'N':>4} | {'exp A':>8} | {'plek B':>6} | {'exp B':>8}"
            )
            for nr in rang_a[:TOP]:
                p = next(s for s in sessies if s.nummer == nr).params
                print(
                    f"  {nr:>3} | {p['stop_distance_pct']:>5} | {p['take_half_at_r']:>4}"
                    f" | {p['trailing_stop_pct']:>5} | {p['max_hold_minutes']:>4}"
                    f" | {a[nr]['n']:>4} | {str(a[nr]['expectancy']):>8}"
                    f" | {plek_b[nr]:>6} | {str(b[nr]['expectancy']):>8}"
                )

            gemiddelde_plek = statistics.fmean(plek_b[nr] for nr in rang_a[:TOP])
            print(
                f"\n  Gemiddelde plek op B van de top {TOP} van A: {gemiddelde_plek:.1f} "
                f"van {AANTAL_SESSIES}."
            )
            print(
                f"  Zouden de winnaars echt beter zijn, dan hoort dat rond "
                f"{(TOP + 1) / 2:.1f} te liggen. Puur toeval geeft "
                f"{(AANTAL_SESSIES + 1) / 2:.1f}."
            )

            kop("5. Hoe goed ziet de beste van vijftig eruit zonder edge?")
            r_waarden = [
                float(r)
                for r in (
                    await session.execute(
                        select(QuantPaperTrade.r_multiple).where(
                            QuantPaperTrade.r_multiple.is_not(None)
                        )
                    )
                ).scalars().all()
            ]
            sd = statistics.pstdev(r_waarden)
            gem_n = statistics.fmean(a[nr]["n"] for nr in a if a[nr]["n"] > 0)
            drempel = verwachte_beste(sd, int(gem_n), AANTAL_SESSIES)
            print(f"  Spreiding van de uitkomsten: {sd:.3f}R per trade ({len(r_waarden)} trades).")
            print(f"  Gemiddeld aantal trades per sessie: {gem_n:.0f}.")
            print(
                f"\n  Verwachte expectancy van de BESTE van {AANTAL_SESSIES} varianten als er\n"
                f"  geen enkele edge is: ongeveer +{drempel:.3f}R per trade."
            )
            beste_a = float(a[rang_a[0]]["expectancy"])
            print(f"  Wat de beste op A werkelijk haalde: {beste_a:+.3f}R.")
            if beste_a <= drempel:
                print(
                    "\n  De beste van vijftig haalt niet meer dan wat puur kiezen al oplevert.\n"
                    "  Er is dus niets gevonden — en dat is het juiste antwoord, want H0\n"
                    "  stapt willekeurig in en heeft per constructie geen edge."
                )
            else:
                print(
                    "\n  De beste ligt boven die drempel. Dat is nog geen edge: de drempel is\n"
                    "  een gemiddelde, niet een bovengrens. Het betekent alleen dat dit het\n"
                    "  waard is om op verse data te toetsen — wat stap 4 hierboven al deed."
                )

            kop("6. Alles bewaard")
            csv_pad = UITVOER / "sweep.csv"
            with csv_pad.open("w", newline="", encoding="utf-8") as bestand:
                schrijver = csv.writer(bestand)
                schrijver.writerow(
                    ["sessie", "versie", *RASTER, "corpus", "run_id", "trades",
                     "expectancy_r", "ci_low", "ci_high", "realized_r", "drawdown_r",
                     "fees_usd", "slippage_usd", "risk_veto", "rang"]
                )
                for naam, bron, rang in (("A", a, rang_a), ("B", b, rang_b)):
                    plek = {nr: i + 1 for i, nr in enumerate(rang)}
                    for sessie in sessies:
                        r = bron[sessie.nummer]
                        schrijver.writerow(
                            [sessie.nummer, sessie.versie,
                             *[sessie.params[k] for k in RASTER], naam, r["run_id"],
                             r["n"], r["expectancy"], r["ci_low"], r["ci_high"],
                             r["realized_r"], r["drawdown_r"], r["fees_usd"],
                             r["slippage_usd"], r["risk_veto"], plek[sessie.nummer]]
                        )
            runs = int(await session.scalar(select(func.count()).select_from(QuantStrategyRun)) or 0)
            trades = int(await session.scalar(select(func.count()).select_from(QuantPaperTrade)) or 0)
            hyps = int(await session.scalar(select(func.count()).select_from(QuantHypothesis)) or 0)
            print(f"  {hyps} voorgeregistreerde versies, {runs} runs, {trades} trades.")
            print(f"  Beide corpora staan nog in de database (afdrukken in de runs).")
            print(f"  CSV: {csv_pad}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
