"""Gedeelde types voor de antwoordmodellen."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator


def _as_utc(value: datetime) -> datetime:
    """Zorgt dat er altijd een tijdzone bij staat.

    PostgreSQL geeft tijden mét zone terug, SQLite zonder. Een tijd zonder zone leest
    de browser als lokale tijd, en dan staat "zojuist bijgewerkt" er ineens twee uur
    naast. Alles wat de deur uit gaat is daarom expliciet UTC.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
