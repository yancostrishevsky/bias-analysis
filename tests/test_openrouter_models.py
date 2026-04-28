from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.adapters.openrouter.client import OpenRouterModelDiscoveryError
from backend.api.routes.openrouter import get_openrouter_models
from backend.application.openrouter_models import list_openrouter_models
from backend.config import get_settings
from backend.storage.repository import Repository


def test_list_openrouter_models_normalizes_openrouter_payload(
    repository: Repository,
    monkeypatch,
) -> None:
    class FakeDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            assert user_scoped is True
            return [
                {
                    "id": "openai/gpt-4.1",
                    "canonical_slug": "openai/gpt-4.1",
                    "name": "GPT-4.1",
                    "description": "General-purpose text model",
                    "created": 1712345678,
                    "context_length": 128000,
                    "pricing": {
                        "prompt": "0.000005",
                        "completion": "0.000015",
                        "request": "0",
                        "image": "0",
                    },
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["temperature", "top_p", "max_tokens"],
                    "top_provider": {
                        "is_moderated": True,
                        "max_completion_tokens": 16384,
                    },
                }
            ]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeDiscoveryClient(),
    )

    payload = list_openrouter_models(repository=repository)

    assert payload.cached is False
    assert payload.total == 1
    assert payload.models[0].id == "openai/gpt-4.1"
    assert payload.models[0].name == "GPT-4.1"
    assert payload.models[0].provider == "Openai"
    assert payload.models[0].prompt_price == 0.000005
    assert payload.models[0].completion_price == 0.000015
    assert payload.models[0].input_modalities == ["text"]
    assert payload.models[0].is_moderated is True
    assert payload.models[0].max_completion_tokens == 16384


def test_list_openrouter_models_treats_negative_pricing_as_missing(
    repository: Repository,
    monkeypatch,
) -> None:
    class FakeDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return [
                {
                    "id": "provider/weird-model",
                    "name": "Weird Model",
                    "context_length": 64000,
                    "pricing": {
                        "prompt": "-1",
                        "completion": -1,
                        "request": "0",
                        "image": "0",
                    },
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "top_provider": {"is_moderated": True, "max_completion_tokens": 4096},
                }
            ]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeDiscoveryClient(),
    )

    payload = list_openrouter_models(repository=repository)

    assert payload.total == 1
    assert payload.models[0].prompt_price is None
    assert payload.models[0].completion_price is None


def test_openrouter_models_endpoint_supports_filtering(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.openrouter.get_repository", lambda: repository)

    class FakeDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return [
                {
                    "id": "text/model",
                    "name": "Text Model",
                    "description": "Text only",
                    "context_length": 32000,
                    "pricing": {"prompt": "0.0001", "completion": "0.0002", "request": "0", "image": "0"},
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "top_provider": {"is_moderated": True, "max_completion_tokens": 4096},
                },
                {
                    "id": "vision/model",
                    "name": "Vision Model",
                    "description": "Image input support",
                    "context_length": 256000,
                    "pricing": {"prompt": "0.0003", "completion": "0.0004", "request": "0", "image": "0"},
                    "architecture": {
                        "modality": "image+text->text",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                    "top_provider": {"is_moderated": False, "max_completion_tokens": 8192},
                },
            ]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeDiscoveryClient(),
    )

    payload = get_openrouter_models(q="vision", modality="vision", min_context_length=200000)

    assert payload.total == 1
    assert payload.models[0].id == "vision/model"
    assert payload.models[0].provider == "Vision"


def test_openrouter_models_cache_hit_and_stale_fallback(
    repository: Repository,
    monkeypatch,
) -> None:
    calls = 0

    class FakeDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise OpenRouterModelDiscoveryError("upstream unavailable")
            return [
                {
                    "id": "model-a",
                    "name": "Model A",
                    "context_length": 64000,
                    "pricing": {"prompt": "0.0001", "completion": "0.0002", "request": "0", "image": "0"},
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "top_provider": {"is_moderated": True, "max_completion_tokens": 4096},
                }
            ]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeDiscoveryClient(),
    )

    first = list_openrouter_models(repository=repository)
    second = list_openrouter_models(repository=repository)

    assert first.cached is False
    assert second.cached is True
    assert calls == 1

    settings = get_settings().openrouter
    cache_key = f"models:{settings.model_discovery_endpoint}"
    cached_payload, _ = repository.peek_cache_payload("openrouter", cache_key)
    assert cached_payload is not None

    repository.set_cache_payload(
        "openrouter",
        cache_key,
        cached_payload,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    fallback = list_openrouter_models(repository=repository)

    assert fallback.cached is True
    assert fallback.total == 1
    assert fallback.models[0].id == "model-a"
    assert calls == 2
