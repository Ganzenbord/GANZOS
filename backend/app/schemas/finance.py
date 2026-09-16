from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

from app.models.finance import AccountType


class FinancialAccountIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    account_type: AccountType
    name: str = Field(min_length=1, max_length=160)
    currency: str = Field(default="EUR", min_length=3, max_length=8)
    external_account_id: str | None = None
    # Gaat versleuteld de database in en komt nooit terug in een antwoord.
    credentials: dict[str, Any] | None = None


class FinancialAccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    account_type: AccountType | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    external_account_id: str | None = None
    active: bool | None = None
    credentials: dict[str, Any] | None = None


class FinancialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    account_type: str
    name: str
    currency: str
    current_value: Decimal | None
    current_value_eur: Decimal | None
    last_synced_at: UtcDatetime | None
    status: str
    status_detail: str | None
    active: bool


class BreakdownRow(BaseModel):
    account_type: str
    total_eur: Decimal


class ExcludedAccount(BaseModel):
    name: str
    reason: str


class FinanceOverviewOut(BaseModel):
    total_eur: Decimal
    connected_accounts: int
    counted_accounts: int
    excluded_accounts: list[ExcludedAccount]
    breakdown: list[BreakdownRow]
    last_updated: UtcDatetime | None
    stale: bool
    trend_pct: float | None
    server_time: UtcDatetime


class FinanceHistoryPoint(BaseModel):
    captured_at: UtcDatetime
    total_eur: Decimal
