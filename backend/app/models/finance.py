"""Financiële accounts.

Bewust abstract: een bankrekening, een crypto-wallet en een beleggingsrekening zijn
allemaal hetzelfde soort rij, met een `provider` die zegt wie de gegevens levert.
Zo komt er later een bank bij zonder dat het dashboard of de API verandert.

De oorspronkelijke valuta en waarde blijven altijd bewaard. `current_value_eur` is
de omgerekende waarde; is die NULL, dan was er geen betrouwbare wisselkoers en telt
het account niet stilzwijgend mee in het totaal.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class AccountType(StrEnum):
    BANK = "bank"
    SAVINGS = "savings"
    CRYPTO_WALLET = "crypto_wallet"
    EXCHANGE = "exchange"
    BROKER = "broker"
    INVESTMENT = "investment"
    OTHER = "other"


class AccountStatus(StrEnum):
    CONNECTED = "connected"
    SYNCING = "syncing"
    SYNC_FAILED = "sync_failed"
    REAUTH_REQUIRED = "reauth_required"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"


# Geld in centen-precisie: float zou bij optellen afrondingsfouten geven.
MONEY = Numeric(20, 2)


class FinancialAccount(Base, TimestampMixin):
    __tablename__ = "financial_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(String(190), nullable=True)

    current_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    current_value_eur: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=AccountStatus.NOT_CONFIGURED, nullable=False
    )
    status_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Versleuteld met de Fernet-sleutel uit GANZ_ENCRYPTION_KEY. Gaat nooit naar de
    # frontend en komt nooit in het activiteitenlog.
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class FinanceSnapshot(Base):
    """Het totaal op een moment, voor de vermogensgrafiek."""

    __tablename__ = "finance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    total_eur: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
