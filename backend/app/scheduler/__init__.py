"""Achtergrondsynchronisatie.

Hier worden providers aangeroepen — en alleen hier. Het dashboard leest daarna de
opgeslagen gegevens. Zonder deze scheiding zou elke pagina-refresh een ronde langs
banken en social-platforms doen, met rate limits als gevolg.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.user import User
from app.services import finance_service, social_service
from app.services.system_service import record_sample

logger = logging.getLogger("ganz.scheduler")
_scheduler: AsyncIOScheduler | None = None


async def _active_user_ids() -> list[int]:
    async with SessionLocal() as session:
        result = await session.execute(select(User.id).where(User.active.is_(True)))
        return list(result.scalars().all())


async def sync_finance_job() -> None:
    for user_id in await _active_user_ids():
        async with SessionLocal() as session:
            try:
                await finance_service.sync_all(session, user_id)
                await session.commit()
            except Exception:  # noqa: BLE001 - de scheduler mag hier nooit op stoppen
                await session.rollback()
                logger.exception("Finance-synchronisatie mislukt voor gebruiker %s", user_id)


async def sync_social_job() -> None:
    for user_id in await _active_user_ids():
        async with SessionLocal() as session:
            try:
                await social_service.sync_all(session, user_id)
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                logger.exception("Social-synchronisatie mislukt voor gebruiker %s", user_id)


def sample_system_job() -> None:
    record_sample()


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.scheduler_enabled or _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sync_finance_job,
        "interval",
        minutes=settings.finance_sync_minutes,
        id="finance_sync",
        # Gemiste rondes niet inhalen: vijf tegelijk zou juist de rate limit raken.
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        sync_social_job,
        "interval",
        minutes=settings.social_sync_minutes,
        id="social_sync",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        sample_system_job, "interval", seconds=30, id="system_sample", max_instances=1
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler gestart: finance elke %s min, social elke %s min.",
        settings.finance_sync_minutes,
        settings.social_sync_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
