"""Wat de dashboard-endpoints teruggeven."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class StatusOut(BaseModel):
    """De toestand van Ganz in vijf regels — wat de bovenbalk laat zien."""

    core_status: str
    core_detail: str
    voice_status: Literal["listening", "not_configured", "unavailable"]
    voice_detail: str
    active_skills: int
    integrations_count: int
    integrations_connected: int
    system_status: str
    system_detail: str


class ActivityItem(BaseModel):
    id: int
    action: str
    message: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    context: dict[str, Any] | None = None
    created_at: datetime


class ActivityPage(BaseModel):
    items: list[ActivityItem]
    total: int
    limit: int
    offset: int
    has_more: bool = Field(description="Of er na deze pagina nog meer is")


class ScheduleItem(BaseModel):
    kind: Literal["upload", "task"]
    id: int
    title: str
    at: datetime
    status: str
    done: bool


class ScheduleToday(BaseModel):
    day: date
    items: list[ScheduleItem]
    total: int
    open: int = Field(description="Hoeveel er nog moeten gebeuren")


class SystemMetrics(BaseModel):
    cpu_pct: float
    ram_pct: float
    disk_pct: float
    measured_at: datetime
    status: str
    status_detail: str
    boot_time: datetime
    history: list[dict[str, Any]] = Field(
        description="De laatste metingen, gevuld door de scheduler. Leeg als die uit staat."
    )


class MemoryOverview(BaseModel):
    memory_count: int
    session_count: int
    activity_count: int
    recent_activity: list[dict[str, Any]]
