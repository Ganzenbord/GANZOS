"""Wie mag wat, en vanaf welk apparaat.

Twee tabellen die los staan van `users` omdat ze allebei over veranderlijke dingen gaan:
een sessie hoort bij één apparaat en kan ingetrokken worden, een recht kan per persoon
afwijken van wat zijn tier zegt.

Waarom een sessie in de database staat en niet alleen in een token: een token dat je hebt
uitgegeven kun je niet meer terughalen. Raakt een telefoon kwijt, dan wil je díe telefoon
eruit kunnen gooien zonder iedereen uit te loggen — en dat kan alleen als er een rij is om
door te strepen.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UtcDateTime


class UserSession(Base, TimestampMixin):
    """Eén ingelogd apparaat.

    Het vernieuwingstoken staat hier als afdruk, nooit als tekst: wie de database leest, kan
    er niet mee inloggen. Bij elk gebruik wordt hij vervangen en schuift de oude naar
    `previous_hash`. Komt die oude daarna alsnog langs, dan is hij onderweg gekopieerd — en
    gaat de hele sessie dicht. Dat is het enige moment waarop je diefstal van een token kunt
    zien, dus die kans moet je pakken.
    """

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # De vorige afdruk, alleen om hergebruik te herkennen. Geen tweede geldige sleutel:
    # inloggen kan er niet mee, hij zet de sessie juist stop.
    previous_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # Wat er in het overzicht "Apparaten" staat. Zelf ingevuld door de client; het is een
    # geheugensteuntje voor de gebruiker, geen bewijs van iets.
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Waarom hij dicht is gegaan: "logout", "ingetrokken", "hergebruikt" of "verlopen".
    revoked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)


class UserPermission(Base, TimestampMixin):
    """Een recht dat voor deze persoon afwijkt van wat zijn tier zegt.

    Een tier is een rechte lijn: tier 2 mag alles wat tier 3 mag, plus meer. Maar "mag
    alleen de lampen, de mail en het weer" is geen stuk van die lijn — dat is een greep
    eruit. Zonder deze tabel zou zo iemand een tier moeten krijgen die hem meteen ook het
    uploadschema en de skills laat zien.

    `granted=False` bestaat ook, en is net zo nodig: iemand die verder alles mag, maar niet
    dit ene ding.
    """

    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission_key", name="uq_user_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    permission_key: Mapped[str] = mapped_column(String(80), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Waarom deze uitzondering er is. Over een jaar weet niemand het meer.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
