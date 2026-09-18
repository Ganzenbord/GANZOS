"""Gebruikers en hun tier.

Tier 1 is de eigenaar en mag alles. Hoe hoger het nummer, hoe minder rechten. Zo kan een
nieuwe, beperktere rol erbij zonder de bestaande te hernummeren.

Geen tier (`NULL`) betekent: wel bekend, geen toegang. Dat is iets anders dan `active=False`
(uitgezet) en iets anders dan de laagste tier (mag een beetje). Je hebt het nodig zodra een
stem herkend kan worden: dan wil je kunnen zeggen "dag Piet" zonder Piet ergens binnen te
laten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime

if TYPE_CHECKING:
    from app.models.access import UserPermission
    from app.models.video import Video
    from app.models.voice import VoiceProfile

TIER_OWNER = 1
TIER_TRUSTED = 2
TIER_LIMITED = 3
TIER_GUEST = 4

# De zwakste tier die nog bestaat. Alles daarboven is "geen toegang" (NULL).
TIER_NONE = None
TIERS = (TIER_OWNER, TIER_TRUSTED, TIER_LIMITED, TIER_GUEST)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Bewust géén standaardwaarde. Met `default=TIER_GUEST` erbij wordt een expliciete
    # `tier=None` bij het opslaan alsnog 4, en is "geen toegang" dus onbereikbaar —
    # precies waar deze kolom voor bedoeld is. Zonder default begint een nieuwe
    # gebruiker zonder toegang, en geef je die bewust.
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # De pincode is de tweede bevestiging vanaf een telefoon of via de stem, waar een
    # heel wachtwoord intikken onhandig is. Alleen de afdruk, nooit de code zelf.
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

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

    # Deze wél altijd meeladen, anders dan de andere twee: bij elk verzoek moet Ganz weten
    # wat je mag, en dat vergeten is niet "een query minder" maar "een recht te veel".
    permission_overrides: Mapped[list["UserPermission"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        passive_deletes=True,
    )

    @property
    def overrides(self) -> dict[str, bool]:
        """De uitzonderingen op zijn tier, als `{recht: mag het}`."""
        return {rij.permission_key: rij.granted for rij in self.permission_overrides}
