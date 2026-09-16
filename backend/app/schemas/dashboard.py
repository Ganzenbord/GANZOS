"""Het antwoordmodel van het dashboard.

Zonder dit model zou FastAPI bedragen als losse floats terugsturen, terwijl
/finance/overview ze als tekst levert. Dan rekent de frontend op twee plekken anders
met hetzelfde bedrag.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import UtcDatetime

from app.schemas.finance import FinanceOverviewOut
from app.schemas.social import SocialOverviewOut
from app.schemas.todo import TodoDayOut
from app.schemas.upload import ScheduleOverviewOut


class DashboardUser(BaseModel):
    id: int
    display_name: str
    tier: int
    permissions: list[str]


class CoreOut(BaseModel):
    core_status: str
    core_detail: str
    voice_status: str
    skills_count: int
    integrations_total: int
    integrations_connected: int
    system_status: str
    system_detail: str


class MissionOut(BaseModel):
    id: int
    title: str
    status: str
    scheduled_for: UtcDatetime | None
    completed_at: UtcDatetime | None
    is_done: bool


class SystemSample(BaseModel):
    cpu_pct: float
    ram_pct: float
    disk_pct: float
    measured_at: UtcDatetime


class SystemOut(SystemSample):
    status: str
    status_detail: str
    history: list[SystemSample]
    boot_time: UtcDatetime


class MemoryInsightsOut(BaseModel):
    memories: int
    sessions: int


class LlmStatusOut(BaseModel):
    provider: str
    model: str | None
    status: str
    latency_ms: int | None
    detail: str | None
    checked_at: UtcDatetime | None


class FeedItem(BaseModel):
    id: int
    action: str
    message: str
    created_at: UtcDatetime


class DashboardOut(BaseModel):
    server_time: UtcDatetime
    user: DashboardUser
    core: CoreOut
    todo: TodoDayOut | None = None
    missions: list[MissionOut] | None = None
    finance: FinanceOverviewOut | None = None
    social: SocialOverviewOut | None = None
    uploads: ScheduleOverviewOut | None = None
    system: SystemOut | None = None
    memory: MemoryInsightsOut | None = None
    llm: list[LlmStatusOut] = []
    feed: list[FeedItem] = []

    # Los meegeven aan de frontend zonder dat het model breekt bij een nieuw veld.
    extra: dict[str, Any] | None = None
