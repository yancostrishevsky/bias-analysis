from __future__ import annotations

import json
from pathlib import Path

from backend.adapters.scholarly import ScholarlySearchRequest, SemanticScholarClientError
from backend.application.enrichment.providers import (
    OpenAlexEnrichmentProvider,
    SemanticScholarEnrichmentProvider,
)
from backend.application.enrichment.service import enrich_results
from backend.application.run_artifacts import RunArtifactsWriter, get_run_artifacts_writer
from backend.config import get_settings
from backend.domain import EnrichmentProvider, ExecutionStatus, Query, ResultOriginType, ResultRecord, Run, RunStatus
from backend.storage.repository import Repository


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_run_artifacts_writer_redacts_and_rewrites_manifest(tmp_path: Path) -> None:
    run = Run()
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    writer = RunArtifactsWriter(
        run_id=run.id,
        root_dir=tmp_path,
        enabled=True,
        pretty_json=True,
    )

    writer.initialize_run(
        run=run,
        queries=[query],
        raw_create_payload={"token": "secret-token", "queries": [query.text]},
        normalized_payload={"selected_models": ["openai/gpt-4o-mini"], "queries": [query.text]},
    )
    writer.write_llm_request(
        query_index=1,
        model_name="openai/gpt-4o-mini",
        request={
            "method": "POST",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer super-secret",
                "Content-Type": "application/json",
                "X-API-Key": "api-secret",
            },
            "payload": {
                "model": "openai/gpt-4o-mini",
                "api_key": "api-secret",
                "prompt": "bias in academic search",
            },
        },
    )
    run.status = RunStatus.RUNNING
    run.stage = "calling_models"
    run.progress_current = 1
    run.progress_total = 2
    run.progress_message = "Model openai/gpt-4o-mini: requesting"
    writer.write_manifest(run=run, query_count=1)
    writer.append_event(stage="run", message="Second event")

    manifest = _read_json(writer.run_dir / "manifest.json")
    request_payload = _read_json(
        writer.run_dir / "llm/query_001/model_openai_gpt-4o-mini/request.json"
    )
    events = _read_jsonl(writer.run_dir / "logs/events.jsonl")

    assert manifest["status"] == "running"
    assert manifest["query_count"] == 1
    assert "Authorization" not in request_payload["headers"]
    assert request_payload["headers"]["X-API-Key"] == "[REDACTED]"
    assert request_payload["payload"]["api_key"] == "[REDACTED]"
    assert request_payload["payload"]["model"] == "openai/gpt-4o-mini"
    assert events[0]["message"] == "Run created"
    assert events[-1]["message"] == "Second event"


def test_enrich_results_writes_attempt_and_canonical_artifacts(
    repository: Repository,
    monkeypatch,
) -> None:
    run = Run()
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])
    writer = get_run_artifacts_writer(run.id)
    writer.initialize_run(
        run=run,
        queries=[query],
        raw_create_payload={"run_type": "scholarly", "queries": [query.text]},
        normalized_payload={"run_type": "scholarly", "sources": ["openalex"], "queries": [query.text]},
    )

    result = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="openalex",
        provider_name="openalex",
        rank=1,
        title="Bias in Academic Search",
        doi="10.1000/example",
        year=2024,
        authors=["Ada Lovelace"],
        raw_payload={
            "id": "https://openalex.org/W123",
            "display_name": "Bias in Academic Search",
            "doi": "10.1000/example",
            "publication_year": 2024,
            "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
            "primary_location": {"source": {"display_name": "Journal of Retrieval Studies"}},
        },
    )
    repository.save_results([result])

    monkeypatch.setattr(
        "backend.application.enrichment.service.build_enrichment_providers",
        lambda repository, artifacts=None, result_ordinals=None: [
            OpenAlexEnrichmentProvider(
                repository=repository,
                provider=EnrichmentProvider.OPENALEX,
                settings=get_settings().openalex,
                client=type("UnusedClient", (), {})(),
                artifacts=artifacts,
                result_ordinals=result_ordinals,
            )
        ],
    )

    payload = enrich_results(repository=repository, results=[result], artifacts=writer)
    provider_records, canonical = payload[str(result.id)]
    attempt = _read_json(
        writer.run_dir / "enrichment/record_001/provider_openalex_attempt_001.json"
    )
    canonical_payload = _read_json(
        writer.run_dir / "enrichment/record_001/canonical_enrichment.json"
    )
    provenance_payload = _read_json(writer.run_dir / "enrichment/record_001/provenance.json")

    assert len(provider_records) == 1
    assert canonical is not None
    assert attempt["resolution_source"] == "source_payload_reuse"
    assert attempt["status"] == "completed"
    assert attempt["normalized_record"]["provider"] == "openalex"
    assert canonical_payload["title"] == "Bias in Academic Search"
    assert provenance_payload["title"]["provider"] == "openalex"


def test_semantic_scholar_failed_attempt_writes_error_context(
    repository: Repository,
) -> None:
    run = Run()
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])
    writer = get_run_artifacts_writer(run.id)
    writer.initialize_run(
        run=run,
        queries=[query],
        raw_create_payload={"run_type": "scholarly", "queries": [query.text]},
        normalized_payload={"run_type": "scholarly", "sources": ["semantic_scholar"], "queries": [query.text]},
    )

    result = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="openalex",
        provider_name="openalex",
        rank=1,
        title="Bias in Academic Search",
        doi="10.1000/example",
        year=2024,
        authors=["Ada Lovelace"],
    )
    repository.save_results([result])

    class FailingSemanticScholarClient:
        def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
            return ScholarlySearchRequest(
                method="GET",
                url="https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query_text, "limit": per_page},
                headers={"x-api-key": "bad-key"},
            )

        def search_papers(self, *args, **kwargs):
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

    provider = SemanticScholarEnrichmentProvider(
        repository=repository,
        provider=EnrichmentProvider.SEMANTIC_SCHOLAR,
        settings=get_settings().semantic_scholar,
        client=FailingSemanticScholarClient(),
        artifacts=writer,
        result_ordinals={str(result.id): 1},
    )

    record = provider.enrich(result)
    attempt = _read_json(
        writer.run_dir / "enrichment/record_001/provider_semantic_scholar_attempt_001.json"
    )
    errors = _read_jsonl(writer.run_dir / "logs/errors.jsonl")

    assert record.status == ExecutionStatus.FAILED
    assert attempt["status"] == "failed"
    assert attempt["failure_kind"] == "rate_limited"
    assert attempt["status_code"] == 429
    assert attempt["endpoint"] == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert attempt["response_body"] == '{"message":"Too Many Requests"}'
    assert attempt["raw_response"]["status_code"] == 429
    assert errors[-1]["provider"] == "semantic_scholar"
    assert errors[-1]["status_code"] == 429
    assert errors[-1]["endpoint"] == "https://api.semanticscholar.org/graph/v1/paper/search"
