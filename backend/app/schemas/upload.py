from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

from app.models.upload import ContentType, UploadRecurrence, UploadStatus


class UploadIn(BaseModel):
    channel_id: int
    title: str | None = Field(default=None, max_length=200)
    content_type: ContentType = ContentType.VIDEO
    scheduled_at: UtcDatetime
    recurrence: UploadRecurrence = UploadRecurrence.ONCE
    timezone: str = "Europe/Amsterdam"


class UploadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content_type: ContentType | None = None
    scheduled_at: UtcDatetime | None = None
    recurrence: UploadRecurrence | None = None
    timezone: str | None = None
    status: UploadStatus | None = None


class UploadStatusIn(BaseModel):
    status: UploadStatus
    detail: str | None = None


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    title: str | None
    content_type: str
    status: str
    status_detail: str | None
    recurrence: str
    timezone: str
    scheduled_at: UtcDatetime
    effective_at: UtcDatetime | None = None
    # De frontend telt hiermee af; hij wordt niet opgeslagen.
    seconds_until: int | None = None
    overdue: bool = False
    channel_name: str | None = None
    platform: str | None = None


class ChannelScheduleRow(BaseModel):
    channel_id: int
    platform: str
    channel_name: str
    channel_status: str
    channel_active: bool
    needs_reauth: bool
    next_upload: UploadOut | None


class ScheduleOverviewOut(BaseModel):
    server_time: UtcDatetime
    channels: list[ChannelScheduleRow]
