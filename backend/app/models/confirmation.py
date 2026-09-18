"""Tweede bevestiging voor gevoelige handelingen.

Een kortlopend token alleen laat geen spoor na: je kunt achteraf niet zien dát er bevestigd
is, waarvoor, of hoe vaak het misging. Daarom staat elke bevestiging hier als rij. Het token
dat de client meekrijgt verwijst naar deze rij; is de rij verlopen of al gebruikt, dan telt
het token niet meer — ook al is het op zichzelf nog geldig.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UtcDateTime

# Zoveel mispogingen mag één bevestiging doen. Dit is de grens binnen één verzoek; wie het
# doorprobeert loopt eerst tegen de grens per gebruiker aan (zie confirmation_service:
# `recent_failures`), want elke poging is een nieuw verzoek en dan begint deze teller weer
# bij nul.
MAX_ATTEMPTS = 3


class ConfirmationMethod(StrEnum):
    PASSWORD = "password"
    PIN = "pin"


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    USED = "used"
    FAILED = "failed"


class ConfirmationRequest(Base, TimestampMixin):
    __tablename__ = "confirmation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Waarvoor bevestigd wordt. Leeg = voor één gevoelige handeling in het algemeen.
    permission_key: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ConfirmationStatus.PENDING.value, index=True, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Waar de aanmelding vandaan kwam die om deze bevestiging vroeg: "password" of "voice".
    origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Bij een stem: hoe zeker die herkenning was. Te zwak, en deze bevestiging telt niet
    # voor gevoelige handelingen — hoe goed de pincode daarna ook is.
    origin_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
