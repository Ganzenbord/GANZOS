"""YouTube via de officiële Data API v3 (en Analytics API voor de omzet).

Statistieken van een kanaal zijn openbaar en gaan met een API-sleutel. Omzet en uploaden
zijn dat niet: daarvoor is een OAuth-token nodig. Is dat er niet, dan geeft Ganz geen omzet
terug — hij verzint er geen — en weigert hij te uploaden met een uitleg.

Het toestemmingsverkeer met Google staat in `youtube_oauth.py`. Deze module gebruikt het
alleen om een verlopen token te vernieuwen; opslaan doet de aanroeper, want een provider
praat niet met de database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
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
    UploadedVideo,
    VideoUpload,
)
from app.integrations.social.youtube_oauth import GoogleOAuth

DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"

# Een upload van een half uur film mag niet afgebroken worden door een tijdslimiet die voor
# een statistiekverzoek bedoeld is.
UPLOAD_TIMEOUT = 60 * 30


async def _in_stukjes(pad: Path, blok: int = 1024 * 1024) -> AsyncIterator[bytes]:
    """Leest het bestand blok voor blok.

    Het moet een *async* stroom zijn: httpx weigert een gewoon bestandsobject op een
    asynchrone verbinding. En het moet in stukjes, want een video van een gigabyte hoort
    niet eerst in zijn geheel in het geheugen te staan.
    """
    with pad.open("rb") as stroom:
        while brok := stroom.read(blok):
            yield brok


def _oauth_from_settings() -> GoogleOAuth:
    # Binnen de functie, zodat de instellingen pas bij gebruik worden gelezen en niet bij
    # het importeren van deze module.
    from app.core.config import get_settings

    settings = get_settings()
    return GoogleOAuth(
        settings.youtube_client_id,
        settings.youtube_client_secret,
        settings.youtube_redirect_uri,
    )


def _to_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class YouTubeProvider:
    platform = "youtube"
    display_name = "YouTube"

    def __init__(
        self,
        timeout: float = 15.0,
        oauth_factory: Callable[[], GoogleOAuth] | None = None,
    ) -> None:
        self._timeout = timeout
        # Een functie en geen kant-en-klaar object: de instellingen staan er nog niet als
        # het register wordt opgebouwd bij het importeren.
        self._oauth_factory = oauth_factory or _oauth_from_settings

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

    # --- Toegang die verloopt ------------------------------------------------

    def needs_refresh(self, credentials: dict[str, Any] | None, margin_seconds: int) -> bool:
        """Is het toegangstoken (bijna) verlopen en is er iets om mee te vernieuwen?"""
        creds = credentials or {}
        if not creds.get("oauth_refresh_token"):
            return False
        vervalt = creds.get("oauth_expires_at")
        if not vervalt:
            # Geen vervaldatum bekend: dan liever één keer te vaak vernieuwen dan een
            # upload van tien minuten halverwege zien stranden.
            return True
        try:
            moment = datetime.fromisoformat(str(vervalt))
        except ValueError:
            return True
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment <= datetime.now(timezone.utc) + timedelta(seconds=margin_seconds)

    async def refresh_credentials(self, credentials: dict[str, Any] | None) -> dict[str, Any]:
        """Vernieuwt het toegangstoken en geeft de bijgewerkte gegevens terug."""
        creds = dict(credentials or {})
        refresh_token = creds.get("oauth_refresh_token")
        if not refresh_token:
            raise ProviderAuthError("Er is geen vernieuwingstoken. Koppel opnieuw met YouTube.")
        tokens = await self._oauth_factory().refresh(str(refresh_token))
        creds.update(tokens.as_credentials())
        return creds

    # --- Uploaden ------------------------------------------------------------

    async def upload_video(
        self, credentials: dict[str, Any] | None, video: VideoUpload
    ) -> UploadedVideo:
        """Publiceert een video in twee stappen (resumable upload).

        Eerst de gegevens, dan pas de bytes. Dat is niet alleen wat Google voorschrijft voor
        grote bestanden: het betekent ook dat een afgekeurde titel al mislukt vóórdat er een
        gigabyte over de lijn is gegaan.
        """
        creds = credentials or {}
        token = creds.get("oauth_access_token")
        if not token:
            raise ProviderNotConfigured(
                "Uploaden kan alleen met een YouTube-koppeling. Koppel eerst met YouTube."
            )

        bestand = Path(video.file_path)
        if not bestand.is_file():
            raise ProviderError(f"Het bestand '{video.file_path}' bestaat niet.")
        grootte = bestand.stat().st_size
        if grootte == 0:
            raise ProviderError(f"Het bestand '{bestand.name}' is leeg.")

        metadata = {
            "snippet": {
                "title": video.title,
                "description": video.description,
                "tags": video.tags,
            },
            "status": {"privacyStatus": video.privacy, "selfDeclaredMadeForKids": False},
        }

        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as client:
            try:
                start = await client.post(
                    UPLOAD_API,
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Upload-Content-Type": "video/*",
                        "X-Upload-Content-Length": str(grootte),
                    },
                    json=metadata,
                )
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"YouTube niet bereikbaar: {exc.__class__.__name__}"
                ) from exc

            if start.status_code in (401, 403):
                raise ProviderAuthError("De YouTube-koppeling is verlopen. Koppel opnieuw.")
            if start.status_code >= 400:
                raise ProviderError(
                    f"YouTube wilde de upload niet beginnen (status {start.status_code})."
                )

            upload_url = start.headers.get("location") or start.headers.get("Location")
            if not upload_url:
                raise ProviderError("YouTube gaf geen adres om naartoe te uploaden.")

            # Het bestand gaat in stukjes de deur uit; een video van een gigabyte hoort niet
            # eerst helemaal in het geheugen te staan.
            try:
                done = await client.put(
                    upload_url,
                    content=_in_stukjes(bestand),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "video/*",
                        "Content-Length": str(grootte),
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"De upload brak af: {exc.__class__.__name__}"
                ) from exc

        if done.status_code in (401, 403):
            raise ProviderAuthError("De YouTube-koppeling verliep tijdens de upload.")
        if done.status_code >= 400:
            raise ProviderError(f"YouTube weigerde de video (status {done.status_code}).")

        try:
            payload = done.json()
        except ValueError:
            raise ProviderError("YouTube gaf een onleesbaar antwoord op de upload.") from None

        video_id = payload.get("id")
        if not video_id:
            raise ProviderError("YouTube gaf geen video-ID terug; de upload is niet zeker.")
        return UploadedVideo(
            external_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            privacy=(payload.get("status") or {}).get("privacyStatus", video.privacy),
        )

    async def get_my_channel(self, credentials: dict[str, Any] | None) -> ChannelInfo:
        """Welk kanaal hoort bij deze koppeling?

        Anders dan `get_channel` heeft dit geen kanaal-ID nodig — juist niet: vlak na het
        koppelen is dat het enige wat nog niet bekend is.
        """
        creds = credentials or {}
        if not creds.get("oauth_access_token"):
            raise ProviderNotConfigured("Hiervoor is een YouTube-koppeling nodig.")
        payload = await self._get(f"{DATA_API}/channels", {"part": "snippet", "mine": "true"}, creds)
        items = payload.get("items") or []
        if not items:
            raise ProviderError(
                "Dit Google-account heeft geen YouTube-kanaal. Maak er eerst een aan."
            )
        snippet = items[0].get("snippet", {})
        channel_id = items[0].get("id", "")
        return ChannelInfo(
            external_channel_id=channel_id,
            name=snippet.get("title", "YouTube-kanaal"),
            url=f"https://www.youtube.com/channel/{channel_id}",
        )
