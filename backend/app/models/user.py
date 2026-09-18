"""Gebruikers en hun tier.

Tier 1 is de eigenaar en mag alles. Hoe hoger het nummer, hoe minder rechten.
Zo kan een nieuwe, beperktere rol erbij zonder de bestaande te hernummeren.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.video import Video
    from app.models.voice import VoiceProfile

TIER_OWNER = 1
TIER_TRUSTED = 2
TIER_LIMITED = 3
TIER_GUEST = 4


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=TIER_GUEST, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # lazy="raise_on_sql": in async SQLAlchemy is stilletjes nalezen een fout die pas op
    # het slechtste moment opvalt. Haal ze bewust op met selectinload().
    voice_profiles: Mapped[list["VoiceProfile"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
        passive_deletes=True,
    )
    videos: Mapped[list["Video"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
        passive_deletes=True,
    )
