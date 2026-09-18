"""De FastAPI-applicatie.

`create_app()` bouwt hem. Wie hem aanroept bepaalt welke instellingen en welke database
erin gaan, dus een test hoeft niets te vervangen wat er al staat. De regel onderaan is er
voor `uvicorn app.main:app`; die legt zelf nog geen verbinding aan — dat gebeurt pas bij
het opstarten (de lifespan).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth,
    dashboard,
    finance,
    health,
    platform,
    skills,
    social,
    status,
    todos,
    uploads,
    voice,
    youtube,
)
from app.core.config import Settings, get_settings
from app.core.database import Database, create_database
from app.integrations.voice import SpeakerEncoder, SpeechBrainEncoder
from app.services.skill_executor import SkillExecutor
from app.services.skill_matcher import (
    EmbeddingMatcher,
    FallbackMatcher,
    LexicalMatcher,
    SkillMatcher,
)
from app.workers.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ganz")

API_MODULES = (
    auth,
    dashboard,
    platform,
    todos,
    finance,
    social,
    uploads,
    voice,
    skills,
    status,
    youtube,
)


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    speaker_encoder: SpeakerEncoder | None = None,
    skill_matcher: SkillMatcher | None = None,
    skill_executor: SkillExecutor | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    # Een meegegeven database is van de aanroeper; die ruimt hem zelf op.
    beheert_database = database is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.database = database or create_database(settings)
        # Het model wordt hier nog niet geladen; dat gebeurt pas bij het eerste gebruik,
        # anders duurt opstarten minuten voor iets wat misschien niet nodig is.
        app.state.speaker_encoder = speaker_encoder or SpeechBrainEncoder(
            model_name=settings.voice_model, cache_dir=settings.voice_model_cache_dir
        )
        app.state.skill_executor = skill_executor or SkillExecutor()
        # Matchen op betekenis als het model er is, anders op woorden. Welke van de twee het
        # werd staat in elke uitslag, dus je ziet het meteen.
        app.state.skill_matcher = skill_matcher or FallbackMatcher(
            EmbeddingMatcher(settings.skill_model, settings.skill_model_cache_dir),
            LexicalMatcher(),
        )
        start_scheduler(app.state.database, settings=settings)
        logger.info("Ganz gestart in omgeving %s", settings.environment)
        try:
            yield
        finally:
            shutdown_scheduler()
            if beheert_database:
                await app.state.database.dispose()

    app = FastAPI(
        title="Ganz Command Center",
        version="2.0.0",
        description="Persoonlijk AI Command Center: to-do, finance, social en uploads.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # /health staat buiten het API-voorvoegsel: een monitor moet hem op een vaste plek vinden.
    app.include_router(health.router)
    for module in API_MODULES:
        app.include_router(module.router, prefix=settings.api_prefix)

    return app


app = create_app()
