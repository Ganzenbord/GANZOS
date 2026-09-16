"""De bestaande Ganz-modules via de API.

Alleen lezen; het wijzigen daarvan zit in de modules zelf. Ze staan hier zodat het
dashboard en de zijbalk echte gegevens tonen in plaats van vaste tekst.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.deps import require_permission
from app.models.platform import (
    Conversation,
    Integration,
    MemoryEntry,
    MissionTask,
    Skill,
    Workflow,
)
from app.models.user import User
from app.services import core_service
from app.services.activity_service import recent_activity
from app.services.system_service import snapshot

router = APIRouter(tags=["ganz"])


@router.get("/core")
async def core(
    user: User = Depends(require_permission("core.read")),
    session: AsyncSession = Depends(get_session),
):
    return await core_service.core_overview(session, user.id)


@router.get("/system")
async def system(user: User = Depends(require_permission("system.read"))):
    return snapshot()


@router.get("/llm")
async def llm(
    user: User = Depends(require_permission("core.read")),
    session: AsyncSession = Depends(get_session),
):
    return await core_service.llm_status(session)


@router.get("/skills")
async def skills(
    user: User = Depends(require_permission("skills.read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Skill).where(Skill.user_id == user.id).order_by(Skill.name)
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "category": row.category,
            "enabled": row.enabled,
            "run_count": row.run_count,
            "last_used_at": row.last_used_at,
        }
        for row in result.scalars().all()
    ]


@router.get("/missions")
async def missions(
    user: User = Depends(require_permission("tasks.read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MissionTask)
        .where(MissionTask.user_id == user.id)
        .order_by(MissionTask.scheduled_for.is_(None), MissionTask.scheduled_for)
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "scheduled_for": row.scheduled_for,
            "completed_at": row.completed_at,
            "source": row.source,
        }
        for row in result.scalars().all()
    ]


@router.get("/memory")
async def memory(
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(require_permission("memory.read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MemoryEntry)
        .where(MemoryEntry.user_id == user.id)
        .order_by(MemoryEntry.importance.desc(), MemoryEntry.created_at.desc())
        .limit(limit)
    )
    entries = [
        {
            "id": row.id,
            "kind": row.kind,
            "title": row.title,
            "content": row.content,
            "importance": row.importance,
            "created_at": row.created_at,
        }
        for row in result.scalars().all()
    ]
    return {"insights": await core_service.memory_insights(session, user.id), "entries": entries}


@router.get("/conversations")
async def conversations(
    user: User = Depends(require_permission("conversations.read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.last_message_at.desc().nullslast())
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "last_message_at": row.last_message_at,
            "created_at": row.created_at,
        }
        for row in result.scalars().all()
    ]


@router.get("/integrations")
async def integrations(
    user: User = Depends(require_permission("integrations.read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Integration).where(Integration.user_id == user.id).order_by(Integration.name)
    )
    # Bewust zonder credentials_encrypted: die hoort de frontend nooit te zien.
    return [
        {
            "id": row.id,
            "key": row.key,
            "name": row.name,
            "category": row.category,
            "status": row.status,
            "status_detail": row.status_detail,
            "last_checked_at": row.last_checked_at,
        }
        for row in result.scalars().all()
    ]


@router.get("/workflows")
async def workflows(
    user: User = Depends(require_permission("workflows.read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Workflow).where(Workflow.user_id == user.id).order_by(Workflow.name)
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "enabled": row.enabled,
            "trigger": row.trigger,
            "run_count": row.run_count,
            "last_run_at": row.last_run_at,
        }
        for row in result.scalars().all()
    ]


@router.get("/activity")
async def activity(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_permission("activity.read")),
    session: AsyncSession = Depends(get_session),
):
    return [
        {
            "id": entry.id,
            "action": entry.action,
            "message": entry.message,
            "subject_type": entry.subject_type,
            "subject_id": entry.subject_id,
            "context": entry.context,
            "created_at": entry.created_at,
        }
        for entry in await recent_activity(session, user_id=user.id, limit=limit)
    ]
