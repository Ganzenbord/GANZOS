"""Het activiteitenlog.

Alle mutaties komen hier langs. De context wordt eerst geschoond: sleutels, tokens,
wachtwoorden én bedragen gaan er uit. Het log mag vertellen dát een rekening is
gekoppeld, niet hoeveel er op staat.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityAction, ActivityLogEntry

# Alles wat hierop lijkt wordt vervangen door "[verwijderd]".
_FORBIDDEN_KEY = re.compile(
    r"(token|secret|password|passwd|pin|api[_-]?key|credential|client[_-]?secret"
    r"|refresh|access[_-]?token|iban|bsn|account[_-]?number|balance|saldo"
    r"|value|amount|revenue|total|vermogen)",
    re.IGNORECASE,
)
REDACTED = "[verwijderd]"
MAX_DEPTH = 4


def scrub_context(value: Any, depth: int = 0) -> Any:
    """Haalt gevoelige velden uit een willekeurige structuur."""
    if depth > MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return {
            key: (REDACTED if _FORBIDDEN_KEY.search(str(key)) else scrub_context(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub_context(item, depth + 1) for item in value]
    return value


async def log_activity(
    session: AsyncSession,
    *,
    action: ActivityAction | str,
    user_id: int | None = None,
    message: str = "",
    subject_type: str | None = None,
    subject_id: str | int | None = None,
    context: dict[str, Any] | None = None,
) -> ActivityLogEntry:
    entry = ActivityLogEntry(
        user_id=user_id,
        action=str(action),
        subject_type=subject_type,
        subject_id=str(subject_id) if subject_id is not None else None,
        message=message[:500],
        context=scrub_context(context) if context else None,
    )
    session.add(entry)
    # Bewust geen commit: de aanroeper bepaalt of de hele handeling doorgaat, zodat
    # er nooit een logregel staat voor iets dat is teruggedraaid.
    await session.flush()
    return entry


async def recent_activity(
    session: AsyncSession, *, user_id: int | None = None, limit: int = 20
) -> Sequence[ActivityLogEntry]:
    query = select(ActivityLogEntry).order_by(ActivityLogEntry.created_at.desc()).limit(limit)
    if user_id is not None:
        query = query.where(ActivityLogEntry.user_id == user_id)
    result = await session.execute(query)
    return result.scalars().all()
