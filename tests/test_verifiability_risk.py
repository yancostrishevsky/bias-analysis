from __future__ import annotations

from backend.adapters.openalex.enrichment_mapper import map_openalex_payload_to_enrichment
from backend.application.enrichment.canonicalize import canonicalize_enrichment_records
from backend.application.records.service import build_unified_record_rows
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
    RunType,
)
from backend.storage.repository import Repository


def test_openalex_mapper_preserves_provider_doi_and_year() -> None:
    result = ResultRecord(
        run_id=Run().id,
        query_id=Query(run_id=Run().id, text="q", position=1).id,
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="model-a",
        provider_name="openrouter",
        rank=1,
        title="Deep learning in radiology",
        doi="10.1148/radiol.2017171111",
        year=2018,
    )
    payload = {
        "id": "https://openalex.org/W1",
        "display_name": "Deep Learning in Radiology",
        "doi": "https://doi.org/10.1016/j.acra.2018.02.018",
        "publication_year": 2019,
        "primary_location": {"source": {"display_name": "Academic Radiology", "publisher": "Elsevier BV"}},
        "authorships": [],
        "ids": {"doi": "https://doi.org/10.1016/j.acra.2018.02.018"},
    }

    record = map_openalex_payload_to_enrichment(
        result=result,
        payload=payload,
        match_strategy=EnrichmentMatchStrategy.TITLE_YEAR,
    )

    assert record is not None
    assert record.doi == "10.1016/j.acra.2018.02.018"
    assert record.publication_year == 2019
    assert record.external_ids["doi"] == "https://doi.org/10.1016/j.acra.2018.02.018"


def test_alias_and_initial_author_differences_do_not_inflate_high_risk(repository: Repository) -> None:
    row = _build_row(
        repository=repository,
        result_kwargs={
            "title": "Artificial intelligence in radiology",
            "doi": "10.1038/s41568-018-0016-5",
            "year": 2018,
            "authors": ["Hosny, A.", "Parmar, C.", "Quackenbush, J."],
            "venue": "Nature Reviews Cancer",
            "publisher": "Springer Nature",
        },
        enrichment=EnrichmentRecord(
            result_record_id=_PLACEHOLDER_RESULT_ID,
            provider=EnrichmentProvider.OPENALEX,
            provider_record_id="openalex:ai-radiology",
            match_strategy=EnrichmentMatchStrategy.DOI,
            doi="10.1038/s41568-018-0016-5",
            title="Artificial intelligence in radiology",
            publication_year=2018,
            authors=["Ahmed Hosny", "Chintan Parmar", "John Quackenbush"],
            venue="Nat Rev Cancer",
            publisher="Nature Portfolio",
        ),
    )

    assert row.hallucination_risk_bucket == "low"
    assert row.conflict_count == 0
    assert row.risk_reasons == []


def test_doi_resolves_to_different_title_remains_high_risk(repository: Repository) -> None:
    row = _build_row(
        repository=repository,
        result_kwargs={
            "title": "Liquid biopsy in cancer detection: a review",
            "doi": "10.1038/s41568-020-00322-0",
            "year": 2020,
            "authors": ["M. Wan", "S. Heider", "C. Gale"],
            "venue": "Nature Reviews Cancer",
            "publisher": "Nature Publishing Group",
        },
        enrichment=EnrichmentRecord(
            result_record_id=_PLACEHOLDER_RESULT_ID,
            provider=EnrichmentProvider.OPENALEX,
            provider_record_id="openalex:contradiction",
            match_strategy=EnrichmentMatchStrategy.DOI,
            doi="10.1038/s41568-020-00322-0",
            title="Antitumour immunity regulated by aberrant ERBB family signalling",
            publication_year=2020,
            authors=["Shogo Kumagai", "Shohei Koyama", "Hiroyoshi Nishikawa"],
            venue="Nature reviews. Cancer",
            publisher="Nature Portfolio",
        ),
    )

    assert row.hallucination_risk_bucket == "high"
    assert "title_mismatch" in row.risk_reasons


def test_title_year_match_exposes_provider_doi_conflict(repository: Repository) -> None:
    run, query, llm_call, result = _persist_llm_result(
        repository,
        {
            "title": "Deep learning in radiology",
            "doi": "10.1148/radiol.2017171111",
            "year": 2018,
            "authors": ["Mazurowski, M."],
            "venue": "Radiology",
            "publisher": "RSNA",
        },
    )
    payload = {
        "id": "https://openalex.org/W2",
        "display_name": "Deep Learning in Radiology",
        "doi": "https://doi.org/10.1016/j.acra.2018.02.018",
        "publication_year": 2018,
        "primary_location": {"source": {"display_name": "Academic Radiology", "publisher": "Elsevier BV"}},
        "authorships": [{"author": {"display_name": "Maciej A. Mazurowski"}, "institutions": []}],
        "ids": {"doi": "https://doi.org/10.1016/j.acra.2018.02.018"},
    }
    enrichment = map_openalex_payload_to_enrichment(
        result=result,
        payload=payload,
        match_strategy=EnrichmentMatchStrategy.TITLE_YEAR,
    )
    assert enrichment is not None
    canonical = canonicalize_enrichment_records(result_record_id=result.id, records=[enrichment])
    repository.replace_enrichments(result.id, [enrichment], canonical)

    row = build_unified_record_rows(repository=repository, run_id=run.id)[0]

    assert row.parsed_doi == "10.1148/radiol.2017171111"
    assert row.enriched_doi == "10.1016/j.acra.2018.02.018"
    assert row.verification_trace["doi_conflict"] is True
    assert "doi_conflict" in row.risk_reasons
    assert row.hallucination_risk_bucket == "high"
    assert llm_call.parse_success is True
    assert query.text == "bias in academic search"


def test_provider_failure_plus_completeness_defaults_to_medium(repository: Repository) -> None:
    run, _, _, result = _persist_llm_result(
        repository,
        {
            "title": "Complete Looking Unverified Paper",
            "doi": "10.1000/example",
            "year": 2024,
            "authors": ["Ada Lovelace"],
            "venue": "Journal of Verification",
            "publisher": "Publisher A",
            "language": "en",
            "url": "https://doi.org/10.1000/example",
        },
    )
    records = [
        EnrichmentRecord(
            result_record_id=result.id,
            provider=EnrichmentProvider.OPENALEX,
            provider_record_id="openalex:skipped",
            status=ExecutionStatus.SKIPPED,
            error_message="OpenAlex did not match the record",
        ),
        EnrichmentRecord(
            result_record_id=result.id,
            provider=EnrichmentProvider.SEMANTIC_SCHOLAR,
            provider_record_id="semantic_scholar:failed",
            status=ExecutionStatus.FAILED,
            error_message="HTTP 429",
        ),
    ]
    repository.replace_enrichments(result.id, records, None)

    row = build_unified_record_rows(repository=repository, run_id=run.id)[0]

    assert row.unmatched_reason == "provider_failed"
    assert row.suspicious_completeness is True
    assert row.hallucination_risk_bucket == "medium"
    assert row.risk_reasons == ["unmatched:provider_failed", "suspicious_completeness"]


def test_successful_not_found_unmatched_still_high_when_complete(repository: Repository) -> None:
    run, _, _, result = _persist_llm_result(
        repository,
        {
            "title": "Complete Looking Missing Paper",
            "doi": "10.1000/missing",
            "year": 2024,
            "authors": ["Ada Lovelace"],
            "venue": "Journal of Verification",
            "publisher": "Publisher A",
            "language": "en",
            "url": "https://doi.org/10.1000/missing",
        },
    )
    records = [
        EnrichmentRecord(
            result_record_id=result.id,
            provider=EnrichmentProvider.OPENALEX,
            provider_record_id="openalex:skipped",
            status=ExecutionStatus.SKIPPED,
            error_message="OpenAlex did not match the record",
        ),
        EnrichmentRecord(
            result_record_id=result.id,
            provider=EnrichmentProvider.SCOPUS,
            provider_record_id="scopus:skipped",
            status=ExecutionStatus.SKIPPED,
            error_message="Scopus did not match the record",
        ),
    ]
    repository.replace_enrichments(result.id, records, None)

    row = build_unified_record_rows(repository=repository, run_id=run.id)[0]

    assert row.unmatched_reason == "not_found"
    assert row.hallucination_risk_bucket == "high"
    assert "unmatched:not_found" in row.risk_reasons


def _build_row(
    *,
    repository: Repository,
    result_kwargs: dict,
    enrichment: EnrichmentRecord,
):
    run, _, _, result = _persist_llm_result(repository, result_kwargs)
    enrichment = enrichment.model_copy(update={"result_record_id": result.id})
    canonical = canonicalize_enrichment_records(result_record_id=result.id, records=[enrichment])
    repository.replace_enrichments(result.id, [enrichment], canonical)
    return build_unified_record_rows(repository=repository, run_id=run.id)[0]


def _persist_llm_result(repository: Repository, result_kwargs: dict) -> tuple[Run, Query, LLMCall, ResultRecord]:
    result_kwargs = dict(result_kwargs)
    run = Run(run_type=RunType.LLM_AUDIT, selected_models=["model-a"], top_k=10)
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
    )
    repository.save_llm_call(llm_call)
    result = ResultRecord(
        run_id=run.id,
        query_id=query.id,
        llm_call_id=llm_call.id,
        origin_type=ResultOriginType.LLM_RESPONSE,
        model_name="model-a",
        provider_name="openrouter",
        execution_status=ExecutionStatus.COMPLETED,
        rank=1,
        canonical_identifier=(result_kwargs.get("doi") or result_kwargs["title"]).lower(),
        language=result_kwargs.pop("language", "en"),
        url=result_kwargs.pop("url", None),
        **result_kwargs,
    )
    repository.save_results([result])
    return run, query, llm_call, result


_PLACEHOLDER_RESULT_ID = Run().id
