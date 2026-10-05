"""Antwoordmodellen van het Quant Lab.

Expliciete velden, geen ruwe rijen. De bedragen gaan er als `Decimal` uit en worden dus
als tekst verstuurd — met opzet: een bedrag dat door een float gaat, komt er soms als
0.7299999999999999 uit.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime


class RiskLimitsOut(BaseModel):
    """De grenzen zoals ze in de code staan. Alleen om te laten zien, niet om te zetten."""

    risk_per_trade_pct: Decimal
    max_risk_per_trade_r: Decimal
    max_open_risk_r: Decimal
    day_loss_halt_r: Decimal
    week_loss_stop_r: Decimal
    heartbeat_max_age_seconds: int


class RiskStatusOut(BaseModel):
    trading_mode: str = Field(description="Altijd 'paper'; er wordt hier niet live gehandeld.")
    limits: RiskLimitsOut
    equity_eur: Decimal
    one_r_eur: Decimal
    open_risk_r: Decimal
    realized_day_r: Decimal
    realized_week_r: Decimal
    week_stop_level_r: Decimal
    kill_switch_active: bool
    day_halt_engaged: bool
    week_stop_engaged: bool
    heartbeat_age_seconds: float | None
    heartbeat_stale: bool
    entries_allowed: bool
    blocking: list[str]
    explanation: str


class RiskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hypothesis: str
    allowed: bool
    veto: str | None
    reason: str
    equity: Decimal
    risk_eur: Decimal
    position_units: Decimal
    realized_day_r: Decimal
    realized_week_r: Decimal
    created_at: UtcDatetime


class ControlIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class KillSwitchOut(BaseModel):
    kill_switch_active: bool
    reason: str
    changed_at: UtcDatetime
    explanation: str


class AgentSpendOut(BaseModel):
    agent: str
    description: str
    monthly_budget_eur: Decimal
    month_spent_eur: Decimal
    month_remaining_eur: Decimal
    daily_cap_eur: Decimal
    day_spent_eur: Decimal


class BudgetStatusOut(BaseModel):
    mode: str
    explanation: str
    month: str
    month_total_eur: Decimal
    month_remaining_eur: Decimal
    monthly_cap_eur: Decimal
    monthly_warning_eur: Decimal
    reserve_eur: Decimal
    usd_eur_rate: Decimal
    agents: list[AgentSpendOut]


class LlmCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: str
    model: str
    # "tokens" hier in de betekenis van rekeneenheden van een taalmodel: een aantal, geen
    # sleutel. Vandaar de uitzondering in tests/test_sanitization.py.
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: Decimal
    cost_eur: Decimal
    fx_rate: Decimal
    purpose: str
    created_at: UtcDatetime


# --- De datalaag (fase 2) ----------------------------------------------------


class DataCheckOut(BaseModel):
    """Eén controle: wat hij vond, hoe erg dat is, en wat het betekent."""

    check: str
    count: int
    severity: str
    explanation: str
    examples: list[str]


class DataQualityOut(BaseModel):
    verdict: str
    explanation: str
    ticks: int
    raw_events: int
    pools: int
    synthetic_events: int
    first_observed_at: UtcDatetime | None
    last_observed_at: UtcDatetime | None
    chain_ok: bool
    chain_explanation: str
    findings: list[DataCheckOut]
    # Alle controles die er zijn, ook die niets vonden. Een scherm dat alleen de
    # bevindingen laat zien, geeft de indruk dat er niet meer gecontroleerd wordt.
    checks: list[DataCheckOut]


class StorageOut(BaseModel):
    events: int
    ticks: int
    bytes_stored: int
    bytes_per_event: int
    measured_seconds: float
    first_received_at: UtcDatetime | None
    last_received_at: UtcDatetime | None
    projected_bytes_per_day: int
    projected_bytes_per_month: int
    explanation: str


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    started_at: UtcDatetime
    stopped_at: UtcDatetime | None
    stop_reason: str | None
    events: int
    ticks: int
    duplicates: int
    parse_failures: int
    bytes_stored: int


# --- De papieren handel (fase 3) ---------------------------------------------


class HypothesisOut(BaseModel):
    """Een geregistreerde hypothese. De brontekst zit er niet in: die is lang, en wie hem
    wil lezen vraagt hem per hypothese op."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    content_hash: str
    statement: str
    paper_only: bool
    source_path: str | None
    registered_at: UtcDatetime


class HypothesisDetailOut(HypothesisOut):
    source_yaml: str


class StrategyRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hypothesis_id: int
    variant: str
    seed: int
    corpus_digest: str
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    ticks: int
    signals_proposed: int
    trades_opened: int
    trades_closed: int
    trades_force_closed: int
    equity_quote: Decimal
    one_r_quote: Decimal
    usd_eur_rate: Decimal
    realized_r: Decimal
    max_drawdown_r: Decimal
    max_open_risk_r: Decimal
    total_fees_usd: Decimal
    total_slippage_usd: Decimal
    safety_oracle: str
    skipped_by_reason: dict[str, int] | None


class PaperTradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    pool_address: str
    token_address: str
    opened_at: UtcDatetime
    closed_at: UtcDatetime | None
    entry_reason: str
    exit_reason: str | None
    risk_r: Decimal
    units: Decimal
    entry_expected_price: Decimal
    entry_fill_price: Decimal
    stop_price: Decimal
    exit_quote_usd: Decimal
    fees_usd: Decimal
    slippage_usd: Decimal
    latency_cost_usd: Decimal
    pnl_usd: Decimal | None
    r_multiple: Decimal | None


class PaperFillOut(BaseModel):
    """Verwacht, markt, fill — in die volgorde te lezen als: wat je wilde, wat de markt
    deed in de tussentijd, en wat je werkelijk kreeg."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    kind: str
    reason: str
    requested_at: UtcDatetime
    filled_at: UtcDatetime
    latency_ms: float
    filled: bool
    failure_reason: str | None
    expected_price: Decimal
    market_price: Decimal | None
    fill_price: Decimal
    units: Decimal
    quote_usd: Decimal
    slippage_usd: Decimal
    latency_cost_usd: Decimal
    fee_usd: Decimal
    exit_haircut_applied: bool


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    pool_address: str
    observed_at: UtcDatetime
    price_usd: Decimal | None
    taken: bool
    reason: str
    detail: str | None


class ExpectancyOut(BaseModel):
    n: int
    expectancy_r: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    confidence: Decimal
    win_rate: Decimal | None
    conclusion_allowed: bool
    min_trades: int
    verdict: str
