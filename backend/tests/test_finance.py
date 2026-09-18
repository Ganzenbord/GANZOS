"""Tests voor het financiële overzicht."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.integrations.base import Balance, ProviderAuthError, ProviderError
from app.integrations.finance.registry import register_finance_provider
from app.models.finance import AccountStatus, AccountType, FinanceSnapshot
from app.services import finance_service
from tests.conftest import auth_headers, confirm_headers


class FakeProvider:
    """Een provider die precies doet wat de test nodig heeft."""

    read_only = True

    def __init__(self, key: str, balance: Balance | None = None, error: Exception | None = None):
        self.key = key
        self.display_name = key
        self._balance = balance
        self._error = error

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        return True

    async def fetch_balance(self, credentials: dict[str, Any] | None) -> Balance:
        if self._error is not None:
            raise self._error
        assert self._balance is not None
        return self._balance


class FakeRates:
    def __init__(self, rates: dict[str, Decimal | None]):
        self._rates = rates

    async def rate_to_eur(self, currency: str) -> Decimal | None:
        if currency.upper() == "EUR":
            return Decimal(1)
        return self._rates.get(currency.upper())


@pytest.fixture
def rates(monkeypatch):
    def install(mapping: dict[str, Decimal | None]):
        monkeypatch.setattr(
            finance_service, "get_fx_rates", lambda: FakeRates(mapping), raising=True
        )

    return install


async def _account(session, owner, provider: str, **kwargs):
    data = {
        "provider": provider,
        "account_type": AccountType.BANK,
        "name": kwargs.pop("name", "Betaalrekening"),
        "currency": kwargs.pop("currency", "EUR"),
        "credentials": {"value": "1"},
        **kwargs,
    }
    account = await finance_service.create_account(session, owner.id, data)
    await session.commit()
    return account


async def test_empty_state_has_no_invented_total(session, owner):
    summary = await finance_service.overview(session, owner.id)
    assert summary["total_eur"] == Decimal("0.00")
    assert summary["connected_accounts"] == 0
    assert summary["trend_pct"] is None


async def test_aggregates_multiple_accounts(session, owner, rates):
    rates({})
    register_finance_provider(
        FakeProvider("t_bank", Balance(value=Decimal("12420.00"), currency="EUR"))
    )
    register_finance_provider(
        FakeProvider("t_broker", Balance(value=Decimal("21950.50"), currency="EUR"))
    )
    bank = await _account(session, owner, "t_bank")
    broker = await _account(
        session, owner, "t_broker", name="Beleggingen", account_type=AccountType.BROKER
    )
    await finance_service.sync_account(session, bank)
    await finance_service.sync_account(session, broker)
    await session.commit()

    summary = await finance_service.overview(session, owner.id)
    assert summary["total_eur"] == Decimal("34370.50")
    assert summary["counted_accounts"] == 2
    assert {row["account_type"] for row in summary["breakdown"]} == {"bank", "broker"}


async def test_converts_to_eur_and_keeps_the_original(session, owner, rates):
    rates({"USD": Decimal("0.90")})
    register_finance_provider(
        FakeProvider("t_usd", Balance(value=Decimal("1000.00"), currency="USD"))
    )
    account = await _account(session, owner, "t_usd", currency="USD")
    await finance_service.sync_account(session, account)
    await session.commit()

    assert account.current_value == Decimal("1000.00")
    assert account.currency == "USD"
    assert account.current_value_eur == Decimal("900.00")
    assert (await finance_service.overview(session, owner.id))["total_eur"] == Decimal("900.00")


async def test_missing_exchange_rate_excludes_the_account(session, owner, rates):
    """Zonder koers telt het account niet mee — liever zichtbaar missen dan gokken."""
    rates({})  # geen enkele koers beschikbaar
    register_finance_provider(
        FakeProvider("t_nok", Balance(value=Decimal("5000.00"), currency="NOK"))
    )
    account = await _account(session, owner, "t_nok", currency="NOK")
    await finance_service.sync_account(session, account)
    await session.commit()

    summary = await finance_service.overview(session, owner.id)
    assert summary["total_eur"] == Decimal("0.00")
    assert summary["counted_accounts"] == 0
    assert account.status == AccountStatus.SYNC_FAILED


async def test_unknown_provider_is_marked_not_configured(session, owner):
    account = await _account(session, owner, "bestaat-niet")
    await finance_service.sync_account(session, account)
    await session.commit()
    assert account.status == AccountStatus.NOT_CONFIGURED
    assert "bestaat-niet" in (account.status_detail or "")


async def test_auth_failure_sets_reauth_and_excludes_from_total(session, owner, rates):
    rates({})
    register_finance_provider(
        FakeProvider("t_expired", error=ProviderAuthError("Token verlopen"))
    )
    account = await _account(session, owner, "t_expired")
    account.current_value_eur = Decimal("100.00")
    await finance_service.sync_account(session, account)
    await session.commit()

    assert account.status == AccountStatus.REAUTH_REQUIRED
    summary = await finance_service.overview(session, owner.id)
    assert summary["total_eur"] == Decimal("0.00")
    assert summary["excluded_accounts"][0]["reason"] == "reauth_required"


async def test_provider_error_keeps_the_previous_value(session, owner, rates):
    """Een mislukte ronde mag het dashboard niet op nul zetten."""
    rates({})
    register_finance_provider(FakeProvider("t_down", error=ProviderError("Server plat")))
    account = await _account(session, owner, "t_down")
    account.current_value_eur = Decimal("250.00")
    await finance_service.sync_account(session, account)
    await session.commit()

    assert account.current_value_eur == Decimal("250.00")
    assert account.status == AccountStatus.SYNC_FAILED


async def test_stale_data_is_reported(session, owner, rates):
    rates({})
    register_finance_provider(
        FakeProvider("t_old", Balance(value=Decimal("10.00"), currency="EUR"))
    )
    account = await _account(session, owner, "t_old")
    await finance_service.sync_account(session, account)
    account.last_synced_at = datetime.now(timezone.utc) - timedelta(hours=5)
    await session.commit()

    assert (await finance_service.overview(session, owner.id))["stale"] is True


async def test_trend_needs_a_reference_point(session, owner, rates):
    rates({})
    register_finance_provider(
        FakeProvider("t_trend", Balance(value=Decimal("110.00"), currency="EUR"))
    )
    account = await _account(session, owner, "t_trend")
    await finance_service.sync_account(session, account)
    await session.commit()

    # Zonder momentopname van vorige week: geen trend.
    assert (await finance_service.overview(session, owner.id))["trend_pct"] is None

    session.add(
        FinanceSnapshot(
            user_id=owner.id,
            total_eur=Decimal("100.00"),
            captured_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
    )
    await session.commit()
    assert (await finance_service.overview(session, owner.id))["trend_pct"] == 10.0


async def test_finance_is_tier_one_only(client, owner, trusted):
    assert (await client.get("/finance/overview", headers=auth_headers(owner))).status_code == 200
    blocked = await client.get("/finance/overview", headers=auth_headers(trusted))
    assert blocked.status_code == 403


async def test_managing_accounts_needs_a_second_confirmation(client, owner, session):
    payload = {
        "provider": "manual",
        "account_type": "bank",
        "name": "Spaarrekening",
        "currency": "EUR",
        "credentials": {"value": "500.00"},
    }
    without = await client.post("/finance/accounts", json=payload, headers=auth_headers(owner))
    assert without.status_code == 428

    with_confirm = await client.post(
        "/finance/accounts", json=payload, headers=await confirm_headers(session, owner)
    )
    assert with_confirm.status_code == 201
    assert with_confirm.json()["current_value_eur"] == "500.00"


async def test_credentials_never_leave_the_backend(client, owner, session):
    await client.post(
        "/finance/accounts",
        json={
            "provider": "manual",
            "account_type": "bank",
            "name": "Rekening",
            "credentials": {"value": "12.34", "api_key": "geheim"},
        },
        headers=await confirm_headers(session, owner),
    )
    listing = await client.get("/finance/accounts", headers=auth_headers(owner))
    body = listing.text
    assert "geheim" not in body
    assert "credentials" not in body


async def test_activity_log_holds_no_amounts(client, owner, session):
    await client.post(
        "/finance/accounts",
        json={
            "provider": "manual",
            "account_type": "bank",
            "name": "Rekening",
            "credentials": {"value": "98765.43"},
        },
        headers=await confirm_headers(session, owner),
    )
    activity = await client.get("/activity", headers=auth_headers(owner))
    assert "98765" not in activity.text
    assert "FINANCE_ACCOUNT_CONNECTED" in activity.text


async def test_sync_timestamp_is_returned_with_a_timezone(client, owner, session):
    """Anders leest de browser 'zojuist bijgewerkt' als lokale tijd en klopt het niet."""
    await client.post(
        "/finance/accounts",
        json={
            "provider": "manual",
            "account_type": "bank",
            "name": "Rekening",
            "credentials": {"value": "10.00"},
        },
        headers=await confirm_headers(session, owner),
    )
    accounts = (await client.get("/finance/accounts", headers=auth_headers(owner))).json()
    stamp = accounts[0]["last_synced_at"]
    assert stamp.endswith("Z") or "+00:00" in stamp
