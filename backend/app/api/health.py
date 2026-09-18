"""/health — leeft de app, en doet de database het ook?

Vroeger gaf dit altijd "ok", ook met een database die plat lag. Dan zegt de monitor dat
alles goed gaat terwijl niets werkt. Nu wordt de verbinding echt aangesproken.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.database import SessionDep

logger = logging.getLogger("ganz.health")

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(
        description="ok = alles draait; degraded = de app leeft maar de database niet"
    )
    environment: str
    database: Literal["ok", "unavailable"]
    detail: str | None = Field(default=None, description="Uitleg in gewone taal bij een probleem")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Controleer of de app en de database bereikbaar zijn",
    responses={503: {"model": HealthResponse, "description": "De database antwoordt niet"}},
)
async def health(request: Request, session: SessionDep, response: Response) -> HealthResponse:
    omgeving = request.app.state.settings.environment
    try:
        # De verbinding zelf aanspreken, niet een tabel: dit werkt ook vóór de eerste migratie.
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        # Met opzet alles opvangen: een platliggende Postgres komt niet als nette
        # SQLAlchemy-fout binnen maar als kale ConnectionRefusedError uit asyncpg. Vangen we
        # alleen SQLAlchemyError, dan geeft /health een 500 precies wanneer je hem nodig hebt.
        logger.warning("Databasecontrole mislukt (%s): %s", type(exc).__name__, exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded",
            environment=omgeving,
            database="unavailable",
            detail="Geen verbinding met de database. Draait PostgreSQL?",
        )

    return HealthResponse(status="ok", environment=omgeving, database="ok")
