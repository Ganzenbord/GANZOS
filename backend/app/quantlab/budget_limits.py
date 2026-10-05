"""Het geldplafond van het lab (sectie 12).

Net als de risicogrenzen staan deze waarden in code en niet in de instellingen: een
plafond dat je met een omgevingsvariabele verzet, is geen plafond. Wat wél instelbaar is,
is de dollar-euro-koers — die hoort bij de werkelijkheid en niet bij het beleid.

De startverdeling komt letterlijk uit de opdracht. De reserve van 70 euro staat met opzet
op niemands naam: een agent die door zijn eigen budget heen is, stopt, ook al is er in het
geheel nog ruimte. Die reserve uitgeven is een beslissing van Stef, niet van een agent.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_DOWN, Decimal

from app.quantlab.agents import QuantAgent

# Harde grens voor alle modelkosten bij elkaar, per kalendermaand.
MONTHLY_HARD_CAP_EUR = Decimal("200")

# Hier gaat de waarschuwing aan: het lab draait door, maar het stoplicht springt op oranje.
MONTHLY_WARNING_EUR = Decimal("150")

# De startverdeling. Scout, Screener en Risk Officer staan er niet in: dat is pure code.
AGENT_MONTHLY_BUDGET_EUR: dict[QuantAgent, Decimal] = {
    QuantAgent.REVIEWER: Decimal("70"),
    QuantAgent.ANALYST: Decimal("50"),
    QuantAgent.CLASSIFIER: Decimal("10"),
}

# Van niemand, voor als er iets bij moet. Alleen met een bewuste wijziging hierboven.
RESERVE_EUR = Decimal("70")

# Een dag mag hoogstens het dubbele van zijn pro-rata deel gebruiken. Precies pro rata zou
# betekenen dat een zuinige week je geen enkele ruimte geeft voor een drukke dag; zonder
# daggrens kan één doorgedraaide dag de hele maand opeten. Twee is het compromis.
DAILY_BURST_FACTOR = Decimal("2")

CENTEN = Decimal("0.01")


def monthly_budget_eur(agent: QuantAgent) -> Decimal:
    return AGENT_MONTHLY_BUDGET_EUR.get(agent, Decimal("0"))


def daily_cap_eur(agent: QuantAgent, on_day: date) -> Decimal:
    """Wat deze agent op deze dag hoogstens mag kosten.

    Afhankelijk van de maandlengte, zodat februari niet strenger uitpakt dan oktober.
    Naar beneden afgerond: een grens die je naar boven afrondt, is een grens erbij.
    """
    maand = monthly_budget_eur(agent)
    if maand <= 0:
        return Decimal("0")
    dagen = Decimal(calendar.monthrange(on_day.year, on_day.month)[1])
    return (maand / dagen * DAILY_BURST_FACTOR).quantize(CENTEN, rounding=ROUND_DOWN)
