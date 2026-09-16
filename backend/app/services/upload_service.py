"""Het uploadschema per kanaal.

De aftelling wordt nergens opgeslagen. De server geeft het exacte moment en zijn
eigen tijd; de frontend rekent daar het verschil uit. Zo klopt de teller ook als de
klok van de computer een paar minuten verkeerd staat.

Een herhalende upload waarvan het moment voorbij is schuift automatisch op naar de
volgende keer. Dat gebeurt bij het uitrekenen, niet in de database, zodat er geen
achterstallige rijen ontstaan als Ganz een nacht uit heeft gestaan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityAction
from app.models.base import utcnow
from app.models.social import ChannelStatus, SocialChannel
from app.models.upload import (
    OPEN_UPLOAD_STATUSES,
    UploadRecurrence,
    UploadSchedule,
    UploadStatus,
)
from app.services.activity_service import log_activity
from app.services.social_service import _owned_channel, list_channels
from app.utils.timeutil import ensure_utc, next_upload_occurrence, seconds_until


class UploadNotFound(Exception):
    pass


async def _owned_upload(
    session: AsyncSession, upload_id: int, user_id: int
) -> UploadSchedule:
    upload = await session.get(UploadSchedule, upload_id)
    if upload is None:
        raise UploadNotFound
    channel = await session.get(SocialChannel, upload.channel_id)
    if channel is None or channel.user_id != user_id:
        raise UploadNotFound
    return upload


def _effective_moment(upload: UploadSchedule, now: datetime) -> datetime | None:
    """Wanneer deze upload eerstvolgend aan de beurt is.

    Een eenmalige upload die te laat is houdt zijn oorspronkelijke tijd: hij is niet
    verlopen maar achterstallig, en dat moet je zien.
    """
    if upload.recurrence == UploadRecurrence.ONCE:
        return ensure_utc(upload.scheduled_at)
    return next_upload_occurrence(
        upload.scheduled_at, upload.recurrence, upload.timezone, now
    )


def serialize(upload: UploadSchedule, now: datetime | None = None) -> dict[str, Any]:
    """Eén upload zoals de API hem teruggeeft, inclusief de resterende tijd.

    Ook de aanmaak- en wijzigingsantwoorden lopen hierlangs, zodat de frontend overal
    dezelfde velden krijgt en niet bij de ene route wel en bij de andere geen
    aftelling heeft.
    """
    now = ensure_utc(now or utcnow())
    data = _serialize(upload, now)
    if data is not None:
        return data
    # Een eenmalige upload die al geweest is heeft geen volgend moment meer.
    return {
        "id": upload.id,
        "channel_id": upload.channel_id,
        "title": upload.title,
        "content_type": upload.content_type,
        "status": upload.status,
        "status_detail": upload.status_detail,
        "recurrence": upload.recurrence,
        "timezone": upload.timezone,
        "scheduled_at": ensure_utc(upload.scheduled_at),
        "effective_at": None,
        "seconds_until": None,
        "overdue": False,
    }


def _serialize(upload: UploadSchedule, now: datetime) -> dict[str, Any] | None:
    moment = _effective_moment(upload, now)
    if moment is None:
        return None
    remaining = seconds_until(moment, now)
    return {
        "id": upload.id,
        "channel_id": upload.channel_id,
        "title": upload.title,
        "content_type": upload.content_type,
        "status": upload.status,
        "status_detail": upload.status_detail,
        "recurrence": upload.recurrence,
        "timezone": upload.timezone,
        "scheduled_at": ensure_utc(upload.scheduled_at),
        "effective_at": moment,
        "seconds_until": remaining,
        "overdue": remaining <= 0 and upload.status == UploadStatus.SCHEDULED,
    }


async def open_uploads(
    session: AsyncSession, channel_id: int
) -> Sequence[UploadSchedule]:
    result = await session.execute(
        select(UploadSchedule)
        .where(
            UploadSchedule.channel_id == channel_id,
            UploadSchedule.status.in_([str(s) for s in OPEN_UPLOAD_STATUSES]),
        )
        .order_by(UploadSchedule.scheduled_at)
    )
    return result.scalars().all()


async def next_for_channel(
    session: AsyncSession, channel_id: int, now: datetime
) -> dict[str, Any] | None:
    candidates = []
    for upload in await open_uploads(session, channel_id):
        data = _serialize(upload, now)
        if data is not None:
            candidates.append(data)
    if not candidates:
        return None
    # Achterstallige uploads eerst: die vragen nu om aandacht.
    return min(candidates, key=lambda item: item["effective_at"])


async def schedule_overview(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> dict[str, Any]:
    now = ensure_utc(now or utcnow())
    channels = await list_channels(session, user_id)
    rows = []
    for channel in channels:
        next_upload = (
            await next_for_channel(session, channel.id, now) if channel.active else None
        )
        rows.append(
            {
                "channel_id": channel.id,
                "platform": channel.platform,
                "channel_name": channel.channel_name,
                "channel_status": channel.status,
                "channel_active": channel.active,
                "needs_reauth": channel.status == ChannelStatus.REAUTH_REQUIRED,
                "next_upload": next_upload,
            }
        )
    # Kanalen met een geplande upload bovenaan, het dichtstbijzijnde moment eerst.
    rows.sort(
        key=lambda row: (
            row["next_upload"] is None,
            row["next_upload"]["effective_at"] if row["next_upload"] else now,
        )
    )
    return {"server_time": now, "channels": rows}


async def list_uploads(
    session: AsyncSession, user_id: int, channel_id: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    now = utcnow()
    channels = {c.id: c for c in await list_channels(session, user_id)}
    ids = [channel_id] if channel_id is not None else list(channels)
    if channel_id is not None and channel_id not in channels:
        raise UploadNotFound
    if not ids:
        return []
    result = await session.execute(
        select(UploadSchedule)
        .where(UploadSchedule.channel_id.in_(ids))
        .order_by(UploadSchedule.scheduled_at.desc())
        .limit(limit)
    )
    items = []
    for upload in result.scalars().all():
        data = serialize(upload, now)
        data["channel_name"] = channels[upload.channel_id].channel_name
        data["platform"] = channels[upload.channel_id].platform
        items.append(data)
    return items


async def create_upload(
    session: AsyncSession, user_id: int, data: dict[str, Any]
) -> UploadSchedule:
    channel = await _owned_channel(session, data["channel_id"], user_id)
    data["scheduled_at"] = ensure_utc(data["scheduled_at"])
    upload = UploadSchedule(**data)
    session.add(upload)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.UPLOAD_SCHEDULED,
        user_id=user_id,
        message=(
            f"Upload ingepland voor '{channel.channel_name}' op "
            f"{upload.scheduled_at:%d-%m-%Y %H:%M} UTC."
        ),
        subject_type="upload_schedule",
        subject_id=upload.id,
        context={"platform": channel.platform, "content_type": upload.content_type},
    )
    return upload


async def update_upload(
    session: AsyncSession, user_id: int, upload_id: int, data: dict[str, Any]
) -> UploadSchedule:
    upload = await _owned_upload(session, upload_id, user_id)
    if "scheduled_at" in data and data["scheduled_at"] is not None:
        data["scheduled_at"] = ensure_utc(data["scheduled_at"])
    for field, value in data.items():
        setattr(upload, field, value)
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.UPLOAD_UPDATED,
        user_id=user_id,
        message="Geplande upload gewijzigd.",
        subject_type="upload_schedule",
        subject_id=upload.id,
    )
    return upload


async def cancel_upload(session: AsyncSession, user_id: int, upload_id: int) -> UploadSchedule:
    upload = await _owned_upload(session, upload_id, user_id)
    upload.status = UploadStatus.CANCELLED
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.UPLOAD_CANCELLED,
        user_id=user_id,
        message="Geplande upload geannuleerd.",
        subject_type="upload_schedule",
        subject_id=upload.id,
    )
    return upload


async def delete_upload(session: AsyncSession, user_id: int, upload_id: int) -> None:
    upload = await _owned_upload(session, upload_id, user_id)
    await session.delete(upload)
    await session.flush()


_STATUS_ACTIONS = {
    UploadStatus.UPLOADING: ActivityAction.UPLOAD_STARTED,
    UploadStatus.COMPLETED: ActivityAction.UPLOAD_COMPLETED,
    UploadStatus.FAILED: ActivityAction.UPLOAD_FAILED,
}


async def set_status(
    session: AsyncSession,
    user_id: int,
    upload_id: int,
    status: UploadStatus,
    detail: str | None = None,
) -> UploadSchedule:
    """Zet de status en plant, bij een herhaling, meteen de volgende keer in.

    De afgeronde rij blijft staan, zodat je later kunt zien wat er wanneer is geplaatst.
    """
    upload = await _owned_upload(session, upload_id, user_id)
    upload.status = status
    upload.status_detail = detail
    await session.flush()

    if status == UploadStatus.COMPLETED and upload.recurrence != UploadRecurrence.ONCE:
        following = next_upload_occurrence(
            upload.scheduled_at, upload.recurrence, upload.timezone, utcnow()
        )
        if following is not None:
            session.add(
                UploadSchedule(
                    channel_id=upload.channel_id,
                    title=upload.title,
                    content_type=upload.content_type,
                    scheduled_at=following,
                    status=UploadStatus.SCHEDULED,
                    recurrence=upload.recurrence,
                    timezone=upload.timezone,
                )
            )
            await session.flush()

    await log_activity(
        session,
        action=_STATUS_ACTIONS.get(status, ActivityAction.UPLOAD_UPDATED),
        user_id=user_id,
        message=f"Upload {upload_id}: status is nu '{status}'.",
        subject_type="upload_schedule",
        subject_id=upload_id,
        context={"detail": (detail or "")[:200]} if detail else None,
    )
    return upload
