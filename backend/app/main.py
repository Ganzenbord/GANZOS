"""De FastAPI-applicatie."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, dashboard, finance, platform, social, todos, uploads
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ganz")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


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

for module in (auth, dashboard, platform, todos, finance, social, uploads):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}
