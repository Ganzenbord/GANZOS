"""Testopzet.

De omgevingsvariabelen worden gezet vóórdat de app wordt geïmporteerd: `config.py`
leest ze één keer en cachet het resultaat. Elke test krijgt een verse SQLite-database,
zodat tests elkaar niet kunnen beïnvloeden.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP_DB = Path(tempfile.mkdtemp(prefix="ganz-test-")) / "test.db"
os.environ["GANZ_ENVIRONMENT"] = "test"
os.environ["GANZ_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["GANZ_SCHEDULER_ENABLED"] = "false"
os.environ["GANZ_SECRET_KEY"] = "test-secret"
os.environ["GANZ_ENCRYPTION_KEY"] = "8sT2Yb0Vc9kQpLmXnZaWdEfGhIjKlMnOpQrStUvWxYz="

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.models.confirmation import (  # noqa: E402
    ConfirmationMethod,
    ConfirmationRequest,
    ConfirmationStatus,
)
from app.models.user import TIER_LIMITED, TIER_OWNER, TIER_TRUSTED  # noqa: E402
from tests.voicefakes import BROER, BUURVROUW, STEF, FakeEncoder  # noqa: E402
from app.core.security import create_token, hash_password  # noqa: E402


@pytest.fixture
async def database():
    """Elke test zijn eigen verbinding, opgeruimd als hij klaar is."""
    db = Database.from_url(os.environ["GANZ_DATABASE_URL"])
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield db
    finally:
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await db.dispose()


@pytest.fixture
async def session(database):
    async with database.session() as db:
        yield db


async def _make_user(db, email: str, tier: int) -> User:
    user = User(
        email=email,
        display_name=email.split("@")[0].title(),
        password_hash=hash_password("geheim123"),
        tier=tier,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
async def owner(session) -> User:
    return await _make_user(session, "stef@example.com", TIER_OWNER)


@pytest.fixture
async def trusted(session) -> User:
    return await _make_user(session, "hulp@example.com", TIER_TRUSTED)


@pytest.fixture
async def limited(session) -> User:
    return await _make_user(session, "gast@example.com", TIER_LIMITED)


@pytest.fixture
def encoder() -> FakeEncoder:
    """Drie stemmen die de tests kunnen gebruiken; alles daarbuiten is een vreemde."""
    namaak = FakeEncoder()
    for marker in (STEF, BROER, BUURVROUW):
        namaak.teach(marker)
    return namaak


@pytest.fixture
async def app(database, encoder):
    """De echte app, met de database van de test erin. Niets hoeft te worden vervangen."""
    application = create_app(
        settings=get_settings(), database=database, speaker_encoder=encoder
    )
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api") as http:
        yield http


def auth_headers(user: User, confirm: bool = False) -> dict[str, str]:
    """Let op: `confirm=True` kan hier niet meer.

    Een bevestiging is sinds fase 2 een rij in `confirmation_requests`, niet alleen een
    token — zodat je achteraf kunt zien dát er bevestigd is, en dezelfde bevestiging niet
    twee keer gebruikt kan worden. Gebruik `await confirm_headers(session, user, key)`.
    """
    if confirm:
        raise AssertionError(
            "Gebruik confirm_headers(session, user, permission_key) in plaats van "
            "auth_headers(..., confirm=True)."
        )
    return {"Authorization": f"Bearer {create_token(user.id, 'access', origin='password')}"}


async def confirm_headers(
    session, user: User, permission_key: str | None = None, *, origin: str = "password"
) -> dict[str, str]:
    """Een inlogtoken plus een echte, bevestigde ConfirmationRequest."""
    verzoek = ConfirmationRequest(
        user_id=user.id,
        permission_key=permission_key,
        method=ConfirmationMethod.PASSWORD.value,
        status=ConfirmationStatus.CONFIRMED.value,
        origin=origin,
        origin_confidence=1.0 if origin == "voice" else None,
        confirmed_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    session.add(verzoek)
    await session.commit()
    headers = auth_headers(user)
    headers["X-Ganz-Confirmation"] = create_token(user.id, "confirmation", cr=verzoek.id)
    return headers
