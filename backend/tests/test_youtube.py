"""De YouTube-koppeling: toestemming, tokens, en echt uploaden.

Er komt in deze tests geen echte Google aan te pas en er staat nergens een sleutel. Wat
Google terugstuurt is een neptransport; wat Ganz ermee doet is echt — inclusief het
versleutelen, het vernieuwen van een verlopen token en het weigeren van een bestand dat
buiten de videomap staat.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.security import decode_token
from app.integrations.base import ProviderAuthError
from app.integrations.social.youtube import YouTubeProvider
from app.models.activity import ActivityAction, ActivityLogEntry
from app.models.social import ChannelStatus, SocialChannel
from app.models.user import User
from app.services import youtube_service
from app.utils.crypto import get_vault
from tests.conftest import auth_headers, confirm_headers

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-secret"
REDIRECT = "http://localhost:8000/api/youtube/oauth/callback"


def instellingen(**extra) -> Settings:
    """De echte instellingen met de YouTube-velden ingevuld."""
    basis = get_settings().model_dump()
    basis.update(
        youtube_client_id=CLIENT_ID,
        youtube_client_secret=CLIENT_SECRET,
        youtube_redirect_uri=REDIRECT,
    )
    basis.update(extra)
    return Settings(**basis)


@pytest.fixture
def met_google(app, monkeypatch):
    """Zet de client-gegevens aan en zet een nep-Google achter httpx."""

    # Eén keer vastleggen: roep je `zet` twee keer aan, dan zou de tweede anders de eerste
    # nepversie als "origineel" pakken en blijven de oude antwoorden gelden.
    origineel = httpx.AsyncClient

    def zet(settings: Settings, routes) -> None:
        app.dependency_overrides[get_settings] = lambda: settings

        def fabriek(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(routes)
            return origineel(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", fabriek)

    yield zet
    app.dependency_overrides.clear()


def google_routes(*, channel_title: str = "Ganzenbord", refresh_token: str | None = "rt-1"):
    """Het minimum dat Google terugstuurt om te kunnen koppelen."""
    tokens = {"access_token": "at-1", "expires_in": 3600, "scope": "youtube.upload"}
    if refresh_token:
        tokens["refresh_token"] = refresh_token

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=tokens)
        if "youtube/v3/channels" in str(request.url):
            return httpx.Response(
                200,
                json={"items": [{"id": "UC123", "snippet": {"title": channel_title}}]},
            )
        return httpx.Response(404, json={"error": "onbekend adres in de test"})

    return handler


# --- Stand van zaken ---------------------------------------------------------


async def test_zonder_client_id_zegt_de_status_precies_dat(
    client: AsyncClient, owner: User
) -> None:
    body = (await client.get("/youtube/status", headers=auth_headers(owner))).json()

    assert body["configured"] is False
    assert body["connected"] is False
    assert body["can_upload"] is False
    assert "client-ID" in body["explanation"]


async def test_koppelen_zonder_client_id_wordt_netjes_geweigerd(
    client: AsyncClient, owner: User, session
) -> None:
    headers = await confirm_headers(session, owner, "integrations.manage")

    antwoord = await client.post("/youtube/connect", headers=headers)

    assert antwoord.status_code == 409
    assert "client-ID" in antwoord.json()["detail"]


async def test_de_status_bevat_nooit_een_token(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    met_google(instellingen(), google_routes())
    await koppel(client, owner, session)

    body = (await client.get("/youtube/status", headers=auth_headers(owner))).json()

    tekst = str(body)
    assert "at-1" not in tekst
    assert "rt-1" not in tekst
    assert CLIENT_SECRET not in tekst
    assert body["connected"] is True
    assert body["channel_name"] == "Ganzenbord"


async def test_een_kanaal_met_alleen_een_api_sleutel_heet_niet_gekoppeld(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    """Een API-sleutel leest openbare cijfers en verder niets. Wie dat verschil niet kent,
    denkt dat de koppeling al staat en snapt niet waarom uploaden niet lukt."""
    from app.models.social import SocialChannel as Kanaal

    session.add(
        Kanaal(
            user_id=owner.id,
            platform="youtube",
            channel_name="Ganzenbord",
            status=ChannelStatus.CONNECTED,
            credentials_encrypted=get_vault().encrypt({"api_key": "AIza-test", "channel_id": "UC1"}),
        )
    )
    await session.commit()
    met_google(instellingen(), google_routes())

    body = (await client.get("/youtube/status", headers=auth_headers(owner))).json()

    assert body["connected"] is False
    assert body["can_upload"] is False
    assert "API-sleutel" in body["explanation"]
    assert "AIza-test" not in str(body)


# --- Toestemming vragen ------------------------------------------------------


async def test_het_koppeladres_vraagt_precies_wat_nodig_is(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    met_google(instellingen(), google_routes())
    headers = await confirm_headers(session, owner, "integrations.manage")

    antwoord = await client.post("/youtube/connect", headers=headers)

    assert antwoord.status_code == 200
    adres = urlparse(antwoord.json()["authorization_url"])
    params = parse_qs(adres.query)
    assert adres.netloc == "accounts.google.com"
    assert params["client_id"] == [CLIENT_ID]
    assert params["redirect_uri"] == [REDIRECT]
    # Zonder deze twee geeft Google geen vernieuwingstoken en is de koppeling na een uur weg.
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    # Wel uploaden, niet verwijderen: force-ssl vragen we met opzet niet.
    scopes = params["scope"][0]
    assert "youtube.upload" in scopes
    assert "force-ssl" not in scopes
    # De state zegt van wie het verzoek kwam, en is niet als inlogtoken te gebruiken.
    state = params["state"][0]
    assert decode_token(state, "youtube_oauth")["sub"] == str(owner.id)
    assert decode_token(state, "access") is None


async def test_koppelen_vraagt_om_een_bevestiging(
    client: AsyncClient, owner: User, met_google
) -> None:
    met_google(instellingen(), google_routes())

    antwoord = await client.post("/youtube/connect", headers=auth_headers(owner))

    assert antwoord.status_code == 428


# --- De terugkoppeling van Google --------------------------------------------


async def koppel(client: AsyncClient, owner: User, session) -> httpx.Response:
    """Doorloopt het hele koppelen zoals de browser dat doet."""
    headers = await confirm_headers(session, owner, "integrations.manage")
    start = await client.post("/youtube/connect", headers=headers)
    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
    return await client.get(
        "/youtube/oauth/callback", params={"code": "code-van-google", "state": state}
    )


async def test_koppelen_legt_het_kanaal_versleuteld_vast(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    met_google(instellingen(), google_routes())

    antwoord = await koppel(client, owner, session)

    assert antwoord.status_code == 200
    assert "Ganzenbord" in antwoord.text
    # Geen token op een pagina die in een gewone browser opent.
    assert "at-1" not in antwoord.text

    kanaal = await session.scalar(select(SocialChannel).where(SocialChannel.platform == "youtube"))
    assert kanaal.channel_name == "Ganzenbord"
    assert kanaal.external_channel_id == "UC123"
    assert kanaal.status == ChannelStatus.CONNECTED
    # Versleuteld: de tokens staan niet leesbaar in de kolom.
    assert "rt-1" not in (kanaal.credentials_encrypted or "")
    assert get_vault().decrypt(kanaal.credentials_encrypted)["oauth_refresh_token"] == "rt-1"


async def test_een_verzonnen_state_koppelt_niets(
    client: AsyncClient, session, met_google
) -> None:
    met_google(instellingen(), google_routes())

    antwoord = await client.get(
        "/youtube/oauth/callback", params={"code": "x", "state": "zelf-verzonnen"}
    )

    assert antwoord.status_code == 400
    assert "verlopen" in antwoord.text or "hoort niet" in antwoord.text
    assert await session.scalar(select(SocialChannel)) is None


async def test_op_annuleren_klikken_verandert_niets(client: AsyncClient, session) -> None:
    antwoord = await client.get("/youtube/oauth/callback", params={"error": "access_denied"})

    assert antwoord.status_code == 400
    assert "afgebroken" in antwoord.text
    assert await session.scalar(select(SocialChannel)) is None


async def test_zonder_vernieuwingstoken_weigert_ganz_de_koppeling(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    """Google geeft de tweede keer geen refresh_token. Een koppeling die na een uur stuk is,
    is erger dan geen koppeling: je merkt het pas als je hem nodig hebt."""
    met_google(instellingen(), google_routes(refresh_token=None))

    antwoord = await koppel(client, owner, session)

    assert antwoord.status_code == 400
    assert "Beveiliging" in antwoord.text
    assert await session.scalar(select(SocialChannel)) is None


async def test_losmaken_gooit_de_tokens_weg_maar_houdt_het_kanaal(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    met_google(instellingen(), google_routes())
    await koppel(client, owner, session)
    headers = await confirm_headers(session, owner, "integrations.manage")

    antwoord = await client.post("/youtube/disconnect", headers=headers)

    assert antwoord.status_code == 200
    assert antwoord.json()["disconnected"] is True
    kanaal = await session.scalar(select(SocialChannel).where(SocialChannel.platform == "youtube"))
    await session.refresh(kanaal)
    assert kanaal.credentials_encrypted is None
    assert kanaal.channel_name == "Ganzenbord"


# --- Tokens die verlopen -----------------------------------------------------


def test_een_token_zonder_vervaldatum_wordt_vernieuwd() -> None:
    provider = YouTubeProvider()

    assert provider.needs_refresh({"oauth_refresh_token": "rt"}, 120) is True
    assert provider.needs_refresh({"oauth_access_token": "at"}, 120) is False


def test_de_marge_telt_mee() -> None:
    """Een token dat over een minuut verloopt is voor een upload van tien minuten te kort."""
    provider = YouTubeProvider()
    bijna = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    ruim = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    assert provider.needs_refresh({"oauth_refresh_token": "rt", "oauth_expires_at": bijna}, 120)
    assert not provider.needs_refresh({"oauth_refresh_token": "rt", "oauth_expires_at": ruim}, 120)


async def test_een_vernieuwd_token_wordt_meteen_opgeslagen(
    client: AsyncClient, owner: User, session, met_google
) -> None:
    """Anders vraagt elke aanroep een nieuw token aan en loopt Ganz tegen Google's limieten."""
    settings = instellingen()
    met_google(settings, google_routes())
    await koppel(client, owner, session)
    kanaal = await session.scalar(select(SocialChannel).where(SocialChannel.platform == "youtube"))

    # Zet het token op verlopen, zoals het na een uur vanzelf gaat.
    verlopen = dict(get_vault().decrypt(kanaal.credentials_encrypted))
    verlopen["oauth_expires_at"] = "2020-01-01T00:00:00+00:00"
    kanaal.credentials_encrypted = get_vault().encrypt(verlopen)
    await session.flush()

    vernieuwd = await youtube_service.fresh_credentials(
        session,
        kanaal,
        settings=settings,
        provider=YouTubeProvider(oauth_factory=lambda: youtube_service.oauth_for(settings)),
    )

    assert vernieuwd["oauth_access_token"] == "at-1"
    assert vernieuwd["oauth_refresh_token"] == "rt-1"
    opgeslagen = get_vault().decrypt(kanaal.credentials_encrypted)
    assert opgeslagen["oauth_expires_at"] == vernieuwd["oauth_expires_at"]
    assert opgeslagen["oauth_expires_at"] != "2020-01-01T00:00:00+00:00"


async def test_een_afgewezen_vernieuwing_vraagt_om_opnieuw_koppelen(
    client: AsyncClient, owner: User, session, met_google, monkeypatch
) -> None:
    settings = instellingen()
    met_google(settings, google_routes())
    await koppel(client, owner, session)
    kanaal = await session.scalar(select(SocialChannel).where(SocialChannel.platform == "youtube"))

    def weiger(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    met_google(settings, weiger)
    verlopen = dict(get_vault().decrypt(kanaal.credentials_encrypted))
    verlopen["oauth_expires_at"] = "2020-01-01T00:00:00+00:00"
    kanaal.credentials_encrypted = get_vault().encrypt(verlopen)
    await session.flush()

    with pytest.raises(ProviderAuthError):
        await youtube_service.fresh_credentials(
            session,
            kanaal,
            settings=settings,
            provider=YouTubeProvider(oauth_factory=lambda: youtube_service.oauth_for(settings)),
        )

    assert kanaal.status == ChannelStatus.REAUTH_REQUIRED
    assert "opnieuw" in kanaal.status_detail


# --- De videomap -------------------------------------------------------------


def test_zonder_ingestelde_videomap_staat_uploaden_uit() -> None:
    with pytest.raises(youtube_service.YouTubeError) as fout:
        youtube_service.resolve_video("video.mp4", instellingen())

    assert fout.value.status_code == 409
    assert "GANZ_YOUTUBE_VIDEO_DIR" in fout.value.message


def test_een_bestand_buiten_de_videomap_gaat_niet_mee(tmp_path) -> None:
    """Een skill noemt een naam. Zonder deze grens is 'upload ../../.ssh/id_rsa' hetzelfde
    soort verzoek als 'upload vakantie.mp4'."""
    videos = tmp_path / "videos"
    videos.mkdir()
    (tmp_path / "geheim.txt").write_text("niet van jou")
    settings = instellingen(youtube_video_dir=str(videos))

    with pytest.raises(youtube_service.YouTubeError) as fout:
        youtube_service.resolve_video("../geheim.txt", settings)

    assert fout.value.status_code == 403


def test_een_symbolische_link_naar_buiten_telt_ook_als_buiten(tmp_path) -> None:
    videos = tmp_path / "videos"
    videos.mkdir()
    (tmp_path / "geheim.txt").write_text("niet van jou")
    (videos / "onschuldig.mp4").symlink_to(tmp_path / "geheim.txt")
    settings = instellingen(youtube_video_dir=str(videos))

    with pytest.raises(youtube_service.YouTubeError) as fout:
        youtube_service.resolve_video("onschuldig.mp4", settings)

    assert fout.value.status_code == 403


def test_een_bestand_in_de_videomap_wordt_gevonden(tmp_path) -> None:
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "aflevering-12.mp4").write_bytes(b"film")
    settings = instellingen(youtube_video_dir=str(videos))

    gevonden = youtube_service.resolve_video("aflevering-12.mp4", settings)

    assert gevonden.name == "aflevering-12.mp4"
    assert gevonden.read_bytes() == b"film"


# --- Uploaden ----------------------------------------------------------------


def upload_routes(video_id: str = "vid-1", privacy: str = "private"):
    """Google's resumable upload in twee stappen: eerst de gegevens, dan de bytes."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": "at-2", "refresh_token": "rt-1", "expires_in": 3600}
            )
        if "upload/youtube/v3/videos" in str(request.url):
            return httpx.Response(200, headers={"Location": "https://upload.test/sessie-1"})
        if str(request.url) == "https://upload.test/sessie-1":
            return httpx.Response(
                200, json={"id": video_id, "status": {"privacyStatus": privacy}}
            )
        return httpx.Response(404, json={"error": "onbekend adres in de test"})

    return handler


async def test_uploaden_zonder_koppeling_zegt_wat_je_moet_doen(
    session, owner: User
) -> None:
    with pytest.raises(youtube_service.YouTubeError) as fout:
        await youtube_service.upload(
            session, owner.id, file_name="x.mp4", title="X", settings=instellingen()
        )

    assert fout.value.status_code == 409
    assert "Koppel" in fout.value.message


async def test_een_echte_upload_gaat_in_twee_stappen(
    client: AsyncClient, owner: User, session, met_google, tmp_path
) -> None:
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "aflevering-12.mp4").write_bytes(b"dit is een film")

    met_google(instellingen(), google_routes())
    await koppel(client, owner, session)

    settings = instellingen(youtube_video_dir=str(videos))
    met_google(settings, upload_routes())

    video = await youtube_service.upload(
        session,
        owner.id,
        file_name="aflevering-12.mp4",
        title="Aflevering 12",
        description="De twaalfde",
        settings=settings,
        provider=YouTubeProvider(oauth_factory=lambda: youtube_service.oauth_for(settings)),
    )

    assert video.external_id == "vid-1"
    assert video.url == "https://www.youtube.com/watch?v=vid-1"
    # Privé, tenzij iemand er expliciet iets anders van maakt. Een verkeerde upload die
    # meteen openbaar is, is niet meer terug te nemen.
    assert video.privacy == "private"

    acties = (await session.execute(select(ActivityLogEntry.action))).scalars().all()
    assert ActivityAction.YOUTUBE_UPLOAD_STARTED in acties
    assert ActivityAction.YOUTUBE_UPLOAD_COMPLETED in acties


async def test_een_mislukte_upload_komt_in_het_logboek(
    client: AsyncClient, owner: User, session, met_google, tmp_path
) -> None:
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "kapot.mp4").write_bytes(b"film")

    met_google(instellingen(), google_routes())
    await koppel(client, owner, session)

    settings = instellingen(youtube_video_dir=str(videos))

    def stuk(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})
        return httpx.Response(500, json={"error": "server"})

    met_google(settings, stuk)

    with pytest.raises(youtube_service.YouTubeError):
        await youtube_service.upload(
            session,
            owner.id,
            file_name="kapot.mp4",
            title="Kapot",
            settings=settings,
            provider=YouTubeProvider(oauth_factory=lambda: youtube_service.oauth_for(settings)),
        )

    acties = (await session.execute(select(ActivityLogEntry.action))).scalars().all()
    assert ActivityAction.YOUTUBE_UPLOAD_FAILED in acties
