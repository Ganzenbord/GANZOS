"""Stemprofielen: de vingerafdruk van een ingesproken stem.

Eén gebruiker mag er meerdere hebben — meer opnames van dezelfde persoon maken het
herkennen betrouwbaarder. Een profiel zonder `embedding` telt niet mee bij het herkennen.

De afdruk staat als lijst getallen in een JSON-kolom. Voor een handvol mensen is dat ruim
genoeg: vergelijken is één vermenigvuldiging per profiel. Wordt het ooit een berg, dan is
pgvector de volgende stap; de kolom kan dan mee verhuizen zonder dat de rest verandert.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime

if TYPE_CHECKING:
    from app.models.user import User


class VoiceProfile(Base, TimestampMixin):
    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    # Welk model de afdruk maakte. Afdrukken van twee modellen zijn onvergelijkbaar, dus bij
    # een modelwissel moet iedereen zich opnieuw laten inschrijven — dat moet je kunnen zien.
    embedding_model: Mapped[str | None] = mapped_column(String(190), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="voice_profiles", lazy="raise_on_sql")  # noqa: F821
