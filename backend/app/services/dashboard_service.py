"""Het dashboard in één antwoord.

Eén verzoek levert alle panelen. Dat scheelt een stuk of tien losse aanroepen bij het
openen, en belangrijker: het dashboard leest uitsluitend wat de scheduler al heeft
opgehaald. Er gaat hier nooit een aanroep naar een bank of een social-platform.

Panelen waar de gebruiker geen recht op heeft komen er niet in — dan staat er `null`
en laat de frontend het paneel weg.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.user import User
from app.core.permissions import allows, effective_permissions
from app.services import (
    core_service,
    finance_service,
    social_service,
    todo_service,
    upload_service,
)
from app.services.activity_service import recent_activity
from app.services.system_service import snapshot


async def build_dashboard(
    session: AsyncSession, user: User, day: date | None = None
) -> dict[str, Any]:
    now = utcnow()
    day = day or now.date()

    payload: dict[str, Any] = {
        "server_time": now,
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "tier": user.tier,
            "permissions": effective_permissions(user.tier, user.overrides),
        },
        "core": await core_service.core_overview(session, user.id),
        "todo": None,
        "missions": None,
        "finance": None,
        "social": None,
        "uploads": None,
        "system": None,
        "memory": None,
        "llm": await core_service.llm_status(session),
        "feed": [],
    }

    # Eén keer vastleggen wat deze persoon mag, inclusief de uitzonderingen op zijn tier.
    # Anders staat `user.overrides` tien keer in dit blok en vergeet je hem een keer.
    def mag(key: str) -> bool:
        return allows(user.tier, key, user.overrides)

    if mag("todo.read"):
        payload["todo"] = await todo_service.get_day(session, user.id, day)
    if mag("tasks.read"):
        payload["missions"] = await core_service.mission_timeline(session, user.id)
    if mag("finance.read"):
        payload["finance"] = await finance_service.overview(session, user.id, now)
    if mag("social.read"):
        payload["social"] = await social_service.overview(session, user.id, now)
    if mag("upload.read"):
        payload["uploads"] = await upload_service.schedule_overview(session, user.id, now)
    if mag("system.read"):
        # Alleen tier 1 krijgt de cijfers erbij; de rest ziet het stoplicht.
        payload["system"] = snapshot(detailed=mag("system.admin"))
    if mag("memory.read"):
        payload["memory"] = await core_service.memory_insights(session, user.id)
    if mag("activity.read"):
        payload["feed"] = [
            {
                "id": entry.id,
                "action": entry.action,
                "message": entry.message,
                "created_at": entry.created_at,
            }
            for entry in await recent_activity(session, user_id=user.id, limit=8)
        ]

    return payload
