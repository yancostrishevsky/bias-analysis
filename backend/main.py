"""FastAPI application entrypoint."""

from fastapi import FastAPI

from backend.api.router import api_router
from backend.config import load_env_file
from backend.storage import get_database


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    load_env_file()
    get_database()
    app = FastAPI(title="Bias Analysis API")
    app.include_router(api_router)
    return app


app = create_app()
