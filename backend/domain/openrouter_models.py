"""Domain DTOs for OpenRouter model discovery."""

from __future__ import annotations

from pydantic import Field

from backend.domain.models import DomainModel


class OpenRouterModelSummary(DomainModel):
    """Frontend-facing normalized OpenRouter model metadata."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    context_length: int | None = Field(default=None, ge=0)
    prompt_price: float | None = Field(default=None, ge=0)
    completion_price: float | None = Field(default=None, ge=0)
    request_price: float | None = Field(default=None, ge=0)
    image_price: float | None = Field(default=None, ge=0)
    provider: str | None = None
    canonical_slug: str | None = None
    modality: str | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    supported_parameters: list[str] = Field(default_factory=list)
    is_moderated: bool | None = None
    max_completion_tokens: int | None = Field(default=None, ge=0)
    created: int | None = Field(default=None, ge=0)


class OpenRouterModelsResponse(DomainModel):
    """OpenRouter model list response exposed to the frontend."""

    models: list[OpenRouterModelSummary] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    cached: bool = False
