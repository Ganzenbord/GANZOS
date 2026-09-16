"""Databaseverbinding. Eén async engine en sessiemaker voor de hele applicatie."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

# SQLite (gebruikt door de tests) kent geen connection pool met deze opties.
_engine_kwargs: dict[str, object] = {"echo": False, "future": True}
if not _settings.database_url.startswith("sqlite"):
    _engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)

engine = create_async_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
