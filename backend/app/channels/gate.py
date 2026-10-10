"""Wanneer mag het volgende kanaal open?

Stefs regel: kanaal 2 begint pas als kanaal 1 minstens €6.000 per maand haalt, kanaal 3 als
kanaal 2 minstens €3.000 haalt, en zo verder. Dat is een goede regel — hij maakt de inzet
klein zolang je nog niets weet. Deze module maakt er een **functie** van in plaats van een
afspraak, want een afspraak die je zelf moet nalopen, loopt op precies twee manieren mis:

**1. December lijkt altijd op succes.** De advertentietarieven op YouTube zijn in november
en december het hoogst van het jaar en in januari het laagst; de daling van december naar
januari wordt op 20 tot 50 procent geschat (bronnen variëren, geen ervan is YouTube zelf).
Een kanaal dat in december €6.000 haalt, kan in januari op €3.000 tot €4.800 staan zonder
dat er iets is veranderd. Een poort die op één maand afgaat, gaat dus elke december open en
blijkt elke januari te vroeg. Daarom rekent deze module met een **gemiddelde over meerdere
maanden**, en zegt hij erbij of dat venster in de piek van het jaar lag.

**2. De maand die nu loopt is geen maand.** YouTube geeft omzet van de eerste van de maand
tot vandaag, dus elke meting is een stand-tot-nu. Die meetellen zou betekenen dat je op de
derde van de maand naar een omzet van drie dagen kijkt en concludeert dat het kanaal
instort. `monthly_totals()` gooit de lopende maand er daarom uit en neemt per afgesloten
maand de **laatste** meting.

En één ding dat deze module met opzet níet doet: valuta omrekenen. Komt de omzet in dollars
binnen terwijl de poort in euro's staat, dan is dat een fout en geen klusje — in dit project
is één keer een koers de verkeerde kant op gegaan, en dat kostte een positie van 15% te
klein zonder dat iemand het zag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# De poort voor het tweede kanaal. Hoger dan de rest, want bij één kanaal weet je nog niet
# of de machine werkt of dat deze ene niche werkt.
FIRST_GATE_EUR = Decimal("6000")

# De poort voor elk kanaal daarna. Stef noemde "3 tot 6k"; hier staat de ondergrens, dus de
# poort gaat open op het eerste moment dat hij acceptabel noemde. Wie strenger wil, zet hem
# hoger — dat is een keuze en geen detail, en daarom staat het getal hier en niet verstopt.
NEXT_GATE_EUR = Decimal("3000")

# Over hoeveel afgesloten maanden het gemiddelde gaat. Drie is het minimum om de
# december-piek niet voor groei te verslijten; bij twee maanden kan het venster volledig in
# de piek vallen.
DEFAULT_WINDOW_MONTHS = 3

# De maanden waarin de tarieven structureel hoog liggen (de feestdagen) en laag (de reset
# van de budgetten in januari).
PIEKMAANDEN = (11, 12)
DALMAAND = 1


@dataclass(frozen=True, slots=True)
class Measurement:
    """Eén meting zoals die in de kanaalcijfers staat: een stand-tot-nu."""

    measured_at: datetime
    revenue: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class MonthRevenue:
    """De omzet van één afgesloten maand."""

    year: int
    month: int
    amount: Decimal

    @property
    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"


@dataclass(frozen=True, slots=True)
class GateRule:
    threshold: Decimal
    window_months: int = DEFAULT_WINDOW_MONTHS
    # Een ondergrens die élke maand in het venster moet halen. Zonder dit haalt een kanaal
    # met één uitschieter en twee magere maanden het gemiddelde alsnog.
    floor_each_month: Decimal | None = None
    currency: str = "EUR"


@dataclass(frozen=True, slots=True)
class GateVerdict:
    passed: bool
    trailing_average: Decimal
    months_measured: int
    explanation: str
    # Of de laatste maand alléén de poort gehaald zou hebben. Staat erbij zodat het scherm
    # het verschil kan laten zien: "december haalde het, het kwartaal niet".
    latest_month_would_pass: bool = False
    season_warning: str | None = None
    months: tuple[MonthRevenue, ...] = ()


class CurrencyMismatch(ValueError):
    """De omzet komt in een andere valuta binnen dan waarin de poort staat."""


def monthly_totals(
    measurements: list[Measurement] | tuple[Measurement, ...],
    *,
    today: date,
    currency: str = "EUR",
) -> tuple[MonthRevenue, ...]:
    """Van metingen naar afgesloten maanden, oudste eerst.

    Per maand de laatste meting, want elke meting is een stand-tot-nu. De lopende maand valt
    eruit: die is nog niet af, en een halve maand ziet eruit als een halvering.
    """
    per_maand: dict[tuple[int, int], Measurement] = {}
    for meting in measurements:
        if meting.currency and meting.currency.upper() != currency.upper():
            raise CurrencyMismatch(
                f"De omzet komt binnen in {meting.currency} terwijl de poort in {currency} "
                "staat. Omrekenen hoort hier niet te gebeuren: zet de poort in dezelfde "
                "valuta, of reken om op de plek waar de koers wordt vastgelegd."
            )
        sleutel = (meting.measured_at.year, meting.measured_at.month)
        bestaand = per_maand.get(sleutel)
        if bestaand is None or meting.measured_at > bestaand.measured_at:
            per_maand[sleutel] = meting

    nu = (today.year, today.month)
    return tuple(
        MonthRevenue(year=jaar, month=maand, amount=Decimal(per_maand[(jaar, maand)].revenue))
        for jaar, maand in sorted(per_maand)
        if (jaar, maand) != nu
    )


def _seizoenswaarschuwing(venster: tuple[MonthRevenue, ...], today: date) -> str | None:
    pieken = [m.label for m in venster if m.month in PIEKMAANDEN]
    if not pieken:
        return None
    if len(pieken) == len(venster):
        return (
            f"Let op: alle maanden in dit venster ({', '.join(pieken)}) vallen in de piek van "
            "het jaar. De advertentietarieven zijn dan het hoogst en in januari het laagst — "
            "dit gemiddelde is dus geflatteerd. Wacht een maand of twee met deze beslissing."
        )
    return (
        f"Let op: {', '.join(pieken)} valt in de piek van het jaar, dus dit gemiddelde ligt "
        "iets hoger dan een gewone maand. In januari zakken de tarieven weer."
    )


def evaluate(
    months: tuple[MonthRevenue, ...],
    rule: GateRule,
    *,
    today: date,
) -> GateVerdict:
    """Mag het volgende kanaal open?

    Het antwoord "nog te vroeg" is een echt antwoord en geen nee: bij minder maanden dan het
    venster is er niets te zeggen, en dat hoort er te staan in plaats van een nul.
    """
    if len(months) < rule.window_months:
        tekort = rule.window_months - len(months)
        return GateVerdict(
            passed=False,
            trailing_average=Decimal("0"),
            months_measured=len(months),
            explanation=(
                f"Nog te vroeg: er zijn {len(months)} afgesloten maanden gemeten en de regel "
                f"kijkt naar {rule.window_months}. Nog {tekort} maand(en) te gaan."
            ),
            months=months,
        )

    venster = months[-rule.window_months :]
    gemiddelde = sum((m.amount for m in venster), Decimal("0")) / Decimal(len(venster))
    laatste = venster[-1]
    laatste_haalt = laatste.amount >= rule.threshold

    onder = [m for m in venster if rule.floor_each_month is not None
             and m.amount < rule.floor_each_month]

    waarschuwing = _seizoenswaarschuwing(venster, today)
    valuta = rule.currency

    if onder:
        return GateVerdict(
            passed=False,
            trailing_average=gemiddelde,
            months_measured=len(months),
            explanation=(
                f"Het gemiddelde over {rule.window_months} maanden is {valuta} "
                f"{gemiddelde:.0f}, maar {', '.join(m.label for m in onder)} bleef onder de "
                f"ondergrens van {valuta} {rule.floor_each_month:.0f}. Eén goede maand tussen "
                "twee magere is geen groei."
            ),
            latest_month_would_pass=laatste_haalt,
            season_warning=waarschuwing,
            months=months,
        )

    if gemiddelde >= rule.threshold:
        return GateVerdict(
            passed=True,
            trailing_average=gemiddelde,
            months_measured=len(months),
            explanation=(
                f"De poort is open: {valuta} {gemiddelde:.0f} gemiddeld over "
                f"{rule.window_months} maanden ({', '.join(m.label for m in venster)}), en de "
                f"grens staat op {valuta} {rule.threshold:.0f}."
            ),
            latest_month_would_pass=laatste_haalt,
            season_warning=waarschuwing,
            months=months,
        )

    uitleg = (
        f"Nog niet: {valuta} {gemiddelde:.0f} gemiddeld over {rule.window_months} maanden, "
        f"en de grens staat op {valuta} {rule.threshold:.0f}."
    )
    if laatste_haalt:
        # Dit is het geval waar de regel voor bestaat. Zonder deze zin lijkt de poort kapot.
        uitleg += (
            f" {laatste.label} haalde het op zichzelf wél ({valuta} {laatste.amount:.0f}), "
            "maar één maand is geen trend — en in december is dat extra verraderlijk."
        )
    return GateVerdict(
        passed=False,
        trailing_average=gemiddelde,
        months_measured=len(months),
        explanation=uitleg,
        latest_month_would_pass=laatste_haalt,
        season_warning=waarschuwing,
        months=months,
    )


def rule_for_channel(number: int, *, window_months: int = DEFAULT_WINDOW_MONTHS) -> GateRule:
    """De poort die open moet voordat kanaal `number` begint.

    Kanaal 1 heeft geen poort: daar begint het. Kanaal 2 vraagt de hoge grens, want met één
    kanaal kun je niet zien of de machine werkt of dat deze ene niche werkt. Vanaf kanaal 3
    weet je dat wel, en mag de grens lager.
    """
    if number <= 1:
        raise ValueError("Het eerste kanaal heeft geen poort; daar begint het.")
    drempel = FIRST_GATE_EUR if number == 2 else NEXT_GATE_EUR
    return GateRule(
        threshold=drempel,
        window_months=window_months,
        # De helft van de drempel als ondergrens per maand: één uitschieter mag het
        # gemiddelde niet in zijn eentje over de grens trekken.
        floor_each_month=drempel / 2,
    )
