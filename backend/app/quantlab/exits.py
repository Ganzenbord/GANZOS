"""De exits (sectie 8): harde stop op -1R, de helft bij +2R, de rest met een trailing stop.

Pure functies, geen database, geen taalmodel — net als de risicolaag. Dit zit in het pad
waarin een positie wordt gesloten, en daar hoort niets in dat kan wachten of kan falen.

Eén keuze die uitleg verdient: **de stop weegt zwaarder dan de winstneming.** Raakt één
tick allebei, dan wordt de stop uitgevoerd. In werkelijkheid weet je niet in welke volgorde
het binnen die tick gebeurde, en dan kies je de ongunstige kant. Zou je de winst pakken,
dan verzin je geld — en precies daarmee gaat paper trading om zeep.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.quantlab.stops import StopRule


class ExitKind(StrEnum):
    STOP = "stop"
    TAKE_HALF = "take_half"
    TRAILING_STOP = "trailing_stop"
    MAX_HOLD = "max_hold"


EXIT_UITLEG: dict[ExitKind, str] = {
    ExitKind.STOP: "De harde stop op -1R is geraakt.",
    ExitKind.TAKE_HALF: "De helft eruit op +2R; de rest loopt verder met een trailing stop.",
    ExitKind.TRAILING_STOP: "De trailing stop onder de top is geraakt.",
    ExitKind.MAX_HOLD: "De positie stond te lang open en is gesloten.",
}


@dataclass(frozen=True)
class ExitRules:
    """De exit-regels uit het hypothese-bestand.

    `stop` bepaalt hoe ver de stop onder de instap komt, en daarmee de positiegrootte: hoe
    dichter de stop, hoe groter de positie voor hetzelfde risico. Dat is per trade anders
    bij een structurele stop — zie `app/quantlab/stops.py`.
    """

    stop: StopRule
    take_half_at_r: Decimal
    trailing_stop_pct: Decimal
    max_hold_minutes: int


@dataclass
class OpenPosition:
    """Een openstaande papieren positie. Veranderlijk: de top en de helft bewegen mee."""

    pool_address: str
    opened_at: datetime
    entry_price: Decimal
    units: Decimal
    stop_price: Decimal
    # Hoeveel prijs één R is. Hiermee wordt +2R een prijs in plaats van een idee.
    r_price_distance: Decimal
    risk_quote: Decimal
    peak_price: Decimal
    half_taken: bool = False
    trade_id: int | None = None

    def r_at(self, price: Decimal) -> Decimal:
        if self.r_price_distance <= 0:
            return Decimal("0")
        return (price - self.entry_price) / self.r_price_distance


@dataclass(frozen=True)
class ExitDecision:
    kind: ExitKind
    fraction: Decimal
    reason: str
    trigger_price: Decimal


def evaluate_exit(
    position: OpenPosition, *, price: Decimal, moment: datetime, rules: ExitRules
) -> ExitDecision | None:
    """Moet er iets uit deze positie? Eén antwoord, met een reden.

    De volgorde is onderdeel van het ontwerp: eerst de stop (de ongunstige kant), dan de
    tijd, dan de trailing stop, dan de winstneming.
    """
    if price <= position.stop_price:
        return ExitDecision(
            kind=ExitKind.STOP,
            fraction=Decimal("1"),
            reason=EXIT_UITLEG[ExitKind.STOP],
            trigger_price=position.stop_price,
        )

    if moment - position.opened_at >= timedelta(minutes=rules.max_hold_minutes):
        return ExitDecision(
            kind=ExitKind.MAX_HOLD,
            fraction=Decimal("1"),
            reason=EXIT_UITLEG[ExitKind.MAX_HOLD],
            trigger_price=price,
        )

    if position.half_taken:
        # De trailing stop geldt pas ná de winstneming. Zou hij eerder gelden, dan is de
        # stop niet meer -1R en klopt de positiegrootte niet met het risico.
        drempel = position.peak_price * (Decimal("1") - rules.trailing_stop_pct)
        if price <= drempel:
            return ExitDecision(
                kind=ExitKind.TRAILING_STOP,
                fraction=Decimal("1"),
                reason=EXIT_UITLEG[ExitKind.TRAILING_STOP],
                trigger_price=drempel,
            )
        return None

    doel = position.entry_price + rules.take_half_at_r * position.r_price_distance
    if price >= doel:
        return ExitDecision(
            kind=ExitKind.TAKE_HALF,
            fraction=Decimal("0.5"),
            reason=EXIT_UITLEG[ExitKind.TAKE_HALF],
            trigger_price=doel,
        )
    return None
