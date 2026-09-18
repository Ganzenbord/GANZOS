"""De koppeling met Google: toestemming vragen en tokens vernieuwen.

Waarom dit een apart bestand is en niet bij de provider staat: het toestemming vragen gaat
over de *gebruiker*, het ophalen van statistieken over een *kanaal*. Ze veranderen om
verschillende redenen, en een verlopen token is iets anders dan een kanaal dat niet bestaat.

Wat er nooit in terechtkomt: een `client_secret` of een `refresh_token` in een logregel of
een foutmelding. Die gaan versleuteld de database in en verder nergens heen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.integrations.base import ProviderAuthError, ProviderError, ProviderNotConfigured

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Waar Ganz toestemming voor vraagt. Niet meer dan dit:
#   youtube.readonly       — je kanaal en je statistieken lezen
#   youtube.upload         — een video uploaden
#   yt-analytics-monetary  — de geschatte omzet
# Bewust géén `youtube.force-ssl`: dat mag ook reacties en video's verwijderen.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
)


@dataclass(slots=True)
class TokenSet:
    """Wat Google teruggeeft, in de vorm waarin Ganz het bewaart."""

    access_token: str
    expires_at: datetime
    refresh_token: str | None = None
    scope: str | None = None

    def as_credentials(self) -> dict[str, Any]:
        return {
            "oauth_access_token": self.access_token,
            "oauth_refresh_token": self.refresh_token,
            "oauth_expires_at": self.expires_at.isoformat(),
            "oauth_scope": self.scope,
        }


def _expiry(seconds: object) -> datetime:
    try:
        geldig = int(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # Google geeft dit altijd mee; ontbreekt het, ga dan uit van het kortste dat
        # voorkomt. Te vroeg vernieuwen kost niets, te laat wel.
        geldig = 600
    return datetime.now(timezone.utc) + timedelta(seconds=geldig)


class GoogleOAuth:
    """Het toestemmingsverkeer met Google.

    De adressen staan als parameter in de constructor zodat een test er een eigen server
    voor kan zetten. In gebruik zijn het altijd die van Google.
    """

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str,
        *,
        auth_endpoint: str = AUTH_ENDPOINT,
        token_endpoint: str = TOKEN_ENDPOINT,
        timeout: float = 15.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._auth_endpoint = auth_endpoint
        self._token_endpoint = token_endpoint
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def _require_configured(self) -> tuple[str, str]:
        if not self.is_configured:
            raise ProviderNotConfigured(
                "Er staat nog geen Google-client-ID en -secret in de instellingen. "
                "Zie docs/youtube.md."
            )
        assert self._client_id and self._client_secret
        return self._client_id, self._client_secret

    def authorization_url(self, state: str) -> str:
        """Het adres waar de gebruiker toestemming geeft."""
        client_id, _ = self._require_configured()
        return f"{self._auth_endpoint}?" + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                # offline + consent: zonder deze twee geeft Google alleen de tweede keer
                # geen refresh_token meer, en dan is de koppeling na een uur weer weg.
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )

    async def _post(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._token_endpoint, data=data)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Google niet bereikbaar: {exc.__class__.__name__}"
            ) from exc

        if response.status_code >= 400:
            # De tekst van Google zelf ("invalid_grant") zegt meer dan een eigen zin, maar
            # het antwoord kan ook het verzonden secret bevatten. Alleen de foutcode dus.
            try:
                code = response.json().get("error", "onbekend")
            except ValueError:
                code = "onbekend"
            if response.status_code in (400, 401) and code in {
                "invalid_grant",
                "invalid_client",
                "unauthorized_client",
            }:
                raise ProviderAuthError(
                    f"Google wees de koppeling af ({code}). Koppel opnieuw met YouTube."
                )
            raise ProviderError(f"Google antwoordde met status {response.status_code} ({code}).")
        return response.json()

    async def exchange_code(self, code: str) -> TokenSet:
        """Wisselt de code uit de terugverwijzing om voor tokens."""
        client_id, client_secret = self._require_configured()
        payload = await self._post(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        token = payload.get("access_token")
        if not token:
            raise ProviderError("Google gaf geen toegangstoken terug.")
        if not payload.get("refresh_token"):
            # Zonder refresh_token is de koppeling na een uur weer stuk. Dat gebeurt als het
            # account al eerder toestemming gaf; intrekken in je Google-account en opnieuw
            # koppelen lost het op.
            raise ProviderAuthError(
                "Google gaf geen vernieuwingstoken terug. Trek de toegang van Ganz in bij "
                "je Google-account (Beveiliging → Apps van derden) en koppel daarna opnieuw."
            )
        return TokenSet(
            access_token=token,
            refresh_token=payload["refresh_token"],
            expires_at=_expiry(payload.get("expires_in")),
            scope=payload.get("scope"),
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        """Haalt een nieuw toegangstoken op. Het vernieuwingstoken blijft hetzelfde."""
        client_id, client_secret = self._require_configured()
        payload = await self._post(
            {
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            }
        )
        token = payload.get("access_token")
        if not token:
            raise ProviderAuthError("Google gaf geen nieuw toegangstoken. Koppel opnieuw.")
        return TokenSet(
            access_token=token,
            # Google stuurt bij een vernieuwing geen nieuw refresh_token mee; de oude blijft
            # geldig. De aanroeper zet hem terug.
            refresh_token=payload.get("refresh_token") or refresh_token,
            expires_at=_expiry(payload.get("expires_in")),
            scope=payload.get("scope"),
        )
