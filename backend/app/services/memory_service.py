"""Wat Ganz onthoudt.

Nu nog alleen een overzicht voor het dashboard. Het geheugen zelf (opslaan, terugzoeken,
belang bijstellen) komt in een eigen fase; deze module is vast de plek waar dat komt te
staan, zodat de rest er nu al naar kan wijzen in plaats van straks te moeten verhuizen.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityLogEntry
from app.models.platform import Conversation, MemoryEntry
from app.services.activity_service import recent_activity


async def overview(session: AsyncSession, user_id: int, *, recent: int = 5) -> dict[str, Any]:
    """Hoeveel Ganz onthoudt, en wat er het laatst gebeurde."""
    herinneringen = await session.scalar(
        select(func.count(MemoryEntry.id)).where(MemoryEntry.user_id == user_id)
    )
    gesprekken = await session.scalar(
        select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
    )
    gebeurtenissen = await session.scalar(
        select(func.count(ActivityLogEntry.id)).where(ActivityLogEntry.user_id == user_id)
    )

    return {
        "memory_count": int(herinneringen or 0),
        "session_count": int(gesprekken or 0),
        "activity_count": int(gebeurtenissen or 0),
        "recent_activity": [
            {
                "id": regel.id,
                "action": regel.action,
                "message": regel.message,
                "created_at": regel.created_at,
            }
            for regel in await recent_activity(session, user_id=user_id, limit=recent)
        ],
    }
