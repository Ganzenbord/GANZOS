"""Activiteitenlog: wat er is gebeurd, nooit waarmee het is gebeurd.

Sleutels, tokens en saldi horen hier niet in; `scrub_context` in
`app/services/activity_service.py` haalt ze eruit voordat er iets wordt opgeslagen.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UtcDateTime, utcnow


class ActivityAction(StrEnum):
    TODO_CREATED = "TODO_CREATED"
    TODO_UPDATED = "TODO_UPDATED"
    TODO_DELETED = "TODO_DELETED"
    TODO_COMPLETED = "TODO_COMPLETED"
    TODO_REOPENED = "TODO_REOPENED"
    TODO_SUBTASK_CREATED = "TODO_SUBTASK_CREATED"
    TODO_SUBTASK_UPDATED = "TODO_SUBTASK_UPDATED"
    TODO_SUBTASK_DELETED = "TODO_SUBTASK_DELETED"

    FINANCE_ACCOUNT_CONNECTED = "FINANCE_ACCOUNT_CONNECTED"
    FINANCE_ACCOUNT_UPDATED = "FINANCE_ACCOUNT_UPDATED"
    FINANCE_ACCOUNT_REMOVED = "FINANCE_ACCOUNT_REMOVED"
    FINANCE_SYNC_COMPLETED = "FINANCE_SYNC_COMPLETED"
    FINANCE_SYNC_FAILED = "FINANCE_SYNC_FAILED"

    SOCIAL_CHANNEL_CONNECTED = "SOCIAL_CHANNEL_CONNECTED"
    SOCIAL_CHANNEL_UPDATED = "SOCIAL_CHANNEL_UPDATED"
    SOCIAL_CHANNEL_REMOVED = "SOCIAL_CHANNEL_REMOVED"
    SOCIAL_SYNC_COMPLETED = "SOCIAL_SYNC_COMPLETED"
    SOCIAL_SYNC_FAILED = "SOCIAL_SYNC_FAILED"

    UPLOAD_SCHEDULED = "UPLOAD_SCHEDULED"
    UPLOAD_UPDATED = "UPLOAD_UPDATED"
    UPLOAD_CANCELLED = "UPLOAD_CANCELLED"
    UPLOAD_STARTED = "UPLOAD_STARTED"
    UPLOAD_COMPLETED = "UPLOAD_COMPLETED"
    UPLOAD_FAILED = "UPLOAD_FAILED"

    USER_LOGGED_IN = "USER_LOGGED_IN"
    USER_LOGGED_OUT = "USER_LOGGED_OUT"
    SESSION_REVOKED = "SESSION_REVOKED"
    SESSION_REUSE_DETECTED = "SESSION_REUSE_DETECTED"
    USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED"

    INTEGRATION_CONNECTED = "INTEGRATION_CONNECTED"
    INTEGRATION_UPDATED = "INTEGRATION_UPDATED"
    INTEGRATION_REMOVED = "INTEGRATION_REMOVED"
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_PIN_SET = "USER_PIN_SET"

    VOICE_ENROLLED = "VOICE_ENROLLED"
    VOICE_IDENTIFIED = "VOICE_IDENTIFIED"
    VOICE_UNKNOWN = "VOICE_UNKNOWN"
    VOICE_PROFILE_REMOVED = "VOICE_PROFILE_REMOVED"

    SKILL_CREATED = "SKILL_CREATED"
    SKILL_UPDATED = "SKILL_UPDATED"
    SKILL_DELETED = "SKILL_DELETED"

    TASK_CREATED = "TASK_CREATED"
    TASK_MATCHED = "TASK_MATCHED"
    TASK_UNMATCHED = "TASK_UNMATCHED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"

    YOUTUBE_CONNECTED = "YOUTUBE_CONNECTED"
    YOUTUBE_DISCONNECTED = "YOUTUBE_DISCONNECTED"
    YOUTUBE_TOKEN_REFRESHED = "YOUTUBE_TOKEN_REFRESHED"
    YOUTUBE_UPLOAD_STARTED = "YOUTUBE_UPLOAD_STARTED"
    YOUTUBE_UPLOAD_COMPLETED = "YOUTUBE_UPLOAD_COMPLETED"
    YOUTUBE_UPLOAD_FAILED = "YOUTUBE_UPLOAD_FAILED"


class ActivityLogEntry(Base):
    __tablename__ = "activity_log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), index=True
    )
