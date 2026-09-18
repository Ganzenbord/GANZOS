"""Stemherkenning: inschrijven, herkennen, en wat de uitslag waard is."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app
from app.models.user import TIER_OWNER, TIER_TRUSTED, User
from app.utils.audio import AudioError, load_wav
from app.utils.embeddings import (
    Candidate,
    EmbeddingError,
    best_match,
    cosine_similarity,
    l2_normalize,
)
from tests.conftest import auth_headers
from tests.voicefakes import (
    BROER,
    BUURVROUW,
    STEF,
    VREEMDE,
    FakeEncoder,
    KapotteEncoder,
    geen_wav,
    lees_marker,
    maak_wav,
    maak_wav_met_breedte,
)

GRENZEN = {"min_seconds": 1.0, "max_seconds": 30.0}


async def schrijf_in(client: AsyncClient, user_id: int, marker: int, headers=None):
    return await client.post(
        "/voice/enroll",
        data={"user_id": str(user_id)},
        files={"audio": ("opname.wav", maak_wav(marker), "audio/wav")},
        headers=headers or {},
    )


async def laat_herkennen(client: AsyncClient, marker: int, *, variant: int = 1):
    return await client.post(
        "/voice/identify",
        files={"audio": ("opname.wav", maak_wav(marker, variant=variant), "audio/wav")},
    )


# --- Het rekenwerk, los van alles ------------------------------------------


def test_normaliseren_maakt_de_lengte_een() -> None:
    assert l2_normalize([3.0, 4.0]) == pytest.approx([0.6, 0.8])


def test_een_afdruk_van_nullen_wordt_geweigerd() -> None:
    with pytest.raises(EmbeddingError):
        l2_normalize([0.0, 0.0])


def test_harder_praten_geeft_dezelfde_uitslag() -> None:
    assert cosine_similarity([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.0)


def test_afdrukken_van_verschillende_lengte_zijn_niet_te_vergelijken() -> None:
    with pytest.raises(EmbeddingError, match="verschillende lengte"):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_de_best_passende_stem_wint() -> None:
    kandidaten = [
        Candidate(profile_id=1, user_id=1, embedding=[1.0, 0.0, 0.0]),
        Candidate(profile_id=2, user_id=2, embedding=[0.0, 1.0, 0.0]),
    ]
    uitslag = best_match([0.9, 0.1, 0.0], kandidaten, threshold=0.25)

    assert uitslag.matched is True
    assert uitslag.user_id == 1
    assert uitslag.confidence > uitslag.runner_up_confidence


def test_onder_de_drempel_is_het_niemand() -> None:
    uitslag = best_match(
        [0.2, 0.98], [Candidate(profile_id=1, user_id=1, embedding=[1.0, 0.0])], threshold=0.25
    )
    assert uitslag.matched is False
    assert uitslag.user_id is None


def test_afdrukken_van_een_ander_model_worden_overgeslagen() -> None:
    # Een profiel uit een oud model heeft een andere lengte. Dat mag de rest niet ophouden.
    kandidaten = [
        Candidate(profile_id=1, user_id=1, embedding=[1.0, 0.0, 0.0, 0.0, 0.0]),
        Candidate(profile_id=2, user_id=2, embedding=[1.0, 0.0, 0.0]),
    ]
    uitslag = best_match([1.0, 0.0, 0.0], kandidaten, threshold=0.25)

    assert uitslag.matched is True
    assert uitslag.user_id == 2


# --- Het inlezen van een opname ---------------------------------------------


def test_een_gewone_opname_wordt_ingelezen() -> None:
    clip = load_wav(maak_wav(STEF, seconds=2.0), **GRENZEN)

    assert clip.sample_rate == 16_000
    assert clip.seconds == pytest.approx(2.0, abs=0.01)
    assert -1.0 <= clip.samples.min() and clip.samples.max() <= 1.0


def test_stereo_wordt_tot_een_spoor_samengevoegd() -> None:
    stereo = load_wav(maak_wav(STEF, channels=2), **GRENZEN)
    assert lees_marker(stereo) == STEF


def test_een_andere_bemonsteringsfrequentie_mag() -> None:
    clip = load_wav(maak_wav(STEF, sample_rate=44_100), **GRENZEN)
    assert clip.sample_rate == 44_100


@pytest.mark.parametrize(
    ("bytes_", "melding"),
    [
        (b"", "leeg"),
        (geen_wav(), "ffmpeg"),
        (maak_wav_met_breedte(3), "24 bits"),
        (maak_wav(STEF, seconds=0.3), "minstens"),
    ],
)
def test_onbruikbare_opnames_geven_uitleg(bytes_: bytes, melding: str) -> None:
    with pytest.raises(AudioError, match=melding):
        load_wav(bytes_, **GRENZEN)


# --- Inschrijven -------------------------------------------------------------


async def test_de_eerste_inschrijving_mag_zonder_dat_iemand_herkend_is(
    client: AsyncClient, owner: User
) -> None:
    # Anders kom je er nooit in: herkennen kan pas als er iets is om mee te vergelijken.
    antwoord = await schrijf_in(client, owner.id, STEF)

    assert antwoord.status_code == 201
    body = antwoord.json()
    assert body["success"] is True
    assert body["profile"]["embedding_model"] == "test-encoder"
    assert body["profile"]["embedding_dim"] == 8
    assert body["profile"]["enrolled_at"] is not None


async def test_daarna_is_inschrijven_dicht(client: AsyncClient, owner: User) -> None:
    await schrijf_in(client, owner.id, STEF)

    antwoord = await schrijf_in(client, owner.id, BROER)

    assert antwoord.status_code == 401


async def test_inschrijven_lukt_met_het_juiste_recht_en_een_bevestiging(
    client: AsyncClient, owner: User, session
) -> None:
    from tests.conftest import confirm_headers

    await schrijf_in(client, owner.id, STEF)
    headers = await confirm_headers(session, owner, "voice.enroll")

    antwoord = await schrijf_in(client, owner.id, BROER, headers)

    assert antwoord.status_code == 201


async def test_inschrijven_zonder_bevestiging_wordt_geweigerd(
    client: AsyncClient, owner: User
) -> None:
    await schrijf_in(client, owner.id, STEF)

    antwoord = await schrijf_in(client, owner.id, BROER, auth_headers(owner))

    assert antwoord.status_code == 428


async def test_wie_niet_genoeg_rechten_heeft_mag_niet_inschrijven(
    client: AsyncClient, owner: User, trusted: User, session
) -> None:
    from tests.conftest import confirm_headers

    await schrijf_in(client, owner.id, STEF)
    # voice.enroll is TIER_OWNER; trusted is tier 2 en komt er dus niet door.
    headers = await confirm_headers(session, trusted, "voice.enroll")

    antwoord = await schrijf_in(client, trusted.id, BROER, headers)

    assert antwoord.status_code == 403


async def test_inschrijven_op_een_onbekende_gebruiker_geeft_uitleg(client: AsyncClient) -> None:
    antwoord = await schrijf_in(client, 99999, STEF)

    assert antwoord.status_code == 404
    assert "create_user" in antwoord.json()["detail"]


# --- Herkennen ---------------------------------------------------------------


async def test_een_ingeschreven_stem_wordt_herkend(client: AsyncClient, owner: User) -> None:
    await schrijf_in(client, owner.id, STEF)

    body = (await laat_herkennen(client, STEF)).json()

    assert body["result"] == "identified"
    assert body["user_id"] == owner.id
    assert body["tier"] == TIER_OWNER
    assert body["confidence"] >= body["threshold"]
    assert body["access_token"]
    assert body["strong"] is True


async def test_een_andere_opname_van_dezelfde_stem_wordt_ook_herkend(
    client: AsyncClient, owner: User
) -> None:
    await schrijf_in(client, owner.id, STEF)

    assert (await laat_herkennen(client, STEF, variant=42)).json()["user_id"] == owner.id


async def test_een_onbekende_stem_krijgt_geen_token(client: AsyncClient, owner: User) -> None:
    await schrijf_in(client, owner.id, STEF)

    body = (await laat_herkennen(client, VREEMDE)).json()

    assert body["result"] == "unknown"
    assert body["user_id"] is None
    assert body["access_token"] is None


async def test_zonder_ingeschreven_stemmen_is_iedereen_onbekend(client: AsyncClient) -> None:
    body = (await laat_herkennen(client, STEF)).json()

    assert body["result"] == "unknown"
    assert body["confidence"] == 0.0


async def test_het_token_uit_een_stem_werkt_als_gewone_aanmelding(
    client: AsyncClient, owner: User
) -> None:
    await schrijf_in(client, owner.id, STEF)
    token = (await laat_herkennen(client, STEF)).json()["access_token"]

    antwoord = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert antwoord.status_code == 200
    assert antwoord.json()["id"] == owner.id


async def test_een_stem_levert_geen_sessie_op(client: AsyncClient, owner: User, session) -> None:
    """Een opname is zo gemaakt. Zou een stem een vernieuwingstoken opleveren, dan wordt een
    geluidsfragment twee maanden toegang — en dat is precies wat je niet wilt."""
    from sqlalchemy import select
    from app.models.access import UserSession

    await schrijf_in(client, owner.id, STEF)

    body = (await laat_herkennen(client, STEF)).json()

    assert body["access_token"]
    assert "refresh_token" not in body
    assert (await session.scalars(select(UserSession))).first() is None


async def test_iemand_zonder_tier_wordt_herkend_maar_mag_niets(
    client: AsyncClient, owner: User, session
) -> None:
    owner.tier = None
    await session.commit()
    await schrijf_in(client, owner.id, STEF)

    body = (await laat_herkennen(client, STEF)).json()
    assert body["result"] == "identified"
    assert body["tier"] is None
    assert "geen toegang" in body["message"]

    vervolg = await client.get(
        "/voice/profiles", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert vervolg.status_code == 403
    assert "geen toegang" in vervolg.json()["detail"]


async def test_een_stem_van_iemand_op_non_actief_telt_niet_mee(
    client: AsyncClient, owner: User, session
) -> None:
    await schrijf_in(client, owner.id, STEF)
    owner.active = False
    await session.commit()

    assert (await laat_herkennen(client, STEF)).json()["result"] == "unknown"


async def test_de_lijst_met_stemmen_vraagt_om_een_recht(
    client: AsyncClient, owner: User, limited: User
) -> None:
    await schrijf_in(client, owner.id, STEF)

    assert (await client.get("/voice/profiles", headers=auth_headers(owner))).status_code == 200
    # voice.read is TIER_TRUSTED; limited is tier 3.
    assert (await client.get("/voice/profiles", headers=auth_headers(limited))).status_code == 403


async def test_een_onbruikbare_opname_geeft_uitleg_via_de_api(client: AsyncClient) -> None:
    antwoord = await client.post(
        "/voice/identify", files={"audio": ("o.wav", b"geen wav", "audio/wav")}
    )

    assert antwoord.status_code == 422
    assert "ffmpeg" in antwoord.json()["detail"]


async def test_zonder_werkend_model_komt_er_uitleg_in_plaats_van_een_crash(
    database, owner: User
) -> None:
    app = create_app(
        settings=get_settings(), database=database, speaker_encoder=KapotteEncoder()
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test/api") as http:
            antwoord = await laat_herkennen(http, STEF)

    assert antwoord.status_code == 503
    assert "requirements-voice.txt" in antwoord.json()["detail"]


def test_de_namaak_encoder_voldoet_aan_hetzelfde_koppelvlak(encoder: FakeEncoder) -> None:
    from app.integrations.voice import SpeakerEncoder

    # Anders test de suite iets anders dan er in productie draait.
    assert isinstance(encoder, SpeakerEncoder)
    assert isinstance(KapotteEncoder(), SpeakerEncoder)


async def test_de_juiste_van_twee_stemmen_wordt_gekozen(
    client: AsyncClient, owner: User, trusted: User, session
) -> None:
    from tests.conftest import confirm_headers

    await schrijf_in(client, owner.id, STEF)
    headers = await confirm_headers(session, owner, "voice.enroll")
    assert (await schrijf_in(client, trusted.id, BROER, headers)).status_code == 201

    assert (await laat_herkennen(client, STEF)).json()["user_id"] == owner.id
    assert (await laat_herkennen(client, BROER)).json()["user_id"] == trusted.id
    assert (await laat_herkennen(client, BUURVROUW)).json()["result"] == "unknown"
    assert TIER_TRUSTED == trusted.tier
