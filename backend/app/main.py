"""De FastAPI-applicatie.

`create_app()` bouwt hem. Wie hem aanroept bepaalt welke instellingen en welke database
erin gaan, dus een test hoeft niets te vervangen wat er al staat. De regel onderaan is er
voor `uvicorn app.main:app`; die legt zelf nog geen verbinding aan — dat gebeurt pas bij
het opstarten (de lifespan).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
# Let op: `app.api.integrations` (dit endpoint) en `app.integrations` (de partijen waar
# Ganz mee praat) zijn twee verschillende dingen. Vandaar de andere naam hier.
from app.api import integrations as integrations_api
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
from app.utils.redact import SecretFilter
from app.workers.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ganz")


def install_secret_filter() -> None:
    """Hangt de schoonmaak aan elke logregel die deze machine verlaat.

    Aan de *handlers* en niet aan de loggers: een filter op een logger geldt alleen voor
    regels die via díé logger binnenkomen, niet voor wat er van onderliggende loggers
    doorheen komt. Een filter op de handler ziet alles wat er daadwerkelijk wordt
    weggeschreven — ook dat van sqlalchemy en uvicorn, en ook naar een bestand of een
    bewakingsdienst die er later bij komt.
    """
    filter = SecretFilter()
    handlers = list(logging.getLogger().handlers)
    for naam in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error"):
        handlers.extend(logging.getLogger(naam).handlers)
    for handler in handlers:
        if not any(isinstance(f, SecretFilter) for f in handler.filters):
            handler.addFilter(filter)

API_MODULES = (
    auth,
    dashboard,
    integrations_api,
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

    install_secret_filter()

    @app.exception_handler(Exception)
    async def onverwachte_fout(request: Request, exc: Exception) -> JSONResponse:
        """Een fout die niemand had voorzien, zonder de binnenkant naar buiten te dragen.

        Een stack trace vertelt de client welke bibliotheken je draait, hoe je paden heten en
        soms wat er in een variabele stond. Dat hoort aan de serverkant te blijven. Wat de
        client wel krijgt is een kenmerk: daarmee wijs je in het logboek precies deze fout
        aan, zonder dat het kenmerk zelf iets prijsgeeft.
        """
        kenmerk = uuid.uuid4().hex[:8]
        logger.exception("Onverwachte fout %s bij %s %s", kenmerk, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "Er ging iets mis aan de kant van Ganz. In het logboek staat deze fout "
                    f"onder kenmerk {kenmerk}."
                ),
                "reference": kenmerk,
            },
        )

    # /health staat buiten het API-voorvoegsel: een monitor moet hem op een vaste plek vinden.
    app.include_router(health.router)
    for module in API_MODULES:
        app.include_router(module.router, prefix=settings.api_prefix)

    return app


app = create_app()
