"""De endpoints waar het Command Center op draait.

Alles hier is lezen. Er wordt niets opgehaald bij een bank of een social-platform: die
gegevens staan al klaar, gezet door de scheduler. Een pagina verversen hoort nooit een
provider aan te roepen.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_session
from app.models.user import User
from app.schemas.status import (
    ActivityPage,
    MemoryOverview,
    ScheduleToday,
    StatusOut,
    SystemMetrics,
)
from app.services import core_service, memory_service, schedule_service
from app.services.activity_service import activity_page
from app.services.system_service import snapshot

router = APIRouter(tags=["dashboard"])


@router.get("/status", response_model=StatusOut)
async def status(
    user: User = Depends(require_permission("core.read")),
    session: AsyncSession = Depends(get_session),
) -> StatusOut:
    """Draait alles nog? Core, stem, skills, integraties en systeem in één antwoord."""
    return StatusOut(**await core_service.status_overview(session, user.id))


@router.get("/activity", response_model=ActivityPage)
async def activity(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, description="Filter op één soort gebeurtenis"),
    user: User = Depends(require_permission("activity.read")),
    session: AsyncSession = Depends(get_session),
) -> ActivityPage:
    """Het logboek, per pagina.

    Het totaal komt mee, want zonder dat kan de frontend niet weten of er nog meer is.
    """
    return ActivityPage(
        **await activity_page(
            session, user_id=user.id, limit=limit, offset=offset, action=action
        )
    )


@router.get("/schedule/today", response_model=ScheduleToday)
async def schedule_today(
    day: date | None = Query(default=None, description="Standaard vandaag (UTC)"),
    user: User = Depends(require_permission("tasks.read")),
    session: AsyncSession = Depends(get_session),
) -> ScheduleToday:
    """Wat er vandaag op de rol staat: geplande uploads en taken, op één lijstje."""
    return ScheduleToday(**await schedule_service.today(session, user.id, day=day))


@router.get("/system/metrics", response_model=SystemMetrics)
async def system_metrics(
    _user: User = Depends(require_permission("system.admin")),
) -> SystemMetrics:
    """De ruwe metingen: belasting, geheugen, schijf, en hoe lang de machine al draait.

    Alleen voor tier 1. Het stoplicht op het dashboard (`/system`) zegt genoeg voor de rest;
    deze cijfers gaan over de computer zelf.
    """
    return SystemMetrics(**snapshot())


@router.get("/memory/overview", response_model=MemoryOverview)
async def memory_overview(
    user: User = Depends(require_permission("memory.read")),
    session: AsyncSession = Depends(get_session),
) -> MemoryOverview:
    """Hoeveel Ganz onthoudt, en wat er het laatst gebeurde."""
    return MemoryOverview(**await memory_service.overview(session, user.id))
