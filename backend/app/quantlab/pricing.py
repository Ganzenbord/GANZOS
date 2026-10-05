"""Wat een modelaanroep kost (sectie 12).

De prijzen hieronder komen uit de officiële prijspagina van Anthropic en staan er mét
bron en datum. Dat is een harde eis uit de opdracht, en met reden: een prijs uit het hoofd
is een gok, en een gok in een budget is een rekening die niemand had verwacht.

Een model dat hier niet staat, kan niet geboekt worden en kan dus ook niet draaien. Dat is
geen tekortkoming maar de bedoeling: nul euro boeken voor een aanroep die wel geld kost,
is erger dan weigeren. JEV.ai staat daarom nog niet in de lijst — zie het fase 1-rapport.

Bedragen zijn per miljoen tokens (MTok) in Amerikaanse dollars, precies zoals de
prijspagina ze geeft. Het omrekenen naar euro's gebeurt per aanroep met een koers die
meegaat in de boeking, zodat het boek later nog narekenbaar is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# Zes decimalen, niet twee. Eén aanroep van de Classifier kost een fractie van een cent;
# zou het boek op centen afronden, dan kosten duizend kleine aanroepen samen nul euro en
# blijft het budget eeuwig op nul staan.
PRECISIE = Decimal("0.000001")
MILJOEN = Decimal("1000000")

PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_VERIFIED_ON = date(2026, 10, 5)


class UnknownModelPrice(LookupError):
    """Van dit model is de prijs niet bekend, dus wordt er niets geboekt en niets gedraaid."""


@dataclass(frozen=True)
class ModelPrice:
    model: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    cache_read_usd_per_mtok: Decimal
    source: str
    verified_on: date


@dataclass(frozen=True)
class TokenUsage:
    """Wat een aanroep heeft verbruikt. Dit zijn de getallen die de API zelf teruggeeft."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


PRICES: dict[str, ModelPrice] = {
    # De Analyst en de Classifier: het goedkope model, want die doen veel aanroepen.
    "claude-haiku-4-5": ModelPrice(
        model="claude-haiku-4-5",
        input_usd_per_mtok=Decimal("1"),
        output_usd_per_mtok=Decimal("5"),
        cache_read_usd_per_mtok=Decimal("0.10"),
        source=PRICING_SOURCE,
        verified_on=PRICING_VERIFIED_ON,
    ),
    # De Reviewer: tien keer zo duur per token, dus hoogstens één keer per dag en met een
    # korte samenvatting in plaats van alle ruwe data. Zie de rekensom in het fase 0-rapport.
    "claude-fable-5-1": ModelPrice(
        model="claude-fable-5-1",
        input_usd_per_mtok=Decimal("10"),
        output_usd_per_mtok=Decimal("50"),
        cache_read_usd_per_mtok=Decimal("0.25"),
        source=PRICING_SOURCE,
        verified_on=PRICING_VERIFIED_ON,
    ),
}


def get_price(model: str) -> ModelPrice:
    try:
        return PRICES[model]
    except KeyError as exc:
        raise UnknownModelPrice(
            f"Van het model '{model}' is de prijs niet bekend. Zet hem met bron en datum "
            f"in app/quantlab/pricing.py; tot die tijd draait dit model niet, zodat er geen "
            f"ongemeten rekening kan ontstaan."
        ) from exc


def cost_usd(model: str, usage: TokenUsage) -> Decimal:
    prijs = get_price(model)
    totaal = (
        Decimal(usage.input_tokens) * prijs.input_usd_per_mtok
        + Decimal(usage.output_tokens) * prijs.output_usd_per_mtok
        + Decimal(usage.cache_read_tokens) * prijs.cache_read_usd_per_mtok
    ) / MILJOEN
    return totaal.quantize(PRECISIE, rounding=ROUND_HALF_UP)


def cost_eur(model: str, usage: TokenUsage, *, rate: Decimal) -> Decimal:
    """Dollars naar euro's met de koers die op dat moment gold.

    De koers gaat mee in de boeking (`fx_rate`), zodat je later kunt zien waarmee is
    gerekend en het bedrag kunt narekenen als de koers blijkt te hebben gelopen.
    """
    return (cost_usd(model, usage) * rate).quantize(PRECISIE, rounding=ROUND_HALF_UP)
