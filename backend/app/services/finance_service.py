"""Het financiële overzicht.

De optelsom telt alleen accounts die daadwerkelijk gekoppeld zijn én een betrouwbare
waarde in euro hebben. Kan een bedrag niet worden omgerekend, dan valt het account
zichtbaar buiten het totaal in plaats van er met een gegokte koers in te verdwijnen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.base import (
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
)
from app.integrations.finance.registry import get_finance_provider
from app.integrations.fx import get_fx_rates
from app.models.activity import ActivityAction
from app.models.base import utcnow
from app.models.finance import AccountStatus, FinanceSnapshot, FinancialAccount
from app.services.activity_service import log_activity
from app.utils.crypto import get_vault
from app.utils.money import quantize_money, to_eur
from app.utils.timeutil import ensure_utc

ZERO = Decimal("0.00")


class AccountNotFound(Exception):
    pass


async def _owned_account(
    session: AsyncSession, account_id: int, user_id: int
) -> FinancialAccount:
    account = await session.get(FinancialAccount, account_id)
    if account is None or account.user_id != user_id:
        raise AccountNotFound
    return account


async def list_accounts(session: AsyncSession, user_id: int) -> Sequence[FinancialAccount]:
    result = await session.execute(
        select(FinancialAccount)
        .where(FinancialAccount.user_id == user_id)
        .order_by(FinancialAccount.account_type, FinancialAccount.name)
    )
    return result.scalars().all()


def _is_stale(account: FinancialAccount, now: datetime, stale_after: timedelta) -> bool:
    if account.last_synced_at is None:
        return True
    return ensure_utc(account.last_synced_at) < now - stale_after


async def overview(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> dict[str, Any]:
    settings = get_settings()
    now = ensure_utc(now or utcnow())
    stale_after = timedelta(minutes=settings.stale_after_minutes)
    accounts = [a for a in await list_accounts(session, user_id) if a.active]

    total = ZERO
    by_type: dict[str, Decimal] = {}
    counted = 0
    excluded: list[dict[str, str]] = []
    last_updated: datetime | None = None

    for account in accounts:
        if account.last_synced_at is not None:
            moment = ensure_utc(account.last_synced_at)
            last_updated = moment if last_updated is None else max(last_updated, moment)

        if account.status in (AccountStatus.REAUTH_REQUIRED, AccountStatus.SYNC_FAILED):
            excluded.append({"name": account.name, "reason": account.status})
            continue
        if account.current_value_eur is None:
            excluded.append(
                {
                    "name": account.name,
                    "reason": "fx_unavailable"
                    if account.current_value is not None
                    else "no_value",
                }
            )
            continue
        value = quantize_money(account.current_value_eur)
        total += value
        by_type[account.account_type] = by_type.get(account.account_type, ZERO) + value
        counted += 1

    trend = await _trend(session, user_id, total, now)

    return {
        "total_eur": quantize_money(total),
        "connected_accounts": len(accounts),
        "counted_accounts": counted,
        "excluded_accounts": excluded,
        "breakdown": [
            {"account_type": key, "total_eur": quantize_money(value)}
            for key, value in sorted(by_type.items(), key=lambda pair: pair[1], reverse=True)
        ],
        "last_updated": last_updated,
        "stale": bool(accounts) and all(_is_stale(a, now, stale_after) for a in accounts),
        "trend_pct": trend,
        "server_time": now,
    }


async def _trend(
    session: AsyncSession, user_id: int, total: Decimal, now: datetime
) -> float | None:
    """Verschil met een week geleden, in procenten.

    Geen momentopname van een week terug? Dan geen trend. Een percentage uit één
    meetpunt is geen trend maar een verzinsel.
    """
    reference = await session.scalar(
        select(FinanceSnapshot)
        .where(
            FinanceSnapshot.user_id == user_id,
            FinanceSnapshot.captured_at <= now - timedelta(days=7),
        )
        .order_by(FinanceSnapshot.captured_at.desc())
        .limit(1)
    )
    if reference is None or reference.total_eur is None or reference.total_eur == 0:
        return None
    change = (total - Decimal(reference.total_eur)) / Decimal(reference.total_eur) * 100
    return float(round(change, 2))


async def capture_snapshot(session: AsyncSession, user_id: int) -> FinanceSnapshot:
    summary = await overview(session, user_id)
    snapshot = FinanceSnapshot(
        user_id=user_id,
        total_eur=summary["total_eur"],
        breakdown={
            row["account_type"]: str(row["total_eur"]) for row in summary["breakdown"]
        },
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def history(
    session: AsyncSession, user_id: int, days: int = 90
) -> Sequence[FinanceSnapshot]:
    since = utcnow() - timedelta(days=days)
    result = await session.execute(
        select(FinanceSnapshot)
        .where(FinanceSnapshot.user_id == user_id, FinanceSnapshot.captured_at >= since)
        .order_by(FinanceSnapshot.captured_at)
    )
    return result.scalars().all()


async def create_account(
    session: AsyncSession, user_id: int, data: dict[str, Any]
) -> FinancialAccount:
    credentials = data.pop("credentials", None)
    account = FinancialAccount(user_id=user_id, **data)
    account.credentials_encrypted = get_vault().encrypt(credentials)
    account.status = (
        AccountStatus.CONNECTED if credentials else AccountStatus.NOT_CONFIGURED
    )
    session.add(account)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.FINANCE_ACCOUNT_CONNECTED,
        user_id=user_id,
        message=f"Financieel account '{account.name}' gekoppeld via {account.provider}.",
        subject_type="financial_account",
        subject_id=account.id,
        context={"provider": account.provider, "account_type": account.account_type},
    )
    return account


async def update_account(
    session: AsyncSession, user_id: int, account_id: int, data: dict[str, Any]
) -> FinancialAccount:
    account = await _owned_account(session, account_id, user_id)
    if "credentials" in data:
        credentials = data.pop("credentials")
        account.credentials_encrypted = get_vault().encrypt(credentials)
        if credentials:
            account.status = AccountStatus.CONNECTED
    for field, value in data.items():
        setattr(account, field, value)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.FINANCE_ACCOUNT_UPDATED,
        user_id=user_id,
        message=f"Financieel account '{account.name}' gewijzigd.",
        subject_type="financial_account",
        subject_id=account.id,
    )
    return account


async def delete_account(session: AsyncSession, user_id: int, account_id: int) -> None:
    account = await _owned_account(session, account_id, user_id)
    name = account.name
    await session.delete(account)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.FINANCE_ACCOUNT_REMOVED,
        user_id=user_id,
        message=f"Financieel account '{name}' losgekoppeld.",
        subject_type="financial_account",
        subject_id=account_id,
    )


async def sync_account(session: AsyncSession, account: FinancialAccount) -> FinancialAccount:
    """Haalt één account op bij zijn provider en zet het resultaat vast.

    Een fout is nooit fataal: de status vertelt wat er mis is en de vorige waarde
    blijft staan, zodat het dashboard niet ineens op nul springt.
    """
    provider = get_finance_provider(account.provider)
    if provider is None:
        account.status = AccountStatus.NOT_CONFIGURED
        account.status_detail = f"Onbekende provider '{account.provider}'."
        await session.flush()
        return account

    credentials = get_vault().decrypt(account.credentials_encrypted)
    try:
        balance = await provider.fetch_balance(credentials)
    except ProviderNotConfigured as exc:
        account.status = AccountStatus.NOT_CONFIGURED
        account.status_detail = str(exc)
        await session.flush()
        return account
    except ProviderAuthError as exc:
        account.status = AccountStatus.REAUTH_REQUIRED
        account.status_detail = str(exc)
        await _log_sync_failure(session, account, str(exc))
        return account
    except ProviderError as exc:
        account.status = AccountStatus.SYNC_FAILED
        account.status_detail = str(exc)
        await _log_sync_failure(session, account, str(exc))
        return account

    rate = await get_fx_rates().rate_to_eur(balance.currency)
    value_eur = to_eur(balance.value, balance.currency, rate)

    account.current_value = quantize_money(balance.value)
    account.current_value_eur = value_eur
    account.fx_rate = rate
    account.currency = balance.currency
    if balance.external_account_id:
        account.external_account_id = balance.external_account_id
    account.last_synced_at = ensure_utc(balance.measured_at or utcnow())
    if value_eur is None:
        account.status = AccountStatus.SYNC_FAILED
        account.status_detail = (
            f"Geen wisselkoers voor {balance.currency}; dit account telt niet mee."
        )
    else:
        account.status = AccountStatus.CONNECTED
        account.status_detail = None
    await session.flush()
    return account


async def _log_sync_failure(
    session: AsyncSession, account: FinancialAccount, detail: str
) -> None:
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.FINANCE_SYNC_FAILED,
        user_id=account.user_id,
        message=f"Synchronisatie van '{account.name}' mislukt.",
        subject_type="financial_account",
        subject_id=account.id,
        context={"provider": account.provider, "detail": detail[:200]},
    )


async def sync_all(session: AsyncSession, user_id: int) -> list[FinancialAccount]:
    accounts = [a for a in await list_accounts(session, user_id) if a.active]
    for account in accounts:
        await sync_account(session, account)
    if accounts:
        await capture_snapshot(session, user_id)
        await log_activity(
            session,
            action=ActivityAction.FINANCE_SYNC_COMPLETED,
            user_id=user_id,
            message=f"{len(accounts)} financiële account(s) bijgewerkt.",
        )
    return accounts
