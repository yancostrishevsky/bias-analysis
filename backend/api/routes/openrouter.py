"""OpenRouter metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.adapters.openrouter.client import OpenRouterModelDiscoveryError
from backend.application.openrouter_models import list_openrouter_models
from backend.domain import OpenRouterModelsResponse
from backend.storage.repository import Repository, get_repository


router = APIRouter(prefix="/openrouter", tags=["openrouter"])


def _repository() -> Repository:
    return get_repository()


@router.get("/models", response_model=OpenRouterModelsResponse)
def get_openrouter_models(
    q: str | None = None,
    modality: str | None = None,
    max_price_prompt: float | None = None,
    max_price_completion: float | None = None,
    min_context_length: int | None = None,
) -> OpenRouterModelsResponse:
    """Return normalized, optionally filtered OpenRouter model metadata."""

    try:
        return list_openrouter_models(
            repository=_repository(),
            q=q,
            modality=modality,
            max_price_prompt=max_price_prompt,
            max_price_completion=max_price_completion,
            min_context_length=min_context_length,
        )
    except OpenRouterModelDiscoveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenRouter models are temporarily unavailable. Check the configured API key and try again.",
        ) from exc
