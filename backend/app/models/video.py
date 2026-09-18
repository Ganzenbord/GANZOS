"""Video's: van concept tot gepubliceerd.

Een `UploadSchedule` zegt wat er wanneer de deur uit moet; een `Video` is het ding zelf.
Ze kunnen aan elkaar hangen, maar hoeven dat niet: een video kan bestaan voordat er een
moment voor gekozen is, en een gepland moment kan er zijn voordat de video af is.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime

if TYPE_CHECKING:
    from app.models.user import User


class VideoStatus(StrEnum):
    DRAFT = "draft"
    RENDERING = "rendering"
    READY = "ready"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


class Video(Base, TimestampMixin):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Blijft bestaan als het kanaal wordt losgekoppeld: de video zelf is er nog.
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("social_channels.id", ondelete="SET NULL"), index=True, nullable=True
    )
    upload_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("upload_schedules.id", ondelete="SET NULL"), index=True, nullable=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=VideoStatus.DRAFT.value, index=True, nullable=False
    )

    # Het id dat het platform zelf aan de video geeft, pas bekend na publiceren.
    external_id: Mapped[str | None] = mapped_column(String(190), index=True, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ruimte voor wat per platform verschilt (thumbnail, tags, zichtbaarheid) zonder dat er
    # bij elk nieuw veld een migratie nodig is. Wat vastligt hoort in een echte kolom.
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    user: Mapped["User"] = relationship(back_populates="videos", lazy="raise_on_sql")  # noqa: F821
