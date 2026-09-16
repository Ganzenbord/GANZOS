"""TikTok via de officiële Display API.

Het gebruikerseindpunt geeft volgers, likes en het aantal video's. Een totaal aantal
weergaven zit er niet in; dat blijft dus leeg.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.integrations.base import (
    ChannelInfo,
    ChannelStats,
    ContentItem,
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
    Revenue,
)

TIKTOK_API = "https://open.tiktokapis.com/v2"


class TikTokProvider:
    platform = "tiktok"
    display_name = "TikTok"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        return bool((credentials or {}).get("access_token"))

    def _require(self, credentials: dict[str, Any] | None) -> dict[str, Any]:
        if not self.is_configured(credentials):
            raise ProviderNotConfigured("Koppel TikTok en geef toestemming.")
        assert credentials is not None
        return credentials

    async def _get(self, path: str, params: dict[str, Any], creds: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{TIKTOK_API}/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {creds['access_token']}"},
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"TikTok niet bereikbaar: {exc.__class__.__name__}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError("De TikTok-sessie is verlopen. Log opnieuw in.")
        if response.status_code >= 400:
            raise ProviderError(f"TikTok antwoordde met status {response.status_code}.")
        return response.json()

    async def get_channel(self, credentials: dict[str, Any] | None) -> ChannelInfo:
        creds = self._require(credentials)
        payload = await self._get(
            "user/info/", {"fields": "open_id,display_name,profile_deep_link"}, creds
        )
        user = (payload.get("data") or {}).get("user") or {}
        return ChannelInfo(
            external_channel_id=str(user.get("open_id", "")),
            name=user.get("display_name", "TikTok-account"),
            url=user.get("profile_deep_link"),
        )

    async def get_stats(self, credentials: dict[str, Any] | None) -> ChannelStats:
        creds = self._require(credentials)
        payload = await self._get(
            "user/info/", {"fields": "follower_count,likes_count,video_count"}, creds
        )
        user = (payload.get("data") or {}).get("user") or {}
        return ChannelStats(
            followers=user.get("follower_count"),
            likes=user.get("likes_count"),
            posts=user.get("video_count"),
            views=None,
            comments=None,
            measured_at=datetime.now(timezone.utc),
        )

    async def get_recent_content(
        self, credentials: dict[str, Any] | None, limit: int = 5
    ) -> list[ContentItem]:
        creds = self._require(credentials)
        payload = await self._get(
            "video/list/", {"fields": "id,title,create_time", "max_count": max(1, min(limit, 20))},
            creds,
        )
        videos = (payload.get("data") or {}).get("videos") or []
        return [
            ContentItem(
                external_id=str(video.get("id")),
                title=video.get("title", ""),
                published_at=(
                    datetime.fromtimestamp(video["create_time"], tz=timezone.utc)
                    if video.get("create_time")
                    else None
                ),
            )
            for video in videos
        ]

    async def get_revenue(self, credentials: dict[str, Any] | None) -> Revenue | None:
        # De Display API kent geen omzetgegevens.
        return None
