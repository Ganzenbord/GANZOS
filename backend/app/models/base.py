"""Gedeelde bouwstenen voor alle tabellen."""

from __future__ import annotations

from datetime import datetime, timezone

from typing import Any

from sqlalchemy import DateTime, Dialect, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Altijd een tijdzone-bewuste UTC-tijd; naïeve tijden geven later rekenfouten."""
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator[datetime]):
    """Een tijdstip dat er altijd mét tijdzone uitkomt, op elke database.

    PostgreSQL bewaart de tijdzone, SQLite niet: daar komt een kale datetime terug. Vergelijk
    je die met een tijdstip dat wél een tijdzone heeft, dan klapt Python eruit met
    "can't compare offset-naive and offset-aware datetimes" — en dan alleen in de tests, of
    juist alleen op de echte database. Dit maakt dat verschil onzichtbaar: alles gaat er als
    UTC in en komt er als UTC uit.

    Aan de tabellen verandert dit niets; het is puur de vertaling aan de Python-kant.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        # Een tijdstip zonder tijdzone is een vergissing; UTC aannemen is de veiligste gok.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
            timezone.utc
        )

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
            timezone.utc
        )


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
