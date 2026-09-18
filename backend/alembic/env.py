"""Alembic-omgeving, async."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base  # noqa: F401 - importeert alle tabellen
from app.models.base import UtcDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # -x db_url=... wint, daarna de instellingen. Zo kun je een migratie op een
    # testdatabase draaien zonder de omgeving aan te passen.
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    return override or get_settings().database_url


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Schrijf eigen kolomtypes uit als gewoon SQLAlchemy.

    `UtcDateTime` is alleen een vertaling aan de Python-kant; in de database is het een
    doodgewone timestamp met tijdzone. Zonder dit zet autogenerate `app.models.base.UtcDateTime`
    in de migratie, en struikelt die bij het draaien over een import die er niet staat —
    een fout die je pas ziet als je de migratie echt uitvoert.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), future=True)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
