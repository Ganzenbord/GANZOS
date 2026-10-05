"""De paper-trading-engine: van tick naar signaal naar positie naar resultaat.

Dit is waar alles samenkomt, en de volgorde is het ontwerp:

1. **Eerst de open posities bijwerken.** Een tick kan een stop raken, en dat moet gebeuren
   vóór er op diezelfde tick wordt ingestapt — anders handel je met geld dat je volgens de
   stop al kwijt was.
2. **Dan de strategie laten voorstellen.** Zij kijkt alleen naar kandidaten, niet naar
   risico of kosten.
3. **Dan de veiligheidsfilters.** Wat niet te verifiëren is, gaat eruit en wordt geteld.
4. **Dan de risicolaag.** Dezelfde pure code als in fase 1, met dezelfde grenzen.
5. **Dan het fill-model.** Vertraging, slippage, fees, kans op falen.

Elke weigering onderweg wordt vastgelegd met een reden. Zonder die log kun je achteraf elke
uitkomst mooi praten door te vergeten wat je hebt laten lopen.

**De risicostand is per run en zit in het geheugen**, niet in de tabellen van fase 1. Dat is
met opzet: vier stressvarianten over hetzelfde corpus zouden anders in elkaars dagstand
gaan zitten, en dan is de vergelijking waardeloos. De tabellen van fase 1 zijn voor het
echte lab; een simulatie houdt zijn eigen boekhouding.

Er wordt in dit project niet live gehandeld. Alles hier is papier.
"""

from __future__ import annotations

import logging
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from app.quantlab.exits import ExitDecision, ExitKind, OpenPosition, evaluate_exit
from app.quantlab.fills import (
    FillKind,
    FillModel,
    FillOutcome,
    FillRequest,
    pool_depth_from_liquidity,
)
from app.quantlab.hypothesis import HypothesisFile
from app.quantlab.metrics import TradeResult
from app.quantlab.risk import (
    EntryRequest,
    RiskSnapshot,
    day_start,
    evaluate_entry,
    one_r_eur,
    week_start,
)
from app.quantlab.safety import SafetyOracle, SafetyStatus
from app.quantlab.strategy import Candidate, Strategy

logger = logging.getLogger("ganz.quantlab.engine")

MONEY = Decimal("0.000001")
R_SCALE = Decimal("0.0001")
UNITS = Decimal("0.00000001")


# Een positie die aan het eind van het corpus nog openstaat, wordt gesloten op de laatst
# bekende prijs. Dat moet, anders verdwijnt hij uit de boekhouding en zie je alleen de
# trades die toevallig afliepen — de gunstige selectie. Maar het is géén uitstap volgens een
# regel, dus hij wordt apart gemarkeerd en apart geteld.
END_OF_CORPUS = "end_of_corpus"

# Hoort het lab een kwartier niets meer van een pool, dan gaat de positie dicht op de laatst
# bekende prijs. Dit is dezelfde gedachte als de dead-man switch uit fase 1: stilte is geen
# rust. Zonder dit blijft een positie hangen in een pool die is doodgebloed, raakt hij zijn
# stop nooit (want er komen geen ticks meer om hem op te raken), en wordt hij pas aan het
# eind van het corpus afgerekend — tegen een prijs van uren eerder.
STALE_POSITION_MINUTES = 15
STALE_DATA = "stale_data"


class SkipReason(StrEnum):
    """Waarom een signaal geen trade werd. Engels als code, Nederlands in `SKIP_UITLEG`."""

    ALREADY_IN_POSITION = "already_in_position"
    SAFETY_FAILED = "safety_failed"
    SELLABILITY_UNVERIFIED = "sellability_unverified"
    LIQUIDITY_TOO_THIN = "liquidity_too_thin"
    RISK_VETO = "risk_veto"
    BAD_PRICE = "bad_price"
    FILL_FAILED = "fill_failed"
    FILL_EXPIRED = "fill_expired"


SKIP_UITLEG: dict[SkipReason, str] = {
    SkipReason.ALREADY_IN_POSITION: "Er staat al een positie open in deze pool.",
    SkipReason.SAFETY_FAILED: "Een veiligheidsfilter wees dit token af.",
    SkipReason.SELLABILITY_UNVERIFIED: (
        "De verkoopbaarheid is niet technisch te verifiëren, dus het token gaat eruit en "
        "wordt geteld."
    ),
    SkipReason.LIQUIDITY_TOO_THIN: (
        "De pool is te klein voor deze positie; de liquiditeit moet een veelvoud van de "
        "positiegrootte zijn."
    ),
    SkipReason.RISK_VETO: "De risicolaag blokkeerde deze instap.",
    SkipReason.BAD_PRICE: "Zonder bruikbare prijs of stopafstand is er geen positie te maken.",
    SkipReason.FILL_FAILED: "De transactie mislukte; de kosten zijn wel geboekt.",
    SkipReason.FILL_EXPIRED: (
        "Er was geen prijs meer na de vertraging: de data stopt hier. Dit is een gat in de "
        "gegevens en geen marktgebeurtenis."
    ),
}


@dataclass
class SignalRecord:
    pool_address: str
    observed_at: datetime
    price_usd: Decimal | None
    taken: bool
    reason: str
    detail: str


@dataclass
class FillRecord:
    sequence: int
    kind: str
    reason: str
    outcome: FillOutcome


@dataclass
class TradeRecord:
    pool_address: str
    token_address: str
    opened_at: datetime
    entry_reason: str
    risk_r: Decimal
    risk_quote: Decimal
    units: Decimal
    entry_expected_price: Decimal
    entry_fill_price: Decimal
    stop_price: Decimal
    fills: list[FillRecord] = field(default_factory=list)
    closed_at: datetime | None = None
    exit_reason: str | None = None
    exit_quote_usd: Decimal = Decimal("0")
    fees_usd: Decimal = Decimal("0")
    slippage_usd: Decimal = Decimal("0")
    latency_cost_usd: Decimal = Decimal("0")
    pnl_usd: Decimal | None = None
    r_multiple: Decimal | None = None


@dataclass
class EngineResult:
    variant: str
    seed: int
    ticks: int
    signals_proposed: int
    trades_opened: int
    trades_closed: int
    trades_force_closed: int
    trades_closed_stale: int
    equity_quote: Decimal
    one_r_quote: Decimal
    realized_r: Decimal
    max_drawdown_r: Decimal
    max_open_risk_r: Decimal
    total_fees_usd: Decimal
    total_slippage_usd: Decimal
    skipped_by_reason: dict[str, int]
    signals: list[SignalRecord]
    trades: list[TradeRecord]

    @property
    def closed_results(self) -> list[TradeResult]:
        return [
            TradeResult(r_multiple=trade.r_multiple)
            for trade in self.trades
            if trade.r_multiple is not None
        ]


class _PriceIndex:
    """De prijzen per pool, op tijd gesorteerd, zodat "de prijs na de vertraging" snel is.

    Een lineaire zoektocht per fill zou bij een uur data al merkbaar zijn en bij een maand
    onbruikbaar. Dit is een binaire zoektocht over een lijst die één keer wordt opgebouwd.
    """

    def __init__(self, ticks: Sequence[Candidate]) -> None:
        self._per_pool: dict[str, tuple[list[datetime], list[Decimal]]] = {}
        for tick in ticks:
            if tick.price_usd is None or tick.price_usd <= 0:
                continue
            tijden, prijzen = self._per_pool.setdefault(tick.pool_address, ([], []))
            tijden.append(tick.observed_at)
            prijzen.append(tick.price_usd)

    def last_price(self, pool_address: str) -> Decimal | None:
        reeks = self._per_pool.get(pool_address)
        return reeks[1][-1] if reeks and reeks[1] else None

    def at_or_after(self, pool_address: str, moment: datetime) -> Decimal | None:
        reeks = self._per_pool.get(pool_address)
        if not reeks:
            return None
        tijden, prijzen = reeks
        index = bisect_left(tijden, moment)
        if index >= len(tijden):
            return None
        return prijzen[index]


@dataclass
class _RiskLedger:
    """De risicostand van déze run, in het geheugen.

    Dezelfde grenzen als fase 1 (via `evaluate_entry`), maar met een eigen boekhouding per
    run. Zie de uitleg bovenaan dit bestand waarom dat niet in de tabellen van fase 1 gaat.
    """

    equity: Decimal
    per_day: dict[datetime, Decimal] = field(default_factory=dict)
    per_week: dict[datetime, Decimal] = field(default_factory=dict)
    open_risk_r: Decimal = Decimal("0")
    max_open_risk_r: Decimal = Decimal("0")
    realized_r: Decimal = Decimal("0")

    def book(self, moment: datetime, r: Decimal) -> None:
        self.per_day[day_start(moment)] = self.per_day.get(day_start(moment), Decimal("0")) + r
        self.per_week[week_start(moment)] = (
            self.per_week.get(week_start(moment), Decimal("0")) + r
        )
        self.realized_r += r

    def reserve(self, r: Decimal) -> None:
        self.open_risk_r += r
        self.max_open_risk_r = max(self.max_open_risk_r, self.open_risk_r)

    def release(self, r: Decimal) -> None:
        self.open_risk_r = max(Decimal("0"), self.open_risk_r - r)

    def snapshot(self, moment: datetime) -> RiskSnapshot:
        return RiskSnapshot(
            equity=self.equity,
            open_risk_r=self.open_risk_r,
            realized_day_r=self.per_day.get(day_start(moment), Decimal("0")),
            realized_week_r=self.per_week.get(week_start(moment), Decimal("0")),
            kill_switch_active=False,
            # In een replay is de hartslag per definitie vers: de data staat er al. De
            # dead-man switch beschermt het echte lab, niet een simulatie over opgeslagen
            # gegevens — daar zou hij alleen ruis toevoegen.
            heartbeat_age_seconds=0.0,
        )


def run_engine(
    *,
    hypothesis: HypothesisFile,
    strategy: Strategy,
    ticks: Sequence[Candidate],
    fill_model: FillModel,
    safety: SafetyOracle,
    equity_quote: Decimal,
    seed: int,
    variant: str = "base",
) -> EngineResult:
    """Laat één hypothese één keer over een reeks ticks lopen.

    `equity_quote` is de papieren equity in de valuta van de venue (USD). De koers
    EUR→USD valt bij het berekenen van R weg, want 1R en de winst worden met dezelfde koers
    omgerekend; de koers staat wel op de run, zodat het narekenbaar blijft.
    """
    prijzen = _PriceIndex(ticks)
    ledger = _RiskLedger(equity=equity_quote)
    regels = hypothesis.exit_rules
    een_r = one_r_eur(equity_quote)

    posities: dict[str, OpenPosition] = {}
    trades: list[TradeRecord] = []
    signalen: list[SignalRecord] = []
    overgeslagen: dict[str, int] = {}
    r_curve: list[Decimal] = []
    stale_gesloten = 0
    fill_teller = seed * 1_000_003

    per_moment: dict[datetime, list[Candidate]] = {}
    _laatste_liquiditeit: dict[str, Decimal] = {}
    for tick in ticks:
        per_moment.setdefault(tick.observed_at, []).append(tick)
        if tick.liquidity_usd is not None:
            _laatste_liquiditeit[tick.pool_address] = tick.liquidity_usd
    momenten = sorted(per_moment)

    def sla_over(kandidaat: Candidate, reden: SkipReason, detail: str = "") -> None:
        overgeslagen[reden.value] = overgeslagen.get(reden.value, 0) + 1
        signalen.append(
            SignalRecord(
                pool_address=kandidaat.pool_address,
                observed_at=kandidaat.observed_at,
                price_usd=kandidaat.price_usd,
                taken=False,
                reason=reden.value,
                detail=(detail or SKUITLEG(reden))[:300],
            )
        )

    def SKUITLEG(reden: SkipReason) -> str:
        return SKIP_UITLEG[reden]

    laatste_tick: dict[str, datetime] = {}
    vorig_moment: datetime | None = None
    for moment in momenten:
        stap = (
            (moment - vorig_moment).total_seconds() if vorig_moment is not None else 0.0
        )
        vorig_moment = moment
        kandidaten = per_moment[moment]
        for kandidaat in kandidaten:
            laatste_tick[kandidaat.pool_address] = moment

        # Posities in een pool waar niets meer van komt, gaan dicht op de laatst bekende
        # prijs. Dat is een waardering en geen uitstap volgens een regel, dus hij wordt
        # apart gemarkeerd en apart geteld.
        for pool, positie in list(posities.items()):
            stil = moment - laatste_tick.get(pool, positie.opened_at)
            if stil < timedelta(minutes=STALE_POSITION_MINUTES):
                continue
            laatste = prijzen.last_price(pool)
            if laatste is None:
                continue
            trade = trades[positie.trade_id]
            _waardeer_en_sluit(
                trade=trade,
                positie=positie,
                prijs=laatste,
                liquiditeit=_laatste_liquiditeit.get(pool) or Decimal("0"),
                moment=moment,
                fill_model=fill_model,
                reden=STALE_DATA,
            )
            _reken_af(trade, positie, een_r)
            ledger.release(trade.risk_r)
            if trade.r_multiple is not None:
                ledger.book(moment, trade.r_multiple)
                r_curve.append(trade.r_multiple)
            stale_gesloten += 1
            del posities[pool]

        # 1. Eerst de open posities. Een stop die op deze tick wordt geraakt, hoort te
        #    gebeuren vóór er op diezelfde tick wordt ingestapt.
        for kandidaat in kandidaten:
            positie = posities.get(kandidaat.pool_address)
            if positie is None or kandidaat.price_usd is None or kandidaat.price_usd <= 0:
                continue
            positie.peak_price = max(positie.peak_price, kandidaat.price_usd)
            besluit = evaluate_exit(
                positie, price=kandidaat.price_usd, moment=moment, rules=regels
            )
            if besluit is None:
                continue

            fill_teller += 1
            trade = trades[positie.trade_id]
            gesloten = _verkoop(
                trade=trade,
                positie=positie,
                besluit=besluit,
                kandidaat=kandidaat,
                moment=moment,
                fill_model=fill_model,
                prijzen=prijzen,
                seed=fill_teller,
            )
            if gesloten:
                _reken_af(trade, positie, een_r)
                ledger.release(trade.risk_r)
                if trade.r_multiple is not None:
                    ledger.book(moment, trade.r_multiple)
                    r_curve.append(trade.r_multiple)
                del posities[kandidaat.pool_address]

        # 2. Dan de strategie.
        voorstel = strategy.propose(
            moment=moment, candidates=kandidaten, step_seconds=stap
        )
        if voorstel is None:
            continue

        if voorstel.pool_address in posities:
            sla_over(voorstel, SkipReason.ALREADY_IN_POSITION)
            continue
        if voorstel.price_usd is None or voorstel.price_usd <= 0:
            sla_over(voorstel, SkipReason.BAD_PRICE)
            continue

        # 3. De veiligheidsfilters.
        uitslag = safety.check(voorstel.pool_address)
        if uitslag.status is SafetyStatus.FAILED:
            sla_over(
                voorstel,
                SkipReason.SAFETY_FAILED,
                f"{uitslag.explanation} Afgewezen: {', '.join(uitslag.failed_filters)}.",
            )
            continue
        if uitslag.status is SafetyStatus.UNVERIFIABLE or (
            hypothesis.exclude_when_sellability_unverified and uitslag.sellable is not True
        ):
            sla_over(voorstel, SkipReason.SELLABILITY_UNVERIFIED, uitslag.explanation)
            continue

        # 4. De positie uitrekenen, en kijken of de pool hem kan dragen.
        stop_afstand = (voorstel.price_usd * regels.stop_distance_pct).quantize(
            Decimal("0.000000000001")
        )
        if stop_afstand <= 0:
            sla_over(voorstel, SkipReason.BAD_PRICE)
            continue
        inleg = (een_r * hypothesis.sizing_risk_r / regels.stop_distance_pct).quantize(
            MONEY, rounding=ROUND_DOWN
        )
        veelvoud = hypothesis.min_liquidity_multiple
        liquiditeit = voorstel.liquidity_usd or Decimal("0")
        if veelvoud > 0 and liquiditeit < inleg * veelvoud:
            sla_over(
                voorstel,
                SkipReason.LIQUIDITY_TOO_THIN,
                f"Liquiditeit {liquiditeit} is minder dan {veelvoud}x de positie {inleg}.",
            )
            continue

        # 5. De risicolaag — dezelfde pure code en dezelfde grenzen als in fase 1.
        besluit = evaluate_entry(
            ledger.snapshot(moment),
            EntryRequest(
                hypothesis=hypothesis.label,
                entry_price=voorstel.price_usd,
                stop_price=voorstel.price_usd - stop_afstand,
                risk_r=hypothesis.sizing_risk_r,
            ),
        )
        if not besluit.allowed:
            sla_over(
                voorstel,
                SkipReason.RISK_VETO,
                f"{besluit.veto.value}: {besluit.reason}",
            )
            continue

        # 6. Het fill-model.
        fill_teller += 1
        uitkomst = fill_model.fill(
            FillRequest(
                kind=FillKind.ENTRY,
                requested_at=moment,
                expected_price=voorstel.price_usd,
                quote_usd=inleg,
                pool=pool_depth_from_liquidity(
                    liquidity_usd=liquiditeit, spot_price=voorstel.price_usd
                ),
            ),
            seed=fill_teller,
            price_after=lambda m, pool=voorstel.pool_address: prijzen.at_or_after(pool, m),
        )
        if not uitkomst.filled:
            reden = (
                SkipReason.FILL_EXPIRED
                if uitkomst.failure_reason == "no_price_after_latency"
                else SkipReason.FILL_FAILED
            )
            sla_over(voorstel, reden, f"{SKIP_UITLEG[reden]} Kosten: ${uitkomst.fee_usd}.")
            continue

        stop = (uitkomst.fill_price - stop_afstand).quantize(Decimal("0.000000000001"))
        trade = TradeRecord(
            pool_address=voorstel.pool_address,
            token_address=voorstel.token_address,
            opened_at=uitkomst.filled_at,
            entry_reason=f"{strategy.name}: willekeurige instap uit het universum",
            risk_r=hypothesis.sizing_risk_r,
            risk_quote=(uitkomst.units * stop_afstand).quantize(MONEY),
            units=uitkomst.units,
            entry_expected_price=voorstel.price_usd,
            entry_fill_price=uitkomst.fill_price,
            stop_price=stop,
            fees_usd=uitkomst.fee_usd,
            slippage_usd=uitkomst.slippage_usd,
            latency_cost_usd=uitkomst.latency_cost_usd,
        )
        trade.fills.append(
            FillRecord(sequence=0, kind="entry", reason="entry", outcome=uitkomst)
        )
        trades.append(trade)
        posities[voorstel.pool_address] = OpenPosition(
            pool_address=voorstel.pool_address,
            opened_at=uitkomst.filled_at,
            entry_price=uitkomst.fill_price,
            units=uitkomst.units,
            stop_price=stop,
            r_price_distance=stop_afstand,
            risk_quote=trade.risk_quote,
            peak_price=uitkomst.fill_price,
            trade_id=len(trades) - 1,
        )
        ledger.reserve(hypothesis.sizing_risk_r)
        signalen.append(
            SignalRecord(
                pool_address=voorstel.pool_address,
                observed_at=moment,
                price_usd=voorstel.price_usd,
                taken=True,
                reason="taken",
                detail=f"Ingestapt voor ${inleg} met een stop op {stop}.",
            )
        )

    # Wat er aan het eind nog openstaat, wordt gesloten op de laatst bekende prijs van die
    # pool. Laten staan zou betekenen dat alleen de afgelopen trades meetellen, en dat is
    # precies de gunstige selectie waar deze opdracht tegen waarschuwt.
    gedwongen = 0
    for pool, positie in list(posities.items()):
        laatste = prijzen.last_price(pool)
        if laatste is None:
            continue
        trade = trades[positie.trade_id]
        _waardeer_en_sluit(
            trade=trade,
            positie=positie,
            prijs=laatste,
            liquiditeit=_laatste_liquiditeit.get(pool) or Decimal("0"),
            moment=momenten[-1] if momenten else positie.opened_at,
            fill_model=fill_model,
            reden=END_OF_CORPUS,
        )
        _reken_af(trade, positie, een_r)
        ledger.release(trade.risk_r)
        if trade.r_multiple is not None:
            ledger.book(momenten[-1], trade.r_multiple)
            r_curve.append(trade.r_multiple)
        gedwongen += 1
        del posities[pool]

    gesloten = [t for t in trades if t.r_multiple is not None]
    from app.quantlab.metrics import max_drawdown_r

    return EngineResult(
        variant=variant,
        seed=seed,
        ticks=len(ticks),
        signals_proposed=len(signalen),
        trades_opened=len(trades),
        trades_closed=len(gesloten),
        trades_force_closed=gedwongen,
        trades_closed_stale=stale_gesloten,
        equity_quote=equity_quote,
        one_r_quote=een_r,
        realized_r=ledger.realized_r.quantize(R_SCALE),
        max_drawdown_r=max_drawdown_r([TradeResult(r_multiple=r) for r in r_curve]),
        max_open_risk_r=ledger.max_open_risk_r,
        total_fees_usd=sum((t.fees_usd for t in trades), Decimal("0")).quantize(MONEY),
        total_slippage_usd=sum((t.slippage_usd for t in trades), Decimal("0")).quantize(MONEY),
        skipped_by_reason=overgeslagen,
        signals=signalen,
        trades=trades,
    )


def _verkoop(
    *,
    trade: TradeRecord,
    positie: OpenPosition,
    besluit: ExitDecision,
    kandidaat: Candidate,
    moment: datetime,
    fill_model: FillModel,
    prijzen: _PriceIndex,
    seed: int,
) -> bool:
    """Voer een (gedeeltelijke) uitstap uit. Geeft True als de positie nu dicht is."""
    stuks = (positie.units * besluit.fraction).quantize(UNITS, rounding=ROUND_DOWN)
    if stuks <= 0:
        return True

    uitkomst = fill_model.fill(
        FillRequest(
            kind=FillKind.EXIT,
            requested_at=moment,
            expected_price=besluit.trigger_price,
            units=stuks,
            pool=pool_depth_from_liquidity(
                liquidity_usd=kandidaat.liquidity_usd or Decimal("0"),
                spot_price=kandidaat.price_usd or besluit.trigger_price,
            ),
        ),
        seed=seed,
        price_after=lambda m, pool=positie.pool_address: prijzen.at_or_after(pool, m),
    )
    trade.fills.append(
        FillRecord(
            sequence=len(trade.fills),
            kind="exit",
            reason=besluit.kind.value,
            outcome=uitkomst,
        )
    )
    trade.fees_usd += uitkomst.fee_usd

    if not uitkomst.filled:
        # Een mislukte uitstap betekent niet dat de positie weg is: de kosten zijn geboekt
        # en op de volgende tick wordt het opnieuw geprobeerd. Dat is wat er in het echt
        # ook gebeurt, en het is duurder dan één poging.
        return False

    trade.exit_quote_usd += uitkomst.quote_usd
    trade.slippage_usd += uitkomst.slippage_usd
    trade.latency_cost_usd += uitkomst.latency_cost_usd
    positie.units = (positie.units - stuks).quantize(UNITS)

    if besluit.kind is ExitKind.TAKE_HALF:
        positie.half_taken = True
        trade.exit_reason = besluit.kind.value
        return positie.units <= 0

    trade.exit_reason = besluit.kind.value
    trade.closed_at = uitkomst.filled_at
    return True


def _waardeer_en_sluit(
    *,
    trade: TradeRecord,
    positie: OpenPosition,
    prijs: Decimal,
    liquiditeit: Decimal,
    moment: datetime,
    fill_model: FillModel,
    reden: str,
) -> None:
    """Sluit een positie op een bekende prijs, als waardering en niet als uitstap.

    Twee gevallen: de pool is stil gevallen, of het corpus houdt op. In beide is er geen
    "prijs na de vertraging" om op te vullen — die bestaat niet in de gegevens. Doen alsof
    er een order is verstuurd die we hebben zien landen, zou een getal opleveren dat
    nergens op berust; dit is een waardering, en hij staat als zodanig in de boekhouding.
    """
    stuks = positie.units
    if stuks <= 0:
        trade.closed_at = moment
        trade.exit_reason = reden
        return

    uitkomst = fill_model.mark_to_market(
        units=stuks,
        price=prijs,
        pool=pool_depth_from_liquidity(
            liquidity_usd=liquiditeit, spot_price=prijs
        )
        if liquiditeit > 0
        else pool_depth_from_liquidity(
            liquidity_usd=stuks * prijs * Decimal("100"), spot_price=prijs
        ),
        moment=moment,
        reason=reden,
    )
    trade.fills.append(
        FillRecord(
            sequence=len(trade.fills), kind="exit", reason=reden, outcome=uitkomst
        )
    )
    trade.fees_usd += uitkomst.fee_usd
    trade.exit_quote_usd += uitkomst.quote_usd
    trade.slippage_usd += uitkomst.slippage_usd
    positie.units = Decimal("0")
    trade.closed_at = moment
    trade.exit_reason = reden


def _reken_af(trade: TradeRecord, positie: OpenPosition, one_r_quote: Decimal) -> None:
    """De uitkomst van een gesloten trade, in geld en in R.

    De koers EUR→USD valt hier weg: 1R en de winst worden met dezelfde koers omgerekend. R
    is dus zuiver relatief, en dat is precies wat je wil — een wisselkoers die beweegt, mag
    het resultaat van een strategie niet veranderen.
    """
    inleg = trade.units * trade.entry_fill_price
    trade.closed_at = trade.closed_at or positie.opened_at
    trade.pnl_usd = (trade.exit_quote_usd - inleg - trade.fees_usd).quantize(MONEY)
    if one_r_quote > 0:
        trade.r_multiple = (trade.pnl_usd / one_r_quote).quantize(R_SCALE)
