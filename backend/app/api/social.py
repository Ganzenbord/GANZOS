"""De social-media API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.api.deps import require_confirmation, require_permission
from app.integrations.social.registry import describe_social_providers
from app.models.user import User
from app.schemas.platform import ChannelHistoryOut, ProviderOut
from app.schemas.social import (
    SocialChannelIn,
    SocialChannelOut,
    SocialChannelPatch,
    SocialOverviewOut,
    SocialStatsOut,
)
from app.services import social_service
from app.services.social_service import ChannelNotFound

router = APIRouter(prefix="/social", tags=["social"])

read_access = require_permission("social.read")
manage_access = require_confirmation("social.manage")

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Dit kanaal bestaat niet")


@router.get("/overview", response_model=SocialOverviewOut)
async def overview(
    user: User = Depends(read_access), session: AsyncSession = Depends(get_session)
):
    return await social_service.overview(session, user.id)


@router.get("/providers", response_model=list[ProviderOut])
async def providers(user: User = Depends(read_access)):
    return describe_social_providers()


@router.get("/channels", response_model=list[SocialChannelOut])
async def list_channels(
    user: User = Depends(read_access), session: AsyncSession = Depends(get_session)
):
    return list(await social_service.list_channels(session, user.id))


@router.post("/channels", response_model=SocialChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: SocialChannelIn,
    user: User = Depends(manage_access),
    session: AsyncSession = Depends(get_session),
):
    channel = await social_service.create_channel(session, user.id, payload.model_dump())
    await social_service.sync_channel(session, channel)
    await session.commit()
    await session.refresh(channel)
    return channel


@router.patch("/channels/{channel_id}", response_model=SocialChannelOut)
async def update_channel(
    channel_id: int,
    payload: SocialChannelPatch,
    user: User = Depends(manage_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        channel = await social_service.update_channel(
            session, user.id, channel_id, payload.model_dump(exclude_unset=True)
        )
    except ChannelNotFound:
        raise NOT_FOUND from None
    await session.commit()
    await session.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: int,
    user: User = Depends(manage_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await social_service.delete_channel(session, user.id, channel_id)
    except ChannelNotFound:
        raise NOT_FOUND from None
    await session.commit()


@router.get("/channels/{channel_id}/stats", response_model=list[SocialStatsOut])
async def channel_stats(
    channel_id: int,
    days: int = Query(default=90, ge=1, le=1825),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    try:
        await social_service._owned_channel(session, channel_id, user.id)
    except ChannelNotFound:
        raise NOT_FOUND from None
    return list(await social_service.stats_history(session, channel_id, days))


@router.post("/sync", response_model=SocialOverviewOut)
async def sync_now(
    user: User = Depends(manage_access), session: AsyncSession = Depends(get_session)
):
    await social_service.sync_all(session, user.id)
    await session.commit()
    return await social_service.overview(session, user.id)


@router.get("/history", response_model=list[ChannelHistoryOut])
async def history(
    days: int = Query(default=90, ge=1, le=1825),
    user: User = Depends(read_access),
    session: AsyncSession = Depends(get_session),
):
    """Per kanaal de metingen over de gevraagde periode."""
    channels = await social_service.list_channels(session, user.id)
    return [
        {
            "channel_id": channel.id,
            "platform": channel.platform,
            "channel_name": channel.channel_name,
            "points": [
                {
                    "measured_at": row.measured_at,
                    "followers": row.followers,
                    "views": row.views,
                    "likes": row.likes,
                }
                for row in await social_service.stats_history(session, channel.id, days)
            ],
        }
        for channel in channels
    ]
