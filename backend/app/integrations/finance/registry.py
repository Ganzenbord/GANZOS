"""Welke financiële providers Ganz kent."""

from __future__ import annotations

from app.integrations.base import FinanceProvider
from app.integrations.finance.crypto import CryptoPriceProvider
from app.integrations.finance.manual import ManualFinanceProvider

_PROVIDERS: dict[str, FinanceProvider] = {
    provider.key: provider
    for provider in (ManualFinanceProvider(), CryptoPriceProvider())
}


def get_finance_provider(key: str) -> FinanceProvider | None:
    return _PROVIDERS.get(key)


def finance_provider_keys() -> list[str]:
    return sorted(_PROVIDERS)


def describe_finance_providers() -> list[dict[str, object]]:
    return [
        {"key": p.key, "display_name": p.display_name, "read_only": p.read_only}
        for p in sorted(_PROVIDERS.values(), key=lambda p: p.key)
    ]


def register_finance_provider(provider: FinanceProvider) -> None:
    """Haakje voor tests en voor een provider die later wordt bijgeplugd."""
    _PROVIDERS[provider.key] = provider
