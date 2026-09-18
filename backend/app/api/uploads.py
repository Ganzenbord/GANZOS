"""De API van het uploadschema."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.api.deps import require_confirmation, require_permission
from app.models.user import User
from app.schemas.upload import (
    ScheduleOverviewOut,
    UploadIn,
    UploadOut,
    UploadPatch,
    UploadStatusIn,
)
from app.services import upload_service
from app.services.social_service import ChannelNotFound
from app.services.upload_service import UploadNotFound

router = APIRouter(prefix="/uploads", tags=["uploads"])

read_access = require_permission("upload.read")
schedule_access = require_permission("upload.schedule")
execute_access = require_confirmation("upload.execute")

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Deze upload bestaat niet")


@router.get("/schedule", response_model=ScheduleOverviewOut)
async def schedule(
    user: User = Depends(read_access), session: AsyncSession = Depends(get_session)
):
    """Alle kanalen met hun eerstvolgende upload.

    `server_time` staat er bewust bij: de frontend rekent daarmee het verschil met de
    eigen klok weg, zodat de aftelling niet gaat lopen op een verkeerd ingestelde pc.
    """
    return await upload_service.schedule_overview(session, user.id)


@router.get("", response_model=list[UploadOut])
async def list_uploads(
    channel_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await upload_service.list_uploads(session, user.id, channel_id, limit)
    except UploadNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dit kanaal bestaat niet") from None


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def create_upload(
    payload: UploadIn,
    user: User = Depends(schedule_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        upload = await upload_service.create_upload(session, user.id, payload.model_dump())
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dit kanaal bestaat niet") from None
    await session.commit()
    await session.refresh(upload)
    return UploadOut.model_validate(upload_service.serialize(upload))


@router.patch("/{upload_id}", response_model=UploadOut)
async def update_upload(
    upload_id: int,
    payload: UploadPatch,
    user: User = Depends(schedule_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        upload = await upload_service.update_upload(
            session, user.id, upload_id, payload.model_dump(exclude_unset=True)
        )
    except UploadNotFound:
        raise NOT_FOUND from None
    await session.commit()
    await session.refresh(upload)
    return UploadOut.model_validate(upload_service.serialize(upload))


@router.post("/{upload_id}/cancel", response_model=UploadOut)
async def cancel_upload(
    upload_id: int,
    user: User = Depends(schedule_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        upload = await upload_service.cancel_upload(session, user.id, upload_id)
    except UploadNotFound:
        raise NOT_FOUND from None
    await session.commit()
    await session.refresh(upload)
    return UploadOut.model_validate(upload_service.serialize(upload))


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    upload_id: int,
    user: User = Depends(schedule_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await upload_service.delete_upload(session, user.id, upload_id)
    except UploadNotFound:
        raise NOT_FOUND from None
    await session.commit()


@router.post("/{upload_id}/status", response_model=UploadOut)
async def set_status(
    upload_id: int,
    payload: UploadStatusIn,
    user: User = Depends(execute_access),
    session: AsyncSession = Depends(get_session),
):
    """Een upload starten, afronden of als mislukt markeren.

    Gevoelig: dit zet daadwerkelijk iets in gang naar buiten toe, dus er is een
    tweede bevestiging nodig.
    """
    try:
        upload = await upload_service.set_status(
            session, user.id, upload_id, payload.status, payload.detail
        )
    except UploadNotFound:
        raise NOT_FOUND from None
    await session.commit()
    await session.refresh(upload)
    return UploadOut.model_validate(upload_service.serialize(upload))
