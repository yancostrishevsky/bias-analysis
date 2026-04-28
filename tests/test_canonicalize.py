from __future__ import annotations

from uuid import uuid4

from backend.application.enrichment.canonicalize import canonicalize_enrichment_records
from backend.domain import EnrichmentMatchStrategy, EnrichmentProvider, EnrichmentRecord, ExecutionStatus


def test_canonicalize_enrichment_records_merges_fields_and_provenance() -> None:
    result_record_id = uuid4()
    openalex_record = EnrichmentRecord(
        result_record_id=result_record_id,
        provider=EnrichmentProvider.OPENALEX,
        provider_record_id="W123",
        match_strategy=EnrichmentMatchStrategy.DOI,
        doi="10.1000/example",
        title="Bias in Scholarly Retrieval",
        publication_year=2024,
        authors=["Ada Lovelace"],
        citation_count=12,
        publisher="OpenAlex Press",
    )
    semantic_record = EnrichmentRecord(
        result_record_id=result_record_id,
        provider=EnrichmentProvider.SEMANTIC_SCHOLAR,
        provider_record_id="S2:456",
        match_strategy=EnrichmentMatchStrategy.TITLE_AUTHORS_YEAR,
        abstract="A metadata-rich abstract.",
        affiliations=["University of Example"],
        fields_of_study=["Information Retrieval"],
        subject_areas=["Bias Analysis"],
        language="en",
        is_open_access=True,
        venue="Journal of Retrieval Studies",
    )

    canonical = canonicalize_enrichment_records(
        result_record_id=result_record_id,
        records=[openalex_record, semantic_record],
    )

    assert canonical is not None
    assert canonical.doi == "10.1000/example"
    assert canonical.abstract == "A metadata-rich abstract."
    assert canonical.venue == "Journal of Retrieval Studies"
    assert canonical.field_provenance["doi"].provider == EnrichmentProvider.OPENALEX
    assert canonical.field_provenance["abstract"].provider == EnrichmentProvider.SEMANTIC_SCHOLAR
    assert canonical.field_provenance["abstract"].match_strategy == EnrichmentMatchStrategy.TITLE_AUTHORS_YEAR


def test_canonicalize_enrichment_records_ignores_failed_records() -> None:
    result_record_id = uuid4()
    failed_record = EnrichmentRecord(
        result_record_id=result_record_id,
        provider=EnrichmentProvider.SCOPUS,
        provider_record_id="failed",
        status=ExecutionStatus.FAILED,
        error_message="timeout",
        title="Should not appear",
    )

    canonical = canonicalize_enrichment_records(
        result_record_id=result_record_id,
        records=[failed_record],
    )

    assert canonical is None
