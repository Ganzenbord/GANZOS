"""De databaseverbinding, verpakt in een object in plaats van in modulevariabelen.

Eerder stonden `engine` en `SessionLocal` los in deze module. Dat werkt, maar het betekent
dat het hele programma één verbinding deelt die al bij het importeren wordt aangelegd: een
test kan er dan niet omheen, twee apps naast elkaar zitten elkaar in de weg, en bij het
afsluiten blijft er van alles openstaan. Nu maakt `create_app()` er één en zet die klaar in
`app.state`; endpoints krijgen hun sessie via Depends.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def from_url(cls, url: str, **engine_kwargs: Any) -> Database:
        opties: dict[str, Any] = {"echo": False, "future": True}
        if not url.startswith("sqlite"):
            # SQLite (de tests) kent deze poolopties niet.
            opties.update(pool_size=10, max_overflow=20, pool_pre_ping=True)
        opties.update(engine_kwargs)

        engine = create_async_engine(url, **opties)
        if engine.dialect.name == "sqlite":
            _enforce_sqlite_foreign_keys(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        return cls(engine=engine, session_factory=factory)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Eén sessie, die bij een fout netjes terugdraait in plaats van half blijft staan."""
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()


def create_database(settings: Settings | None = None) -> Database:
    return Database.from_url((settings or get_settings()).database_url)


def get_database(request: Request) -> Database:
    """De verbinding staat klaar in app.state, gezet door de lifespan van create_app()."""
    return request.app.state.database


DatabaseDep = Annotated[Database, Depends(get_database)]


async def get_session(database: DatabaseDep) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _enforce_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """SQLite negeert foreign keys tenzij je er per verbinding om vraagt.

    Zonder dit doet een ON DELETE CASCADE in de tests niets, terwijl hij op Postgres wél
    werkt — en dan slaagt een test die juist dat zou moeten bewaken.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
