"""De koppelvlakken waar alle externe partijen zich aan houden.

Een nieuwe bank, exchange of platform toevoegen betekent: één klasse schrijven die
hieraan voldoet en hem in het register zetten. De services, de API en het dashboard
veranderen niet mee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """Er ging iets mis bij de externe partij."""


class ProviderAuthError(ProviderError):
    """De koppeling is verlopen; de gebruiker moet opnieuw inloggen."""


class ProviderNotConfigured(ProviderError):
    """Er zijn nog geen gegevens ingevuld om mee te verbinden."""


@dataclass(slots=True)
class Balance:
    value: Decimal
    currency: str
    external_account_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    measured_at: datetime | None = None


@dataclass(slots=True)
class ChannelInfo:
    external_channel_id: str
    name: str
    url: str | None = None


@dataclass(slots=True)
class ChannelStats:
    """Alles mag None zijn: niet elke partij levert elke metriek."""

    followers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    posts: int | None = None
    measured_at: datetime | None = None


@dataclass(slots=True)
class ContentItem:
    external_id: str
    title: str
    published_at: datetime | None = None
    url: str | None = None


@dataclass(slots=True)
class Revenue:
    amount: Decimal
    currency: str
    period_start: datetime | None = None
    period_end: datetime | None = None


@runtime_checkable
class FinanceProvider(Protocol):
    key: str
    display_name: str
    # Read-only waar het kan: Ganz hoeft nooit geld te verplaatsen.
    read_only: bool

    def is_configured(self, credentials: dict[str, Any] | None) -> bool: ...

    async def fetch_balance(self, credentials: dict[str, Any] | None) -> Balance: ...


@runtime_checkable
class SocialProvider(Protocol):
    platform: str
    display_name: str

    def is_configured(self, credentials: dict[str, Any] | None) -> bool: ...

    async def get_channel(self, credentials: dict[str, Any] | None) -> ChannelInfo: ...

    async def get_stats(self, credentials: dict[str, Any] | None) -> ChannelStats: ...

    async def get_recent_content(
        self, credentials: dict[str, Any] | None, limit: int = 5
    ) -> list[ContentItem]: ...

    async def get_revenue(self, credentials: dict[str, Any] | None) -> Revenue | None: ...
