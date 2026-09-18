"""Wat er vandaag op de rol staat.

Twee soorten dingen komen hier samen: uploads die gepland staan, en taken die Ganz zelf
moet uitvoeren. Ze zitten in verschillende tabellen maar horen op één lijstje — de vraag
"wat staat er vandaag te gebeuren" kent dat onderscheid niet.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import FINAL_STATUSES, MissionTask
from app.models.social import SocialChannel
from app.models.upload import OPEN_UPLOAD_STATUSES, UploadSchedule
from app.services import upload_service


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Begin en eind van een dag in UTC.

    Met opzet UTC en niet de lokale tijd: alles in Ganz wordt zo opgeslagen, en op de grens
    van de dag omrekenen zou betekenen dat "vandaag" iets anders betekent in de database dan
    in dit lijstje.
    """
    begin = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return begin, begin + timedelta(days=1)


async def today(
    session: AsyncSession, user_id: int, *, day: date | None = None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    day = day or now.date()
    begin, eind = day_bounds(day)

    # Een upload hangt aan een kanaal, en een kanaal aan een gebruiker — er is geen
    # user_id op de upload zelf. Vandaar de join; zonder die stap zie je andermans uploads.
    uploads = await session.scalars(
        select(UploadSchedule)
        .join(SocialChannel, SocialChannel.id == UploadSchedule.channel_id)
        .where(
            SocialChannel.user_id == user_id,
            UploadSchedule.scheduled_at >= begin,
            UploadSchedule.scheduled_at < eind,
        )
        .order_by(UploadSchedule.scheduled_at)
    )
    taken = await session.scalars(
        select(MissionTask)
        .where(
            MissionTask.user_id == user_id,
            MissionTask.scheduled_for >= begin,
            MissionTask.scheduled_for < eind,
        )
        .order_by(MissionTask.scheduled_for)
    )

    items: list[dict[str, Any]] = []
    for upload in uploads:
        regel = upload_service.serialize(upload, now)
        items.append(
            {
                "kind": "upload",
                "id": upload.id,
                "title": regel.get("title") or upload.title,
                "at": upload.scheduled_at,
                "status": upload.status,
                "done": upload.status not in {str(s) for s in OPEN_UPLOAD_STATUSES},
            }
        )
    for taak in taken:
        items.append(
            {
                "kind": "task",
                "id": taak.id,
                "title": taak.title,
                "at": taak.scheduled_for,
                "status": taak.status,
                "done": taak.status in FINAL_STATUSES,
            }
        )

    items.sort(key=lambda regel: regel["at"])
    return {
        "day": day,
        "items": items,
        "total": len(items),
        "open": sum(1 for regel in items if not regel["done"]),
    }
