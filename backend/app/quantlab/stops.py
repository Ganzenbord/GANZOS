"""Waar de stop komt te liggen, per trade.

Eerst stond hier een vast percentage: 25% onder de instap, voor elk token hetzelfde. Dat
was een gok. De opdracht noemt "harde stop op -1R" maar geen afstand, en zonder afstand is
er geen positiegrootte — dus moest er een getal komen, en dat getal was van mij.

Nu wordt de stop per trade afgeleid uit wat dát token zelf deed: onder de bodem van het
venster waar de koers uit kwam. De gedachte in één zin: **de trade is weerlegd als de koers
terugvalt door het bereik waar hij uit kwam.** Een rustig token krijgt daarmee een krappe
stop en een grote positie, een wild token een wijde stop en een kleine positie — en in
beide gevallen staat er precies 1R op het spel.

Deterministische code en geen taalmodel. Dit zit in het pad waarin een trade tot stand
komt, en sectie 6 is daar duidelijk over: LLM's adviseren, code beslist.

Wat de stop niet verandert: de **grootte** van een verlies. Die is per constructie 1R. Wat
hij verandert is hoe vaak je wordt uitgestopt, en hoe ver de koers moet lopen voordat de
helft eruit kan (+2R is twee keer de stopafstand boven de instap).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum

PRICE_SCALE = Decimal("0.000000000001")
PCT_SCALE = Decimal("0.0001")

# De afleiding van de ondergrens. Dit is het enige getal in de stopregel waar een rekensom
# achter zit, en daarom staat die rekensom hier en niet alleen in een rapport.
#
# Bij een pool die precies aan het filter "liquiditeit minstens 50x de positie" voldoet, is
# de quote-kant 25x de positie. De price impact van een constant-product pool is dan
# ongeveer inleg/quote-kant = 1/25 = 4%. De positie is 1R gedeeld door de stopafstand, dus
# de slippage kost 0,04/stopafstand van je 1R. Wil je daar hoogstens 20% van 1R aan
# kwijtraken, dan moet de stop minstens 0,04/0,20 = 20% zijn.
#
# Hoe krapper de stop, hoe groter de positie, hoe meer van je risicobudget opgaat voordat
# de trade iets heeft gedaan. Bij een stop van 10% is dat 40% van 1R — aan slippage alleen.
MIN_DISTANCE_DERIVATION: dict[str, Decimal] = {
    "liquidity_multiple": Decimal("50"),
    "budget_share_of_r": Decimal("0.20"),
    "min_distance_pct": Decimal("0.20"),
}

# De bovengrens is níét afgeleid. Hij houdt tegen dat de helft pas bij een verdubbeling
# eruit gaat (+2R is twee keer de stopafstand), want dan is het geen trade meer maar een
# lot. Wat hier een redelijke grens is, hangt af van hoe hard een token van minuten oud
# werkelijk beweegt, en dat is niet gemeten. Zie het fase 3-rapport.
DEFAULT_MAX_DISTANCE_PCT = Decimal("0.50")


class StopKind(StrEnum):
    # Blijft bestaan om tegen te kunnen vergelijken: een structurele stop is alleen beter
    # als je kunt laten zien dát hij beter is.
    FIXED = "fixed"
    STRUCTURAL_RANGE = "structural_range"


@dataclass(frozen=True)
class StopRule:
    kind: StopKind
    distance_pct: Decimal | None = None
    window_minutes: int = 10
    margin_pct: Decimal = Decimal("0.02")
    min_distance_pct: Decimal = MIN_DISTANCE_DERIVATION["min_distance_pct"]
    max_distance_pct: Decimal = DEFAULT_MAX_DISTANCE_PCT


@dataclass(frozen=True)
class StopPlacement:
    stop_price: Decimal
    distance: Decimal
    distance_pct: Decimal
    basis: str
    clamped: str | None


def slippage_share_of_r(
    stop_distance_pct: Decimal, *, liquidity_multiple: Decimal
) -> Decimal:
    """Welk deel van 1R de slippage bij de instap kost, op een pool aan de grens.

    De rekensom staat bij `MIN_DISTANCE_DERIVATION`. Dit is de worst case: een pool die net
    aan het liquiditeitsfilter voldoet. Een diepere pool is goedkoper.
    """
    if stop_distance_pct <= 0 or liquidity_multiple <= 0:
        raise ValueError("Stopafstand en liquiditeitsveelvoud moeten positief zijn.")
    impact = Decimal("2") / liquidity_multiple
    return (impact / stop_distance_pct).quantize(PCT_SCALE, rounding=ROUND_HALF_UP)


def place_stop(
    rule: StopRule,
    *,
    entry_price: Decimal,
    window_low: Decimal | None = None,
    window_high: Decimal | None = None,
) -> StopPlacement:
    """Waar komt de stop voor déze trade?

    `window_low` is de laagste prijs van het venster vóór de instap. Is die er niet — een
    token zonder geschiedenis — dan valt de stop terug op de ondergrens. Dat is geen gok
    maar de voorzichtigste bruikbare waarde: krapper kost te veel aan slippage.
    """
    if entry_price <= 0:
        raise ValueError("Zonder een positieve instapprijs is er geen stop te plaatsen.")

    if rule.kind is StopKind.FIXED:
        if rule.distance_pct is None or rule.distance_pct <= 0:
            raise ValueError(
                "Een vaste stop heeft een `distance_pct` nodig die groter is dan nul."
            )
        return _plaats(
            entry_price,
            rule.distance_pct,
            basis=f"Vaste afstand van {rule.distance_pct * 100}% onder de instap.",
            clamped=None,
        )

    if window_low is None:
        return _plaats(
            entry_price,
            rule.min_distance_pct,
            basis=(
                "Geen venster met geschiedenis beschikbaar, dus de ondergrens van "
                f"{rule.min_distance_pct * 100}% gebruikt."
            ),
            clamped="min",
        )

    rauw = (window_low * (Decimal("1") - rule.margin_pct)).quantize(
        PRICE_SCALE, rounding=ROUND_DOWN
    )
    afstand_pct = ((entry_price - rauw) / entry_price).quantize(
        PCT_SCALE, rounding=ROUND_HALF_UP
    )
    uitleg = (
        f"{rule.margin_pct * 100}% onder de bodem van de laatste "
        f"{rule.window_minutes} minuten ({window_low})."
    )

    if afstand_pct < rule.min_distance_pct:
        # Dit dekt twee gevallen: een bodem net onder de instap, en een bodem er bóven
        # (dat kan bij een willekeurige instap als de koers net is gezakt). Een stop boven
        # de instap is geen stop.
        return _plaats(
            entry_price,
            rule.min_distance_pct,
            basis=(
                f"{uitleg} Dat zou {afstand_pct * 100}% zijn, krapper dan de ondergrens "
                f"van {rule.min_distance_pct * 100}%, dus opgetrokken."
            ),
            clamped="min",
        )
    if afstand_pct > rule.max_distance_pct:
        return _plaats(
            entry_price,
            rule.max_distance_pct,
            basis=(
                f"{uitleg} Dat zou {afstand_pct * 100}% zijn, wijder dan de bovengrens "
                f"van {rule.max_distance_pct * 100}%, dus teruggebracht."
            ),
            clamped="max",
        )
    return _plaats(entry_price, afstand_pct, basis=uitleg, clamped=None)


def _plaats(
    entry_price: Decimal, afstand_pct: Decimal, *, basis: str, clamped: str | None
) -> StopPlacement:
    afstand = (entry_price * afstand_pct).quantize(PRICE_SCALE, rounding=ROUND_HALF_UP)
    return StopPlacement(
        stop_price=(entry_price - afstand).quantize(PRICE_SCALE),
        distance=afstand,
        distance_pct=afstand_pct,
        basis=basis[:300],
        clamped=clamped,
    )
