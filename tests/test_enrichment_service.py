from __future__ import annotations

from backend.adapters.http import JsonHttpClient
from backend.application.enrichment.providers import OpenAlexEnrichmentProvider
from backend.application.enrichment.service import enrich_results
from backend.domain import EnrichmentProvider, ExecutionStatus, Query, ResultOriginType, ResultRecord, Run
from backend.storage.repository import Repository


def test_enrich_results_contains_unexpected_provider_failures(
    repository: Repository,
    monkeypatch,
) -> None:
    run = Run()
    query = Query(run_id=run.id, text="bias in academic search", position=1)
    repository.create_run(run, [query])
    result = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="openalex",
        provider_name="openalex",
        rank=1,
        title="Bias in Academic Search",
    )
    repository.save_results([result])

    class ExplodingProvider:
        provider = EnrichmentProvider.OPENALEX

        def enrich(self, result: ResultRecord):
            raise RuntimeError("boom")

        def failed_record(self, result: ResultRecord, message: str):
            from backend.domain import EnrichmentRecord

            return EnrichmentRecord(
                result_record_id=result.id,
                provider=EnrichmentProvider.OPENALEX,
                provider_record_id="openalex:failed",
                status=ExecutionStatus.FAILED,
                error_message=message,
            )

    monkeypatch.setattr(
        "backend.application.enrichment.service.build_enrichment_providers",
        lambda repository, artifacts=None, result_ordinals=None: [ExplodingProvider()],
    )

    payload = enrich_results(repository=repository, results=[result])

    provider_records, canonical = payload[str(result.id)]
    assert canonical is None
    assert len(provider_records) == 1
    assert provider_records[0].status == ExecutionStatus.FAILED
    assert "Unexpected enrichment error: boom" in (provider_records[0].error_message or "")


def test_openalex_provider_post_init_constructs_without_super_error(
    repository: Repository,
) -> None:
    provider = OpenAlexEnrichmentProvider(
        repository=repository,
        provider=EnrichmentProvider.OPENALEX,
        settings=type(
            "Settings",
            (),
            {
                "enabled": True,
                "timeout_seconds": 5.0,
                "max_retries": 1,
                "rate_limit_seconds": 0.0,
                "cache_ttl_seconds": 60,
                "api_key": None,
                "base_url": "https://api.openalex.org",
            },
        )(),
        http_client=JsonHttpClient(timeout_seconds=5.0, max_retries=1, rate_limit_seconds=0.0),
        client=type("Client", (), {})(),
    )

    assert provider.http_client is not None
    assert provider.client is not None
