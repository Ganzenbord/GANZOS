"""Tijd, herhaling en aftellen."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.todo import TodoRecurrence
from app.models.upload import UploadRecurrence


def ensure_utc(moment: datetime) -> datetime:
    """Maakt van een naïeve tijd een UTC-tijd.

    SQLite geeft tijden zonder tijdzone terug, ook als ze als UTC zijn opgeslagen.
    Zonder deze stap vergelijk je in de tests appels met peren.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def resolve_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        # Een onbekende tijdzone mag het inplannen niet blokkeren.
        return ZoneInfo("UTC")


def todo_occurs_on(recurrence: str, day: date) -> bool:
    """Staat deze taak op deze dag op de lijst?"""
    match recurrence:
        case TodoRecurrence.DAILY:
            return True
        case TodoRecurrence.WEEKDAYS:
            return day.weekday() < 5
        case TodoRecurrence.WEEKENDS:
            return day.weekday() >= 5
        case TodoRecurrence.WEEKLY | TodoRecurrence.ONCE:
            # Wekelijks en eenmalig blijven staan tot de gebruiker ze afvinkt; de
            # service filtert eenmalige taken weg zodra dat gebeurd is.
            return True
        case _:
            return True


def next_upload_occurrence(
    scheduled_at: datetime, recurrence: str, tz_name: str, after: datetime
) -> datetime | None:
    """Het eerstvolgende moment op of na `after`.

    Herhalingen worden in de tijdzone van de gebruiker opgeschoven, niet in UTC. Anders
    verspringt een upload van 18:00 naar 17:00 zodra de zomertijd ingaat.
    """
    scheduled_at = ensure_utc(scheduled_at)
    after = ensure_utc(after)
    if scheduled_at >= after:
        return scheduled_at
    if recurrence == UploadRecurrence.ONCE:
        return None

    step = timedelta(days=1) if recurrence == UploadRecurrence.DAILY else timedelta(days=7)
    zone = resolve_zone(tz_name)
    local = scheduled_at.astimezone(zone)
    # Er zitten zelden meer dan een paar honderd stappen tussen; de grens voorkomt
    # een oneindige lus bij een onverwachte herhalingswaarde.
    for _ in range(1000):
        local += step
        candidate = local.astimezone(timezone.utc)
        if candidate >= after:
            return candidate
    return None


def seconds_until(moment: datetime, now: datetime) -> int:
    return int((ensure_utc(moment) - ensure_utc(now)).total_seconds())
