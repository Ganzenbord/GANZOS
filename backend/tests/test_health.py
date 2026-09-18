"""/health moet de database echt aanspreken, niet alleen "ok" roepen."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.database import Database
from app.main import create_app


async def test_health_geeft_200_met_werkende_database(client: AsyncClient) -> None:
    # De client praat met /api ervoor; /health staat er met opzet buiten.
    antwoord = await client.get("http://test/health")

    assert antwoord.status_code == 200
    body = antwoord.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["environment"] == "test"
    assert body["detail"] is None


async def test_health_geeft_503_als_de_database_niet_bereikbaar_is() -> None:
    # Een pad dat niet bestaat: SQLite kan het bestand niet openen.
    kapot = Database.from_url("sqlite+aiosqlite:////bestaat-niet/ganz.db")
    app = create_app(settings=get_settings(), database=kapot)

    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as http:
                antwoord = await http.get("/health")
    finally:
        await kapot.dispose()

    assert antwoord.status_code == 503
    body = antwoord.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert "database" in body["detail"].lower()


async def test_een_platliggende_postgres_geeft_ook_503() -> None:
    """Een geweigerde verbinding komt als kale OSError binnen, niet als SQLAlchemy-fout.

    Vangen we alleen SQLAlchemyError, dan geeft /health een 500 precies wanneer je hem
    nodig hebt. Deze test houdt vast dat het een 503 blijft.
    """
    from app.core.database import get_session

    class WeigerendeSessie:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise ConnectionRefusedError(111, "Connect call failed ('127.0.0.1', 5432)")

    async def geweigerd():
        yield WeigerendeSessie()

    database = Database.from_url("sqlite+aiosqlite://")
    app = create_app(settings=get_settings(), database=database)
    app.dependency_overrides[get_session] = geweigerd

    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as http:
                antwoord = await http.get("/health")
    finally:
        await database.dispose()

    assert antwoord.status_code == 503
    assert antwoord.json()["database"] == "unavailable"
