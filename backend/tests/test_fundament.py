"""Het fundament: geen globale databasestate, en de nieuwe tabellen doen wat ze moeten."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

import app.core.database as database_module
from app.core.database import Database
from app.models import User, Video, VideoStatus, VoiceProfile


def test_de_module_houdt_geen_verbinding_vast() -> None:
    """Vroeger stonden `engine` en `SessionLocal` los in database.py.

    Dan deelt het hele programma één verbinding die bij het importeren al is aangelegd, en
    kan een test daar niet omheen. Deze test legt vast dat dat niet terugsluipt.
    """
    assert not hasattr(database_module, "engine")
    assert not hasattr(database_module, "SessionLocal")


async def test_de_app_zet_zijn_database_klaar_in_state(app: FastAPI, database: Database) -> None:
    assert app.state.database is database
    assert app.state.settings.environment == "test"


async def test_een_stemprofiel_hoort_bij_een_gebruiker(database: Database, owner: User) -> None:
    async with database.session() as session:
        session.add(
            VoiceProfile(
                user_id=owner.id,
                label="Opname 1",
                embedding=[0.1, 0.2, 0.3],
                embedding_model="test-encoder",
                embedding_dim=3,
                sample_seconds=2.5,
            )
        )
        await session.commit()

    async with database.session() as session:
        opgehaald = await session.scalar(
            select(User).where(User.id == owner.id).options(selectinload(User.voice_profiles))
        )
        assert [p.label for p in opgehaald.voice_profiles] == ["Opname 1"]
        assert opgehaald.voice_profiles[0].embedding == [0.1, 0.2, 0.3]
        assert opgehaald.voice_profiles[0].active is True


async def test_een_video_begint_als_concept(database: Database, owner: User) -> None:
    async with database.session() as session:
        video = Video(user_id=owner.id, title="Aflevering 12 — short 1")
        session.add(video)
        await session.commit()
        assert video.status == VideoStatus.DRAFT.value
        assert video.meta == {}
        assert video.published_at is None


async def test_een_gebruiker_verwijderen_neemt_stem_en_video_mee(
    database: Database, owner: User
) -> None:
    async with database.session() as session:
        session.add(VoiceProfile(user_id=owner.id, label="Opname 1"))
        session.add(Video(user_id=owner.id, title="Weg hiermee"))
        await session.commit()

    async with database.session() as session:
        gebruiker = await session.get(User, owner.id)
        await session.delete(gebruiker)
        await session.commit()

    async with database.session() as session:
        stemmen = await session.scalar(select(func.count()).select_from(VoiceProfile))
        videos = await session.scalar(select(func.count()).select_from(Video))
        assert stemmen == 0
        assert videos == 0


async def test_tijdstippen_komen_er_met_tijdzone_uit(database: Database, owner: User) -> None:
    """Op SQLite gaf een datum vroeger een kale datetime terug, op Postgres niet.

    Vergelijk je die met een tijdstip dat wél een tijdzone heeft, dan klapt Python eruit —
    en dan alleen op één van de twee. `UtcDateTime` maakt dat verschil onzichtbaar.
    """
    async with database.session() as session:
        opnieuw = await session.get(User, owner.id)
        assert opnieuw.created_at.tzinfo is not None
        assert opnieuw.updated_at.utcoffset().total_seconds() == 0
