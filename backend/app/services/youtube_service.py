"""De YouTube-koppeling: toestemming geven, bijhouden en gebruiken.

Wat hier gebeurt en niet in de provider: alles wat met de database te maken heeft. De
provider praat met Google en weet niets van gebruikers; deze dienst bewaart de tokens
versleuteld, houdt bij welk kanaal erbij hoort en zet er een regel over in het logboek.

Drie dingen die met opzet zo zijn:

- **De koppeling hangt aan een kanaal, niet aan een losse tabel.** Een gekoppeld YouTube-
  account ís een `SocialChannel`; daarmee lopen de statistieken, de omzet en het
  uploadschema er vanzelf overheen zonder tweede weg naast de bestaande.
- **De `state` is een ondertekend token, geen rij in de database.** Google stuurt hem
  onveranderd terug; de handtekening bewijst dat het verzoek van Ganz zelf kwam en van wie.
  Vijftien minuten geldig — lang genoeg om een account te kiezen, kort genoeg om niets
  waard te zijn als iemand de link later vindt.
- **Uploaden mag alleen uit één map.** Een skill noemt een bestandsnaam; zonder die grens
  zou een skill elk bestand van de computer naar YouTube kunnen sturen.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import create_token, decode_token
from app.integrations.base import (
    ProviderAuthError,
    ProviderError,
    ProviderNotConfigured,
    UploadedVideo,
    VideoUpload,
)
from app.integrations.social.youtube import YouTubeProvider
from app.integrations.social.youtube_oauth import GoogleOAuth
from app.models.activity import ActivityAction
from app.models.social import ChannelStatus, SocialChannel, SocialPlatform
from app.models.user import User
from app.services.activity_service import log_activity
from app.utils.crypto import get_vault

logger = logging.getLogger("ganz.youtube")

PLATFORM = SocialPlatform.YOUTUBE.value


class YouTubeError(Exception):
    """Gaat mis op een manier die de gebruiker moet weten."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def oauth_for(settings: Settings) -> GoogleOAuth:
    return GoogleOAuth(
        settings.youtube_client_id,
        settings.youtube_client_secret,
        settings.youtube_redirect_uri,
    )


async def _channel_of(session: AsyncSession, user_id: int) -> SocialChannel | None:
    """Het gekoppelde YouTube-kanaal van deze gebruiker, als er een is."""
    result = await session.execute(
        select(SocialChannel)
        .where(SocialChannel.user_id == user_id, SocialChannel.platform == PLATFORM)
        .order_by(SocialChannel.id)
    )
    return result.scalars().first()


# --- Stand van zaken ---------------------------------------------------------


async def status(session: AsyncSession, user_id: int, settings: Settings) -> dict[str, Any]:
    """Wat er klaar is en wat niet, in gewone taal.

    Eén plek die dit weet, zodat de knop, het stoplicht en de uploader hetzelfde zeggen.
    """
    oauth = oauth_for(settings)
    kanaal = await _channel_of(session, user_id)
    credentials = get_vault().decrypt(kanaal.credentials_encrypted) if kanaal else None
    gekoppeld = bool(credentials and credentials.get("oauth_refresh_token"))

    upload_map = (settings.youtube_video_dir or "").strip()

    if not oauth.is_configured:
        uitleg = (
            "Er staat nog geen Google-client-ID en -secret in de instellingen. "
            "Zonder die twee kan Ganz niet om toestemming vragen."
        )
    elif not gekoppeld and credentials:
        # Er staat al een kanaal met alleen een API-sleutel. Dat leest openbare cijfers en
        # verder niets; wie dat verschil niet kent, denkt dat de koppeling al staat.
        uitleg = (
            "Er staat een kanaal met alleen een API-sleutel. Daarmee leest Ganz de openbare "
            "cijfers. Voor uploaden en omzet is een koppeling nodig: klik op "
            "'Koppel met YouTube'."
        )
    elif not gekoppeld:
        uitleg = "Nog niet gekoppeld. Klik op 'Koppel met YouTube' en geef toestemming."
    elif not upload_map:
        uitleg = (
            "Gekoppeld. Uploaden staat uit: stel eerst in waar je video's staan "
            "(GANZ_YOUTUBE_VIDEO_DIR)."
        )
    else:
        uitleg = "Gekoppeld. Statistieken en uploaden werken."

    return {
        "configured": oauth.is_configured,
        "connected": gekoppeld,
        "can_upload": bool(gekoppeld and upload_map),
        "channel_name": kanaal.channel_name if kanaal else None,
        "channel_id": kanaal.external_channel_id if kanaal else None,
        "channel_status": kanaal.status if kanaal else None,
        "upload_privacy": settings.youtube_upload_privacy,
        "video_dir": upload_map or None,
        "redirect_uri": settings.youtube_redirect_uri,
        "explanation": uitleg,
    }


# --- Koppelen ----------------------------------------------------------------


def start(user: User, settings: Settings) -> str:
    """Het adres waar de gebruiker toestemming geeft."""
    oauth = oauth_for(settings)
    if not oauth.is_configured:
        raise YouTubeError(
            "Er staat nog geen Google-client-ID en -secret in de instellingen. "
            "Zie docs/youtube.md.",
            status_code=409,
        )
    return oauth.authorization_url(create_token(user.id, "youtube_oauth"))


async def finish(
    session: AsyncSession,
    *,
    code: str,
    state: str,
    settings: Settings,
    provider: YouTubeProvider | None = None,
) -> SocialChannel:
    """Wisselt de code om voor tokens en legt het kanaal vast."""
    payload = decode_token(state, "youtube_oauth")
    if payload is None:
        raise YouTubeError(
            "Deze koppeling hoort niet bij een verzoek van Ganz, of hij is verlopen. "
            "Begin opnieuw.",
            status_code=400,
        )
    user_id = int(payload["sub"])

    oauth = oauth_for(settings)
    provider = provider or YouTubeProvider(oauth_factory=lambda: oauth)

    try:
        tokens = await oauth.exchange_code(code)
        credentials = tokens.as_credentials()
        info = await provider.get_my_channel(credentials)
    except ProviderAuthError as exc:
        raise YouTubeError(str(exc), status_code=401) from exc
    except ProviderNotConfigured as exc:
        raise YouTubeError(str(exc), status_code=409) from exc
    except ProviderError as exc:
        raise YouTubeError(str(exc), status_code=502) from exc

    kanaal = await _channel_of(session, user_id)
    if kanaal is None:
        kanaal = SocialChannel(user_id=user_id, platform=PLATFORM, channel_name=info.name)
        session.add(kanaal)
    kanaal.channel_name = info.name
    kanaal.external_channel_id = info.external_channel_id
    kanaal.credentials_encrypted = get_vault().encrypt(credentials)
    kanaal.status = ChannelStatus.CONNECTED
    kanaal.status_detail = None
    kanaal.active = True
    await session.flush()

    await log_activity(
        session,
        action=ActivityAction.YOUTUBE_CONNECTED,
        user_id=user_id,
        message=f"YouTube-kanaal '{info.name}' gekoppeld.",
        subject_type="social_channel",
        subject_id=kanaal.id,
        context={"channel_id": info.external_channel_id},
    )
    return kanaal


async def disconnect(session: AsyncSession, user_id: int) -> bool:
    """Gooit de tokens weg. Het kanaal en zijn cijfers blijven staan.

    Met opzet: wat je gemeten hebt, blijf je zien. Alleen de sleutel naar Google is weg, en
    daarmee kan Ganz niets meer namens jou doen.
    """
    kanaal = await _channel_of(session, user_id)
    if kanaal is None or not kanaal.credentials_encrypted:
        return False
    kanaal.credentials_encrypted = None
    kanaal.status = ChannelStatus.NOT_CONFIGURED
    kanaal.status_detail = "De koppeling is losgemaakt."
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.YOUTUBE_DISCONNECTED,
        user_id=user_id,
        message=f"YouTube-kanaal '{kanaal.channel_name}' losgemaakt.",
        subject_type="social_channel",
        subject_id=kanaal.id,
    )
    return True


# --- Tokens die verlopen -----------------------------------------------------


async def fresh_credentials(
    session: AsyncSession,
    channel: SocialChannel,
    *,
    settings: Settings | None = None,
    provider: YouTubeProvider | None = None,
) -> dict[str, Any] | None:
    """Geeft bruikbare gegevens terug en vernieuwt het token als dat nodig is.

    Het vernieuwde token gaat meteen versleuteld terug de database in. Gebeurt dat niet, dan
    vraagt elke aanroep een nieuw token aan en loopt Ganz tegen de limieten van Google aan.
    """
    settings = settings or get_settings()
    provider = provider or YouTubeProvider()
    credentials = get_vault().decrypt(channel.credentials_encrypted)
    if not credentials:
        return None
    if not provider.needs_refresh(credentials, settings.youtube_token_margin_seconds):
        return credentials

    try:
        credentials = await provider.refresh_credentials(credentials)
    except ProviderAuthError as exc:
        channel.status = ChannelStatus.REAUTH_REQUIRED
        channel.status_detail = str(exc)
        await session.flush()
        raise
    channel.credentials_encrypted = get_vault().encrypt(credentials)
    if channel.status == ChannelStatus.REAUTH_REQUIRED:
        channel.status = ChannelStatus.CONNECTED
        channel.status_detail = None
    await session.flush()
    await log_activity(
        session,
        action=ActivityAction.YOUTUBE_TOKEN_REFRESHED,
        user_id=channel.user_id,
        message=f"Toegang tot '{channel.channel_name}' vernieuwd.",
        subject_type="social_channel",
        subject_id=channel.id,
    )
    return credentials


# --- Uploaden ----------------------------------------------------------------


def resolve_video(file_name: str, settings: Settings) -> Path:
    """Zoekt het bestand op binnen de ingestelde map — en nergens anders.

    Een skill noemt alleen een naam. Zou Ganz elk pad accepteren, dan is "upload
    vakantie.mp4" en "upload ../../.ssh/id_rsa.mp4" hetzelfde soort verzoek.
    """
    map_naam = (settings.youtube_video_dir or "").strip()
    if not map_naam:
        raise YouTubeError(
            "Uploaden staat uit. Stel eerst in waar je video's staan "
            "(GANZ_YOUTUBE_VIDEO_DIR).",
            status_code=409,
        )
    wortel = Path(map_naam).expanduser().resolve()
    if not wortel.is_dir():
        raise YouTubeError(
            f"De ingestelde videomap '{wortel}' bestaat niet.", status_code=409
        )

    kandidaat = (wortel / file_name).expanduser()
    try:
        volledig = kandidaat.resolve()
    except OSError as exc:  # pragma: no cover - alleen bij een kapot pad
        raise YouTubeError(f"Dat pad kan niet: {exc.__class__.__name__}") from exc

    # `..` en een symbolische link wijzen allebei ergens anders heen. Resolve haalt ze weg;
    # deze controle gaat over wat er ná het uitrekenen overblijft.
    if not volledig.is_relative_to(wortel):
        raise YouTubeError(
            "Dat bestand staat buiten de videomap. Alleen wat daarin staat kan geüpload "
            "worden.",
            status_code=403,
        )
    if not volledig.is_file():
        raise YouTubeError(f"Het bestand '{file_name}' staat niet in de videomap.", 404)
    return volledig


async def upload(
    session: AsyncSession,
    user_id: int,
    *,
    file_name: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str | None = None,
    settings: Settings | None = None,
    provider: YouTubeProvider | None = None,
) -> UploadedVideo:
    """Publiceert een video naar het gekoppelde kanaal."""
    settings = settings or get_settings()
    provider = provider or YouTubeProvider()

    kanaal = await _channel_of(session, user_id)
    if kanaal is None or not kanaal.credentials_encrypted:
        raise YouTubeError(
            "Er is nog geen YouTube-koppeling. Koppel eerst met YouTube.", status_code=409
        )
    bestand = resolve_video(file_name, settings)

    await log_activity(
        session,
        action=ActivityAction.YOUTUBE_UPLOAD_STARTED,
        user_id=user_id,
        message=f"Upload gestart: '{title}'.",
        subject_type="social_channel",
        subject_id=kanaal.id,
        context={"file": bestand.name},
    )

    try:
        credentials = await fresh_credentials(
            session, kanaal, settings=settings, provider=provider
        )
        if not credentials:
            raise YouTubeError("De koppeling is onleesbaar. Koppel opnieuw.", status_code=409)
        video = await provider.upload_video(
            credentials,
            VideoUpload(
                file_path=str(bestand),
                title=title,
                description=description,
                tags=tags or [],
                privacy=privacy or settings.youtube_upload_privacy,
            ),
        )
    except ProviderAuthError as exc:
        await _log_failure(session, user_id, kanaal, title, str(exc))
        raise YouTubeError(str(exc), status_code=401) from exc
    except (ProviderNotConfigured, ProviderError) as exc:
        await _log_failure(session, user_id, kanaal, title, str(exc))
        raise YouTubeError(str(exc), status_code=502) from exc
    except YouTubeError as exc:
        await _log_failure(session, user_id, kanaal, title, exc.message)
        raise

    await log_activity(
        session,
        action=ActivityAction.YOUTUBE_UPLOAD_COMPLETED,
        user_id=user_id,
        message=f"'{title}' staat op YouTube ({video.privacy}).",
        subject_type="social_channel",
        subject_id=kanaal.id,
        context={"video_id": video.external_id, "privacy": video.privacy},
    )
    return video


async def _log_failure(
    session: AsyncSession, user_id: int, kanaal: SocialChannel, title: str, reden: str
) -> None:
    await log_activity(
        session,
        action=ActivityAction.YOUTUBE_UPLOAD_FAILED,
        user_id=user_id,
        message=f"Upload van '{title}' mislukt: {reden}",
        subject_type="social_channel",
        subject_id=kanaal.id,
    )
