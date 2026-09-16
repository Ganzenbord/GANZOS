"""Gebruikers en hun tier.

Tier 1 is de eigenaar en mag alles. Hoe hoger het nummer, hoe minder rechten.
Zo kan een nieuwe, beperktere rol erbij zonder de bestaande te hernummeren.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

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
