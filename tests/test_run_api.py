from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.adapters.openalex.client import OpenAlexRequest
from backend.adapters.openrouter.client import OpenRouterError, OpenRouterRequest
from backend.adapters.scholarly import ScholarlySearchRequest, SemanticScholarClientError
from backend.application.run_artifacts import get_run_artifacts_writer
from backend.api.routes.runs import (
    RunCreateRequest,
    create_run,
    delete_run,
    get_run_analysis,
    get_run_options,
    get_run_records,
    get_run_replay_status,
    get_run_results,
    export_run_records_file,
    replay_llm_artifacts,
    start_run,
)
from backend.config import get_settings
from backend.application.enrichment.canonicalize import canonicalize_enrichment_records
from backend.domain import (
    EnrichmentMatchStrategy,
    EnrichmentProvider,
    EnrichmentRecord,
    ExecutionStatus,
    LLMCall,
    Query,
    ResultOriginType,
    ResultRecord,
    Run,
    RunStatus,
    RunType,
)
from backend.storage.repository import Repository


def _artifact_dir(run_id) -> Path:
    return get_run_artifacts_writer(run_id).run_dir


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fake_discovery_models(*model_ids: str) -> list[dict[str, object]]:
    return [
        {
            "id": model_id,
            "name": model_id,
            "context_length": 64000,
            "pricing": {
                "prompt": "0.0001",
                "completion": "0.0002",
                "request": "0",
                "image": "0",
            },
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "top_provider": {
                "is_moderated": True,
                "max_completion_tokens": 4096,
            },
        }
        for model_id in model_ids
    ]


def test_get_run_options_exposes_run_modes_and_models() -> None:
    payload = get_run_options()

    assert payload.supported_run_types == ["scholarly", "llm_audit"]
    assert payload.available_models == ["model-a", "model-b"]
    assert [item.id for item in payload.model_catalog] == ["model-a", "model-b"]
    assert payload.available_scholarly_sources == [
        "openalex",
        "semantic_scholar",
        "scopus",
        "core",
    ]
    assert [item.id for item in payload.source_catalog] == [
        "openalex",
        "semantic_scholar",
        "scopus",
        "core",
    ]
    assert payload.source_catalog[0].display_name == "OpenAlex"
    assert payload.source_catalog[1].display_name == "Semantic Scholar"
    assert payload.enrichment_provider_order == [
        "openalex",
        "semantic_scholar",
        "scopus",
        "core",
    ]


def test_get_run_options_exposes_curated_model_catalog_when_env_not_overridden(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_AVAILABLE_MODELS", "")
    monkeypatch.setenv("OPENROUTER_DEFAULT_MODELS", "")
    get_settings.cache_clear()

    payload = get_run_options()
    catalog_by_id = {item.id: item for item in payload.model_catalog}

    assert "openai/gpt-4.1-mini" in payload.available_models
    assert "google/gemini-2.5-flash" in payload.available_models
    assert "anthropic/claude-sonnet-4.5" in payload.available_models
    assert payload.default_models == [
        "openai/gpt-4.1-mini",
        "google/gemini-2.5-flash",
        "anthropic/claude-haiku-4.5",
    ]
    assert catalog_by_id["openai/gpt-5.4"].recommended is True
    assert catalog_by_id["anthropic/claude-sonnet-4.5"].display_name == "Anthropic Claude Sonnet 4.5"


def test_get_run_options_marks_stale_sonnet_slug_unselectable(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "OPENROUTER_AVAILABLE_MODELS",
        "anthropic/claude-3.5-sonnet,openai/gpt-4.1-mini",
    )
    monkeypatch.setenv(
        "OPENROUTER_DEFAULT_MODELS",
        "anthropic/claude-3.5-sonnet",
    )
    get_settings.cache_clear()

    payload = get_run_options()
    catalog_by_id = {item.id: item for item in payload.model_catalog}

    assert payload.available_models == ["openai/gpt-4.1-mini"]
    assert payload.default_models == ["openai/gpt-4.1-mini"]
    assert catalog_by_id["anthropic/claude-3.5-sonnet"].selectable is False
    assert catalog_by_id["anthropic/claude-3.5-sonnet"].validation_state == "deprecated"
    assert catalog_by_id["anthropic/claude-3.5-sonnet"].replacement_model_id == "anthropic/claude-sonnet-4.5"


def test_create_run_rejects_unknown_model_selection(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    with pytest.raises(
        HTTPException,
        match="Selected OpenRouter models are unavailable in the current catalog: model-z",
    ):
        create_run(
            RunCreateRequest(
                run_type="llm_audit",
                queries=["bias in academic search"],
                selected_models=["model-z"],
                sources=[],
                top_k=5,
            )
        )


def test_create_run_rejects_empty_llm_model_selection(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    with pytest.raises(HTTPException, match="Select at least one OpenRouter model"):
        create_run(
            RunCreateRequest(
                run_type="llm_audit",
                queries=["bias in academic search"],
                selected_models=[],
                sources=[],
                top_k=5,
            )
        )


def test_create_run_accepts_up_to_ten_selected_models(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return [
                {
                    "id": f"model-{index}",
                    "name": f"Model {index}",
                    "context_length": 64000,
                    "pricing": {"prompt": "0.0001", "completion": "0.0002", "request": "0", "image": "0"},
                    "architecture": {
                        "modality": "text->text",
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "top_provider": {"is_moderated": True, "max_completion_tokens": 4096},
                }
                for index in range(10)
            ]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeDiscoveryClient(),
    )

    detail = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=[f"model-{index}" for index in range(10)],
            sources=[],
            top_k=5,
        )
    )

    assert detail.run.selected_models == [f"model-{index}" for index in range(10)]


def test_create_run_rejects_more_than_ten_selected_models(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    with pytest.raises(HTTPException, match="Select at most 10 OpenRouter models"):
        create_run(
            RunCreateRequest(
                run_type="llm_audit",
                queries=["bias in academic search"],
                selected_models=[f"model-{index}" for index in range(11)],
                sources=[],
                top_k=5,
            )
        )


def test_start_run_rejects_llm_audit_without_selected_models(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    run = Run(run_type=RunType.LLM_AUDIT, selected_models=[], top_k=5)
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])

    with pytest.raises(HTTPException, match="Select at least one OpenRouter model"):
        start_run(run.id)


def test_start_run_rejects_stale_llm_model_selection_against_current_catalog(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)
    monkeypatch.setenv("OPENROUTER_MODEL_DISCOVERY_TTL_SECONDS", "0")
    get_settings.cache_clear()

    discovery_state = {"calls": 0}

    class FakeDiscoveryClient:
        def list_models(self, *, user_scoped: bool, request=None):
            response_sets = [
                _fake_discovery_models("model-a"),
                _fake_discovery_models("model-b"),
            ]
            index = min(discovery_state["calls"], len(response_sets) - 1)
            discovery_state["calls"] += 1
            return response_sets[index]

    monkeypatch.setattr(
        "backend.application.openrouter_models.OpenRouterClient.from_settings",
        lambda: FakeDiscoveryClient(),
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=5,
        )
    )

    with pytest.raises(
        HTTPException,
        match="Selected OpenRouter models are unavailable in the current catalog: model-a",
    ):
        start_run(created.run.id)

    run_dir = _artifact_dir(created.run.id)
    events = _read_jsonl(run_dir / "logs/events.jsonl")
    assert any(
        event.get("message") == "Model validation failed before execution"
        and event.get("unavailable_models") == ["model-a"]
        for event in events
    )


def test_start_scholarly_run_persists_results(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenAlexClient:
        def build_search_works_request(self, *, query_text: str, per_page: int) -> OpenAlexRequest:
            return OpenAlexRequest(
                method="GET",
                url="https://api.openalex.org/works",
                params={"search": query_text, "per_page": per_page},
                headers={},
            )

        def search_works(
            self,
            query_text: str,
            per_page: int,
            *,
            request: OpenAlexRequest | None = None,
            include_raw: bool = False,
        ) -> list[dict[str, object]] | tuple[list[dict[str, object]], dict[str, object]]:
            assert query_text == "bias in academic search"
            assert per_page == 3
            works = [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "Bias in Academic Search",
                    "doi": "https://doi.org/10.1000/example",
                    "publication_year": 2024,
                    "language": "en",
                    "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                    "primary_location": {
                        "landing_page_url": "https://example.org/bias-paper",
                        "source": {
                            "display_name": "Journal of Retrieval Studies",
                            "host_organization_name": "Example Press",
                        },
                    },
                    "cited_by_count": 12,
                }
            ]
            if include_raw:
                return works, {"results": works, "meta": {"count": len(works)}}
            return works

    monkeypatch.setattr(
        "backend.application.run_executor.OpenAlexClient.from_settings",
        lambda: FakeOpenAlexClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="scholarly",
            queries=["bias in academic search"],
            sources=["openalex"],
            selected_models=[],
            top_k=3,
        )
    )
    run_id = created.run.id
    run_dir = _artifact_dir(run_id)

    assert run_dir.exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "run.json").exists()
    assert (run_dir / "queries.json").exists()

    started = start_run(run_id)
    results = get_run_results(run_id)

    assert started.run.status == "completed"
    assert started.run.stage == "done"
    assert started.run.finished_at is not None
    assert len(results) == 1
    assert results[0].source_name == "openalex"
    assert results[0].canonical_identifier == "https://doi.org/10.1000/example"
    assert (run_dir / "scholarly/query_001/source_openalex_request.json").exists()
    assert (run_dir / "scholarly/query_001/source_openalex_response.json").exists()
    assert (run_dir / "scholarly/query_001/source_openalex_results_raw.json").exists()
    assert (run_dir / "scholarly/query_001/source_openalex_results_normalized.json").exists()
    assert (run_dir / "scholarly/query_001/results_raw.json").exists()
    assert (run_dir / "scholarly/query_001/results_normalized.json").exists()
    assert (run_dir / "analysis/summary.json").exists()


def test_delete_run_removes_database_rows_and_artifacts(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    created = create_run(
        RunCreateRequest(
            run_type="scholarly",
            queries=["bias in academic search"],
            sources=["openalex"],
            selected_models=[],
            top_k=3,
        )
    )
    run_id = created.run.id
    run_dir = _artifact_dir(run_id)

    assert run_dir.exists()

    delete_run(run_id)

    assert run_dir.exists() is False
    with pytest.raises(HTTPException, match="not found"):
        get_run_results(run_id)


def test_start_scholarly_run_supports_multiple_collection_sources(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeCollector:
        def __init__(self, *, name: str, title: str) -> None:
            self.name = name
            self.display_name = title

        def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
            return ScholarlySearchRequest(
                method="GET",
                url=f"https://example.org/{self.name}/search",
                params={"q": query_text, "limit": per_page},
                headers={"x-source": self.name},
            )

        def search(
            self,
            query_text: str,
            per_page: int,
            *,
            request: ScholarlySearchRequest | None = None,
            include_raw: bool = False,
        ) -> list[dict[str, object]] | tuple[list[dict[str, object]], dict[str, object]]:
            results = [
                {
                    "id": f"{self.name}-1",
                    "title": f"{self.display_name} result",
                    "doi": f"10.1000/{self.name}",
                    "year": 2024,
                }
            ]
            if include_raw:
                return results, {"source": self.name, "results": results}
            return results

        def map_result(
            self,
            *,
            run_id,
            query_id,
            rank: int,
            payload: dict[str, object],
        ) -> ResultRecord:
            return ResultRecord(
                run_id=run_id,
                query_id=query_id,
                origin_type=ResultOriginType.SCHOLARLY_SOURCE,
                source_name=self.name,
                provider_name=self.name,
                execution_status=ExecutionStatus.COMPLETED,
                rank=rank,
                canonical_identifier=str(payload["doi"]),
                title=str(payload["title"]),
                doi=str(payload["doi"]),
                year=int(payload["year"]),
                raw_payload=dict(payload),
            )

    monkeypatch.setattr(
        "backend.application.run_executor._build_scholarly_collectors",
        lambda: {
            "openalex": FakeCollector(name="openalex", title="OpenAlex"),
            "semantic_scholar": FakeCollector(name="semantic_scholar", title="Semantic Scholar"),
        },
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="scholarly",
            queries=["bias in academic search"],
            sources=["openalex", "semantic_scholar"],
            selected_models=[],
            top_k=2,
        )
    )
    run_dir = _artifact_dir(created.run.id)

    started = start_run(created.run.id)
    results = get_run_results(created.run.id)
    aggregated_raw = _read_json(run_dir / "scholarly/query_001/results_raw.json")

    assert started.run.status == "completed"
    assert [result.source_name for result in results] == ["openalex", "semantic_scholar"]
    assert {item.name: item.status for item in started.entity_statuses} == {
        "openalex": "completed",
        "semantic_scholar": "completed",
    }
    assert (run_dir / "scholarly/query_001/source_openalex_request.json").exists()
    assert (run_dir / "scholarly/query_001/source_openalex_results_normalized.json").exists()
    assert (run_dir / "scholarly/query_001/source_semantic_scholar_request.json").exists()
    assert (run_dir / "scholarly/query_001/source_semantic_scholar_results_normalized.json").exists()
    assert [item["source_name"] for item in aggregated_raw] == ["openalex", "semantic_scholar"]


def test_start_scholarly_run_writes_semantic_scholar_error_response_artifact(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeCollector:
        def __init__(self, *, name: str, title: str) -> None:
            self.name = name
            self.display_name = title

        def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
            return ScholarlySearchRequest(
                method="GET",
                url=f"https://example.test/{self.name}",
                params={"query": query_text, "limit": per_page},
                headers={},
            )

        def search(
            self,
            query_text: str,
            per_page: int,
            *,
            request: ScholarlySearchRequest | None = None,
            include_raw: bool = False,
        ) -> list[dict[str, object]] | tuple[list[dict[str, object]], dict[str, object]]:
            if self.name == "semantic_scholar":
                raise SemanticScholarClientError(
                    (
                        "Semantic Scholar rejected the configured SEMANTIC_SCHOLAR_API_KEY; "
                        "unauthenticated retry failed "
                        "(endpoint=https://api.semanticscholar.org/graph/v1/paper/search, "
                        "status=429, kind=rate_limited, body={\"message\":\"Too Many Requests\"})"
                    ),
                    status_code=429,
                    failure_kind="rate_limited",
                    auth_fallback_attempted=True,
                    endpoint="https://api.semanticscholar.org/graph/v1/paper/search",
                    response_body='{"message":"Too Many Requests"}',
                    raw_response={
                        "provider": "semantic_scholar",
                        "endpoint": "https://api.semanticscholar.org/graph/v1/paper/search",
                        "status_code": 429,
                        "failure_kind": "rate_limited",
                        "response_body": '{"message":"Too Many Requests"}',
                    },
                )
            results = [
                {
                    "id": f"{self.name}-1",
                    "title": f"{self.display_name} result",
                    "doi": f"10.1000/{self.name}",
                    "year": 2024,
                }
            ]
            if include_raw:
                return results, {"source": self.name, "results": results}
            return results

        def map_result(
            self,
            *,
            run_id,
            query_id,
            rank: int,
            payload: dict[str, object],
        ) -> ResultRecord:
            return ResultRecord(
                run_id=run_id,
                query_id=query_id,
                origin_type=ResultOriginType.SCHOLARLY_SOURCE,
                source_name=self.name,
                provider_name=self.name,
                execution_status=ExecutionStatus.COMPLETED,
                rank=rank,
                canonical_identifier=str(payload["doi"]),
                title=str(payload["title"]),
                doi=str(payload["doi"]),
                year=int(payload["year"]),
                raw_payload=dict(payload),
            )

    monkeypatch.setattr(
        "backend.application.run_executor._build_scholarly_collectors",
        lambda: {
            "openalex": FakeCollector(name="openalex", title="OpenAlex"),
            "semantic_scholar": FakeCollector(name="semantic_scholar", title="Semantic Scholar"),
        },
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="scholarly",
            queries=["bias in academic search"],
            sources=["openalex", "semantic_scholar"],
            selected_models=[],
            top_k=2,
        )
    )
    run_dir = _artifact_dir(created.run.id)

    started = start_run(created.run.id)
    error_response = _read_json(
        run_dir / "scholarly/query_001/source_semantic_scholar_response.json"
    )
    errors = _read_jsonl(run_dir / "logs/errors.jsonl")

    assert started.run.status == "partial"
    assert error_response["status_code"] == 429
    assert error_response["failure_kind"] == "rate_limited"
    assert errors[-1]["source"] == "semantic_scholar"
    assert errors[-1]["status_code"] == 429
    assert errors[-1]["endpoint"] == "https://api.semanticscholar.org/graph/v1/paper/search"


def test_delete_run_allows_running_runs(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    run = Run(run_type=RunType.SCHOLARLY, status="running", stage="collecting", sources=["openalex"], top_k=5)
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])
    run_dir = _artifact_dir(run.id)
    get_run_artifacts_writer(run.id).initialize_run(
        run=run,
        queries=[query],
        raw_create_payload={"run_type": "scholarly", "queries": [query.text], "sources": ["openalex"], "top_k": 5},
        normalized_payload={"run_type": "scholarly", "queries": [query.text], "sources": ["openalex"], "top_k": 5},
    )

    delete_run(run.id)

    assert run_dir.exists() is False
    with pytest.raises(HTTPException, match="not found"):
        get_run_results(run.id)


def test_start_llm_audit_run_allows_partial_model_failure(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a", "model-b")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer test-openrouter-key",
                    "Content-Type": "application/json",
                },
                payload={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "require_json": require_json,
                },
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            assert "Query: bias in academic search" in prompt
            assert require_json is True
            if model == "model-b":
                from backend.adapters.openrouter.client import OpenRouterError

                raise OpenRouterError("provider rate limit")

            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {"id": "resp-1"}
                output_text = json.dumps(
                    {
                        "articles": [
                            {
                                "rank": 1,
                                "title": "Bias in Academic Search",
                                "doi": "10.1000/example",
                                "year": 2024,
                                "venue": "Journal of Retrieval Studies",
                                "authors": ["Ada Lovelace"],
                                "url": "https://example.org/bias-paper",
                                "rationale": "high relevance",
                            }
                        ]
                    }
                )
                latency_ms = 120
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a", "model-b"],
            sources=[],
            top_k=2,
        )
    )
    run_id = created.run.id
    run_dir = _artifact_dir(run_id)

    started = start_run(run_id)
    results = get_run_results(run_id)

    assert started.run.status == "partial"
    assert started.run.stage == "done"
    assert started.run.finished_at is not None
    assert "1 llm calls failed" in started.run.error_message
    assert len(results) == 1
    assert results[0].model_name == "model-a"
    assert results[0].origin_type == "llm_response"
    model_states = {item.name: item for item in started.entity_statuses}
    assert model_states["model-a"].progress_current == 1
    assert model_states["model-a"].progress_total == 1
    assert model_states["model-b"].status == "failed"
    assert "provider rate limit" in (model_states["model-b"].error_message or "")
    success_request = _read_json(run_dir / "llm/query_001/model_model-a/request.json")
    failed_request = _read_json(run_dir / "llm/query_001/model_model-b/request.json")
    success_metadata = _read_json(run_dir / "llm/query_001/model_model-a/metadata.json")
    failed_error = _read_json(run_dir / "llm/query_001/model_model-b/parse_error.json")

    assert "Authorization" not in success_request["headers"]
    assert failed_request["headers"]["Content-Type"] == "application/json"
    assert success_metadata["status"] == "completed"
    assert failed_error["error_message"] == "provider rate limit"
    assert (run_dir / "llm/query_001/model_model-a/response_raw.json").exists()
    assert (run_dir / "llm/query_001/model_model-a/parsed_output.json").exists()
    assert (run_dir / "analysis/llm_audit.json").exists()
    assert _read_json(run_dir / "analysis/summary.json")["total_results"] == 1


def test_start_llm_audit_uses_discovery_catalog_for_execution_preflight(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)
    monkeypatch.setenv("OPENROUTER_AVAILABLE_MODELS", "openai/gpt-4o-mini")
    monkeypatch.setenv("OPENROUTER_DEFAULT_MODELS", "openai/gpt-4o-mini")
    get_settings.cache_clear()

    requested_models: list[str] = []
    selected_model_id = "deepseek/deepseek-chat-v3-0324"

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models(selected_model_id)

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer test-openrouter-key",
                    "Content-Type": "application/json",
                },
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            requested_models.append(model)

            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {"id": "resp-1"}
                output_text = json.dumps(
                    {
                        "articles": [
                            {
                                "rank": 1,
                                "title": "Bias in Academic Search",
                                "doi": "10.1000/example",
                                "year": 2024,
                                "venue": "Journal of Retrieval Studies",
                                "authors": ["Ada Lovelace"],
                                "url": "https://example.org/bias-paper",
                                "rationale": "high relevance",
                            }
                        ]
                    }
                )
                latency_ms = 90
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=[selected_model_id],
            sources=[],
            top_k=2,
        )
    )
    run_dir = _artifact_dir(created.run.id)

    started = start_run(created.run.id)
    events = _read_jsonl(run_dir / "logs/events.jsonl")

    assert started.run.status == "completed"
    assert requested_models == [selected_model_id]
    assert not any(event.get("message") == "Model disabled before execution" for event in events)
    assert any(
        event.get("message") == "Validated OpenRouter model catalog for execution"
        and event.get("unavailable_models") == []
        for event in events
    )


def test_start_llm_audit_emits_running_progress_during_model_request(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    run_id_holder: dict[str, object] = {}

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer test-openrouter-key",
                    "Content-Type": "application/json",
                },
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            current_run = repository.get_run(run_id_holder["run_id"])
            current_detail = repository.get_run_detail(run_id_holder["run_id"])

            assert current_run.status == "running"
            assert current_run.stage == "calling_models"
            assert current_run.progress_message == "Model model-a: requesting"
            assert current_detail.entity_statuses[0].status == "running"
            assert "requesting" in (current_detail.entity_statuses[0].progress_message or "")

            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {"id": "resp-1"}
                output_text = json.dumps(
                    {
                        "articles": [
                            {
                                "rank": 1,
                                "title": "Bias in Academic Search",
                                "doi": "10.1000/example",
                                "year": 2024,
                                "venue": "Journal of Retrieval Studies",
                                "authors": ["Ada Lovelace"],
                                "url": "https://example.org/bias-paper",
                                "rationale": "high relevance",
                            }
                        ]
                    }
                )
                latency_ms = 100
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=2,
        )
    )
    run_id_holder["run_id"] = created.run.id

    started = start_run(created.run.id)

    assert started.run.status == "completed"
    assert started.run.finished_at is not None


def test_start_llm_audit_unavailable_model_404_skips_remaining_queries_and_preserves_error_payload(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)
    monkeypatch.setenv(
        "OPENROUTER_AVAILABLE_MODELS",
        "openai/gpt-4o-mini,anthropic/claude-3.5-sonnet",
    )
    monkeypatch.setenv(
        "OPENROUTER_DEFAULT_MODELS",
        "openai/gpt-4o-mini,anthropic/claude-3.5-sonnet",
    )
    get_settings.cache_clear()

    bad_model_calls = 0

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer test-openrouter-key",
                    "Content-Type": "application/json",
                },
                payload={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                },
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            nonlocal bad_model_calls
            if model == "anthropic/claude-3.5-sonnet":
                bad_model_calls += 1
                raise OpenRouterError(
                    "OpenRouter model 'anthropic/claude-3.5-sonnet' is unavailable: "
                    "No endpoints found for anthropic/claude-3.5-sonnet.",
                    model=model,
                    status_code=404,
                    url="https://openrouter.ai/api/v1/chat/completions",
                    response_text=(
                        '{"error":{"message":"No endpoints found for '
                        'anthropic/claude-3.5-sonnet.","code":404}}'
                    ),
                    response_payload={
                        "error": {
                            "message": "No endpoints found for anthropic/claude-3.5-sonnet.",
                            "code": 404,
                        }
                    },
                    provider_error_code="404",
                    failure_kind="model_unavailable",
                    latency_ms=42,
                )

            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {"id": f"resp-{model}"}
                output_text = json.dumps(
                    {
                        "articles": [
                            {
                                "rank": 1,
                                "title": f"Supported result for {prompt.split('Query: ', 1)[1]}",
                                "doi": None,
                                "year": 2024,
                                "venue": "Journal of Retrieval Studies",
                                "authors": ["Ada Lovelace"],
                                "url": "https://example.org/bias-paper",
                                "rationale": "high relevance",
                            }
                        ]
                    }
                )
                latency_ms = 110
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    run = Run(
        run_type=RunType.LLM_AUDIT,
        selected_models=["anthropic/claude-3.5-sonnet", "openai/gpt-4o-mini"],
        top_k=1,
    )
    queries = [
        Query(run_id=run.id, text="first query", position=1),
        Query(run_id=run.id, text="second query", position=2),
    ]
    repository.create_run(run, queries)
    get_run_artifacts_writer(run.id).initialize_run(
        run=run,
        queries=queries,
        raw_create_payload={
            "run_type": "llm_audit",
            "queries": [query.text for query in queries],
            "selected_models": list(run.selected_models),
            "sources": [],
            "top_k": 1,
        },
        normalized_payload={
            "run_type": "llm_audit",
            "queries": [query.text for query in queries],
            "selected_models": list(run.selected_models),
            "sources": [],
            "top_k": 1,
        },
    )
    run_dir = _artifact_dir(run.id)

    started = start_run(run.id)
    results = get_run_results(run.id)

    assert bad_model_calls == 1
    assert started.run.status == "partial"
    assert started.run.stage == "done"
    assert started.run.error_message == "1 llm calls failed; 1 model executions skipped"
    assert len(results) == 2

    model_states = {item.name: item for item in started.entity_statuses}
    assert model_states["anthropic/claude-3.5-sonnet"].status == "failed"
    assert model_states["anthropic/claude-3.5-sonnet"].failed_count == 2

    failed_metadata = _read_json(
        run_dir / "llm/query_001/model_anthropic_claude-3.5-sonnet/metadata.json"
    )
    skipped_metadata = _read_json(
        run_dir / "llm/query_002/model_anthropic_claude-3.5-sonnet/metadata.json"
    )
    skipped_error = _read_json(
        run_dir / "llm/query_002/model_anthropic_claude-3.5-sonnet/parse_error.json"
    )
    first_error = _read_json(
        run_dir / "llm/query_001/model_anthropic_claude-3.5-sonnet/parse_error.json"
    )

    assert failed_metadata["failure_kind"] == "model_unavailable"
    assert failed_metadata["status_code"] == 404
    assert skipped_metadata["status"] == "skipped"
    assert "OpenRouter model 'anthropic/claude-3.5-sonnet' is unavailable" in first_error["error_message"]
    assert "Skipped remaining queries after OpenRouter model 'anthropic/claude-3.5-sonnet' is unavailable" in skipped_error["error_message"]


def test_artifact_write_failures_do_not_break_run_execution(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer test-openrouter-key"},
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {"id": "resp-1"}
                output_text = json.dumps(
                    {
                        "articles": [
                            {
                                "rank": 1,
                                "title": "Bias in Academic Search",
                                "doi": "10.1000/example",
                                "year": 2024,
                                "venue": "Journal of Retrieval Studies",
                                "authors": ["Ada Lovelace"],
                                "url": "https://example.org/bias-paper",
                                "rationale": "high relevance",
                            }
                        ]
                    }
                )
                latency_ms = 50
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_artifacts.RunArtifactsWriter._write_json_atomic",
        lambda self, relative_path, payload: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        "backend.application.run_artifacts.RunArtifactsWriter._append_jsonl_entry",
        lambda self, relative_path, payload: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=2,
        )
    )
    started = start_run(created.run.id)
    results = get_run_results(created.run.id)

    assert started.run.status == "completed"
    assert started.run.finished_at is not None
    assert len(results) == 1


def test_start_run_refreshes_run_artifact_snapshot(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer test-openrouter-key"},
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {"id": "resp-1"}
                output_text = json.dumps(
                    {
                        "articles": [
                            {
                                "rank": 1,
                                "title": "Bias in Academic Search",
                                "doi": "10.1000/example",
                                "year": 2024,
                                "venue": "Journal of Retrieval Studies",
                                "authors": ["Ada Lovelace"],
                                "url": "https://example.org/bias-paper",
                                "rationale": "high relevance",
                            }
                        ]
                    }
                )
                latency_ms = 75
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: None,
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=1,
        )
    )
    run_dir = _artifact_dir(created.run.id)

    started = start_run(created.run.id)
    run_snapshot = _read_json(run_dir / "run.json")

    assert started.run.status == "completed"
    assert run_snapshot["run"]["status"] == "completed"
    assert run_snapshot["run"]["stage"] == "done"
    assert run_snapshot["run"]["started_at"] is not None
    assert run_snapshot["run"]["finished_at"] is not None
    assert run_snapshot["raw_create_payload"]["queries"] == ["bias in academic search"]


def test_get_run_replay_status_reports_replayable_llm_artifacts(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer test-openrouter-key"},
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "articles": [
                                            {
                                                "rank": 1,
                                                "title": "Replay Ready",
                                                "doi": "10.1000/replay-ready",
                                                "year": 2024,
                                                "venue": "Journal of Replay",
                                                "authors": ["Ada Lovelace"],
                                                "url": "https://example.org/replay-ready",
                                                "rationale": "stored artifact exists",
                                            }
                                        ]
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                }
                output_text = raw_response["choices"][0]["message"]["content"]
                latency_ms = 75
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: {},
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=1,
        )
    )
    start_run(created.run.id)

    payload = get_run_replay_status(created.run.id)

    assert payload.replay_available is True
    assert payload.replay_summary is None
    assert payload.current_output_source == "fresh_execution"
    assert payload.current_output_generated_at is not None


def test_replay_llm_artifacts_uses_stored_raw_response_without_openrouter_calls(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer test-openrouter-key"},
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "articles": [
                                            {
                                                "rank": 1,
                                                "title": "Fresh From Raw",
                                                "doi": "10.1000/raw",
                                                "year": 2024,
                                                "venue": "Journal of Replay",
                                                "authors": ["Ada Lovelace"],
                                                "url": "https://example.org/raw",
                                                "rationale": "replayed from artifact",
                                            }
                                        ]
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                }
                output_text = raw_response["choices"][0]["message"]["content"]
                latency_ms = 80
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: {},
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=1,
        )
    )
    start_run(created.run.id)
    run_dir = _artifact_dir(created.run.id)
    model_dir = run_dir / "llm/query_001/model_model-a"
    (model_dir / "parsed_output.json").write_text(
        json.dumps(
            [
                {
                    "rank": 1,
                    "title": "Stale Parsed Output",
                    "doi": "10.1000/stale",
                    "year": 2021,
                    "venue": "Old Journal",
                    "authors": ["Grace Hopper"],
                    "url": "https://example.org/stale",
                    "rationale": "should not be reused",
                }
            ]
        ),
        encoding="utf-8",
    )

    replay_enrichment_titles: list[list[str]] = []

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: (_ for _ in ()).throw(AssertionError("Replay should not call OpenRouter")),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: replay_enrichment_titles.append(
            [result.title for result in results]
        )
        or {},
    )

    replayed = replay_llm_artifacts(created.run.id)
    results = get_run_results(created.run.id)
    replay_status = get_run_replay_status(created.run.id)
    replay_summary = _read_json(run_dir / "replay/summary.json")
    replay_metadata = _read_json(run_dir / "replay/llm/query_001/model_model-a/metadata.json")
    replay_parsed = _read_json(run_dir / "replay/llm/query_001/model_model-a/parsed_output.json")

    assert replayed.run.status == "completed"
    assert [result.title for result in results] == ["Fresh From Raw"]
    assert replay_enrichment_titles == [["Fresh From Raw"]]
    assert replay_summary["external_llm_calls"] == 0
    assert replay_metadata["artifact_source"] == "response_raw"
    assert replay_parsed[0]["title"] == "Fresh From Raw"
    assert replay_status.replay_available is True
    assert replay_status.replay_summary is not None
    assert replay_status.current_output_source == "artifact_replay"


def test_replay_llm_artifacts_recovers_inactive_running_run_before_replay(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: {},
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a", "model-b"],
            sources=[],
            top_k=1,
        )
    )
    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: (_ for _ in ()).throw(AssertionError("Replay should not call OpenRouter")),
    )
    run_id = created.run.id
    query = created.queries[0]
    writer = get_run_artifacts_writer(run_id)
    stale_started_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    writer.write_llm_request(
        query_index=1,
        model_name="model-a",
        request={
            "method": "POST",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers": {"Content-Type": "application/json"},
            "payload": {"model": "model-a", "messages": [{"role": "user", "content": "Query: bias in academic search"}]},
        },
    )
    writer.write_llm_response(
        query_index=1,
        model_name="model-a",
        response={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "articles": [
                                    {
                                        "rank": 1,
                                        "title": "Recovered Replay Result",
                                        "doi": "10.1000/recovered",
                                        "year": 2024,
                                        "venue": "Journal of Replay",
                                        "authors": ["Ada Lovelace"],
                                        "url": "https://example.org/recovered",
                                        "rationale": "recovered from stored raw response",
                                    }
                                ]
                            }
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        },
    )
    writer.write_llm_metadata(
        query_index=1,
        model_name="model-a",
        metadata={
            "status": "completed",
            "started_at": stale_started_at,
            "finished_at": stale_started_at + timedelta(seconds=3),
            "latency_ms": 3000,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    )
    writer.write_llm_request(
        query_index=1,
        model_name="model-b",
        request={
            "method": "POST",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers": {"Content-Type": "application/json"},
            "payload": {"model": "model-b", "messages": [{"role": "user", "content": "Query: bias in academic search"}]},
        },
    )

    run = repository.get_run(run_id)
    run.status = RunStatus.RUNNING
    run.stage = "calling_models"
    run.progress_current = 2
    run.progress_total = 2
    run.progress_message = "Model model-b: requesting"
    run.started_at = stale_started_at
    run.completed_at = None
    run.finished_at = None
    run.error_message = None
    repository.update_run(run)
    repository.update_run_model_status(
        run_id=run_id,
        model_name="model-a",
        status=ExecutionStatus.COMPLETED,
        progress_current=1,
        progress_total=1,
        progress_message="Completed",
        started_at=stale_started_at,
        finished_at=stale_started_at + timedelta(seconds=3),
    )
    repository.update_run_model_status(
        run_id=run_id,
        model_name="model-b",
        status=ExecutionStatus.RUNNING,
        progress_current=0,
        progress_total=1,
        progress_message="Query 1/1: requesting",
        started_at=stale_started_at,
    )
    repository.save_llm_call(
        LLMCall(
            run_id=run_id,
            query_id=query.id,
            model_name="model-b",
            provider_name="openrouter",
            status=ExecutionStatus.RUNNING,
            prompt_text="Query: bias in academic search",
            request_payload={"model": "model-b"},
            response_payload={},
            parse_success=False,
            started_at=stale_started_at,
        )
    )

    replayed = replay_llm_artifacts(run_id)
    results = get_run_results(run_id)
    replay_error = _read_json(_artifact_dir(run_id) / "llm/query_001/model_model-b/parse_error.json")

    assert replayed.run.status == "partial"
    assert replayed.run.stage == "done"
    assert [result.title for result in results] == ["Recovered Replay Result"]
    assert "Recovered inactive LLM run after process interruption" in replay_error["error_message"]


def test_replay_llm_artifacts_fails_cleanly_when_replayable_artifacts_are_missing(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    class FakeOpenRouterClient:
        def list_models(self, *, user_scoped: bool, request=None):
            return _fake_discovery_models("model-a")

        def build_completion_request(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
        ) -> OpenRouterRequest:
            return OpenRouterRequest(
                method="POST",
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer test-openrouter-key"},
                payload={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int,
            temperature: float,
            top_p: float,
            require_json: bool,
            request: OpenRouterRequest | None = None,
        ):
            class Response:
                request_payload = request.payload if request is not None else {"model": model}
                raw_response = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "articles": [
                                            {
                                                "rank": 1,
                                                "title": "Replay Candidate",
                                                "doi": None,
                                                "year": 2024,
                                                "venue": "Journal of Replay",
                                                "authors": ["Ada Lovelace"],
                                                "url": "https://example.org/raw",
                                                "rationale": "initial artifact",
                                            }
                                        ]
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
                output_text = raw_response["choices"][0]["message"]["content"]
                latency_ms = 80
                finish_reason = "stop"
                prompt_tokens = 10
                completion_tokens = 20
                total_tokens = 30

            return Response()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: FakeOpenRouterClient(),
    )
    monkeypatch.setattr(
        "backend.application.run_executor.enrich_results",
        lambda *, repository, results, progress_callback=None, artifacts=None: {},
    )

    created = create_run(
        RunCreateRequest(
            run_type="llm_audit",
            queries=["bias in academic search"],
            selected_models=["model-a"],
            sources=[],
            top_k=1,
        )
    )
    start_run(created.run.id)
    run_dir = _artifact_dir(created.run.id)
    model_dir = run_dir / "llm/query_001/model_model-a"
    (model_dir / "response_raw.json").unlink()
    (model_dir / "parsed_output.json").unlink()

    monkeypatch.setattr(
        "backend.application.run_executor.OpenRouterClient.from_settings",
        lambda: (_ for _ in ()).throw(AssertionError("Replay should not call OpenRouter")),
    )

    replayed = replay_llm_artifacts(created.run.id)
    results = get_run_results(created.run.id)
    replay_summary = _read_json(run_dir / "replay/summary.json")
    replay_error = _read_json(run_dir / "replay/llm/query_001/model_model-a/parse_error.json")

    assert replayed.run.status == "failed"
    assert results == []
    assert replay_summary["failed_calls"] == 1
    assert "Missing replayable artifacts" in replay_error["error_message"]


def test_analysis_endpoint_returns_multi_model_overlap_and_llm_metrics(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    run = Run(
        run_type=RunType.LLM_AUDIT,
        selected_models=["model-a", "model-b"],
        top_k=2,
    )
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])

    repository.save_llm_call(
        LLMCall(
            run_id=run.id,
            query_id=query.id,
            model_name="model-a",
            provider_name="openrouter",
            status=ExecutionStatus.COMPLETED,
            prompt_text="prompt",
            parse_success=True,
            latency_ms=100,
            total_tokens=50,
        )
    )
    repository.save_llm_call(
        LLMCall(
            run_id=run.id,
            query_id=query.id,
            model_name="model-b",
            provider_name="openrouter",
            status=ExecutionStatus.COMPLETED,
            prompt_text="prompt",
            parse_success=True,
            latency_ms=140,
            total_tokens=60,
        )
    )
    writer = get_run_artifacts_writer(run.id)
    model_a_dir = writer.run_dir / "llm" / "query_001" / "model_model-a"
    model_a_dir.mkdir(parents=True, exist_ok=True)
    (model_a_dir / "metadata.json").write_text(
        json.dumps(
            {
                "parse_mode": "full_json",
                "parsed_item_count": 2,
                "partial_json_recovery": False,
            }
        ),
        encoding="utf-8",
    )
    (model_a_dir / "request.json").write_text(
        json.dumps({"payload": {"model": "model-a"}}),
        encoding="utf-8",
    )
    model_b_dir = writer.run_dir / "llm" / "query_001" / "model_model-b"
    model_b_dir.mkdir(parents=True, exist_ok=True)
    (model_b_dir / "metadata.json").write_text(
        json.dumps(
            {
                "parse_mode": "partial_array_recovery",
                "parsed_item_count": 2,
                "partial_json_recovery": True,
            }
        ),
        encoding="utf-8",
    )
    (model_b_dir / "request.json").write_text(
        json.dumps({"payload": {"model": "model-b"}}),
        encoding="utf-8",
    )

    results = [
        ResultRecord(
            run_id=run.id,
            query_id=query.id,
            origin_type=ResultOriginType.LLM_RESPONSE,
            model_name="model-a",
            provider_name="openrouter",
            rank=1,
            canonical_identifier="10.1000/shared",
            title="Shared Paper",
            doi="10.1000/shared",
            year=2024,
            authors=["Ada Lovelace"],
            venue="Journal A",
            publisher="Publisher A",
            language="en",
        ),
        ResultRecord(
            run_id=run.id,
            query_id=query.id,
            origin_type=ResultOriginType.LLM_RESPONSE,
            model_name="model-a",
            provider_name="openrouter",
            rank=2,
            canonical_identifier="10.1000/unique-a",
            title="Unique Paper A",
            doi="10.1000/unique-a",
            year=2022,
            authors=["Ada Lovelace"],
            venue="Journal B",
            publisher="Publisher B",
            language="en",
        ),
        ResultRecord(
            run_id=run.id,
            query_id=query.id,
            origin_type=ResultOriginType.LLM_RESPONSE,
            model_name="model-b",
            provider_name="openrouter",
            rank=1,
            canonical_identifier="10.1000/shared",
            title="Shared Paper",
            doi="10.1000/shared",
            year=2024,
            authors=["Ada Lovelace"],
            venue="Journal A",
            publisher="Publisher A",
            language="en",
        ),
        ResultRecord(
            run_id=run.id,
            query_id=query.id,
            origin_type=ResultOriginType.LLM_RESPONSE,
            model_name="model-b",
            provider_name="openrouter",
            rank=2,
            canonical_identifier="10.1000/unique-b",
            title="Unique Paper B",
            doi="10.1000/unique-b",
            year=2021,
            authors=["Grace Hopper"],
            venue="Journal C",
            publisher="Publisher C",
            language="en",
        ),
    ]
    repository.save_results(results)

    for result in results:
        provider_record = EnrichmentRecord(
            result_record_id=result.id,
            provider=EnrichmentProvider.OPENALEX,
            provider_record_id=f"openalex:{result.canonical_identifier}",
            match_strategy=EnrichmentMatchStrategy.DOI,
            doi=result.doi,
            title=result.title,
            publication_year=result.year,
            language=result.language,
            authors=result.authors,
            citation_count=20,
            is_open_access=True,
            publisher=result.publisher,
            venue=result.venue,
            fields_of_study=["Information Retrieval"],
        )
        canonical = canonicalize_enrichment_records(
            result_record_id=result.id,
            records=[provider_record],
        )
        repository.replace_enrichments(result.id, [provider_record], canonical)

    payload = get_run_analysis(run.id)

    assert payload.summary.entity_label == "Model"
    assert payload.summary.entity_count == 2
    assert payload.llm is not None
    assert payload.baseline_coverage_rows
    assert any(row.query_id == str(query.id) and row.entity == "model-a" for row in payload.coverage_rows)
    assert any(row.query_id is None and row.entity == "model-a" for row in payload.coverage_rows)
    assert any(row.query_id == str(query.id) and row.entity == "model-b" for row in payload.distributions)
    assert any(row.top_1_agreement == 1.0 for row in payload.overlap_rows if row.query_id is None)
    assert any(
        row.model_name == "model-a" and row.parse_mode == "full_json" and row.parsed_item_count == 2
        for row in payload.llm.calls
    )
    assert any(
        row.model_name == "model-b" and row.partial_json_recovery is True
        for row in payload.llm.calls
    )
    assert any(row.metric == "parse_success_rate" and row.entity == "overall" for row in payload.llm.metrics)
    assert any(row.metric == "verification_coverage_rate" and row.entity == "overall" for row in payload.llm.metrics)
    assert any(
        row.left_entity == "model-a" and row.right_entity == "model-b"
        for row in payload.overlap_rows
    )
    assert any(row.metric == "publisher_hhi" and row.entity == "overall" for row in payload.concentration_rows)


def test_records_endpoint_and_exports_expose_verifiability_layers(
    repository: Repository,
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.api.routes.runs.get_repository", lambda: repository)

    run = Run(
        run_type=RunType.LLM_AUDIT,
        selected_models=["model-a"],
        top_k=3,
    )
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])

    llm_call = LLMCall(
        run_id=run.id,
        query_id=query.id,
        model_name="model-a",
        provider_name="openrouter",
        status=ExecutionStatus.COMPLETED,
        prompt_text="prompt",
        parse_success=True,
        latency_ms=90,
        total_tokens=40,
    )
    repository.save_llm_call(llm_call)

    writer = get_run_artifacts_writer(run.id)
    model_dir = writer.run_dir / "llm" / "query_001" / "model_model-a"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "metadata.json").write_text(
        json.dumps(
            {
                "parse_mode": "brace_slice",
                "parsed_item_count": 3,
                "partial_json_recovery": False,
            }
        ),
        encoding="utf-8",
    )
    (model_dir / "request.json").write_text(
        json.dumps({"payload": {"model": "model-a"}}),
        encoding="utf-8",
    )

    matched = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        llm_call_id=llm_call.id,
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="model-a",
        provider_name="openrouter",
        rank=1,
        canonical_identifier="10.1000/verified",
        title="Verified Paper",
        doi="10.1000/verified",
        year=2024,
        authors=["Ada Lovelace"],
        venue="Journal of Verification",
        publisher="Publisher A",
        language="en",
    )
    fabricated = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        llm_call_id=llm_call.id,
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="model-a",
        provider_name="openrouter",
        rank=2,
        canonical_identifier="invented-paper",
        title="Invented Verified Looking Paper",
        doi="not-a-doi",
        year=2025,
        authors=["Imaginary Author"],
        venue="Journal of Very Real Studies",
        publisher="Publisher B",
        language="en",
        raw_payload={"raw_item": {"title": "Invented Verified Looking Paper", "doi": "not-a-doi", "journal": "Journal of Very Real Studies"}},
    )
    conflict = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        llm_call_id=llm_call.id,
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="model-a",
        provider_name="openrouter",
        rank=3,
        canonical_identifier="10.1000/conflict",
        title="Conflict Paper",
        doi="10.1000/conflict",
        year=2020,
        authors=["Grace Hopper"],
        venue="Journal X",
        publisher="Publisher C",
        language="en",
    )
    repository.save_results([matched, fabricated, conflict])

    provider_record = EnrichmentRecord(
        result_record_id=matched.id,
        provider=EnrichmentProvider.OPENALEX,
        provider_record_id="openalex:verified",
        match_strategy=EnrichmentMatchStrategy.DOI,
        doi=matched.doi,
        title=matched.title,
        publication_year=matched.year,
        language=matched.language,
        authors=matched.authors,
        citation_count=12,
        is_open_access=True,
        publisher=matched.publisher,
        venue=matched.venue,
        fields_of_study=["Information Retrieval"],
    )
    canonical = canonicalize_enrichment_records(result_record_id=matched.id, records=[provider_record])
    repository.replace_enrichments(matched.id, [provider_record], canonical)

    conflict_provider = EnrichmentRecord(
        result_record_id=conflict.id,
        provider=EnrichmentProvider.OPENALEX,
        provider_record_id="openalex:conflict",
        match_strategy=EnrichmentMatchStrategy.DOI,
        doi="10.1000/conflict",
        title="Conflict Paper Revised",
        publication_year=2022,
        language="en",
        authors=["Different Author"],
        citation_count=5,
        is_open_access=False,
        publisher="Publisher Z",
        venue="Journal Y",
        fields_of_study=["Information Retrieval"],
    )
    conflict_canonical = canonicalize_enrichment_records(result_record_id=conflict.id, records=[conflict_provider])
    repository.replace_enrichments(conflict.id, [conflict_provider], conflict_canonical)

    payload = get_run_records(run.id)

    assert payload.summary.total_rows == 3
    assert payload.summary.export_formats == ["csv", "json", "jsonl"]
    assert any(option.value == "high" for option in payload.filters.risk_buckets)
    assert any(row.hallucination_risk_bucket == "high" for row in payload.rows)
    assert any(row.matched is True and row.hallucination_risk_bucket == "low" for row in payload.rows)
    assert any(row.any_conflict is True for row in payload.rows)

    filtered = get_run_records(run.id, risk_bucket="high")
    assert filtered.summary.filtered_rows >= 1
    assert all(row.hallucination_risk_bucket == "high" for row in filtered.rows)

    unmatched_high = get_run_records(run.id, risk_bucket="high", matched=False)
    assert unmatched_high.summary.filtered_rows == 1
    assert unmatched_high.rows[0].matched is False
    assert unmatched_high.rows[0].doi_valid is False

    top_only = get_run_records(run.id, top_k=1)
    assert top_only.summary.filtered_rows == 1
    assert all(row.rank <= 1 for row in top_only.rows)

    export_response = export_run_records_file(run.id, format="jsonl", view="verification", risk_bucket="high", matched=False)
    lines = export_response.body.decode("utf-8").splitlines()

    assert export_response.headers["content-disposition"].endswith('run_%s_verification.jsonl"' % run.id)
    assert json.loads(lines[0])["_type"] == "metadata"
    exported_row = json.loads(lines[1])
    assert exported_row["hallucination_risk_bucket"] == "high"
    assert exported_row["matched"] is False
