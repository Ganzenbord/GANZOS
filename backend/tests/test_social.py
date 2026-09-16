"""Tests voor de gecombineerde social-statistieken."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.integrations.base import (
    ChannelInfo,
    ChannelStats,
    ProviderAuthError,
    ProviderError,
    Revenue,
)
from app.integrations.social.registry import register_social_provider
from app.models.social import ChannelStatus, SocialChannelStats
from app.services import social_service
from tests.conftest import auth_headers


class FakeSocial:
    def __init__(
        self,
        platform: str,
        stats: ChannelStats | None = None,
        revenue: Revenue | None = None,
        error: Exception | None = None,
    ):
        self.platform = platform
        self.display_name = platform
        self._stats = stats
        self._revenue = revenue
        self._error = error

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        return True

    async def get_channel(self, credentials):
        return ChannelInfo(external_channel_id="x", name=self.platform)

    async def get_stats(self, credentials):
        if self._error is not None:
            raise self._error
        assert self._stats is not None
        return self._stats

    async def get_recent_content(self, credentials, limit: int = 5):
        return []

    async def get_revenue(self, credentials):
        return self._revenue


async def _channel(session, owner, platform: str, name: str | None = None):
    channel = await social_service.create_channel(
        session,
        owner.id,
        {
            "platform": platform,
            "channel_name": name or f"{platform} kanaal",
            "external_channel_id": None,
            "credentials": {"access_token": "x"},
        },
    )
    await session.commit()
    return channel


async def test_empty_state(session, owner):
    summary = await social_service.overview(session, owner.id)
    assert summary["followers"] is None
    assert summary["channels_total"] == 0
    assert summary["revenue_available"] is False


async def test_combines_all_connected_channels(session, owner):
    register_social_provider(
        FakeSocial("s_yt", ChannelStats(followers=6421, views=2_000_000, likes=30_000))
    )
    register_social_provider(
        FakeSocial("s_ig", ChannelStats(followers=4832, views=500_000, likes=15_000))
    )
    register_social_provider(
        FakeSocial("s_tt", ChannelStats(followers=1589, views=340_000, likes=3_921))
    )
    for platform in ("s_yt", "s_ig", "s_tt"):
        channel = await _channel(session, owner, platform)
        await social_service.sync_channel(session, channel)
    await session.commit()

    summary = await social_service.overview(session, owner.id)
    assert summary["followers"] == 12_842
    assert summary["views"] == 2_840_000
    assert summary["likes"] == 48_921
    assert summary["channels_counted"] == 3
    assert len(summary["platforms"]) == 3


async def test_missing_metrics_stay_empty_instead_of_zero(session, owner):
    """Instagram levert geen views; dat mag geen 0 worden."""
    register_social_provider(FakeSocial("s_only_followers", ChannelStats(followers=100)))
    channel = await _channel(session, owner, "s_only_followers")
    await social_service.sync_channel(session, channel)
    await session.commit()

    summary = await social_service.overview(session, owner.id)
    assert summary["followers"] == 100
    assert summary["views"] is None
    assert summary["likes"] is None


async def test_growth_is_calculated_from_two_measurements(session, owner):
    register_social_provider(FakeSocial("s_growth", ChannelStats(followers=1084)))
    channel = await _channel(session, owner, "s_growth")
    session.add(
        SocialChannelStats(
            channel_id=channel.id,
            followers=1000,
            measured_at=datetime.now(timezone.utc) - timedelta(days=9),
        )
    )
    await social_service.sync_channel(session, channel)
    await session.commit()

    assert (await social_service.overview(session, owner.id))["growth_pct"] == 8.4


async def test_growth_is_empty_without_a_baseline(session, owner):
    register_social_provider(FakeSocial("s_new", ChannelStats(followers=500)))
    channel = await _channel(session, owner, "s_new")
    await social_service.sync_channel(session, channel)
    await session.commit()
    assert (await social_service.overview(session, owner.id))["growth_pct"] is None


async def test_revenue_only_when_a_platform_reports_it(session, owner):
    register_social_provider(FakeSocial("s_free", ChannelStats(followers=10)))
    channel = await _channel(session, owner, "s_free")
    await social_service.sync_channel(session, channel)
    await session.commit()
    summary = await social_service.overview(session, owner.id)
    assert summary["revenue"] is None
    assert summary["revenue_available"] is False

    register_social_provider(
        FakeSocial(
            "s_paid",
            ChannelStats(followers=10),
            revenue=Revenue(amount=Decimal("1284.00"), currency="EUR"),
        )
    )
    paid = await _channel(session, owner, "s_paid")
    await social_service.sync_channel(session, paid)
    await session.commit()

    summary = await social_service.overview(session, owner.id)
    assert summary["revenue"] == Decimal("1284.00")
    assert summary["revenue_available"] is True


async def test_expired_token_sets_reauth_and_is_reported(session, owner):
    register_social_provider(
        FakeSocial("s_dead", error=ProviderAuthError("Sessie verlopen"))
    )
    channel = await _channel(session, owner, "s_dead", name="TikTok Kanaal 1")
    await social_service.sync_channel(session, channel)
    await session.commit()

    assert channel.status == ChannelStatus.REAUTH_REQUIRED
    summary = await social_service.overview(session, owner.id)
    assert summary["channels_counted"] == 0
    assert summary["attention"][0]["channel_name"] == "TikTok Kanaal 1"
    assert summary["attention"][0]["status"] == "reauth_required"


async def test_provider_failure_does_not_crash_the_overview(session, owner):
    register_social_provider(FakeSocial("s_err", error=ProviderError("500")))
    register_social_provider(FakeSocial("s_ok", ChannelStats(followers=42)))
    broken = await _channel(session, owner, "s_err")
    healthy = await _channel(session, owner, "s_ok")
    await social_service.sync_channel(session, broken)
    await social_service.sync_channel(session, healthy)
    await session.commit()

    summary = await social_service.overview(session, owner.id)
    assert summary["followers"] == 42
    assert summary["channels_counted"] == 1


async def test_channels_of_other_users_are_invisible(client, owner, trusted, session):
    await _channel(session, owner, "youtube", name="Van Stef")
    listing = await client.get("/social/channels", headers=auth_headers(trusted))
    assert listing.status_code == 200
    assert listing.json() == []


async def test_managing_channels_needs_confirmation(client, trusted):
    payload = {"platform": "youtube", "channel_name": "Nieuw kanaal"}
    without = await client.post("/social/channels", json=payload, headers=auth_headers(trusted))
    assert without.status_code == 428
    ok = await client.post(
        "/social/channels", json=payload, headers=auth_headers(trusted, confirm=True)
    )
    assert ok.status_code == 201
    # Zonder gegevens is een kanaal niet gekoppeld; dat moet het ook zeggen.
    assert ok.json()["status"] == "not_configured"
