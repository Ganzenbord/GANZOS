"""De gecombineerde social-statistieken.

Het dashboard toont het totaal van álle gekoppelde, actieve kanalen samen. Kanalen die
niet gekoppeld zijn of opnieuw ingelogd moeten worden tellen niet mee, maar worden wel
apart gemeld — anders lijkt een dalend totaal een probleem met het kanaal in plaats
van met de koppeling.

Een metriek die een platform niet levert blijft leeg. Leeg is iets anders dan nul.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import (
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
)
from app.integrations.social.registry import get_social_provider
from app.models.activity import ActivityAction
from app.models.base import utcnow
from app.models.social import ChannelStatus, SocialChannel, SocialChannelStats
from app.services.activity_service import log_activity
from app.utils.crypto import get_vault
from app.utils.money import quantize_money
from app.utils.timeutil import ensure_utc

METRICS = ("followers", "views", "likes", "comments", "posts")


class ChannelNotFound(Exception):
    pass


async def _owned_channel(session: AsyncSession, channel_id: int, user_id: int) -> SocialChannel:
    channel = await session.get(SocialChannel, channel_id)
    if channel is None or channel.user_id != user_id:
        raise ChannelNotFound
    return channel


async def list_channels(session: AsyncSession, user_id: int) -> Sequence[SocialChannel]:
    result = await session.execute(
        select(SocialChannel)
        .where(SocialChannel.user_id == user_id)
        .order_by(SocialChannel.platform, SocialChannel.channel_name)
    )
    return result.scalars().all()


async def latest_stats(
    session: AsyncSession, channel_id: int, before: datetime | None = None
) -> SocialChannelStats | None:
    query = (
        select(SocialChannelStats)
        .where(SocialChannelStats.channel_id == channel_id)
        .order_by(SocialChannelStats.measured_at.desc())
        .limit(1)
    )
    if before is not None:
        query = query.where(SocialChannelStats.measured_at <= before)
    return await session.scalar(query)


def _sum_metric(rows: Sequence[SocialChannelStats], metric: str) -> int | None:
    """Telt op, maar geeft None als geen enkel kanaal deze metriek levert."""
    values = [getattr(row, metric) for row in rows if getattr(row, metric) is not None]
    return sum(values) if values else None


async def overview(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> dict[str, Any]:
    now = ensure_utc(now or utcnow())
    channels = list(await list_channels(session, user_id))
    counted = [
        channel
        for channel in channels
        if channel.active and channel.status == ChannelStatus.CONNECTED
    ]

    current_rows: list[SocialChannelStats] = []
    per_platform: dict[str, dict[str, Any]] = {}
    last_updated: datetime | None = None

    for channel in counted:
        stats = await latest_stats(session, channel.id)
        if stats is None:
            continue
        current_rows.append(stats)
        moment = ensure_utc(stats.measured_at)
        last_updated = moment if last_updated is None else max(last_updated, moment)

        bucket = per_platform.setdefault(
            channel.platform,
            {"platform": channel.platform, "channels": 0, **{m: None for m in METRICS}},
        )
        bucket["channels"] += 1
        for metric in METRICS:
            value = getattr(stats, metric)
            if value is not None:
                bucket[metric] = (bucket[metric] or 0) + value

    totals = {metric: _sum_metric(current_rows, metric) for metric in METRICS}

    # Groei over zeven dagen, alleen als er voor álle meegetelde kanalen een meting
    # van een week terug is. Anders zou een net gekoppeld kanaal als "groei" tellen.
    baseline_rows: list[SocialChannelStats] = []
    week_ago = now - timedelta(days=7)
    for channel in counted:
        row = await latest_stats(session, channel.id, before=week_ago)
        if row is not None:
            baseline_rows.append(row)
    growth_pct = None
    if len(baseline_rows) == len(counted) and counted:
        before_total = _sum_metric(baseline_rows, "followers")
        after_total = totals["followers"]
        if before_total and after_total is not None:
            growth_pct = float(round((after_total - before_total) / before_total * 100, 2))

    revenue = await _revenue_this_month(session, counted, now)

    return {
        **totals,
        "growth_pct": growth_pct,
        "revenue": revenue["amount"],
        "revenue_currency": revenue["currency"],
        "revenue_available": revenue["available"],
        "channels_total": len(channels),
        "channels_counted": len(counted),
        "platforms": sorted(per_platform.values(), key=lambda item: item["platform"]),
        "attention": [
            {
                "id": channel.id,
                "platform": channel.platform,
                "channel_name": channel.channel_name,
                "status": channel.status,
                "detail": channel.status_detail,
            }
            for channel in channels
            if channel.status != ChannelStatus.CONNECTED or not channel.active
        ],
        "last_updated": last_updated,
        "server_time": now,
    }


async def _revenue_this_month(
    session: AsyncSession, channels: Sequence[SocialChannel], now: datetime
) -> dict[str, Any]:
    """Omzet van deze maand. Levert geen enkel platform omzet, dan 'niet beschikbaar'."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = Decimal("0.00")
    currency: str | None = None
    found = False
    for channel in channels:
        row = await session.scalar(
            select(SocialChannelStats)
            .where(
                SocialChannelStats.channel_id == channel.id,
                SocialChannelStats.revenue.is_not(None),
                SocialChannelStats.measured_at >= month_start,
            )
            .order_by(SocialChannelStats.measured_at.desc())
            .limit(1)
        )
        if row is None or row.revenue is None:
            continue
        found = True
        total += Decimal(row.revenue)
        currency = currency or row.revenue_currency or "EUR"
    if not found:
        return {"amount": None, "currency": None, "available": False}
    return {"amount": quantize_money(total), "currency": currency or "EUR", "available": True}


async def create_channel(
    session: AsyncSession, user_id: int, data: dict[str, Any]
) -> SocialChannel:
    credentials = data.pop("credentials", None)
    channel = SocialChannel(user_id=user_id, **data)
    channel.credentials_encrypted = get_vault().encrypt(credentials)
    channel.status = ChannelStatus.CONNECTED if credentials else ChannelStatus.NOT_CONFIGURED
    session.add(channel)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.SOCIAL_CHANNEL_CONNECTED,
        user_id=user_id,
        message=f"Kanaal '{channel.channel_name}' ({channel.platform}) gekoppeld.",
        subject_type="social_channel",
        subject_id=channel.id,
        context={"platform": channel.platform},
    )
    return channel


async def update_channel(
    session: AsyncSession, user_id: int, channel_id: int, data: dict[str, Any]
) -> SocialChannel:
    channel = await _owned_channel(session, channel_id, user_id)
    if "credentials" in data:
        credentials = data.pop("credentials")
        channel.credentials_encrypted = get_vault().encrypt(credentials)
        if credentials:
            channel.status = ChannelStatus.CONNECTED
            channel.status_detail = None
    for field, value in data.items():
        setattr(channel, field, value)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.SOCIAL_CHANNEL_UPDATED,
        user_id=user_id,
        message=f"Kanaal '{channel.channel_name}' gewijzigd.",
        subject_type="social_channel",
        subject_id=channel.id,
    )
    return channel


async def delete_channel(session: AsyncSession, user_id: int, channel_id: int) -> None:
    channel = await _owned_channel(session, channel_id, user_id)
    name = channel.channel_name
    await session.delete(channel)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.SOCIAL_CHANNEL_REMOVED,
        user_id=user_id,
        message=f"Kanaal '{name}' verwijderd.",
        subject_type="social_channel",
        subject_id=channel_id,
    )


async def stats_history(
    session: AsyncSession, channel_id: int, days: int = 90
) -> Sequence[SocialChannelStats]:
    since = utcnow() - timedelta(days=days)
    result = await session.execute(
        select(SocialChannelStats)
        .where(
            SocialChannelStats.channel_id == channel_id,
            SocialChannelStats.measured_at >= since,
        )
        .order_by(SocialChannelStats.measured_at)
    )
    return result.scalars().all()


async def sync_channel(session: AsyncSession, channel: SocialChannel) -> SocialChannel:
    """Haalt één kanaal op. Een verlopen token zet de status op reauth_required;
    Ganz blijft gewoon draaien."""
    provider = get_social_provider(channel.platform)
    if provider is None:
        channel.status = ChannelStatus.NOT_CONFIGURED
        channel.status_detail = f"Onbekend platform '{channel.platform}'."
        await session.flush()
        return channel

    credentials = get_vault().decrypt(channel.credentials_encrypted)
    try:
        stats = await provider.get_stats(credentials)
        revenue = await provider.get_revenue(credentials)
    except ProviderNotConfigured as exc:
        channel.status = ChannelStatus.NOT_CONFIGURED
        channel.status_detail = str(exc)
        await session.flush()
        return channel
    except ProviderAuthError as exc:
        channel.status = ChannelStatus.REAUTH_REQUIRED
        channel.status_detail = str(exc)
        await _log_sync_failure(session, channel, str(exc))
        return channel
    except ProviderError as exc:
        channel.status = ChannelStatus.SYNC_FAILED
        channel.status_detail = str(exc)
        await _log_sync_failure(session, channel, str(exc))
        return channel

    session.add(
        SocialChannelStats(
            channel_id=channel.id,
            followers=stats.followers,
            views=stats.views,
            likes=stats.likes,
            comments=stats.comments,
            posts=stats.posts,
            revenue=quantize_money(revenue.amount) if revenue else None,
            revenue_currency=revenue.currency if revenue else None,
            measured_at=ensure_utc(stats.measured_at or utcnow()),
        )
    )
    channel.status = ChannelStatus.CONNECTED
    channel.status_detail = None
    channel.last_synced_at = utcnow()
    await session.flush()
    return channel


async def _log_sync_failure(session: AsyncSession, channel: SocialChannel, detail: str) -> None:
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.SOCIAL_SYNC_FAILED,
        user_id=channel.user_id,
        message=f"Synchronisatie van '{channel.channel_name}' mislukt.",
        subject_type="social_channel",
        subject_id=channel.id,
        context={"platform": channel.platform, "detail": detail[:200]},
    )


async def sync_all(session: AsyncSession, user_id: int) -> list[SocialChannel]:
    channels = [c for c in await list_channels(session, user_id) if c.active]
    for channel in channels:
        await sync_channel(session, channel)
    if channels:
        await log_activity(
            session,
            action=ActivityAction.SOCIAL_SYNC_COMPLETED,
            user_id=user_id,
            message=f"{len(channels)} kanaal/kanalen bijgewerkt.",
        )
    return channels
