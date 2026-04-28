from __future__ import annotations

from uuid import uuid4

from backend.application.analysis.service import _build_view_row
from backend.application.enrichment.providers import _map_core_payload, _map_scopus_payload
from backend.application.llm_parser import build_article_retrieval_prompt
from backend.domain import (
    CanonicalEnrichment,
    EnrichmentMatchStrategy,
    EnrichmentProvider,
    EnrichmentRecord,
    FieldProvenance,
    ResultOriginType,
    ResultRecord,
)


def test_prompt_requests_bias_analysis_fields_explicitly() -> None:
    prompt = build_article_retrieval_prompt(
        query_text="liquid biopsy cancer detection review",
        top_k=10,
    )

    assert "publication_year" in prompt
    assert "language" in prompt
    assert "is_open_access" in prompt
    assert "country_primary" in prompt
    assert "publisher" in prompt
    assert "venue" in prompt


def test_map_scopus_payload_normalizes_bias_fields_from_raw_payload() -> None:
    result = ResultRecord(
        run_id=uuid4(),
        query_id=uuid4(),
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="openai/gpt-4o-mini",
        provider_name="openrouter",
        rank=1,
        title="Liquid biopsy in cancer screening, detection, and monitoring",
        doi="10.1038/s41568-019-0212-6",
        year=2019,
        authors=["Giulia Siravegna"],
    )

    record = _map_scopus_payload(
        result,
        {
            "dc:identifier": "SCOPUS_ID:1",
            "dc:title": result.title,
            "prism:doi": result.doi,
            "prism:coverDate": "2019-01-01",
            "prism:publicationName": "Nature Reviews Cancer",
            "openaccessFlag": True,
            "affiliation": [
                {
                    "affiliation-country": "United States",
                    "affilname": "Nature Reviews Drug Discovery",
                }
            ],
        },
    )

    assert record.publication_year == 2019
    assert record.is_open_access is True
    assert record.country_primary == "United States"
    assert record.country_dominant == "United States"
    assert record.countries == ["United States"]
    assert record.venue == "Nature Reviews Cancer"


def test_map_core_payload_normalizes_language_and_venue_bias_fields() -> None:
    result = ResultRecord(
        run_id=uuid4(),
        query_id=uuid4(),
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="openai/gpt-4o-mini",
        provider_name="openrouter",
        rank=1,
        title="Liquid biopsy in cancer diagnosis",
    )

    record = _map_core_payload(
        result,
        {
            "id": "CORE_ID:1",
            "title": result.title,
            "doi": "10.1000/example",
            "publishedDate": "2019-01-01T00:00:00",
            "language": {"code": "en", "name": "English"},
            "publisher": "'Springer Science and Business Media LLC'",
            "journals": [{"title": "Nature Reviews Cancer"}],
        },
    )

    assert record.publication_year == 2019
    assert record.language == "en"
    assert record.publisher == "Springer Science and Business Media LLC"
    assert record.venue == "Nature Reviews Cancer"


def test_build_view_row_prefers_canonical_then_provider_raw_then_llm_structured() -> None:
    result = ResultRecord(
        id=uuid4(),
        run_id=uuid4(),
        query_id=uuid4(),
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="openai/gpt-4o-mini",
        provider_name="openrouter",
        rank=1,
        title="Liquid biopsy in cancer diagnosis",
        year=2021,
        venue="LLM Venue",
        publisher="LLM Publisher",
        language="fr",
        raw_payload={
            "bias_fields": {
                "publication_year": 2021,
                "language": "fr",
                "is_open_access": False,
                "country_primary": "FR",
                "publisher": "LLM Publisher",
                "venue": "LLM Venue",
            }
        },
    )

    openalex_record_id = uuid4()
    canonical = CanonicalEnrichment(
        result_record_id=result.id,
        source_record_ids=[openalex_record_id],
        publication_year=2020,
        venue="Canonical Venue",
        field_provenance={
            "publication_year": FieldProvenance(
                provider=EnrichmentProvider.OPENALEX,
                enrichment_record_id=openalex_record_id,
                match_strategy=EnrichmentMatchStrategy.DOI,
            ),
            "venue": FieldProvenance(
                provider=EnrichmentProvider.OPENALEX,
                enrichment_record_id=openalex_record_id,
                match_strategy=EnrichmentMatchStrategy.DOI,
            ),
        },
    )

    scopus_record = EnrichmentRecord(
        result_record_id=result.id,
        provider=EnrichmentProvider.SCOPUS,
        provider_record_id="scopus:1",
        match_strategy=EnrichmentMatchStrategy.DOI,
        raw_payload={
            "openaccessFlag": True,
            "affiliation": [{"affiliation-country": "United States"}],
        },
    )
    core_record = EnrichmentRecord(
        result_record_id=result.id,
        provider=EnrichmentProvider.CORE,
        provider_record_id="core:1",
        match_strategy=EnrichmentMatchStrategy.DOI,
        raw_payload={
            "language": {"code": "en", "name": "English"},
            "publisher": "Trusted Publisher",
        },
    )

    row = _build_view_row(
        result=result,
        query_text="liquid biopsy cancer detection review",
        provider_records=[scopus_record, core_record],
        canonical=canonical,
    )

    assert row["publication_year"] == 2020
    assert row["venue"] == "Canonical Venue"
    assert row["language"] == "en"
    assert row["is_open_access"] is True
    assert row["country_primary"] == "United States"
    assert row["publisher"] == "Trusted Publisher"
    assert row["bias_field_sources"] == {
        "publication_year": "openalex",
        "language": "core:raw",
        "is_open_access": "scopus:raw",
        "country_primary": "scopus:raw",
        "publisher": "core:raw",
        "venue": "openalex",
    }


def test_build_view_row_uses_structured_llm_bias_fields_when_enrichment_is_missing() -> None:
    result = ResultRecord(
        id=uuid4(),
        run_id=uuid4(),
        query_id=uuid4(),
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="openai/gpt-4o-mini",
        provider_name="openrouter",
        rank=1,
        title="Bias in Scholarly Retrieval",
        year=2024,
        venue="Journal of Retrieval Studies",
        publisher="Journal Press",
        language="en",
        raw_payload={
            "bias_fields": {
                "publication_year": 2024,
                "language": "en",
                "is_open_access": True,
                "country_primary": "US",
                "publisher": "Journal Press",
                "venue": "Journal of Retrieval Studies",
            }
        },
    )

    row = _build_view_row(
        result=result,
        query_text="bias in academic search",
        provider_records=[],
        canonical=None,
    )

    assert row["publication_year"] == 2024
    assert row["language"] == "en"
    assert row["is_open_access"] is True
    assert row["country_primary"] == "US"
    assert row["publisher"] == "Journal Press"
    assert row["venue"] == "Journal of Retrieval Studies"
    assert all(source == "llm_structured" for source in row["bias_field_sources"].values())
