"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import api_router
from backend.config import get_settings, load_env_file
from backend.storage import get_database


LOGGER = logging.getLogger(__name__)


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_env_file()
    settings = get_settings()
    _configure_logging(settings.log_level)
    get_database()
    LOGGER.info(
        "Starting Bias Analysis API env=%s database_path=%s run_artifacts_dir=%s run_artifacts_enabled=%s",
        settings.app_env,
        settings.database.path,
        settings.run_artifacts.path,
        settings.run_artifacts.enabled,
    )
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    load_env_file()
    settings = get_settings()
    app = FastAPI(title="Bias Analysis API", lifespan=lifespan)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(api_router)
    return app


app = create_app()
