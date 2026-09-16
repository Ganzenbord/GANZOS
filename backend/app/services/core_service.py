"""De toestand van Ganz zelf: Core, stem, skills, integraties en taalmodellen."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import (
    Conversation,
    Integration,
    IntegrationStatus,
    LlmProviderStatus,
    MemoryEntry,
    MissionStatus,
    MissionTask,
    Skill,
)
from app.services.system_service import snapshot


async def core_overview(session: AsyncSession, user_id: int) -> dict[str, Any]:
    skills = await session.scalar(
        select(func.count(Skill.id)).where(Skill.user_id == user_id, Skill.enabled.is_(True))
    )
    integrations_total = await session.scalar(
        select(func.count(Integration.id)).where(Integration.user_id == user_id)
    )
    integrations_ok = await session.scalar(
        select(func.count(Integration.id)).where(
            Integration.user_id == user_id,
            Integration.status == IntegrationStatus.CONNECTED,
        )
    )
    system = snapshot()
    return {
        "core_status": "active",
        "core_detail": "Ganz is operationeel",
        # De stem is pas "luisterend" als er een spraakintegratie gekoppeld is.
        # Anders zou het stoplicht groen staan terwijl er niets meeluistert.
        "voice_status": await _voice_status(session, user_id),
        "skills_count": skills or 0,
        "integrations_total": integrations_total or 0,
        "integrations_connected": integrations_ok or 0,
        "system_status": system["status"],
        "system_detail": system["status_detail"],
    }


async def _voice_status(session: AsyncSession, user_id: int) -> str:
    voice = await session.scalar(
        select(Integration).where(
            Integration.user_id == user_id, Integration.category == "voice"
        )
    )
    if voice is None:
        return "not_configured"
    return "listening" if voice.status == IntegrationStatus.CONNECTED else "unavailable"


async def memory_insights(session: AsyncSession, user_id: int) -> dict[str, Any]:
    memories = await session.scalar(
        select(func.count(MemoryEntry.id)).where(MemoryEntry.user_id == user_id)
    )
    sessions = await session.scalar(
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    )
    return {"memories": memories or 0, "sessions": sessions or 0}


async def llm_status(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(LlmProviderStatus).order_by(LlmProviderStatus.provider)
    )
    return [
        {
            "provider": row.provider,
            "model": row.model,
            "status": row.status,
            "latency_ms": row.latency_ms,
            "detail": row.detail,
            "checked_at": row.checked_at,
        }
        for row in result.scalars().all()
    ]


async def mission_timeline(
    session: AsyncSession, user_id: int, limit: int = 8
) -> list[dict[str, Any]]:
    """De missies van vandaag. De tijdlijn is van het dashboard verdwenen, maar de
    gegevens en de API blijven bestaan — het paneel staat nu naast de to-do lijst."""
    result = await session.execute(
        select(MissionTask)
        .where(MissionTask.user_id == user_id)
        .order_by(MissionTask.scheduled_for.is_(None), MissionTask.scheduled_for)
        .limit(limit)
    )
    return [
        {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "scheduled_for": task.scheduled_for,
            "completed_at": task.completed_at,
            "is_done": task.status == MissionStatus.DONE,
        }
        for task in result.scalars().all()
    ]
