"""Geplande uploads per kanaal.

De aftelling staat niet in de database. Er staat één exact moment in UTC
(`scheduled_at`); de frontend rekent daar samen met de servertijd het verschil uit.
Een opgeslagen "nog 28 minuten" zou binnen een minuut onwaar zijn.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime
from app.models.social import SocialChannel


class UploadStatus(StrEnum):
    SCHEDULED = "scheduled"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_CONFIRMATION = "waiting_confirmation"


class ContentType(StrEnum):
    VIDEO = "video"
    SHORT = "short"
    REEL = "reel"
    POST = "post"
    STORY = "story"
    OTHER = "other"


class UploadRecurrence(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


# Statussen die nog in de toekomst iets gaan doen; alleen die tellen mee voor
# "de volgende upload" op het dashboard.
OPEN_UPLOAD_STATUSES = (
    UploadStatus.SCHEDULED,
    UploadStatus.UPLOADING,
    UploadStatus.WAITING_CONFIRMATION,
)


class UploadSchedule(Base, TimestampMixin):
    __tablename__ = "upload_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("social_channels.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_type: Mapped[str] = mapped_column(String(16), default=ContentType.VIDEO, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        UtcDateTime, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default=UploadStatus.SCHEDULED, nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurrence: Mapped[str] = mapped_column(
        String(16), default=UploadRecurrence.ONCE, nullable=False
    )
    # De tijdzone waarin de gebruiker het heeft ingepland. `scheduled_at` blijft UTC,
    # maar zonder deze zone kun je een herhaling niet correct over een zomertijdgrens
    # heen zetten.
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Amsterdam", nullable=False)

    channel: Mapped[SocialChannel] = relationship(back_populates="uploads")
