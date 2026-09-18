"""Het dashboard: één aanroep voor alle panelen."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.api.deps import require_permission
from app.models.base import utcnow
from app.models.user import User
from app.schemas.platform import TimeOut
from app.schemas.dashboard import DashboardOut
from app.services.dashboard_service import build_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    day: date | None = Query(default=None),
    user: User = Depends(require_permission("core.read")),
    session: AsyncSession = Depends(get_session),
):
    return await build_dashboard(session, user, day)


@router.get("/time", response_model=TimeOut)
async def server_time():
    """De servertijd, voor de aftelling. Vrij toegankelijk: het verraadt niets."""
    return TimeOut(server_time=utcnow(), timezone="UTC")
