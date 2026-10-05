"""Expectancy, onzekerheid en drawdown — in R, na kosten.

De cultuurregel uit de opdracht staat hier in code: **geen enkele claim zonder N, kosten en
onzekerheidsmarge.** Een expectancy zonder interval is geen getal maar een gevoel, en
"88% winrate" zonder expectancy na kosten is ruis.

Het betrouwbaarheidsinterval komt uit een bootstrap en niet uit een formule. Reden: de
verdeling van R-uitkomsten bij een sniper-strategie is scheef en heeft een lange staart
(veel kleine verliezen, af en toe een grote winst). Een normale benadering gaat daar
precies de verkeerde kant op. Een bootstrap maakt geen aanname over de vorm; hij hersampelt
wat er werkelijk is gebeurd.

Onder de drempel uit de hypothese (150 trades) is de conclusie "te vroeg". Dat is geen
bescheidenheid maar rekenkunde: met twintig trades past er bijna elke werkelijkheid in het
interval.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

R_SCALE = Decimal("0.0001")
BOOTSTRAP_SAMPLES = 2000
DEFAULT_CONFIDENCE = Decimal("0.90")
DEFAULT_MIN_TRADES = 150


@dataclass(frozen=True)
class TradeResult:
    r_multiple: Decimal


@dataclass(frozen=True)
class ExpectancyResult:
    n: int
    expectancy_r: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    confidence: Decimal
    win_rate: Decimal | None
    conclusion_allowed: bool
    min_trades: int
    verdict: str


def expectancy(
    trades: Sequence[TradeResult],
    *,
    seed: int,
    confidence: Decimal = DEFAULT_CONFIDENCE,
    min_trades: int = DEFAULT_MIN_TRADES,
    samples: int = BOOTSTRAP_SAMPLES,
) -> ExpectancyResult:
    """De verwachte R per trade, met een bootstrap-interval eromheen."""
    waarden = [float(trade.r_multiple) for trade in trades]
    n = len(waarden)
    if n == 0:
        return ExpectancyResult(
            n=0,
            expectancy_r=None,
            ci_low=None,
            ci_high=None,
            confidence=confidence,
            win_rate=None,
            conclusion_allowed=False,
            min_trades=min_trades,
            verdict="Er zijn geen gesloten trades, dus er is geen expectancy.",
        )

    gemiddelde = Decimal(str(statistics.fmean(waarden))).quantize(
        R_SCALE, rounding=ROUND_HALF_UP
    )
    winst = Decimal(sum(1 for w in waarden if w > 0)) / Decimal(n)

    laag = hoog = gemiddelde
    if n > 1:
        toeval = random.Random(seed)
        gemiddelden = sorted(
            statistics.fmean(toeval.choices(waarden, k=n)) for _ in range(samples)
        )
        staart = (Decimal("1") - confidence) / 2
        laag = Decimal(str(gemiddelden[int(float(staart) * samples)])).quantize(R_SCALE)
        hoog = Decimal(str(gemiddelden[min(samples - 1, int((1 - float(staart)) * samples))])
                       ).quantize(R_SCALE)

    genoeg = n >= min_trades
    if not genoeg:
        oordeel = (
            f"Te vroeg voor een conclusie: {n} van de {min_trades} gesloten trades. "
            f"De expectancy staat nu op {gemiddelde}R, maar het interval is nog zo breed "
            "dat er bijna elke werkelijkheid in past."
        )
    elif laag > 0:
        oordeel = (
            f"Over {n} trades is de expectancy {gemiddelde}R en ligt de ondergrens van het "
            f"{confidence:%}-interval op {laag}R, dus boven nul."
        )
    else:
        oordeel = (
            f"Over {n} trades is de expectancy {gemiddelde}R, maar de ondergrens van het "
            f"{confidence:%}-interval ligt op {laag}R. Daarmee is nul niet uitgesloten."
        )

    return ExpectancyResult(
        n=n,
        expectancy_r=gemiddelde,
        ci_low=laag,
        ci_high=hoog,
        confidence=confidence,
        win_rate=winst.quantize(R_SCALE),
        conclusion_allowed=genoeg,
        min_trades=min_trades,
        verdict=oordeel,
    )


def max_drawdown_r(trades: Sequence[TradeResult]) -> Decimal:
    """De grootste val van top tot bodem in de opgetelde R-curve.

    In R en niet in euro's, want dat is de maat waarin de kill-criteria staan (meer dan 30R
    drawdown en H1 stopt) en de enige maat die vergelijkbaar blijft als de equity verandert.
    """
    top = Decimal("0")
    stand = Decimal("0")
    diepste = Decimal("0")
    for trade in trades:
        stand += trade.r_multiple
        top = max(top, stand)
        diepste = max(diepste, top - stand)
    return diepste.quantize(R_SCALE, rounding=ROUND_HALF_UP).normalize()
