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
