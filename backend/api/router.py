"""Top-level API router."""

from fastapi import APIRouter

from backend.api.routes.health import router as health_router
from backend.api.routes.openrouter import router as openrouter_router
from backend.api.routes.runs import router as runs_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(openrouter_router)
api_router.include_router(runs_router)
