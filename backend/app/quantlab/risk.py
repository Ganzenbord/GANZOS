"""De Risk Officer, als pure functies (sectie 9).

Geen database, geen netwerk, geen taalmodel. Wat hier in gaat is een stand van zaken, en
wat eruit komt is ja of nee met een reden. Dat is bewust zo klein: deze code zit in het
pad waarin een trade tot stand komt, en daar hoort niets in dat kan wachten, kan falen of
kan antwoorden met iets anders dan afgesproken.

Dat laatste is ook een harde eis uit sectie 6: geen enkele LLM-aanroep in dit pad. Er is
een test (`test_de_risicolaag_praat_met_geen_enkel_taalmodel`) die de imports van dit
bestand leest en faalt zodra iemand dat verandert.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from app.quantlab.risk_limits import (
    DAY_LOSS_HALT_R,
    HEARTBEAT_MAX_AGE_SECONDS,
    MAX_OPEN_RISK_R,
    MAX_RISK_PER_TRADE_R,
    RISK_PER_TRADE_PCT,
    WEEK_LOSS_STOP_R,
)


def day_start(now: datetime) -> datetime:
    """Het begin van de UTC-dag.

    Eén tijdzone voor alles. Zonder dat vervalt een dagstop twee keer per etmaal of
    helemaal niet, afhankelijk van waar je staat."""
    moment = now.astimezone(timezone.utc)
    return datetime.combine(moment.date(), time.min, tzinfo=timezone.utc)


def week_start(now: datetime) -> datetime:
    """Maandag 00:00 UTC van de week waarin `now` valt."""
    begin = day_start(now)
    return begin - timedelta(days=begin.isoweekday() - 1)

CENTEN = Decimal("0.01")
# Stukken worden met acht decimalen gerekend: een memecoin kost soms 0,0000012 euro, en
# afronden op hele stukken zou dan alles of niets zijn.
STUKKEN = Decimal("0.00000001")


class RiskVeto(StrEnum):
    """Waarom een instap niet doorgaat. Engels als identifier, Nederlands in `VETO_UITLEG`."""

    KILL_SWITCH_ACTIVE = "kill_switch_active"
    HEARTBEAT_STALE = "heartbeat_stale"
    WEEK_LOSS_STOP = "week_loss_stop"
    DAY_LOSS_HALT = "day_loss_halt"
    NO_EQUITY = "no_equity"
    RISK_PER_TRADE_EXCEEDED = "risk_per_trade_exceeded"
    INVALID_STOP = "invalid_stop"
    OPEN_RISK_EXCEEDED = "open_risk_exceeded"


VETO_UITLEG: dict[RiskVeto, str] = {
    RiskVeto.KILL_SWITCH_ACTIVE: (
        "De noodstop staat aan. Er gaan geen nieuwe posities open tot iemand hem er "
        "bewust uit haalt."
    ),
    RiskVeto.HEARTBEAT_STALE: (
        "Het lab hoort niets meer van het proces dat de markt volgt. Zolang dat zo is, "
        "gaat er niets open: stilte is geen rust."
    ),
    RiskVeto.WEEK_LOSS_STOP: (
        "Het verlies van deze week heeft de weekgrens van 8R geraakt. Alles staat stil "
        "tot Stef de grens handmatig opnieuw zet."
    ),
    RiskVeto.DAY_LOSS_HALT: (
        "Het verlies van vandaag heeft de daggrens van 3R geraakt. Er gaat vandaag niets "
        "meer open; morgen (UTC) begint de dagstand opnieuw."
    ),
    RiskVeto.NO_EQUITY: (
        "Er is geen papieren equity om risico over te rekenen. Zonder equity is 1R nul, "
        "en een positie van nul is geen positie."
    ),
    RiskVeto.RISK_PER_TRADE_EXCEEDED: (
        "Deze instap vraagt meer dan 1R, of nul. Per trade mag er hoogstens één keer de "
        "vaste inzet op het spel staan."
    ),
    RiskVeto.INVALID_STOP: (
        "De stop valt samen met de instapprijs, dus er is geen afstand om risico over te "
        "rekenen. Zonder stop is er geen bekend verlies."
    ),
    RiskVeto.OPEN_RISK_EXCEEDED: (
        "Hier samen met wat al openstaat zou er meer dan 5R tegelijk aan tafel liggen. "
        "Eerst iets sluiten."
    ),
}


@dataclass(frozen=True)
class RiskSnapshot:
    """De stand van zaken op één moment. Onveranderlijk: niemand draait er een getal in om.

    `week_stop_level_r` is de stand waarop de weekstop aangaat. Standaard -8R; na een
    handmatige reset schuift hij 8R mee, zodat het verlies van deze week in de cijfers
    blijft staan en alleen de stop opnieuw is gezet.
    """

    equity: Decimal
    open_risk_r: Decimal
    realized_day_r: Decimal
    realized_week_r: Decimal
    kill_switch_active: bool
    heartbeat_age_seconds: float | None
    week_stop_level_r: Decimal = WEEK_LOSS_STOP_R

    def met(self, **wijzigingen: object) -> "RiskSnapshot":
        """Een kopie met één ding anders. Handig in tests en in de simulatie."""
        return replace(self, **wijzigingen)  # type: ignore[arg-type]

    @property
    def heartbeat_stale(self) -> bool:
        if self.heartbeat_age_seconds is None:
            # Nooit een hartslag gehad is erger dan een oude, niet beter.
            return True
        return self.heartbeat_age_seconds > HEARTBEAT_MAX_AGE_SECONDS

    @property
    def week_stop_engaged(self) -> bool:
        return self.realized_week_r <= self.week_stop_level_r

    @property
    def day_halt_engaged(self) -> bool:
        return self.realized_day_r <= DAY_LOSS_HALT_R


@dataclass(frozen=True)
class EntryRequest:
    """Wat een hypothese wil doen. `risk_r` is hoeveel R hij ervoor over heeft."""

    hypothesis: str
    entry_price: Decimal
    stop_price: Decimal
    risk_r: Decimal = Decimal("1")


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    veto: RiskVeto | None
    reason: str
    risk_eur: Decimal
    position_units: Decimal


def one_r_amount(equity: Decimal) -> Decimal:
    """Hoeveel geld één R is, in de valuta van de equity.

    Valuta-agnostisch met opzet: de functie rekent een percentage en weet niet of er
    dollars of euro's in gaan. De papieren rekening staat in dollars (de venues rekenen
    in dollars); het maandbudget voor de modellen staat in euro's. Door hier geen valuta
    aan te nemen, kan er ook niets stilletjes worden omgerekend.

    Deze functie ziet uitsluitend de equity, en dat is de hele bescherming tegen
    martingale: er is geen parameter waarin "ik heb net drie keer verloren" kan passen.
    Naar beneden afgerond, want naar boven zou betekenen dat 1R stiekem meer is dan 0,75%.
    """
    if equity <= 0:
        return Decimal("0")
    return (equity * RISK_PER_TRADE_PCT).quantize(CENTEN, rounding=ROUND_DOWN)


def position_units(
    *, risk_eur: Decimal, entry_price: Decimal, stop_price: Decimal
) -> Decimal:
    """Hoeveel stuks je koopt zodat de stop precies `risk_eur` kost.

    Naar beneden afgerond: één stuk te veel zou het werkelijke risico boven 1R duwen.
    """
    afstand = abs(entry_price - stop_price)
    if afstand == 0:
        raise ValueError(
            "De stop valt samen met de instapprijs; dan is er geen afstand om risico "
            "over te rekenen."
        )
    return (risk_eur / afstand).quantize(STUKKEN, rounding=ROUND_DOWN)


def evaluate_entry(snapshot: RiskSnapshot, request: EntryRequest) -> RiskDecision:
    """Mag deze instap door? Eén antwoord, één reden.

    De volgorde van de controles is onderdeel van het ontwerp. Eerst wat iemand bewust
    heeft aangezet (de noodstop), dan wat betekent dat we het niet weten (de hartslag),
    dan de zwaarste grens (week), dan de lichtere (dag). Zouden er twee tegelijk gelden en
    meldde hij de lichtste, dan denk je dat je er morgen weer in mag.
    """
    if snapshot.kill_switch_active:
        return _nee(RiskVeto.KILL_SWITCH_ACTIVE)
    if snapshot.heartbeat_stale:
        return _nee(RiskVeto.HEARTBEAT_STALE)
    if snapshot.week_stop_engaged:
        return _nee(RiskVeto.WEEK_LOSS_STOP)
    if snapshot.day_halt_engaged:
        return _nee(RiskVeto.DAY_LOSS_HALT)
    if snapshot.equity <= 0:
        return _nee(RiskVeto.NO_EQUITY)
    if request.risk_r <= 0 or request.risk_r > MAX_RISK_PER_TRADE_R:
        return _nee(RiskVeto.RISK_PER_TRADE_EXCEEDED)
    if snapshot.open_risk_r + request.risk_r > MAX_OPEN_RISK_R:
        return _nee(RiskVeto.OPEN_RISK_EXCEEDED)

    risico = (one_r_amount(snapshot.equity) * request.risk_r).quantize(
        CENTEN, rounding=ROUND_DOWN
    )
    try:
        stuks = position_units(
            risk_eur=risico,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
        )
    except ValueError:
        return _nee(RiskVeto.INVALID_STOP)
    if stuks <= 0:
        # Minder dan één onderdeel van een stuk: niet verboden, maar ook geen positie.
        return _nee(RiskVeto.INVALID_STOP)

    return RiskDecision(
        allowed=True,
        veto=None,
        reason="Binnen alle grenzen.",
        risk_eur=risico,
        position_units=stuks,
    )


def _nee(veto: RiskVeto) -> RiskDecision:
    return RiskDecision(
        allowed=False,
        veto=veto,
        reason=VETO_UITLEG[veto],
        risk_eur=Decimal("0"),
        position_units=Decimal("0"),
    )
