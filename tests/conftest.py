from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import get_settings
from backend.storage.database import Database
from backend.storage.repository import Repository


@pytest.fixture(autouse=True)
def configured_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_AVAILABLE_MODELS", "model-a,model-b")
    monkeypatch.setenv("OPENROUTER_DEFAULT_MODELS", "model-a,model-b")
    monkeypatch.setenv("OPENALEX_API_KEY", "test-openalex-key")
    monkeypatch.setenv("ENRICHMENT_PROVIDER_ORDER", "openalex,semantic_scholar,scopus,core")
    monkeypatch.setenv("ENRICHMENT_ENABLED_PROVIDERS", "openalex,semantic_scholar,scopus,core")
    monkeypatch.setenv("RUN_ARTIFACTS_ENABLED", "true")
    monkeypatch.setenv("RUN_ARTIFACTS_PRETTY_JSON", "true")
    monkeypatch.setenv("RUN_ARTIFACTS_DIR", str(tmp_path / "run_artifacts"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fake_openrouter_model_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeOpenRouterDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            assert isinstance(user_scoped, bool)
            return [
                {
                    "id": "model-a",
                    "canonical_slug": "model-a",
                    "name": "Model A",
                    "description": "Test model A",
                    "context_length": 64000,
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "request": "0",
                        "image": "0",
                    },
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["temperature", "top_p"],
                    "top_provider": {
                        "is_moderated": True,
                        "max_completion_tokens": 4000,
                    },
                },
                {
                    "id": "model-b",
                    "canonical_slug": "model-b",
                    "name": "Model B",
                    "description": "Test model B",
                    "context_length": 128000,
                    "pricing": {
                        "prompt": "0.000003",
                        "completion": "0.000004",
                        "request": "0",
                        "image": "0",
                    },
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": ["temperature", "max_tokens"],
                    "top_provider": {
                        "is_moderated": False,
                        "max_completion_tokens": 8000,
                    },
                },
            ]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterDiscoveryClient(),
    )


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    database = Database(tmp_path / "bias-analysis-test.sqlite3")
    database.initialize()
    return Repository(database)
