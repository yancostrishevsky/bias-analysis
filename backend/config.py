"""Environment configuration helpers and typed settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def load_env_file(env_path: Path | None = None) -> None:
    """Load key-value pairs from the repo-root .env file into the environment."""

    path = env_path or DEFAULT_ENV_PATH
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")
        if not separator:
            continue

        cleaned_key = key.strip()
        if not cleaned_key:
            continue

        cleaned_value = _strip_wrapping_quotes(value.strip())
        os.environ.setdefault(cleaned_key, cleaned_value)


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _split_csv(value: str | None, *, default: list[str]) -> list[str]:
    if value is None:
        return list(default)

    items: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        cleaned = part.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items or list(default)


def _bool_from_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    return default


def _float_from_env(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int_from_env(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value


OpenRouterModelValidationState = Literal["healthy", "preview", "deprecated", "custom"]
ScholarlySourceValidationState = Literal["healthy", "requires_configuration", "custom"]


class SettingsModel(BaseModel):
    """Base settings model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OpenRouterModelOption(SettingsModel):
    """Curated metadata for one selectable or historical OpenRouter model id."""

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    family: str = Field(min_length=1)
    description: str | None = None
    recommended: bool = False
    default_enabled: bool = False
    selectable: bool = True
    validation_state: OpenRouterModelValidationState = "healthy"
    validation_reason: str | None = None
    replacement_model_id: str | None = None
    source: Literal["curated", "configured_custom"] = "curated"


class ScholarlySourceOption(SettingsModel):
    """Curated metadata for one scholarly collection source."""

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str | None = None
    selectable: bool = True
    validation_state: ScholarlySourceValidationState = "healthy"
    validation_reason: str | None = None
    credential_required: bool = False


class ProviderSettings(SettingsModel):
    """Configuration for enrichment providers."""

    enabled: bool = True
    timeout_seconds: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    rate_limit_seconds: float = Field(default=0.0, ge=0.0)
    cache_ttl_seconds: int = Field(default=86400, ge=0)
    api_key: str | None = None
    base_url: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class OpenRouterSettings(SettingsModel):
    """Configuration for OpenRouter-backed LLM calls."""

    enabled: bool = True
    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    model_discovery_endpoint: Literal["user", "catalog"] = "user"
    model_discovery_ttl_seconds: int = Field(default=300, ge=0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1400, ge=1)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    default_models: list[str] = Field(default_factory=list)
    available_models: list[str] = Field(default_factory=list)
    model_catalog: list[OpenRouterModelOption] = Field(default_factory=list)
    app_name: str = "bias-analysis"
    site_url: str | None = None

    def model_option(self, model_id: str) -> OpenRouterModelOption | None:
        """Return model metadata by id."""

        for option in self.model_catalog:
            if option.id == model_id:
                return option
        return None


class DatabaseSettings(SettingsModel):
    """SQLite persistence settings."""

    path: Path = Field(default=REPO_ROOT / "data" / "app.db")


class RunArtifactsSettings(SettingsModel):
    """Filesystem settings for per-run debug artifacts."""

    enabled: bool = True
    path: Path = Field(default=REPO_ROOT / "data" / "run_artifacts")
    pretty_json: bool = True


class AppSettings(SettingsModel):
    """Top-level application settings."""

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    cors_allowed_origins: list[str] = Field(default_factory=list)
    database: DatabaseSettings
    run_artifacts: RunArtifactsSettings
    scholarly_sources: list[str] = Field(default_factory=lambda: ["openalex"])
    source_catalog: list[ScholarlySourceOption] = Field(default_factory=list)
    default_run_type: str = "scholarly"
    enrichment_provider_order: list[str] = Field(default_factory=list)
    enabled_enrichment_providers: list[str] = Field(default_factory=list)
    openrouter: OpenRouterSettings
    openalex: ProviderSettings
    semantic_scholar: ProviderSettings
    scopus: ProviderSettings
    core: ProviderSettings

    def source_option(self, source_id: str) -> ScholarlySourceOption | None:
        """Return collection-source metadata by id."""

        for option in self.source_catalog:
            if option.id == source_id:
                return option
        return None


_CURATED_OPENROUTER_MODEL_CATALOG: tuple[dict[str, object], ...] = (
    {
        "id": "openrouter/auto",
        "display_name": "OpenRouter Auto",
        "provider": "OpenRouter",
        "family": "router",
        "description": "Adaptive routing across currently available providers.",
        "recommended": True,
    },
    {
        "id": "openai/gpt-5.4",
        "display_name": "OpenAI GPT-5.4",
        "provider": "OpenAI",
        "family": "gpt-5",
        "description": "Frontier reasoning and coding model for deeper audit comparisons.",
        "recommended": True,
    },
    {
        "id": "openai/gpt-4.1-mini",
        "display_name": "OpenAI GPT-4.1 Mini",
        "provider": "OpenAI",
        "family": "gpt-4.1",
        "description": "Low-cost general-purpose model with a large context window.",
        "recommended": True,
        "default_enabled": True,
    },
    {
        "id": "openai/o4-mini",
        "display_name": "OpenAI o4-mini",
        "provider": "OpenAI",
        "family": "o-series",
        "description": "Compact reasoning model for structured comparison runs.",
        "recommended": True,
    },
    {
        "id": "google/gemini-2.5-flash",
        "display_name": "Google Gemini 2.5 Flash",
        "provider": "Google",
        "family": "gemini-2.5",
        "description": "Fast workhorse model suited to larger query batches.",
        "recommended": True,
        "default_enabled": True,
    },
    {
        "id": "google/gemini-2.5-pro",
        "display_name": "Google Gemini 2.5 Pro",
        "provider": "Google",
        "family": "gemini-2.5",
        "description": "Higher-end reasoning model for harder audit prompts.",
        "recommended": True,
    },
    {
        "id": "anthropic/claude-haiku-4.5",
        "display_name": "Anthropic Claude Haiku 4.5",
        "provider": "Anthropic",
        "family": "claude-4.5",
        "description": "Fast Anthropic workhorse model for cheaper comparison runs.",
        "recommended": True,
        "default_enabled": True,
    },
    {
        "id": "anthropic/claude-sonnet-4.5",
        "display_name": "Anthropic Claude Sonnet 4.5",
        "provider": "Anthropic",
        "family": "claude-4.5",
        "description": "Higher-capability Anthropic Sonnet model for broader comparisons.",
        "recommended": True,
    },
    {
        "id": "anthropic/claude-opus-4.1",
        "display_name": "Anthropic Claude Opus 4.1",
        "provider": "Anthropic",
        "family": "claude-4",
        "description": "Frontier Anthropic model for deeper audit passes.",
        "recommended": False,
    },
    {
        "id": "anthropic/claude-3.5-sonnet",
        "display_name": "Anthropic Claude 3.5 Sonnet",
        "provider": "Anthropic",
        "family": "claude-3.5",
        "description": "Historical model id retained to explain legacy run artifacts.",
        "recommended": False,
        "selectable": False,
        "validation_state": "deprecated",
        "validation_reason": "OpenRouter returns 404 No endpoints found for this stale model id.",
        "replacement_model_id": "anthropic/claude-sonnet-4.5",
    },
)
_CURATED_OPENROUTER_MODEL_REGISTRY = {
    str(entry["id"]): entry for entry in _CURATED_OPENROUTER_MODEL_CATALOG
}
_DEFAULT_OPENROUTER_AVAILABLE_MODELS = [
    "openrouter/auto",
    "openai/gpt-4.1-mini",
    "openai/o4-mini",
    "openai/gpt-5.4",
    "google/gemini-2.5-flash",
    "google/gemini-2.5-pro",
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.1",
]
_DEFAULT_OPENROUTER_DEFAULT_MODELS = [
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash",
    "anthropic/claude-haiku-4.5",
]
_LOCAL_DEV_CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
]


def _build_openrouter_settings() -> OpenRouterSettings:
    configured_available_ids = _split_csv(
        os.getenv("OPENROUTER_AVAILABLE_MODELS"),
        default=_DEFAULT_OPENROUTER_AVAILABLE_MODELS,
    )
    configured_default_ids = _split_csv(
        os.getenv("OPENROUTER_DEFAULT_MODELS"),
        default=_DEFAULT_OPENROUTER_DEFAULT_MODELS,
    )
    catalog = _build_openrouter_model_catalog(
        available_model_ids=configured_available_ids,
        default_model_ids=configured_default_ids,
    )

    available_models = [entry.id for entry in catalog if entry.selectable]
    if not available_models:
        catalog = _build_openrouter_model_catalog(
            available_model_ids=_DEFAULT_OPENROUTER_AVAILABLE_MODELS,
            default_model_ids=_DEFAULT_OPENROUTER_DEFAULT_MODELS,
        )
        available_models = [entry.id for entry in catalog if entry.selectable]

    default_models = [
        entry.id for entry in catalog if entry.selectable and entry.default_enabled
    ]
    if not default_models:
        fallback_defaults = [
            model_id
            for model_id in _DEFAULT_OPENROUTER_DEFAULT_MODELS
            if model_id in available_models
        ]
        if fallback_defaults:
            default_models = fallback_defaults
            for index, entry in enumerate(catalog):
                if entry.id in fallback_defaults:
                    catalog[index] = entry.model_copy(update={"default_enabled": True})
        elif available_models:
            default_models = [available_models[0]]
            for index, entry in enumerate(catalog):
                if entry.id == available_models[0]:
                    catalog[index] = entry.model_copy(update={"default_enabled": True})
                    break

    return OpenRouterSettings(
        enabled=_bool_from_env("OPENROUTER_ENABLED", default=True),
        api_key=os.getenv("OPENROUTER_API_KEY", "").strip() or None,
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip(),
        model_discovery_endpoint=(
            "catalog"
            if os.getenv("OPENROUTER_MODEL_DISCOVERY_ENDPOINT", "user").strip().lower() == "catalog"
            else "user"
        ),
        model_discovery_ttl_seconds=_int_from_env("OPENROUTER_MODEL_DISCOVERY_TTL_SECONDS", default=300),
        timeout_seconds=_float_from_env("OPENROUTER_TIMEOUT_SECONDS", default=60.0),
        max_retries=_int_from_env("OPENROUTER_MAX_RETRIES", default=3),
        temperature=_float_from_env("OPENROUTER_TEMPERATURE", default=0.2),
        max_tokens=_int_from_env("OPENROUTER_MAX_TOKENS", default=1400),
        top_p=_float_from_env("OPENROUTER_TOP_P", default=1.0),
        default_models=default_models,
        available_models=available_models,
        model_catalog=catalog,
        app_name=os.getenv("OPENROUTER_APP_NAME", "bias-analysis").strip() or "bias-analysis",
        site_url=os.getenv("OPENROUTER_SITE_URL", "").strip() or None,
    )


def _default_data_root(app_env: str) -> Path:
    if app_env == "production":
        return Path("/data")
    return REPO_ROOT / "data"


def _default_cors_allowed_origins(app_env: str) -> list[str]:
    if app_env == "production":
        return []
    return list(_LOCAL_DEV_CORS_ALLOWED_ORIGINS)


def _build_openrouter_model_catalog(
    *,
    available_model_ids: list[str],
    default_model_ids: list[str],
) -> list[OpenRouterModelOption]:
    ordered_ids = _ordered_model_ids(available_model_ids, default_model_ids)
    return [
        _build_openrouter_model_option(
            model_id,
            default_enabled=model_id in default_model_ids,
        )
        for model_id in ordered_ids
    ]


def _ordered_model_ids(*groups: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for model_id in group:
            if model_id in seen:
                continue
            seen.add(model_id)
            ordered.append(model_id)
    return ordered


def _build_openrouter_model_option(
    model_id: str,
    *,
    default_enabled: bool,
) -> OpenRouterModelOption:
    payload = _CURATED_OPENROUTER_MODEL_REGISTRY.get(model_id)
    if payload is not None:
        return OpenRouterModelOption(**{**payload, "default_enabled": default_enabled})

    provider_slug, _, family_slug = model_id.partition("/")
    provider = provider_slug.replace("-", " ").title() if provider_slug else "Custom"
    family = family_slug or provider_slug or "custom"
    return OpenRouterModelOption(
        id=model_id,
        display_name=model_id,
        provider=provider,
        family=family,
        description="Custom model id configured via environment variables.",
        recommended=False,
        default_enabled=default_enabled,
        selectable=True,
        validation_state="custom",
        validation_reason=(
            "Configured explicitly through OPENROUTER_AVAILABLE_MODELS; not pre-validated by the app."
        ),
        source="configured_custom",
    )


def _build_scholarly_source_catalog(
    *,
    source_ids: list[str],
    openalex: ProviderSettings,
    semantic_scholar: ProviderSettings,
    scopus: ProviderSettings,
    core: ProviderSettings,
) -> list[ScholarlySourceOption]:
    metadata: dict[str, dict[str, object]] = {
        "openalex": {
            "display_name": "OpenAlex",
            "description": "Open scholarly graph search for works, venues, and citation metadata.",
            "selectable": True,
            "validation_state": "healthy",
            "validation_reason": None,
            "credential_required": False,
        },
        "semantic_scholar": {
            "display_name": "Semantic Scholar",
            "description": "Graph search across paper metadata, authorship, and citation signals.",
            "selectable": True,
            "validation_state": "healthy",
            "validation_reason": None,
            "credential_required": False,
        },
        "scopus": {
            "display_name": "Scopus",
            "description": "Elsevier Scopus search for subscription-backed bibliographic records.",
            "selectable": bool(scopus.api_key),
            "validation_state": "healthy" if scopus.api_key else "requires_configuration",
            "validation_reason": None if scopus.api_key else "Scopus API credentials are required.",
            "credential_required": True,
        },
        "core": {
            "display_name": "CORE",
            "description": "CORE repository search across aggregated open-access full-text metadata.",
            "selectable": bool(core.api_key),
            "validation_state": "healthy" if core.api_key else "requires_configuration",
            "validation_reason": None if core.api_key else "CORE API credentials are required.",
            "credential_required": True,
        },
    }
    options: list[ScholarlySourceOption] = []
    seen: set[str] = set()
    for source_id in source_ids:
        cleaned = source_id.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        payload = metadata.get(cleaned)
        if payload is None:
            options.append(
                ScholarlySourceOption(
                    id=cleaned,
                    display_name=cleaned,
                    description="Custom scholarly source id configured through SCHOLARLY_SOURCES.",
                    selectable=False,
                    validation_state="custom",
                    validation_reason="Custom scholarly sources are not implemented by the app.",
                )
            )
            continue
        options.append(ScholarlySourceOption(id=cleaned, **payload))
    return options


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the singleton application settings."""

    load_env_file()
    app_env = os.getenv("APP_ENV", "development").strip().lower() or "development"
    default_data_root = _default_data_root(app_env)

    scholarly_sources = _split_csv(
        os.getenv("SCHOLARLY_SOURCES"),
        default=["openalex", "semantic_scholar", "scopus", "core"],
    )
    provider_order = _split_csv(
        os.getenv("ENRICHMENT_PROVIDER_ORDER"),
        default=["openalex", "semantic_scholar", "scopus", "core"],
    )
    enabled_providers = _split_csv(
        os.getenv("ENRICHMENT_ENABLED_PROVIDERS"),
        default=provider_order,
    )
    openalex_settings = ProviderSettings(
        enabled="openalex" in enabled_providers,
        timeout_seconds=_float_from_env("OPENALEX_TIMEOUT_SECONDS", default=20.0),
        max_retries=_int_from_env("OPENALEX_MAX_RETRIES", default=3),
        rate_limit_seconds=_float_from_env("OPENALEX_RATE_LIMIT_SECONDS", default=0.0),
        cache_ttl_seconds=_int_from_env("OPENALEX_CACHE_TTL_SECONDS", default=86400),
        api_key=os.getenv("OPENALEX_API_KEY", "").strip() or None,
        base_url=os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org").strip(),
    )
    semantic_scholar_settings = ProviderSettings(
        enabled="semantic_scholar" in enabled_providers,
        timeout_seconds=_float_from_env("SEMANTIC_SCHOLAR_TIMEOUT_SECONDS", default=20.0),
        max_retries=_int_from_env("SEMANTIC_SCHOLAR_MAX_RETRIES", default=3),
        rate_limit_seconds=_float_from_env(
            "SEMANTIC_SCHOLAR_RATE_LIMIT_SECONDS",
            default=0.0,
        ),
        cache_ttl_seconds=_int_from_env("SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS", default=86400),
        api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip() or None,
        base_url=os.getenv(
            "SEMANTIC_SCHOLAR_BASE_URL",
            "https://api.semanticscholar.org/graph/v1",
        ).strip(),
    )
    scopus_settings = ProviderSettings(
        enabled="scopus" in enabled_providers,
        timeout_seconds=_float_from_env("SCOPUS_TIMEOUT_SECONDS", default=20.0),
        max_retries=_int_from_env("SCOPUS_MAX_RETRIES", default=3),
        rate_limit_seconds=_float_from_env("SCOPUS_RATE_LIMIT_SECONDS", default=0.0),
        cache_ttl_seconds=_int_from_env("SCOPUS_CACHE_TTL_SECONDS", default=86400),
        api_key=(
            os.getenv("SCOPUS_API_KEY", "").strip()
            or os.getenv("ELSEVIER_API_KEY", "").strip()
            or None
        ),
        base_url=os.getenv("SCOPUS_BASE_URL", "https://api.elsevier.com").strip(),
        extra_headers={
            "X-ELS-Insttoken": os.getenv("SCOPUS_INSTTOKEN", "").strip()
            or os.getenv("SCOPUS_INST_TOKEN", "").strip(),
        },
    )
    core_settings = ProviderSettings(
        enabled="core" in enabled_providers,
        timeout_seconds=_float_from_env("CORE_TIMEOUT_SECONDS", default=20.0),
        max_retries=_int_from_env("CORE_MAX_RETRIES", default=3),
        rate_limit_seconds=_float_from_env("CORE_RATE_LIMIT_SECONDS", default=0.0),
        cache_ttl_seconds=_int_from_env("CORE_CACHE_TTL_SECONDS", default=86400),
        api_key=os.getenv("CORE_API_KEY", "").strip() or None,
        base_url=os.getenv("CORE_API_BASE_URL", "https://api.core.ac.uk/v3").strip(),
    )

    return AppSettings(
        app_env=app_env,
        host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=_int_from_env("PORT", default=8000),
        log_level=os.getenv("LOG_LEVEL", "info").strip().lower() or "info",
        cors_allowed_origins=_split_csv(
            os.getenv("CORS_ALLOWED_ORIGINS"),
            default=_default_cors_allowed_origins(app_env),
        ),
        database=DatabaseSettings(
            path=Path(
                os.getenv("DATABASE_PATH", str(default_data_root / "app.db"))
            ),
        ),
        run_artifacts=RunArtifactsSettings(
            enabled=_bool_from_env("RUN_ARTIFACTS_ENABLED", default=True),
            path=Path(
                os.getenv(
                    "RUN_ARTIFACTS_DIR",
                    os.getenv("ARTIFACTS_DIR", str(default_data_root / "run_artifacts")),
                )
            ),
            pretty_json=_bool_from_env("RUN_ARTIFACTS_PRETTY_JSON", default=True),
        ),
        scholarly_sources=scholarly_sources,
        source_catalog=_build_scholarly_source_catalog(
            source_ids=scholarly_sources,
            openalex=openalex_settings,
            semantic_scholar=semantic_scholar_settings,
            scopus=scopus_settings,
            core=core_settings,
        ),
        default_run_type="scholarly",
        enrichment_provider_order=provider_order,
        enabled_enrichment_providers=enabled_providers,
        openrouter=_build_openrouter_settings(),
        openalex=openalex_settings,
        semantic_scholar=semantic_scholar_settings,
        scopus=scopus_settings,
        core=core_settings,
    )
