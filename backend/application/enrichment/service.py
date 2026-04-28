"""Application-layer orchestration for provider-specific result enrichment."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable

from backend.application.enrichment.canonicalize import canonicalize_enrichment_records
from backend.application.enrichment.providers import build_enrichment_providers
from backend.application.run_artifacts import RunArtifactsWriter
from backend.domain import (
    CanonicalEnrichment,
    EnrichmentRecord,
    EnrichmentProvider,
    ExecutionStatus,
    ResultRecord,
)
from backend.storage.repository import Repository


def enrich_results(
    *,
    repository: Repository,
    results: Sequence[ResultRecord],
    progress_callback: Callable[[int, int, str], None] | None = None,
    artifacts: RunArtifactsWriter | None = None,
) -> dict[str, tuple[list[EnrichmentRecord], CanonicalEnrichment | None]]:
    """Build provider-specific and canonical enrichments for collected results."""

    result_ordinals = {str(result.id): index for index, result in enumerate(results, start=1)}
    providers = build_enrichment_providers(
        repository,
        artifacts=artifacts,
        result_ordinals=result_ordinals,
    )
    output: dict[str, tuple[list[EnrichmentRecord], CanonicalEnrichment | None]] = {}
    total_results = len(results)
    for index, result in enumerate(results, start=1):
        if progress_callback is not None:
            progress_callback(index, total_results, f"Enriching {index}/{total_results}")
        provider_records = [_safe_enrich(provider, result) for provider in providers]
        canonical_enrichment = canonicalize_enrichment_records(
            result_record_id=result.id,
            records=provider_records,
        )
        repository.replace_enrichments(result.id, provider_records, canonical_enrichment)
        if artifacts is not None:
            artifacts.write_canonical_enrichment(
                record_index=index,
                canonical_enrichment=canonical_enrichment,
            )
            artifacts.write_provenance(
                record_index=index,
                canonical_enrichment=canonical_enrichment,
            )
            artifacts.append_event(
                stage="enrichment",
                message="Canonical enrichment stored",
                result_record_id=str(result.id),
                record_index=index,
                provider_count=len(provider_records),
                canonical_present=canonical_enrichment is not None,
            )
        output[str(result.id)] = (provider_records, canonical_enrichment)
    return output


def _safe_enrich(provider: Any, result: ResultRecord) -> EnrichmentRecord:
    try:
        return provider.enrich(result)
    except Exception as exc:  # pragma: no cover - defensive runtime containment
        failed_record = getattr(provider, "failed_record", None)
        if callable(failed_record):
            return failed_record(result, f"Unexpected enrichment error: {exc}")

        provider_name = getattr(getattr(provider, "provider", None), "value", None) or "openalex"
        return EnrichmentRecord(
            result_record_id=result.id,
            provider=EnrichmentProvider(provider_name),
            provider_record_id=f"{provider_name}:failed",
            status=ExecutionStatus.FAILED,
            error_message=f"Unexpected enrichment error: {exc}",
        )
