"""Social-mediakanalen en hun statistieken.

Niet elke provider levert dezelfde cijfers: TikTok geeft geen omzet, Instagram geen
kijktijd. Daarom mag elke metriek NULL zijn. NULL betekent "niet geleverd" en is iets
anders dan 0 — het dashboard laat dat verschil ook zien.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime, utcnow


class SocialPlatform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


class ChannelStatus(StrEnum):
    CONNECTED = "connected"
    SYNCING = "syncing"
    SYNC_FAILED = "sync_failed"
    REAUTH_REQUIRED = "reauth_required"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"


class SocialChannel(Base, TimestampMixin):
    __tablename__ = "social_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    channel_name: Mapped[str] = mapped_column(String(160), nullable=False)
    external_channel_id: Mapped[str | None] = mapped_column(String(190), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ChannelStatus.NOT_CONFIGURED, nullable=False
    )
    status_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    stats: Mapped[list["SocialChannelStats"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan", lazy="noload"
    )
    uploads: Mapped[list["UploadSchedule"]] = relationship(  # noqa: F821
        back_populates="channel", cascade="all, delete-orphan", lazy="noload"
    )


class SocialChannelStats(Base):
    """Eén meting. De groei wordt berekend uit twee metingen, niet opgeslagen."""

    __tablename__ = "social_channel_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("social_channels.id", ondelete="CASCADE"), index=True, nullable=False
    )
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    posts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    revenue_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    measured_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True
    )

    channel: Mapped[SocialChannel] = relationship(back_populates="stats")
