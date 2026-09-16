from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

from app.models.social import SocialPlatform


class SocialChannelIn(BaseModel):
    platform: SocialPlatform
    channel_name: str = Field(min_length=1, max_length=160)
    external_channel_id: str | None = None
    credentials: dict[str, Any] | None = None


class SocialChannelPatch(BaseModel):
    channel_name: str | None = Field(default=None, min_length=1, max_length=160)
    external_channel_id: str | None = None
    active: bool | None = None
    credentials: dict[str, Any] | None = None


class SocialChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    channel_name: str
    external_channel_id: str | None
    active: bool
    status: str
    status_detail: str | None
    last_synced_at: UtcDatetime | None


class SocialStatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    followers: int | None
    views: int | None
    likes: int | None
    comments: int | None
    posts: int | None
    revenue: Decimal | None
    revenue_currency: str | None
    measured_at: UtcDatetime


class PlatformTotals(BaseModel):
    platform: str
    channels: int
    followers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    posts: int | None = None


class ChannelAttention(BaseModel):
    id: int
    platform: str
    channel_name: str
    status: str
    detail: str | None = None


class SocialOverviewOut(BaseModel):
    followers: int | None
    views: int | None
    likes: int | None
    comments: int | None
    posts: int | None
    growth_pct: float | None
    revenue: Decimal | None
    revenue_currency: str | None
    revenue_available: bool
    channels_total: int
    channels_counted: int
    platforms: list[PlatformTotals]
    attention: list[ChannelAttention]
    last_updated: UtcDatetime | None
    server_time: UtcDatetime
