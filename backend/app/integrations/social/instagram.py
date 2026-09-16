"""Instagram via de Graph API.

De Graph API geeft volgers en het aantal berichten. Een levenslang totaal aan views
of likes bestaat er niet; die metrieken blijven dus leeg in plaats van dat Ganz ze
uit losse berichten bij elkaar schraapt en het een totaal noemt.
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

GRAPH_API = "https://graph.facebook.com/v21.0"


class InstagramProvider:
    platform = "instagram"
    display_name = "Instagram"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        creds = credentials or {}
        return bool(creds.get("ig_user_id")) and bool(creds.get("access_token"))

    def _require(self, credentials: dict[str, Any] | None) -> dict[str, Any]:
        if not self.is_configured(credentials):
            raise ProviderNotConfigured(
                "Vul het Instagram-account-ID en een geldig toegangstoken in."
            )
        assert credentials is not None
        return credentials

    async def _get(self, path: str, params: dict[str, Any], creds: dict[str, Any]) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{GRAPH_API}/{path}",
                    params={**params, "access_token": creds["access_token"]},
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Instagram niet bereikbaar: {exc.__class__.__name__}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError("Het Instagram-token is verlopen. Log opnieuw in.")
        if response.status_code >= 400:
            raise ProviderError(f"Instagram antwoordde met status {response.status_code}.")
        return response.json()

    async def get_channel(self, credentials: dict[str, Any] | None) -> ChannelInfo:
        creds = self._require(credentials)
        payload = await self._get(
            str(creds["ig_user_id"]), {"fields": "id,username"}, creds
        )
        return ChannelInfo(
            external_channel_id=str(payload.get("id", creds["ig_user_id"])),
            name=payload.get("username", "Instagram-account"),
            url=(
                f"https://www.instagram.com/{payload['username']}/"
                if payload.get("username")
                else None
            ),
        )

    async def get_stats(self, credentials: dict[str, Any] | None) -> ChannelStats:
        creds = self._require(credentials)
        payload = await self._get(
            str(creds["ig_user_id"]), {"fields": "followers_count,media_count"}, creds
        )
        return ChannelStats(
            followers=payload.get("followers_count"),
            posts=payload.get("media_count"),
            views=None,
            likes=None,
            comments=None,
            measured_at=datetime.now(timezone.utc),
        )

    async def get_recent_content(
        self, credentials: dict[str, Any] | None, limit: int = 5
    ) -> list[ContentItem]:
        creds = self._require(credentials)
        payload = await self._get(
            f"{creds['ig_user_id']}/media",
            {"fields": "id,caption,permalink,timestamp", "limit": max(1, min(limit, 50))},
            creds,
        )
        items: list[ContentItem] = []
        for entry in payload.get("data", []):
            stamp = entry.get("timestamp")
            items.append(
                ContentItem(
                    external_id=str(entry.get("id")),
                    title=(entry.get("caption") or "")[:200],
                    published_at=(
                        datetime.fromisoformat(stamp.replace("+0000", "+00:00"))
                        if stamp
                        else None
                    ),
                    url=entry.get("permalink"),
                )
            )
        return items

    async def get_revenue(self, credentials: dict[str, Any] | None) -> Revenue | None:
        # Instagram kent geen omzet-eindpunt voor gewone accounts.
        return None
