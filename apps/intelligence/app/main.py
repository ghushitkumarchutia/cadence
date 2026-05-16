from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import close_connections, get_db_pool, get_redis
from app.api.routes import health, replay, scoring
from app.infrastructure import CORS_ORIGINS

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("intelligence_service_starting")
    await get_redis()
    await get_db_pool()
    logger.info("intelligence_service_ready")
    yield
    await close_connections()
    logger.info("intelligence_service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cadence Intelligence Service",
        description="Feature extraction, drift scoring, and baseline computation",
        version="1.0.0",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(scoring.router)
    app.include_router(replay.router)

    return app


app = create_app()
