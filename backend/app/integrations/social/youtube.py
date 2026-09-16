"""YouTube via de officiële Data API v3 (en Analytics API voor de omzet).

Statistieken van een kanaal zijn openbaar en gaan met een API-sleutel. Omzet is dat
niet: daarvoor is een OAuth-token met de yt-analytics-monetary scope nodig. Is dat er
niet, dan geeft Ganz geen omzet terug — hij verzint er geen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.integrations.base import (
    Balance,  # noqa: F401  (gedeelde import houdt de modules symmetrisch)
    ChannelInfo,
    ChannelStats,
    ContentItem,
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
    Revenue,
)

DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"


def _to_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class YouTubeProvider:
    platform = "youtube"
    display_name = "YouTube"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def is_configured(self, credentials: dict[str, Any] | None) -> bool:
        creds = credentials or {}
        return bool(creds.get("channel_id")) and bool(
            creds.get("api_key") or creds.get("oauth_access_token")
        )

    async def _get(self, url: str, params: dict[str, Any], creds: dict[str, Any]) -> Any:
        headers = {}
        token = creds.get("oauth_access_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif creds.get("api_key"):
            params = {**params, "key": creds["api_key"]}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube niet bereikbaar: {exc.__class__.__name__}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError("De YouTube-koppeling is verlopen. Log opnieuw in.")
        if response.status_code >= 400:
            raise ProviderError(f"YouTube antwoordde met status {response.status_code}.")
        return response.json()

    def _require(self, credentials: dict[str, Any] | None) -> dict[str, Any]:
        if not self.is_configured(credentials):
            raise ProviderNotConfigured(
                "Vul een kanaal-ID en een API-sleutel in, of koppel via OAuth."
            )
        assert credentials is not None
        return credentials

    async def get_channel(self, credentials: dict[str, Any] | None) -> ChannelInfo:
        creds = self._require(credentials)
        payload = await self._get(
            f"{DATA_API}/channels", {"part": "snippet", "id": creds["channel_id"]}, creds
        )
        items = payload.get("items") or []
        if not items:
            raise ProviderError("Dit kanaal-ID bestaat niet of is niet zichtbaar.")
        snippet = items[0].get("snippet", {})
        channel_id = items[0].get("id", creds["channel_id"])
        return ChannelInfo(
            external_channel_id=channel_id,
            name=snippet.get("title", "YouTube-kanaal"),
            url=f"https://www.youtube.com/channel/{channel_id}",
        )

    async def get_stats(self, credentials: dict[str, Any] | None) -> ChannelStats:
        creds = self._require(credentials)
        payload = await self._get(
            f"{DATA_API}/channels", {"part": "statistics", "id": creds["channel_id"]}, creds
        )
        items = payload.get("items") or []
        if not items:
            raise ProviderError("Geen statistieken ontvangen voor dit kanaal.")
        stats = items[0].get("statistics", {})
        return ChannelStats(
            followers=_to_int(stats.get("subscriberCount")),
            views=_to_int(stats.get("viewCount")),
            posts=_to_int(stats.get("videoCount")),
            # De Data API levert geen totaal aantal likes of reacties per kanaal.
            likes=None,
            comments=None,
            measured_at=datetime.now(timezone.utc),
        )

    async def get_recent_content(
        self, credentials: dict[str, Any] | None, limit: int = 5
    ) -> list[ContentItem]:
        creds = self._require(credentials)
        payload = await self._get(
            f"{DATA_API}/search",
            {
                "part": "snippet",
                "channelId": creds["channel_id"],
                "order": "date",
                "maxResults": max(1, min(limit, 50)),
                "type": "video",
            },
            creds,
        )
        items: list[ContentItem] = []
        for entry in payload.get("items", []):
            video_id = (entry.get("id") or {}).get("videoId")
            snippet = entry.get("snippet", {})
            if not video_id:
                continue
            published = snippet.get("publishedAt")
            items.append(
                ContentItem(
                    external_id=video_id,
                    title=snippet.get("title", ""),
                    published_at=(
                        datetime.fromisoformat(published.replace("Z", "+00:00"))
                        if published
                        else None
                    ),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                )
            )
        return items

    async def get_revenue(self, credentials: dict[str, Any] | None) -> Revenue | None:
        creds = credentials or {}
        if not creds.get("oauth_access_token"):
            # Zonder OAuth is omzet simpelweg niet op te vragen.
            return None
        today = date.today()
        start = today.replace(day=1)
        payload = await self._get(
            ANALYTICS_API,
            {
                "ids": "channel==MINE",
                "startDate": start.isoformat(),
                "endDate": today.isoformat(),
                "metrics": "estimatedRevenue",
            },
            creds,
        )
        rows = payload.get("rows") or []
        if not rows or not rows[0]:
            return None
        try:
            amount = Decimal(str(rows[0][0]))
        except InvalidOperation:
            return None
        return Revenue(
            amount=amount,
            currency=payload.get("currency", "EUR"),
            period_start=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(0),
        )
