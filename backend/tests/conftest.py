"""Testopzet.

De omgevingsvariabelen worden gezet vóórdat de app wordt geïmporteerd: `config.py`
leest ze één keer en cachet het resultaat. Elke test krijgt een verse SQLite-database,
zodat tests elkaar niet kunnen beïnvloeden.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.mkdtemp(prefix="ganz-test-")) / "test.db"
os.environ["GANZ_ENVIRONMENT"] = "test"
os.environ["GANZ_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["GANZ_SCHEDULER_ENABLED"] = "false"
os.environ["GANZ_SECRET_KEY"] = "test-secret"
os.environ["GANZ_ENCRYPTION_KEY"] = "8sT2Yb0Vc9kQpLmXnZaWdEfGhIjKlMnOpQrStUvWxYz="

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.database import SessionLocal, engine, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.models.user import TIER_LIMITED, TIER_OWNER, TIER_TRUSTED  # noqa: E402
from app.security import create_token, hash_password  # noqa: E402


@pytest.fixture(autouse=True)
async def fresh_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def session():
    async with SessionLocal() as db:
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
async def client():
    """Deelt de sessie van de test, zodat wat de test schrijft ook zichtbaar is."""

    async def override():
        async with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api") as http:
        yield http
    app.dependency_overrides.clear()


def auth_headers(user: User, confirm: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_token(user.id, 'access')}"}
    if confirm:
        headers["X-Ganz-Confirmation"] = create_token(user.id, "confirmation")
    return headers
