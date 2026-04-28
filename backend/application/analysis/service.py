"""Run analysis builders for the interactive detail page."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence
from uuid import UUID

from backend.application.run_artifacts import get_run_artifacts_writer
from backend.domain import (
    AnalysisFilterOption,
    AnalysisFilters,
    BiasFieldSourceRow,
    BiasFieldWarningRow,
    CanonicalEnrichment,
    ConcentrationRow,
    CoverageRow,
    DistributionRow,
    EnrichmentProvider,
    EnrichmentRecord,
    LLMAnalysisSection,
    LLMCallRow,
    LLMMetricRow,
    OverlapRow,
    Query,
    ResultRecord,
    ResultOriginType,
    RunAnalysis,
    RunAnalysisSummary,
    RunDetail,
    RunType,
    TopKComparisonRow,
)
from backend.storage.repository import Repository

_BIAS_FIELDS = (
    "publication_year",
    "language",
    "is_open_access",
    "country_primary",
    "publisher",
    "venue",
)
_PROVIDER_PRIORITY = (
    EnrichmentProvider.OPENALEX,
    EnrichmentProvider.SEMANTIC_SCHOLAR,
    EnrichmentProvider.SCOPUS,
    EnrichmentProvider.CORE,
)
_UNKNOWN_TEXT_MARKERS = {"unknown", "n/a", "na", "none", "null"}
_LANGUAGE_NAME_TO_CODE = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}


def build_run_analysis(*, repository: Repository, run_id: UUID) -> RunAnalysis:
    """Build the dashboard payload for one run."""

    run_detail = repository.get_run_detail(run_id)
    results = repository.list_results(run_id)
    enrichments_by_result = repository.list_enrichments_by_result(run_id)
    llm_calls = repository.list_llm_calls(run_id)

    view_rows: list[dict[str, Any]] = []
    baseline_view_rows: list[dict[str, Any]] = []
    bias_warnings: list[BiasFieldWarningRow] = []
    for result in results:
        provider_records, canonical = enrichments_by_result.get(result.id, ([], None))
        row = _build_view_row(
            result=result,
            query_text=_query_text(run_detail.queries, result.query_id),
            provider_records=provider_records,
            canonical=canonical,
        )
        view_rows.append(row)
        baseline_view_rows.append(
            _build_baseline_view_row(
                result=result,
                query_text=_query_text(run_detail.queries, result.query_id),
            )
        )
        bias_warnings.extend(_bias_field_warnings(row))
    entity_label = "Model" if run_detail.run.run_type == RunType.LLM_AUDIT else "Source"
    entities = sorted({row["entity"] for row in view_rows if row["entity"] != "overall"})
    top_ks = _top_ks(run_detail.run.top_k)

    return RunAnalysis(
        summary=RunAnalysisSummary(
            run_id=str(run_detail.run.id),
            run_type=run_detail.run.run_type,
            status=run_detail.run.status.value,
            total_results=len(results),
            query_count=len(run_detail.queries),
            entity_label=entity_label,
            entity_count=len(entities),
            completed_entity_count=sum(
                1 for status in run_detail.entity_statuses if status.status.value == "completed"
            ),
            failed_entity_count=sum(
                1 for status in run_detail.entity_statuses if status.failed_count > 0
            ),
        ),
        filters=AnalysisFilters(
            queries=[
                AnalysisFilterOption(value=str(query.id), label=f"Q{query.position}: {query.text}")
                for query in run_detail.queries
            ],
            entities=[
                AnalysisFilterOption(value=entity, label=entity)
                for entity in entities
            ],
            top_ks=top_ks,
            default_top_k=run_detail.run.top_k,
        ),
        distributions=_distribution_rows(view_rows=view_rows, queries=run_detail.queries),
        coverage_rows=_coverage_rows(view_rows=view_rows, queries=run_detail.queries),
        baseline_coverage_rows=_coverage_rows(view_rows=baseline_view_rows, queries=run_detail.queries),
        bias_field_sources=_bias_field_source_rows(view_rows),
        bias_field_warnings=bias_warnings,
        top_k_rows=_top_k_rows(view_rows=view_rows, queries=run_detail.queries, top_ks=top_ks),
        overlap_rows=_overlap_rows(view_rows=view_rows),
        concentration_rows=_concentration_rows(view_rows=view_rows),
        llm=_llm_analysis(
            run_detail=run_detail,
            view_rows=view_rows,
            llm_calls=llm_calls,
            llm_artifact_metadata=_read_llm_artifact_metadata(run_id=run_id, queries=run_detail.queries),
        ),
    )


def _build_view_row(
    *,
    result: ResultRecord,
    query_text: str,
    provider_records: Sequence[EnrichmentRecord],
    canonical: CanonicalEnrichment | None,
) -> dict[str, Any]:
    entity = result.model_name or result.source_name or "overall"
    canonical_doi = canonical.doi if canonical else None
    doi = canonical_doi or result.doi
    bias_field_sources: dict[str, str] = {}
    provider_raw_recoveries: dict[str, str] = {}
    upstream_unused_sources: dict[str, str] = {}
    bias_values = {
        field_name: _resolve_bias_field(
            field_name=field_name,
            result=result,
            canonical=canonical,
            provider_records=provider_records,
            bias_field_sources=bias_field_sources,
            provider_raw_recoveries=provider_raw_recoveries,
            upstream_unused_sources=upstream_unused_sources,
        )
        for field_name in _BIAS_FIELDS
    }
    return {
        "result_id": str(result.id),
        "query_id": str(result.query_id),
        "query_text": query_text,
        "entity": entity,
        "origin_type": result.origin_type.value,
        "rank": result.rank,
        "canonical_identifier": result.canonical_identifier or doi or result.title.lower(),
        "title": canonical.title if canonical and canonical.title else result.title,
        "doi": doi,
        "abstract": canonical.abstract if canonical else None,
        "publication_year": bias_values["publication_year"],
        "language": bias_values["language"],
        "is_open_access": bias_values["is_open_access"],
        "open_access_status": canonical.open_access_status if canonical else None,
        "citation_count": canonical.citation_count if canonical else None,
        "publisher": bias_values["publisher"],
        "venue": bias_values["venue"],
        "country_primary": bias_values["country_primary"],
        "country_dominant": canonical.country_dominant if canonical else None,
        "countries": canonical.countries if canonical else [],
        "affiliations": canonical.affiliations if canonical else [],
        "fields_of_study": canonical.fields_of_study if canonical else [],
        "landing_page_url": canonical.landing_page_url if canonical else result.url,
        "pdf_url": canonical.pdf_url if canonical else None,
        "verified": canonical is not None and bool(canonical.source_record_ids),
        "bias_field_sources": bias_field_sources,
        "bias_field_provider_raw_recoveries": provider_raw_recoveries,
        "bias_field_upstream_unused_sources": upstream_unused_sources,
        "result_title": result.title,
        "result_year": result.year,
        "result_venue": result.venue,
        "result_doi": result.doi,
    }


def _build_baseline_view_row(
    *,
    result: ResultRecord,
    query_text: str,
) -> dict[str, Any]:
    entity = result.model_name or result.source_name or "overall"
    return {
        "result_id": str(result.id),
        "query_id": str(result.query_id),
        "query_text": query_text,
        "entity": entity,
        "origin_type": result.origin_type.value,
        "rank": result.rank,
        "canonical_identifier": result.canonical_identifier or result.doi or result.title.lower(),
        "title": result.title,
        "doi": result.doi,
        "abstract": None,
        "publication_year": _result_bias_value(result, "publication_year"),
        "language": _result_bias_value(result, "language"),
        "is_open_access": _result_bias_value(result, "is_open_access"),
        "open_access_status": None,
        "citation_count": None,
        "publisher": _result_bias_value(result, "publisher"),
        "venue": _result_bias_value(result, "venue"),
        "country_primary": _result_bias_value(result, "country_primary"),
        "country_dominant": None,
        "countries": [],
        "affiliations": [],
        "fields_of_study": [],
        "landing_page_url": result.url,
        "pdf_url": None,
        "verified": False,
        "bias_field_sources": {},
        "bias_field_provider_raw_recoveries": {},
        "bias_field_upstream_unused_sources": {},
        "result_title": result.title,
        "result_year": result.year,
        "result_venue": result.venue,
        "result_doi": result.doi,
    }


def _resolve_bias_field(
    *,
    field_name: str,
    result: ResultRecord,
    canonical: CanonicalEnrichment | None,
    provider_records: Sequence[EnrichmentRecord],
    bias_field_sources: dict[str, str],
    provider_raw_recoveries: dict[str, str],
    upstream_unused_sources: dict[str, str],
) -> Any:
    if canonical is not None:
        canonical_value = getattr(canonical, field_name)
        if _has_value(canonical_value):
            bias_field_sources[field_name] = _canonical_field_source(canonical, field_name)
            return canonical_value

    provider_records = _sorted_provider_records(provider_records)
    for record in provider_records:
        normalized_value = getattr(record, field_name)
        if _has_value(normalized_value):
            bias_field_sources[field_name] = record.provider.value
            return normalized_value

    provider_raw_source: str | None = None
    provider_raw_value: Any = None
    for record in provider_records:
        provider_raw_value = _provider_raw_bias_value(record, field_name)
        if _has_value(provider_raw_value):
            provider_raw_source = f"{record.provider.value}:raw"
            break

    result_value = _result_bias_value(result, field_name)
    if _has_value(provider_raw_value):
        if _has_value(result_value):
            provider_raw_recoveries[field_name] = provider_raw_source or "provider_raw"
            bias_field_sources[field_name] = provider_raw_source or "provider_raw"
            return provider_raw_value
        provider_raw_recoveries[field_name] = provider_raw_source or "provider_raw"
        bias_field_sources[field_name] = provider_raw_source or "provider_raw"
        return provider_raw_value

    if _has_value(result_value):
        bias_field_sources[field_name] = _result_bias_source(result)
        return result_value

    if provider_raw_source is not None:
        upstream_unused_sources[field_name] = provider_raw_source
    bias_field_sources[field_name] = "unknown"
    return None


def _canonical_field_source(canonical: CanonicalEnrichment, field_name: str) -> str:
    provenance = canonical.field_provenance.get(field_name)
    if provenance is None:
        return "canonical"
    return provenance.provider.value


def _sorted_provider_records(records: Sequence[EnrichmentRecord]) -> list[EnrichmentRecord]:
    priority = {provider: index for index, provider in enumerate(_PROVIDER_PRIORITY)}
    return [
        record
        for record in sorted(
            records,
            key=lambda record: (
                priority.get(record.provider, len(priority)),
                record.enriched_at,
            ),
        )
        if record.status.value == "completed"
    ]


def _provider_raw_bias_value(record: EnrichmentRecord, field_name: str) -> Any:
    payload = record.raw_payload
    if not isinstance(payload, dict):
        return None
    if record.provider == EnrichmentProvider.OPENALEX:
        return _openalex_raw_bias_value(payload, field_name)
    if record.provider == EnrichmentProvider.SEMANTIC_SCHOLAR:
        return _semantic_raw_bias_value(payload, field_name)
    if record.provider == EnrichmentProvider.SCOPUS:
        return _scopus_raw_bias_value(payload, field_name)
    if record.provider == EnrichmentProvider.CORE:
        return _core_raw_bias_value(payload, field_name)
    return None


def _result_bias_value(result: ResultRecord, field_name: str) -> Any:
    if field_name == "publication_year":
        return result.year or _coerce_year(_result_bias_fields(result).get("publication_year"))
    if field_name == "language":
        return _normalize_language_value(result.language, _result_bias_fields(result).get("language"))
    if field_name == "publisher":
        return _clean_optional_text(result.publisher, _result_bias_fields(result).get("publisher"))
    if field_name == "venue":
        return _clean_optional_text(result.venue, _result_bias_fields(result).get("venue"))
    if field_name == "is_open_access":
        return _coerce_bool_value(_result_bias_fields(result).get("is_open_access"))
    if field_name == "country_primary":
        return _normalize_country_value(_result_bias_fields(result).get("country_primary"))
    return None


def _result_bias_source(result: ResultRecord) -> str:
    if result.origin_type == ResultOriginType.LLM_RESPONSE:
        return "llm_structured"
    if result.source_name:
        return result.source_name
    return "result_record"


def _result_bias_fields(result: ResultRecord) -> dict[str, Any]:
    raw_payload = result.raw_payload if isinstance(result.raw_payload, dict) else {}
    bias_fields = raw_payload.get("bias_fields")
    if isinstance(bias_fields, dict):
        return bias_fields
    raw_item = raw_payload.get("raw_item")
    if isinstance(raw_item, dict):
        return raw_item
    return {}


def _openalex_raw_bias_value(payload: dict[str, Any], field_name: str) -> Any:
    primary_location = payload.get("primary_location") if isinstance(payload.get("primary_location"), dict) else {}
    source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
    if field_name == "publication_year":
        return _coerce_year(payload.get("publication_year"))
    if field_name == "language":
        return _normalize_language_value(payload.get("language"))
    if field_name == "is_open_access":
        open_access = payload.get("open_access") if isinstance(payload.get("open_access"), dict) else {}
        return _coerce_bool_value(open_access.get("is_oa"))
    if field_name == "country_primary":
        countries = _openalex_countries(payload.get("authorships"))
        return _country_primary_from_names(countries)
    if field_name == "publisher":
        return _clean_optional_text(
            source.get("host_organization_name"),
            source.get("publisher"),
            source.get("display_name"),
        )
    if field_name == "venue":
        return _clean_optional_text(source.get("display_name"))
    return None


def _semantic_raw_bias_value(payload: dict[str, Any], field_name: str) -> Any:
    journal = payload.get("journal") if isinstance(payload.get("journal"), dict) else {}
    publication_venue = payload.get("publicationVenue") if isinstance(payload.get("publicationVenue"), dict) else {}
    if field_name == "publication_year":
        return _coerce_year(payload.get("year"))
    if field_name == "language":
        return _normalize_language_value(payload.get("language"))
    if field_name == "is_open_access":
        return _coerce_bool_value(payload.get("isOpenAccess"))
    if field_name == "publisher":
        return _clean_optional_text(journal.get("publisher"), publication_venue.get("publisher"))
    if field_name == "venue":
        return _clean_optional_text(publication_venue.get("name"), journal.get("name"), payload.get("venue"))
    return None


def _scopus_raw_bias_value(payload: dict[str, Any], field_name: str) -> Any:
    if field_name == "publication_year":
        return _coerce_year(payload.get("prism:coverDate"))
    if field_name == "language":
        return _normalize_language_value(payload.get("prism:language"), payload.get("language"))
    if field_name == "is_open_access":
        return _coerce_bool_value(payload.get("openaccessFlag"), payload.get("openaccess"))
    if field_name == "country_primary":
        return _country_primary_from_names(_scopus_countries(payload))
    if field_name == "publisher":
        return _clean_optional_text(payload.get("publishername"), payload.get("dc:publisher"))
    if field_name == "venue":
        return _clean_optional_text(payload.get("prism:publicationName"))
    return None


def _core_raw_bias_value(payload: dict[str, Any], field_name: str) -> Any:
    if field_name == "publication_year":
        return _coerce_year(payload.get("year"), payload.get("publishedDate"))
    if field_name == "language":
        return _normalize_language_value(payload.get("language"))
    if field_name == "is_open_access":
        return _coerce_bool_value(payload.get("isOpenAccess"), payload.get("downloadUrl"))
    if field_name == "publisher":
        return _clean_optional_text(payload.get("publisher"))
    if field_name == "venue":
        journals = payload.get("journals")
        if isinstance(journals, list):
            for journal in journals:
                if not isinstance(journal, dict):
                    continue
                title = _clean_optional_text(journal.get("title"))
                if title is not None:
                    return title
        return _clean_optional_text(payload.get("journal"), payload.get("venue"))
    return None


def _openalex_countries(authorships: Any) -> list[str]:
    countries: list[str] = []
    seen: set[str] = set()
    if not isinstance(authorships, list):
        return countries
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        institutions = authorship.get("institutions")
        if not isinstance(institutions, list):
            continue
        for institution in institutions:
            if not isinstance(institution, dict):
                continue
            country = _normalize_country_value(institution.get("country_code"))
            if country and country not in seen:
                seen.add(country)
                countries.append(country)
    return countries


def _scopus_countries(payload: dict[str, Any]) -> list[str]:
    affiliations = payload.get("affiliation")
    if not isinstance(affiliations, list):
        return []
    countries: list[str] = []
    seen: set[str] = set()
    for affiliation in affiliations:
        if not isinstance(affiliation, dict):
            continue
        country = _normalize_country_value(affiliation.get("affiliation-country"))
        if country and country not in seen:
            seen.add(country)
            countries.append(country)
    return countries


def _normalize_language_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, dict):
            code = _clean_optional_text(value.get("code"))
            if code:
                return code.lower()
            name = _clean_optional_text(value.get("name"))
            if name:
                lowered_name = name.lower()
                return _LANGUAGE_NAME_TO_CODE.get(lowered_name, lowered_name)
        text = _clean_optional_text(value)
        if text is None:
            continue
        lowered = text.lower()
        if lowered in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[lowered]
        if len(lowered) == 2 and lowered.isalpha():
            return lowered
        return lowered
    return None


def _clean_optional_text(*values: Any) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
            cleaned = cleaned[1:-1].strip()
        if not cleaned or cleaned.lower() in _UNKNOWN_TEXT_MARKERS:
            continue
        return cleaned
    return None


def _coerce_bool_value(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if cleaned in {"1", "true", "yes", "open", "oa"}:
                return True
            if cleaned in {"0", "false", "no", "closed"}:
                return False
            if cleaned in _UNKNOWN_TEXT_MARKERS:
                continue
            if cleaned.startswith("http"):
                return True
    return None


def _coerce_year(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned or cleaned.lower() in _UNKNOWN_TEXT_MARKERS:
                continue
            digits = "".join(character for character in cleaned if character.isdigit())
            if len(digits) >= 4:
                try:
                    return int(digits[:4])
                except ValueError:
                    continue
    return None


def _normalize_country_value(value: Any) -> str | None:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return None
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned.upper()
    return cleaned


def _country_primary_from_names(countries: list[str]) -> str | None:
    if not countries:
        return None
    if len(countries) == 1:
        return countries[0]
    return "MULTI"


def _distribution_rows(*, view_rows: list[dict[str, Any]], queries: Sequence[Query]) -> list[DistributionRow]:
    rows: list[DistributionRow] = []
    metric_extractors = {
        "publication_year_bucket": lambda row: _publication_year_bucket(row.get("publication_year")),
        "language": lambda row: _clean_text(row.get("language")) or "unknown",
        "open_access": lambda row: _open_access_label(row.get("is_open_access"), row.get("open_access_status")),
        "country": lambda row: _country_label(row),
        "publisher": lambda row: _clean_text(row.get("publisher")) or "unknown",
        "venue": lambda row: _clean_text(row.get("venue")) or "unknown",
    }

    scopes = _scopes(view_rows=view_rows, queries=queries, include_query_entity=True)
    for metric, extractor in metric_extractors.items():
        for query_id, entity, subset in scopes:
            counts: Counter[str] = Counter()
            for row in subset:
                label = extractor(row)
                if label:
                    counts[label] += 1
            total = sum(counts.values())
            if total == 0:
                continue
            for label, count in counts.most_common(12):
                rows.append(
                    DistributionRow(
                        metric=metric,
                        query_id=query_id,
                        entity=entity,
                        label=label,
                        count=count,
                        ratio=float(count / total),
                    )
                )
    return rows


def _coverage_rows(*, view_rows: list[dict[str, Any]], queries: Sequence[Query]) -> list[CoverageRow]:
    fields = (
        "doi",
        "title",
        "abstract",
        "publication_year",
        "language",
        "is_open_access",
        "citation_count",
        "publisher",
        "venue",
        "country_primary",
        "affiliations",
        "fields_of_study",
        "landing_page_url",
        "pdf_url",
    )
    rows: list[CoverageRow] = []
    for query_id, entity, subset in _scopes(view_rows=view_rows, queries=queries, include_query_entity=True):
        total_count = len(subset)
        for field_name in fields:
            populated = sum(1 for item in subset if _has_value(item.get(field_name)))
            rows.append(
                CoverageRow(
                    query_id=query_id,
                    entity=entity,
                    field=field_name,
                    populated_count=populated,
                    missing_count=total_count - populated,
                    total_count=total_count,
                    coverage_ratio=(float(populated / total_count) if total_count else 0.0),
                )
            )
    return rows


def _bias_field_source_rows(view_rows: Sequence[dict[str, Any]]) -> list[BiasFieldSourceRow]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in view_rows:
        sources = row.get("bias_field_sources")
        if not isinstance(sources, dict):
            continue
        for field_name in _BIAS_FIELDS:
            source = sources.get(field_name)
            if isinstance(source, str) and source:
                counts[(field_name, source)] += 1
    return [
        BiasFieldSourceRow(field=field_name, source=source, count=count)
        for (field_name, source), count in sorted(counts.items())
    ]


def _bias_field_warnings(row: dict[str, Any]) -> list[BiasFieldWarningRow]:
    warnings: list[BiasFieldWarningRow] = []
    recoveries = row.get("bias_field_provider_raw_recoveries")
    if isinstance(recoveries, dict):
        for field_name, source in recoveries.items():
            if isinstance(source, str) and source:
                warnings.append(
                    BiasFieldWarningRow(
                        result_id=row["result_id"],
                        query_id=row["query_id"],
                        entity=row["entity"],
                        field=field_name,
                        reason="Recovered from completed provider raw payload because canonical/provider mapping missed it",
                        upstream_source=source,
                    )
                )
    unused = row.get("bias_field_upstream_unused_sources")
    if isinstance(unused, dict):
        for field_name, source in unused.items():
            if isinstance(source, str) and source:
                warnings.append(
                    BiasFieldWarningRow(
                        result_id=row["result_id"],
                        query_id=row["query_id"],
                        entity=row["entity"],
                        field=field_name,
                        reason="Remained unknown despite completed provider raw payload containing a recoverable value",
                        upstream_source=source,
                    )
                )
    return warnings


def _top_k_rows(
    *,
    view_rows: list[dict[str, Any]],
    queries: Sequence[Query],
    top_ks: Sequence[int],
) -> list[TopKComparisonRow]:
    rows: list[TopKComparisonRow] = []
    metrics = (
        ("open_access_share", lambda items: _share_true(item.get("is_open_access") for item in items)),
        ("citation_mean", lambda items: _mean_numeric(item.get("citation_count") for item in items)),
        ("publication_year_mean", lambda items: _mean_numeric(item.get("publication_year") for item in items)),
    )

    for query_id, entity, subset in _scopes(view_rows=view_rows, queries=queries, include_query_entity=True):
        ordered = sorted(subset, key=lambda item: item["rank"])
        for k in top_ks:
            top_subset = ordered[:k]
            for metric_name, metric_fn in metrics:
                top_value = metric_fn(top_subset)
                overall_value = metric_fn(ordered)
                delta = None
                if top_value is not None and overall_value is not None:
                    delta = top_value - overall_value
                rows.append(
                    TopKComparisonRow(
                        query_id=query_id,
                        entity=entity,
                        k=k,
                        metric=metric_name,
                        top_k_value=top_value,
                        overall_value=overall_value,
                        delta=delta,
                    )
                )
    return rows


def _overlap_rows(*, view_rows: list[dict[str, Any]]) -> list[OverlapRow]:
    by_query_entity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in view_rows:
        by_query_entity[(row["query_id"], row["entity"])].append(row)

    grouped_by_query: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for (query_id, entity), subset in by_query_entity.items():
        grouped_by_query[query_id][entity] = sorted(subset, key=lambda item: item["rank"])

    rows: list[OverlapRow] = []
    aggregated: dict[tuple[str, str], list[OverlapRow]] = defaultdict(list)
    for query_id, entities in grouped_by_query.items():
        for left_entity, right_entity in combinations(sorted(entities), 2):
            left = entities[left_entity]
            right = entities[right_entity]
            overlap_row = OverlapRow(
                query_id=query_id,
                left_entity=left_entity,
                right_entity=right_entity,
                jaccard=_jaccard(left, right),
                overlap_at_k=_overlap_at_k(left, right),
                rank_biased_overlap=_rbo(left, right),
                top_1_agreement=_top_1_agreement(left, right),
            )
            rows.append(overlap_row)
            aggregated[(left_entity, right_entity)].append(overlap_row)

    for (left_entity, right_entity), values in aggregated.items():
            rows.append(
            OverlapRow(
                query_id=None,
                left_entity=left_entity,
                right_entity=right_entity,
                jaccard=_mean_numeric(value.jaccard for value in values),
                overlap_at_k=_mean_numeric(value.overlap_at_k for value in values),
                rank_biased_overlap=_mean_numeric(value.rank_biased_overlap for value in values),
                top_1_agreement=_mean_numeric(value.top_1_agreement for value in values),
            )
        )
    return rows


def _concentration_rows(*, view_rows: list[dict[str, Any]]) -> list[ConcentrationRow]:
    rows: list[ConcentrationRow] = []
    scopes = [("overall", view_rows)] + [
        (entity, subset)
        for entity, subset in _group_by_entity(view_rows).items()
    ]
    for entity, subset in scopes:
        rows.append(
            ConcentrationRow(
                entity=entity,
                metric="publisher_hhi",
                value=_hhi(_clean_text(item.get("publisher")) for item in subset),
            )
        )
        rows.append(
            ConcentrationRow(
                entity=entity,
                metric="venue_hhi",
                value=_hhi(_clean_text(item.get("venue")) for item in subset),
            )
        )
    return rows


def _llm_analysis(
    *,
    run_detail: RunDetail,
    view_rows: list[dict[str, Any]],
    llm_calls: Sequence[Any],
    llm_artifact_metadata: dict[tuple[str, str], dict[str, Any]],
) -> LLMAnalysisSection | None:
    if run_detail.run.run_type != RunType.LLM_AUDIT:
        return None

    call_rows = [
        LLMCallRow(
            query_id=str(call.query_id),
            model_name=call.model_name,
            status=call.status.value,
            parse_success=call.parse_success,
            parse_mode=_clean_optional_text(
                llm_artifact_metadata.get((str(call.query_id), call.model_name), {}).get("parse_mode")
            ),
            partial_json_recovery=bool(
                llm_artifact_metadata.get((str(call.query_id), call.model_name), {}).get("partial_json_recovery")
            ),
            parsed_item_count=_coerce_int(
                llm_artifact_metadata.get((str(call.query_id), call.model_name), {}).get("parsed_item_count")
            ),
            latency_ms=call.latency_ms,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            total_tokens=call.total_tokens,
            error_message=call.error_message or call.parse_error,
        )
        for call in llm_calls
    ]

    metrics: list[LLMMetricRow] = []
    for entity, subset in [("overall", view_rows)] + list(_group_by_entity(view_rows).items()):
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="verification_coverage_rate",
                value=_share_true(item.get("verified") for item in subset),
                count=len(subset),
            )
        )
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="metadata_conflict_rate",
                value=_share_true(_metadata_conflict(item) for item in subset),
                count=len(subset),
            )
        )
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="doi_conflict_rate",
                value=_share_true(_specific_metadata_conflict(item, "doi") for item in subset),
                count=len(subset),
            )
        )
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="year_conflict_rate",
                value=_share_true(_specific_metadata_conflict(item, "publication_year") for item in subset),
                count=len(subset),
            )
        )
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="venue_conflict_rate",
                value=_share_true(_specific_metadata_conflict(item, "venue") for item in subset),
                count=len(subset),
            )
        )
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="title_conflict_rate",
                value=_share_true(_specific_metadata_conflict(item, "title") for item in subset),
                count=len(subset),
            )
        )

    for entity, subset in [("overall", llm_calls)] + list(_group_llm_calls_by_model(llm_calls).items()):
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="parse_success_rate",
                value=_share_true(call.parse_success for call in subset),
                count=len(subset),
            )
        )
        metrics.append(
            LLMMetricRow(
                entity=entity,
                metric="latency_ms_mean",
                value=_mean_numeric(call.latency_ms for call in subset),
                count=len(subset),
            )
        )

    metrics.append(
        LLMMetricRow(
            entity="overall",
            metric="repeatability",
            value=None,
            note="Single-call-per-query execution in v1; repeatability metrics are not populated.",
        )
    )

    return LLMAnalysisSection(calls=call_rows, metrics=metrics)


def _read_llm_artifact_metadata(
    *,
    run_id: UUID,
    queries: Sequence[Query],
) -> dict[tuple[str, str], dict[str, Any]]:
    writer = get_run_artifacts_writer(run_id)
    if not writer.enabled or not writer.run_dir.exists():
        return {}

    query_positions = {str(query.id): query.position for query in queries}
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    llm_dir = writer.run_dir / "llm"
    if not llm_dir.is_dir():
        return metadata

    for query_id, position in query_positions.items():
        query_dir = llm_dir / f"query_{position:03d}"
        if not query_dir.is_dir():
            continue
        for model_dir in query_dir.iterdir():
            if not model_dir.is_dir() or not model_dir.name.startswith("model_"):
                continue
            model_name = _resolve_model_name_from_dir_name(query_dir=query_dir, dir_name=model_dir.name)
            if model_name is None:
                continue
            payload = _read_json_dict(model_dir / "metadata.json")
            if payload is None:
                continue
            metadata[(query_id, model_name)] = payload
    return metadata


def _resolve_model_name_from_dir_name(*, query_dir: Path, dir_name: str) -> str | None:
    sanitized = dir_name.removeprefix("model_")
    request_files = list(query_dir.glob(f"{dir_name}/request.json"))
    if request_files:
        payload = _read_json_dict(request_files[0])
        if isinstance(payload, dict):
            request_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            model_name = _clean_optional_text(request_payload.get("model"), payload.get("model"))
            if model_name:
                return model_name
    return sanitized.replace("_", "/") if sanitized else None


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _query_text(queries: Sequence[Query], query_id: UUID) -> str:
    for query in queries:
        if query.id == query_id:
            return query.text
    return str(query_id)


def _group_by_entity(view_rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in view_rows:
        groups[row["entity"]].append(row)
    return groups


def _group_llm_calls_by_model(llm_calls: Sequence[Any]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for call in llm_calls:
        groups[call.model_name].append(call)
    return groups


def _scopes(
    *,
    view_rows: Sequence[dict[str, Any]],
    queries: Sequence[Query],
    include_query_entity: bool,
) -> list[tuple[str | None, str, list[dict[str, Any]]]]:
    scopes: list[tuple[str | None, str, list[dict[str, Any]]]] = [(None, "overall", list(view_rows))]
    for entity, subset in _group_by_entity(view_rows).items():
        scopes.append((None, entity, subset))

    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_query_entity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in view_rows:
        by_query[row["query_id"]].append(row)
        by_query_entity[(row["query_id"], row["entity"])].append(row)

    for query in queries:
        query_key = str(query.id)
        scopes.append((query_key, "overall", by_query.get(query_key, [])))
    if include_query_entity:
        for key, subset in by_query_entity.items():
            scopes.append((key[0], key[1], subset))
    return scopes


def _publication_year_bucket(value: Any) -> str | None:
    if not isinstance(value, int):
        return "unknown"
    current_year = datetime.now(timezone.utc).year
    age = current_year - value
    if age <= 2:
        return "0-2 years"
    if age <= 5:
        return "3-5 years"
    if age <= 10:
        return "6-10 years"
    return ">10 years"


def _country_label(row: dict[str, Any]) -> str:
    for key in ("country_dominant", "country_primary"):
        value = _clean_text(row.get(key))
        if value:
            return value
    countries = row.get("countries")
    if isinstance(countries, list) and countries:
        return str(countries[0])
    return "unknown"


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _open_access_label(is_open_access: Any, open_access_status: Any) -> str:
    if isinstance(open_access_status, str) and open_access_status.strip():
        return open_access_status.strip().lower()
    if is_open_access is True:
        return "open"
    if is_open_access is False:
        return "closed"
    return "unknown"


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _share_true(values: Iterable[Any]) -> float | None:
    sequence = [bool(value) for value in values if value is not None]
    if not sequence:
        return None
    return float(sum(sequence) / len(sequence))


def _mean_numeric(values: Iterable[Any]) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, (int, float))]
    if not numbers:
        return None
    return float(mean(numbers))


def _jaccard(left: Sequence[dict[str, Any]], right: Sequence[dict[str, Any]]) -> float:
    left_ids = {row["canonical_identifier"] for row in left if row.get("canonical_identifier")}
    right_ids = {row["canonical_identifier"] for row in right if row.get("canonical_identifier")}
    if not left_ids and not right_ids:
        return 1.0
    if not left_ids or not right_ids:
        return 0.0
    return float(len(left_ids & right_ids) / len(left_ids | right_ids))


def _overlap_at_k(left: Sequence[dict[str, Any]], right: Sequence[dict[str, Any]], k: int | None = None) -> float:
    depth = k or min(len(left), len(right))
    left_ids = {row["canonical_identifier"] for row in left[:depth] if row.get("canonical_identifier")}
    right_ids = {row["canonical_identifier"] for row in right[:depth] if row.get("canonical_identifier")}
    if not left_ids and not right_ids:
        return 1.0
    if not left_ids or not right_ids:
        return 0.0
    return float(len(left_ids & right_ids) / min(len(left_ids), len(right_ids)))


def _top_1_agreement(left: Sequence[dict[str, Any]], right: Sequence[dict[str, Any]]) -> float | None:
    if not left or not right:
        return None
    left_id = left[0].get("canonical_identifier")
    right_id = right[0].get("canonical_identifier")
    if not left_id or not right_id:
        return None
    return 1.0 if left_id == right_id else 0.0


def _rbo(left: Sequence[dict[str, Any]], right: Sequence[dict[str, Any]], p: float = 0.9) -> float | None:
    if not left or not right:
        return None
    depth = min(len(left), len(right))
    if depth == 0:
        return None

    seen_left: set[str] = set()
    seen_right: set[str] = set()
    overlap = 0
    cumulative = 0.0
    for current_depth in range(1, depth + 1):
        left_id = left[current_depth - 1].get("canonical_identifier")
        right_id = right[current_depth - 1].get("canonical_identifier")
        if isinstance(left_id, str) and left_id not in seen_left:
            seen_left.add(left_id)
            if left_id in seen_right:
                overlap += 1
        if isinstance(right_id, str) and right_id not in seen_right:
            seen_right.add(right_id)
            if right_id in seen_left:
                overlap += 1
        cumulative += (1 - p) * (overlap / current_depth) * (p ** (current_depth - 1))
    agreement_at_depth = overlap / depth
    return float(cumulative + agreement_at_depth * (p**depth))


def _hhi(values: Iterable[str | None]) -> float | None:
    cleaned = [value for value in values if value]
    if not cleaned:
        return None
    counts = Counter(cleaned)
    total = sum(counts.values())
    return float(sum((count / total) ** 2 for count in counts.values()))


def _metadata_conflict(row: dict[str, Any]) -> bool:
    return any(
        _specific_metadata_conflict(row, field_name)
        for field_name in ("doi", "publication_year", "venue", "title")
    )


def _specific_metadata_conflict(row: dict[str, Any], field_name: str) -> bool:
    if field_name == "doi":
        canonical_value = _clean_text(row.get("doi"))
        raw_value = _clean_text(row.get("result_doi"))
        return bool(canonical_value and raw_value and canonical_value != raw_value)
    if field_name == "publication_year":
        canonical_year = row.get("publication_year")
        raw_year = row.get("result_year")
        return isinstance(canonical_year, int) and isinstance(raw_year, int) and canonical_year != raw_year
    if field_name == "venue":
        canonical_value = _clean_text(row.get("venue"))
        raw_value = _clean_text(row.get("result_venue"))
        return bool(canonical_value and raw_value and canonical_value.lower() != raw_value.lower())
    if field_name == "title":
        canonical_value = _clean_text(row.get("title"))
        raw_value = _clean_text(row.get("result_title"))
        return bool(canonical_value and raw_value and canonical_value.lower() != raw_value.lower())
    return False


def _top_ks(run_top_k: int) -> list[int]:
    values = {run_top_k}
    for candidate in (5, 10, 20):
        if candidate <= run_top_k:
            values.add(candidate)
    return sorted(values)
