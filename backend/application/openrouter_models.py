"""Application service for OpenRouter model discovery and filtering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from backend.adapters.openrouter.client import OpenRouterClient, OpenRouterModelDiscoveryError
from backend.config import get_settings
from backend.domain import OpenRouterModelsResponse, OpenRouterModelSummary
from backend.storage.repository import Repository


LOGGER = logging.getLogger(__name__)
_CACHE_PROVIDER = "openrouter"


@dataclass(frozen=True)
class OpenRouterModelCatalogSnapshot:
    """One normalized OpenRouter catalog snapshot used across one validation/execution step."""

    endpoint: str
    cached: bool
    models: tuple[OpenRouterModelSummary, ...]

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(model.id for model in self.models)

    @property
    def total(self) -> int:
        return len(self.models)


@dataclass(frozen=True)
class OpenRouterModelSelectionValidation:
    """Validation result for a selected set of OpenRouter model ids."""

    selected_models: list[str]
    unavailable_model_ids: list[str]
    catalog: OpenRouterModelCatalogSnapshot


def list_openrouter_models(
    *,
    repository: Repository,
    q: str | None = None,
    modality: str | None = None,
    max_price_prompt: float | None = None,
    max_price_completion: float | None = None,
    min_context_length: int | None = None,
) -> OpenRouterModelsResponse:
    """Return normalized OpenRouter models with optional local filtering."""

    catalog = load_openrouter_model_catalog_snapshot(repository=repository)
    models = list(catalog.models)

    filtered = [
        model
        for model in models
        if _matches_query(model, q=q)
        and _matches_modality(model, modality=modality)
        and _matches_max_price(model.prompt_price, ceiling=max_price_prompt)
        and _matches_max_price(model.completion_price, ceiling=max_price_completion)
        and _matches_min_context(model, minimum=min_context_length)
    ]
    filtered.sort(key=lambda item: (item.name.lower(), item.id.lower()))
    return OpenRouterModelsResponse(models=filtered, total=len(filtered), cached=catalog.cached)


def load_openrouter_model_catalog_snapshot(
    *,
    repository: Repository,
) -> OpenRouterModelCatalogSnapshot:
    """Load the current normalized OpenRouter catalog snapshot."""

    payload, cached = _load_or_refresh_cached_models(repository=repository)
    models = tuple(
        OpenRouterModelSummary.model_validate(item)
        for item in payload.get("models", [])
        if isinstance(item, dict)
    )
    return OpenRouterModelCatalogSnapshot(
        endpoint=get_settings().openrouter.model_discovery_endpoint,
        cached=cached,
        models=models,
    )


def resolve_openrouter_model_selection(
    *,
    repository: Repository,
    selected_models: list[str],
) -> OpenRouterModelSelectionValidation:
    """Resolve and validate selected model ids against the current discovered catalog."""

    normalized = _normalize_selected_models(selected_models)
    catalog = load_openrouter_model_catalog_snapshot(repository=repository)
    unavailable = [model_id for model_id in normalized if model_id not in catalog.ids]
    LOGGER.info(
        "OpenRouter selection validation endpoint=%s cached=%s selected=%s catalog_size=%s unavailable=%s",
        catalog.endpoint,
        catalog.cached,
        normalized,
        catalog.total,
        unavailable,
    )
    return OpenRouterModelSelectionValidation(
        selected_models=normalized,
        unavailable_model_ids=unavailable,
        catalog=catalog,
    )


def validate_openrouter_model_selection(
    *,
    repository: Repository,
    selected_models: list[str],
) -> list[str]:
    """Validate model ids against the current discovered catalog."""

    validation = resolve_openrouter_model_selection(
        repository=repository,
        selected_models=selected_models,
    )
    if validation.unavailable_model_ids:
        raise ValueError(
            "Selected OpenRouter models are unavailable in the current catalog: "
            f"{', '.join(validation.unavailable_model_ids)}"
        )
    return validation.selected_models


def _load_or_refresh_cached_models(*, repository: Repository) -> tuple[dict[str, Any], bool]:
    settings = get_settings().openrouter
    cache_key = f"models:{settings.model_discovery_endpoint}"
    ttl_seconds = max(0, settings.model_discovery_ttl_seconds)

    stale_payload: dict[str, Any] | None = None
    stale_expiry: datetime | None = None
    if ttl_seconds > 0:
        stale_payload, stale_expiry = repository.peek_cache_payload(_CACHE_PROVIDER, cache_key)
        if stale_payload is not None and (stale_expiry is None or stale_expiry > datetime.now(timezone.utc)):
            cached_models = stale_payload.get("models", [])
            LOGGER.info(
                "OpenRouter model discovery cache hit endpoint=%s models=%s",
                settings.model_discovery_endpoint,
                len(cached_models) if isinstance(cached_models, list) else 0,
            )
            return stale_payload, True
        LOGGER.info("OpenRouter model discovery cache miss endpoint=%s", settings.model_discovery_endpoint)

    LOGGER.info("OpenRouter model discovery fetch start endpoint=%s", settings.model_discovery_endpoint)
    try:
        normalized_models = _fetch_models_from_upstream()
    except OpenRouterModelDiscoveryError as exc:
        if stale_payload is not None:
            cached_models = stale_payload.get("models", [])
            LOGGER.warning(
                "OpenRouter model discovery refresh failed; serving cached models endpoint=%s models=%s",
                settings.model_discovery_endpoint,
                len(cached_models) if isinstance(cached_models, list) else 0,
            )
            return stale_payload, True
        LOGGER.warning(
            "OpenRouter model discovery failed without cached fallback endpoint=%s status_code=%s",
            settings.model_discovery_endpoint,
            exc.status_code,
        )
        raise

    payload = {
        "models": [item.model_dump(mode="json") for item in normalized_models],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if ttl_seconds > 0:
        repository.set_cache_payload(
            _CACHE_PROVIDER,
            cache_key,
            payload,
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
    LOGGER.info(
        "OpenRouter model discovery returned endpoint=%s models=%s",
        settings.model_discovery_endpoint,
        len(normalized_models),
    )
    return payload, False


def _fetch_models_from_upstream() -> list[OpenRouterModelSummary]:
    settings = get_settings().openrouter
    client = OpenRouterClient.from_settings()
    # Prefer /models/user so the picker reflects the configured account's provider
    # preferences, privacy settings, and guardrails instead of the global catalog.
    raw_models = client.list_models(user_scoped=settings.model_discovery_endpoint == "user")
    normalized = [_normalize_openrouter_model(item) for item in raw_models]
    normalized.sort(key=lambda item: (item.name.lower(), item.id.lower()))
    return normalized


def _normalize_selected_models(selected_models: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in selected_models:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _normalize_openrouter_model(payload: dict[str, Any]) -> OpenRouterModelSummary:
    pricing = payload.get("pricing") if isinstance(payload.get("pricing"), dict) else {}
    architecture = payload.get("architecture") if isinstance(payload.get("architecture"), dict) else {}
    top_provider = payload.get("top_provider") if isinstance(payload.get("top_provider"), dict) else {}

    model_id = _as_non_empty_string(payload.get("id")) or _as_non_empty_string(payload.get("canonical_slug")) or "unknown"
    canonical_slug = _as_non_empty_string(payload.get("canonical_slug"))
    provider = _provider_from_model_id(canonical_slug or model_id)
    input_modalities = _normalize_string_list(architecture.get("input_modalities"))
    output_modalities = _normalize_string_list(architecture.get("output_modalities"))

    return OpenRouterModelSummary(
        id=model_id,
        name=_as_non_empty_string(payload.get("name")) or canonical_slug or model_id,
        description=_as_non_empty_string(payload.get("description")),
        context_length=(
            _as_int(payload.get("context_length"))
            or _as_int(top_provider.get("context_length"))
        ),
        prompt_price=_as_float(pricing.get("prompt")),
        completion_price=_as_float(pricing.get("completion")),
        request_price=_as_float(pricing.get("request")),
        image_price=_as_float(pricing.get("image")),
        provider=provider,
        canonical_slug=canonical_slug,
        modality=_as_non_empty_string(architecture.get("modality")),
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        supported_parameters=_normalize_string_list(payload.get("supported_parameters")),
        is_moderated=_as_bool(top_provider.get("is_moderated")),
        max_completion_tokens=_as_int(top_provider.get("max_completion_tokens")),
        created=_as_int(payload.get("created")),
    )


def _matches_query(model: OpenRouterModelSummary, *, q: str | None) -> bool:
    if not q:
        return True
    needle = q.strip().lower()
    if not needle:
        return True
    haystacks = [model.id, model.name, model.description or ""]
    return any(needle in item.lower() for item in haystacks)


def _matches_modality(model: OpenRouterModelSummary, *, modality: str | None) -> bool:
    if not modality:
        return True

    requested = modality.strip().lower()
    if not requested or requested == "all":
        return True

    all_modalities = set(model.input_modalities) | set(model.output_modalities)
    text_only = all_modalities.issubset({"text"}) and bool(all_modalities)
    multimodal = len(all_modalities) > 1 or ("image" in all_modalities and "text" in all_modalities)

    if requested in {"text", "text_only", "text-only"}:
        return text_only
    if requested in {"vision", "image"}:
        return "image" in all_modalities
    if requested == "audio":
        return "audio" in all_modalities
    if requested == "multimodal":
        return multimodal
    if requested == (model.modality or "").lower():
        return True
    return requested in all_modalities


def _matches_max_price(value: float | None, *, ceiling: float | None) -> bool:
    if ceiling is None:
        return True
    if value is None:
        return False
    return value <= ceiling


def _matches_min_context(model: OpenRouterModelSummary, *, minimum: int | None) -> bool:
    if minimum is None:
        return True
    if model.context_length is None:
        return False
    return model.context_length >= minimum


def _provider_from_model_id(model_id: str) -> str | None:
    provider, _, _ = model_id.partition("/")
    cleaned = provider.strip()
    if not cleaned:
        return None
    return cleaned.replace("-", " ").title()


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _as_non_empty_string(item)
        if cleaned is None or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _as_non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    parsed: float | None = None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
    if parsed is None:
        return None
    # OpenRouter may use negative sentinel values for unavailable pricing.
    # Treat them as missing metadata rather than propagating invalid prices.
    if parsed < 0:
        return None
    return parsed


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None
