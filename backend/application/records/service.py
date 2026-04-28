"""Unified record exploration and export builders."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import UUID

from backend.application.analysis.service import _read_llm_artifact_metadata
from backend.application.enrichment.providers import normalize_doi
from backend.domain import (
    AnalysisFilterOption,
    CanonicalEnrichment,
    EnrichmentRecord,
    LLMCall,
    Query,
    RecordsFilterOption,
    ResultOriginType,
    ResultRecord,
    RunDetail,
    RunRecordsFilters,
    RunRecordsResponse,
    RunRecordsSummary,
    RunType,
    UnifiedRecordRow,
)
from backend.storage.repository import Repository

_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
_UNKNOWN_TEXT = {"unknown", "n/a", "na", "none", "null"}
_PARSE_CONFIDENCE = {
    "full_json": 1.0,
    "fenced_json": 0.85,
    "brace_slice": 0.7,
    "partial_array_recovery": 0.45,
}


def build_run_records_response(
    *,
    repository: Repository,
    run_id: UUID,
    query_id: str | None = None,
    entity: str | None = None,
    top_k: int | None = None,
    rank_bucket: str | None = None,
    parse_status: str | None = None,
    matched: bool | None = None,
    doi_valid: bool | None = None,
    conflicting: bool | None = None,
    language: str | None = None,
    publisher: str | None = None,
    country: str | None = None,
    oa_status: str | None = None,
    source_type: str | None = None,
    risk_bucket: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    search: str | None = None,
    only_enriched: bool = False,
    only_verified: bool = False,
    only_conflicting: bool = False,
) -> RunRecordsResponse:
    run_detail = repository.get_run_detail(run_id)
    rows = build_unified_record_rows(repository=repository, run_id=run_id, run_detail=run_detail)
    filtered_rows = _filter_rows(
        rows=rows,
        query_id=query_id,
        entity=entity,
        top_k=top_k,
        rank_bucket=rank_bucket,
        parse_status=parse_status,
        matched=matched,
        doi_valid=doi_valid,
        conflicting=conflicting,
        language=language,
        publisher=publisher,
        country=country,
        oa_status=oa_status,
        source_type=source_type,
        risk_bucket=risk_bucket,
        year_from=year_from,
        year_to=year_to,
        search=search,
        only_enriched=only_enriched,
        only_verified=only_verified,
        only_conflicting=only_conflicting,
    )
    return RunRecordsResponse(
        summary=RunRecordsSummary(
            run_id=str(run_id),
            run_type=run_detail.run.run_type,
            total_rows=len(rows),
            filtered_rows=len(filtered_rows),
        ),
        filters=_build_filter_options(run_detail=run_detail, rows=rows),
        rows=filtered_rows,
    )


def build_unified_record_rows(
    *,
    repository: Repository,
    run_id: UUID,
    run_detail: RunDetail | None = None,
) -> list[UnifiedRecordRow]:
    detail = run_detail or repository.get_run_detail(run_id)
    results = repository.list_results(run_id)
    enrichments_by_result = repository.list_enrichments_by_result(run_id)
    llm_calls = repository.list_llm_calls(run_id)
    llm_call_lookup = {call.id: call for call in llm_calls}
    llm_call_metadata = _read_llm_artifact_metadata(run_id=run_id, queries=detail.queries)
    repeat_indices = _repeat_indices(llm_calls)
    query_lookup = {str(query.id): query for query in detail.queries}

    rows: list[UnifiedRecordRow] = []
    for result in results:
        provider_records, canonical = enrichments_by_result.get(result.id, ([], None))
        llm_call = llm_call_lookup.get(result.llm_call_id) if result.llm_call_id else None
        llm_metadata = (
            llm_call_metadata.get((str(result.query_id), result.model_name or ""))
            if result.model_name
            else None
        )
        query = query_lookup[str(result.query_id)]
        rows.append(
            _build_unified_row(
                run_detail=detail,
                query=query,
                result=result,
                provider_records=provider_records,
                canonical=canonical,
                llm_call=llm_call,
                llm_metadata=llm_metadata,
                repeat_index=repeat_indices.get(result.llm_call_id) if result.llm_call_id else None,
            )
        )
    return rows


def export_run_records(
    *,
    repository: Repository,
    run_id: UUID,
    export_format: str,
    export_view: str,
    filters: dict[str, Any],
) -> tuple[str, str, str]:
    response = build_run_records_response(repository=repository, run_id=run_id, **filters)
    rows = [_export_row(row=row, export_view=export_view) for row in response.rows]
    metadata = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "run-records-v1",
        "run_id": str(run_id),
        "run_type": response.summary.run_type.value,
        "export_format": export_format,
        "export_view": export_view,
        "filters": filters,
    }

    if export_format == "json":
        filename = f"run_{run_id}_{export_view}.json"
        return (
            json.dumps({"metadata": metadata, "rows": rows}, ensure_ascii=True, indent=2),
            "application/json",
            filename,
        )

    if export_format == "jsonl":
        filename = f"run_{run_id}_{export_view}.jsonl"
        lines = [json.dumps({"_type": "metadata", **metadata}, ensure_ascii=True)]
        lines.extend(json.dumps(row, ensure_ascii=True) for row in rows)
        return ("\n".join(lines) + "\n", "application/x-ndjson", filename)

    if export_format != "csv":
        raise ValueError(f"Unsupported export format '{export_format}'")

    filename = f"run_{run_id}_{export_view}.csv"
    return (_to_csv(rows), "text/csv; charset=utf-8", filename)


def _build_unified_row(
    *,
    run_detail: RunDetail,
    query: Query,
    result: ResultRecord,
    provider_records: Sequence[EnrichmentRecord],
    canonical: CanonicalEnrichment | None,
    llm_call: LLMCall | None,
    llm_metadata: dict[str, Any] | None,
    repeat_index: int | None,
) -> UnifiedRecordRow:
    entity = result.model_name or result.source_name or "overall"
    raw_payload = _raw_record_payload(result)
    raw_title = _first_text(raw_payload.get("title"), raw_payload.get("display_name"), result.title)
    raw_doi = _normalize_optional_text(raw_payload.get("doi"), result.doi)
    raw_year = _coerce_year(raw_payload.get("publication_year"), raw_payload.get("year"), result.year)
    raw_journal = _first_text(
        raw_payload.get("venue"),
        raw_payload.get("journal"),
        raw_payload.get("prism:publicationName"),
        result.venue,
    )
    raw_authors = _raw_authors(raw_payload, fallback=result.authors)
    parsed_title = result.title
    parsed_doi = _normalize_optional_text(result.doi)
    parsed_year = result.year
    parsed_journal = result.venue
    parsed_authors = list(result.authors)
    enriched_title = canonical.title if canonical and canonical.title else None
    enriched_doi = canonical.doi if canonical and canonical.doi else None
    enriched_year = canonical.publication_year if canonical else None
    enriched_journal = canonical.venue if canonical else None
    enriched_authors = list(canonical.authors) if canonical else []
    matched = canonical is not None and bool(canonical.source_record_ids)
    title_match_status = _title_match_status(parsed_title, enriched_title) if matched else None
    year_conflict = bool(matched and parsed_year is not None and enriched_year is not None and parsed_year != enriched_year)
    doi_valid = _doi_valid(parsed_doi)
    doi_conflict = bool(matched and _doi_conflict(parsed_doi, enriched_doi))
    journal_conflict = bool(matched and _journal_conflict(parsed_journal, enriched_journal))
    author_match_status = _author_match_status(parsed_authors, enriched_authors) if matched else None
    author_conflict = author_match_status == "no"
    publisher_conflict = bool(matched and _publisher_conflict(result.publisher, canonical.publisher if canonical else None))
    conflict_count = sum(
        1
        for value in (doi_conflict, year_conflict, journal_conflict, author_conflict, publisher_conflict)
        if value
    )
    unmatched_reason = None if matched else _unmatched_reason(provider_records)
    parse_strategy = _first_text(llm_metadata.get("parse_mode") if llm_metadata else None)
    parse_status = _parse_status(run_detail=run_detail, llm_call=llm_call)
    parse_fallback_used = bool(parse_strategy and parse_strategy != "full_json")
    parse_confidence = _parse_confidence(parse_status=parse_status, parse_strategy=parse_strategy)
    source_type = _infer_source_type(result=result, canonical=canonical, raw_payload=raw_payload)
    language = canonical.language if canonical and canonical.language else result.language
    country_primary = canonical.country_primary if canonical else _normalize_optional_text(_raw_country(raw_payload))
    countries = list(canonical.countries) if canonical else ([] if not country_primary else [country_primary])
    oa_status = canonical.open_access_status if canonical else None
    is_oa = canonical.is_open_access if canonical else _raw_is_oa(raw_payload)
    oa_pathway = _oa_pathway(oa_status)
    cited_by_count = canonical.citation_count if canonical else None
    topics = canonical.fields_of_study if canonical else []
    subfields = canonical.subject_areas if canonical else []
    suspicious_completeness = _suspicious_completeness(
        matched=matched,
        parsed_doi=parsed_doi,
        parsed_year=parsed_year,
        parsed_journal=parsed_journal,
        language=language,
        result=result,
    )
    risk_reasons = _risk_reasons(
        run_type=run_detail.run.run_type,
        parse_status=parse_status,
        matched=matched,
        unmatched_reason=unmatched_reason,
        doi_valid=doi_valid,
        doi_conflict=doi_conflict,
        title_match_status=title_match_status,
        year_conflict=year_conflict,
        journal_conflict=journal_conflict,
        author_conflict=author_conflict,
        publisher_conflict=publisher_conflict,
        conflict_count=conflict_count,
        suspicious_completeness=suspicious_completeness,
    )
    hallucination_risk_bucket = _hallucination_risk_bucket(
        run_type=run_detail.run.run_type,
        risk_reasons=risk_reasons,
    )
    provenance_summary = _provenance_summary(canonical, provider_records)

    return UnifiedRecordRow(
        run_id=str(run_detail.run.id),
        run_mode=run_detail.run.run_type,
        query_id=str(query.id),
        query_text=query.text,
        query_category=None,
        model_or_platform=entity,
        provider=result.provider_name or result.source_name,
        repeat_index=repeat_index,
        rank=result.rank,
        rank_bucket=_rank_bucket(rank=result.rank, run_top_k=run_detail.run.top_k),
        raw_title=raw_title,
        raw_doi=raw_doi,
        raw_year=raw_year,
        raw_journal=raw_journal,
        raw_authors=raw_authors,
        raw_rationale=_first_text(result.raw_payload.get("rationale")) if isinstance(result.raw_payload, dict) else None,
        parsed_title=parsed_title,
        parsed_doi=parsed_doi,
        parsed_year=parsed_year,
        parsed_journal=parsed_journal,
        parsed_authors=parsed_authors,
        enriched_title=enriched_title,
        enriched_doi=enriched_doi,
        enriched_year=enriched_year,
        enriched_journal=enriched_journal,
        enriched_authors=enriched_authors,
        external_match_id=_external_match_id(canonical),
        matched=matched,
        match_strategy=_match_strategy(canonical, provider_records),
        doi_valid=doi_valid,
        title_match_status=title_match_status,
        year_conflict=year_conflict,
        journal_conflict=journal_conflict,
        author_conflict=author_conflict,
        publisher_conflict=publisher_conflict,
        any_conflict=conflict_count > 0,
        conflict_count=conflict_count,
        unmatched_reason=unmatched_reason,
        language=language,
        country_primary=country_primary,
        countries=countries,
        publisher=canonical.publisher if canonical and canonical.publisher else result.publisher,
        source_type=source_type,
        is_oa=is_oa,
        oa_status=oa_status,
        oa_pathway=oa_pathway,
        cited_by_count=cited_by_count,
        topic=topics[0] if topics else None,
        subfield=subfields[0] if subfields else None,
        parse_status=parse_status,
        parse_confidence=parse_confidence,
        parse_strategy=parse_strategy,
        parse_fallback_used=parse_fallback_used,
        parse_errors=(llm_call.error_message or llm_call.parse_error) if llm_call else None,
        suspicious_completeness=suspicious_completeness,
        hallucination_risk_bucket=hallucination_risk_bucket,
        risk_reasons=risk_reasons,
        provenance_summary=provenance_summary,
        raw_payload=raw_payload,
        parsed_payload={
            "title": parsed_title,
            "doi": parsed_doi,
            "year": parsed_year,
            "journal": parsed_journal,
            "authors": parsed_authors,
            "language": language,
            "publisher": result.publisher,
        },
        enriched_payload=canonical.model_dump(mode="json") if canonical else {},
        verification_trace={
            "doi_conflict": doi_conflict,
            "parsed_doi": parsed_doi,
            "enriched_doi": enriched_doi,
            "title_match_status": title_match_status,
            "year_conflict": year_conflict,
            "parsed_year": parsed_year,
            "enriched_year": enriched_year,
            "journal_conflict": journal_conflict,
            "author_match_status": author_match_status,
            "publisher_conflict": publisher_conflict,
            "conflict_count": conflict_count,
            "suspicious_completeness": suspicious_completeness,
            "unmatched_reason": unmatched_reason,
            "risk_reasons": risk_reasons,
        },
    )


def _repeat_indices(llm_calls: Sequence[LLMCall]) -> dict[UUID, int]:
    groups: dict[tuple[str, str], list[LLMCall]] = defaultdict(list)
    for call in llm_calls:
        groups[(str(call.query_id), call.model_name)].append(call)

    indices: dict[UUID, int] = {}
    for group_calls in groups.values():
        for index, call in enumerate(
            sorted(group_calls, key=lambda item: (item.started_at or item.created_at, item.id)),
            start=1,
        ):
            indices[call.id] = index
    return indices


def _filter_rows(
    *,
    rows: Sequence[UnifiedRecordRow],
    query_id: str | None,
    entity: str | None,
    top_k: int | None,
    rank_bucket: str | None,
    parse_status: str | None,
    matched: bool | None,
    doi_valid: bool | None,
    conflicting: bool | None,
    language: str | None,
    publisher: str | None,
    country: str | None,
    oa_status: str | None,
    source_type: str | None,
    risk_bucket: str | None,
    year_from: int | None,
    year_to: int | None,
    search: str | None,
    only_enriched: bool,
    only_verified: bool,
    only_conflicting: bool,
) -> list[UnifiedRecordRow]:
    search_text = (search or "").strip().lower()
    filtered: list[UnifiedRecordRow] = []
    for row in rows:
        if query_id and row.query_id != query_id:
            continue
        if entity and row.model_or_platform != entity:
            continue
        if top_k is not None and row.rank > top_k:
            continue
        if rank_bucket and row.rank_bucket != rank_bucket:
            continue
        if parse_status and (row.parse_status or "") != parse_status:
            continue
        if matched is not None and row.matched is not matched:
            continue
        if doi_valid is not None and row.doi_valid is not doi_valid:
            continue
        if conflicting is not None and row.any_conflict is not conflicting:
            continue
        if language and (row.language or "") != language:
            continue
        if publisher and (row.publisher or "") != publisher:
            continue
        if country and country not in {row.country_primary or "", *row.countries}:
            continue
        if oa_status and (row.oa_status or "") != oa_status:
            continue
        if source_type and (row.source_type or "") != source_type:
            continue
        if risk_bucket and (row.hallucination_risk_bucket or "") != risk_bucket:
            continue
        if year_from is not None and (row.enriched_year or row.parsed_year or 0) < year_from:
            continue
        if year_to is not None and (row.enriched_year or row.parsed_year or 9999) > year_to:
            continue
        if only_enriched and not row.enriched_payload:
            continue
        if only_verified and not row.matched:
            continue
        if only_conflicting and not row.any_conflict:
            continue
        if search_text and not _matches_search(row, search_text):
            continue
        filtered.append(row)
    return filtered


def _matches_search(row: UnifiedRecordRow, search_text: str) -> bool:
    haystack = " ".join(
        value
        for value in (
            row.query_text,
            row.model_or_platform,
            row.raw_title,
            row.parsed_title,
            row.enriched_title,
            row.raw_doi,
            row.parsed_doi,
            row.enriched_doi,
            row.raw_journal,
            row.parsed_journal,
            row.enriched_journal,
            row.publisher,
            row.language,
        )
        if isinstance(value, str)
    ).lower()
    authors = " ".join(row.raw_authors + row.parsed_authors + row.enriched_authors).lower()
    return search_text in haystack or search_text in authors


def _build_filter_options(*, run_detail: RunDetail, rows: Sequence[UnifiedRecordRow]) -> RunRecordsFilters:
    return RunRecordsFilters(
        queries=[
            RecordsFilterOption(value=str(query.id), label=f"Q{query.position}: {query.text}")
            for query in run_detail.queries
        ],
        entities=_option_list(row.model_or_platform for row in rows),
        languages=_option_list(row.language for row in rows),
        publishers=_option_list(row.publisher for row in rows),
        countries=_option_list(country for row in rows for country in ([row.country_primary] + list(row.countries))),
        oa_statuses=_option_list(row.oa_status for row in rows),
        source_types=_option_list(row.source_type for row in rows),
        parse_statuses=_option_list(row.parse_status for row in rows),
        risk_buckets=_option_list(row.hallucination_risk_bucket for row in rows),
    )


def _option_list(values: Iterable[str | None]) -> list[RecordsFilterOption]:
    unique = sorted({value.strip() for value in values if isinstance(value, str) and value.strip()})
    return [RecordsFilterOption(value=value, label=value) for value in unique]


def _raw_record_payload(result: ResultRecord) -> dict[str, Any]:
    if not isinstance(result.raw_payload, dict):
        return {}
    raw_item = result.raw_payload.get("raw_item")
    if isinstance(raw_item, dict):
        return raw_item
    return result.raw_payload


def _raw_authors(raw_payload: dict[str, Any], *, fallback: Sequence[str]) -> list[str]:
    raw = raw_payload.get("authors") or raw_payload.get("author")
    if isinstance(raw, list):
        values: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                text = _first_text(item.get("name"), item.get("display_name"), item.get("authname"))
                if text:
                    values.append(text)
            elif isinstance(item, str):
                cleaned = _normalize_optional_text(item)
                if cleaned:
                    values.append(cleaned)
        return values or list(fallback)
    return list(fallback)


def _raw_country(raw_payload: dict[str, Any]) -> str | None:
    bias_fields = raw_payload.get("bias_fields")
    if isinstance(bias_fields, dict):
        return _normalize_optional_text(bias_fields.get("country_primary"))
    return None


def _raw_is_oa(raw_payload: dict[str, Any]) -> bool | None:
    bias_fields = raw_payload.get("bias_fields")
    if isinstance(bias_fields, dict):
        value = bias_fields.get("is_open_access")
        if isinstance(value, bool):
            return value
    return None


def _parse_status(*, run_detail: RunDetail, llm_call: LLMCall | None) -> str | None:
    if run_detail.run.run_type != RunType.LLM_AUDIT:
        return "not_applicable"
    if llm_call is None:
        return "missing"
    if llm_call.parse_success:
        return "parsed"
    if llm_call.status.value in {"failed", "partial", "skipped"}:
        return "failed"
    return llm_call.status.value


def _parse_confidence(*, parse_status: str | None, parse_strategy: str | None) -> float | None:
    if parse_status == "failed":
        return 0.0
    if parse_strategy is None:
        return None
    return _PARSE_CONFIDENCE.get(parse_strategy, 0.6)


def _rank_bucket(*, rank: int, run_top_k: int) -> str:
    if rank == 1:
        return "top_1"
    if rank <= 3:
        return "top_3"
    if rank <= 5:
        return "top_5"
    if rank <= run_top_k:
        return "top_k"
    return "rest"


def _doi_valid(value: str | None) -> bool | None:
    normalized = normalize_doi(value)
    if normalized is None:
        return None
    return bool(_DOI_RE.match(normalized))


def _doi_conflict(left: str | None, right: str | None) -> bool:
    left_value = normalize_doi(left)
    right_value = normalize_doi(right)
    return bool(left_value and right_value and left_value != right_value)


def _title_match_status(parsed_title: str | None, enriched_title: str | None) -> str | None:
    if not parsed_title or not enriched_title:
        return None
    left = _normalize_compare_text(parsed_title)
    right = _normalize_compare_text(enriched_title)
    if left == right:
        return "exact"
    score = SequenceMatcher(None, left, right).ratio()
    if score >= 0.86:
        return "fuzzy"
    return "no"


def _author_match_status(parsed_authors: Sequence[str], enriched_authors: Sequence[str]) -> str | None:
    left = {_author_signature(item) for item in parsed_authors if item}
    right = {_author_signature(item) for item in enriched_authors if item}
    left = {item for item in left if item is not None}
    right = {item for item in right if item is not None}
    if not left or not right:
        return None
    if left == right:
        return "full"
    if any(_author_signature_match(left_item, right_item) for left_item in left for right_item in right):
        return "partial"
    return "no"


def _text_conflict(left: str | None, right: str | None) -> bool:
    left_value = _normalize_compare_text(left)
    right_value = _normalize_compare_text(right)
    return bool(left_value and right_value and left_value != right_value)


def _journal_conflict(left: str | None, right: str | None) -> bool:
    left_value = _normalize_journal_text(left)
    right_value = _normalize_journal_text(right)
    return bool(left_value and right_value and left_value != right_value)


def _publisher_conflict(left: str | None, right: str | None) -> bool:
    left_value = _normalize_publisher_text(left)
    right_value = _normalize_publisher_text(right)
    return bool(left_value and right_value and left_value != right_value)


def _normalize_compare_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = _ascii_fold(value).lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_publisher_text(value: str | None) -> str:
    normalized = _normalize_compare_text(value)
    if not normalized:
        return ""
    normalized = re.sub(r"\b(llc|ltd|limited|inc|incorporated|bv|plc|gmbh|sarl|sa)\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    aliases = {
        "bmc": "springer nature",
        "biomed central": "springer nature",
        "mdpi": "multidisciplinary digital publishing institute",
        "nature portfolio": "springer nature",
        "nature publishing group": "springer nature",
        "springer": "springer nature",
        "springer science and business media": "springer nature",
        "springer science business media": "springer nature",
    }
    return aliases.get(normalized, normalized)


def _normalize_journal_text(value: str | None) -> str:
    normalized = _normalize_compare_text(value)
    if not normalized:
        return ""
    aliases = {
        "acad radiol": "academic radiology",
        "clinical radiol": "clinical radiology",
        "eur radiol": "european radiology",
        "j am coll radiol": "journal of the american college of radiology",
        "j magn reson imaging": "journal of magnetic resonance imaging",
        "nat rev cancer": "nature reviews cancer",
        "nature rev cancer": "nature reviews cancer",
    }
    return aliases.get(normalized, normalized)


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _author_signature(value: str) -> tuple[str, str] | None:
    cleaned = _ascii_fold(value).strip()
    if not cleaned:
        return None
    if "," in cleaned:
        last, rest = cleaned.split(",", 1)
        last_name = _normalize_compare_text(last).split()
        given_parts = _normalize_compare_text(rest).split()
    else:
        parts = _normalize_compare_text(cleaned).split()
        if not parts:
            return None
        raw_tokens = re.findall(r"[A-Za-z]+", cleaned)
        last_raw_token = raw_tokens[-1] if raw_tokens else ""
        if len(parts) > 1 and 1 <= len(last_raw_token) <= 4 and last_raw_token.isupper():
            last_name = [parts[0]]
            given_parts = parts[1:]
        else:
            last_name = [parts[-1]]
            given_parts = parts[:-1]
    if not last_name:
        return None
    initials = "".join(part[0] for part in given_parts if part)
    return (last_name[0], initials)


def _author_signature_match(left: tuple[str, str], right: tuple[str, str]) -> bool:
    if left[0] != right[0]:
        return False
    if not left[1] or not right[1]:
        return True
    return left[1].startswith(right[1]) or right[1].startswith(left[1]) or left[1][0] == right[1][0]


def _unmatched_reason(provider_records: Sequence[EnrichmentRecord]) -> str:
    if not provider_records:
        return "coverage_unknown"
    statuses = {record.status.value for record in provider_records}
    messages = [(record.error_message or "").lower() for record in provider_records]
    if "failed" in statuses:
        return "provider_failed"
    if statuses == {"skipped"}:
        if any("disabled" in message for message in messages):
            return "disabled"
        if all("did not match" in message for message in messages):
            return "not_found"
        return "skipped"
    return "coverage_unknown"


def _infer_source_type(
    *,
    result: ResultRecord,
    canonical: CanonicalEnrichment | None,
    raw_payload: dict[str, Any],
) -> str | None:
    if result.source_name == "core":
        return "repository"
    raw_type = _normalize_optional_text(raw_payload.get("type"))
    if raw_type:
        mapped = {
            "journal-article": "journal",
            "article": "journal",
            "proceedings-article": "conference",
            "conference-paper": "conference",
            "posted-content": "preprint",
            "preprint": "preprint",
            "repository": "repository",
        }
        return mapped.get(raw_type, raw_type)
    venue = canonical.venue if canonical and canonical.venue else result.venue
    if venue:
        return "journal"
    return None


def _oa_pathway(open_access_status: str | None) -> str | None:
    if not open_access_status:
        return None
    lowered = open_access_status.strip().lower()
    if lowered in {"gold", "hybrid", "green", "bronze"}:
        return lowered
    if lowered in {"open", "closed"}:
        return lowered
    return lowered


def _suspicious_completeness(
    *,
    matched: bool,
    parsed_doi: str | None,
    parsed_year: int | None,
    parsed_journal: str | None,
    language: str | None,
    result: ResultRecord,
) -> bool:
    if matched or result.origin_type != ResultOriginType.LLM_RESPONSE:
        return False
    populated = sum(
        1
        for value in (
            parsed_doi,
            parsed_year,
            parsed_journal,
            language,
            result.publisher,
            result.url,
        )
        if value not in (None, "")
    )
    return populated >= 5


def _hallucination_risk_bucket(
    *,
    run_type: RunType,
    risk_reasons: Sequence[str],
) -> str | None:
    if run_type != RunType.LLM_AUDIT:
        return None
    high_reasons = {
        "parse_failed",
        "invalid_doi",
        "doi_conflict",
        "title_mismatch",
        "year_conflict",
        "multiple_metadata_conflicts",
        "unmatched:not_found",
    }
    if any(reason in high_reasons for reason in risk_reasons):
        return "high"
    medium_reasons = {
        "unmatched:provider_failed",
        "unmatched:skipped",
        "unmatched:disabled",
        "unmatched:coverage_unknown",
        "journal_conflict",
        "author_conflict",
        "publisher_conflict",
        "suspicious_completeness",
        "title_fuzzy_match",
    }
    if any(reason in medium_reasons for reason in risk_reasons):
        return "medium"
    return "low"


def _risk_reasons(
    *,
    run_type: RunType,
    parse_status: str | None,
    matched: bool,
    unmatched_reason: str | None,
    doi_valid: bool | None,
    doi_conflict: bool,
    title_match_status: str | None,
    year_conflict: bool,
    journal_conflict: bool,
    author_conflict: bool,
    publisher_conflict: bool,
    conflict_count: int,
    suspicious_completeness: bool,
) -> list[str]:
    if run_type != RunType.LLM_AUDIT:
        return []
    reasons: list[str] = []
    if parse_status == "failed":
        reasons.append("parse_failed")
    if not matched:
        reasons.append(f"unmatched:{unmatched_reason or 'coverage_unknown'}")
    if doi_valid is False:
        reasons.append("invalid_doi")
    if doi_conflict:
        reasons.append("doi_conflict")
    if title_match_status == "no":
        reasons.append("title_mismatch")
    elif title_match_status == "fuzzy":
        reasons.append("title_fuzzy_match")
    if year_conflict:
        reasons.append("year_conflict")
    if journal_conflict:
        reasons.append("journal_conflict")
    if author_conflict:
        reasons.append("author_conflict")
    if publisher_conflict:
        reasons.append("publisher_conflict")
    if conflict_count >= 3:
        reasons.append("multiple_metadata_conflicts")
    if suspicious_completeness:
        reasons.append("suspicious_completeness")
    return reasons


def _provenance_summary(
    canonical: CanonicalEnrichment | None,
    provider_records: Sequence[EnrichmentRecord],
) -> str | None:
    if canonical is not None and canonical.field_provenance:
        counts = Counter(value.provider.value for value in canonical.field_provenance.values())
        return ", ".join(f"{provider}:{count}" for provider, count in sorted(counts.items()))
    if provider_records:
        counts = Counter(record.provider.value for record in provider_records)
        return ", ".join(f"{provider}:{count}" for provider, count in sorted(counts.items()))
    return None


def _external_match_id(canonical: CanonicalEnrichment | None) -> str | None:
    if canonical is None:
        return None
    for key in ("doi", "openalex", "semantic_scholar", "scopus", "core"):
        value = canonical.external_ids.get(key) or canonical.source_ids.get(key)
        if value:
            return str(value)
    return None


def _match_strategy(
    canonical: CanonicalEnrichment | None,
    provider_records: Sequence[EnrichmentRecord],
) -> str | None:
    if canonical is not None:
        for value in canonical.field_provenance.values():
            if value.match_strategy is not None:
                return value.match_strategy.value
    for record in provider_records:
        if record.match_strategy is not None:
            return record.match_strategy.value
    return None


def _to_csv(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(value) for key, value in row.items()})
    return buffer.getvalue()


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=True)
    return value


def _export_row(*, row: UnifiedRecordRow, export_view: str) -> dict[str, Any]:
    full = row.model_dump(mode="json")
    if export_view == "unified":
        return full
    if export_view == "raw":
        keys = [
            "run_id",
            "run_mode",
            "query_id",
            "query_text",
            "model_or_platform",
            "provider",
            "repeat_index",
            "rank",
            "rank_bucket",
            "raw_title",
            "raw_doi",
            "raw_year",
            "raw_journal",
            "raw_authors",
            "raw_rationale",
            "raw_payload",
        ]
        return {key: full.get(key) for key in keys}
    if export_view == "enriched":
        keys = [
            "run_id",
            "run_mode",
            "query_id",
            "query_text",
            "model_or_platform",
            "provider",
            "rank",
            "parsed_title",
            "parsed_doi",
            "parsed_year",
            "parsed_journal",
            "parsed_authors",
            "enriched_title",
            "enriched_doi",
            "enriched_year",
            "enriched_journal",
            "enriched_authors",
            "external_match_id",
            "matched",
            "match_strategy",
            "language",
            "country_primary",
            "countries",
            "publisher",
            "source_type",
            "is_oa",
            "oa_status",
            "oa_pathway",
            "cited_by_count",
            "topic",
            "subfield",
            "provenance_summary",
            "enriched_payload",
        ]
        return {key: full.get(key) for key in keys}
    if export_view == "verification":
        keys = [
            "run_id",
            "run_mode",
            "query_id",
            "query_text",
            "model_or_platform",
            "provider",
            "rank",
            "parsed_title",
            "parsed_doi",
            "parsed_year",
            "parsed_journal",
            "matched",
            "match_strategy",
            "doi_valid",
            "title_match_status",
            "year_conflict",
            "journal_conflict",
            "author_conflict",
            "publisher_conflict",
            "any_conflict",
            "conflict_count",
            "unmatched_reason",
            "parse_status",
            "parse_confidence",
            "parse_strategy",
            "parse_fallback_used",
            "parse_errors",
            "suspicious_completeness",
            "hallucination_risk_bucket",
            "risk_reasons",
            "verification_trace",
        ]
        return {key: full.get(key) for key in keys}
    raise ValueError(f"Unsupported export view '{export_view}'")


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned and cleaned.lower() not in _UNKNOWN_TEXT:
                return cleaned
    return None


def _normalize_optional_text(*values: Any) -> str | None:
    return _first_text(*values)


def _coerce_year(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and 1800 <= value <= 2100:
            return value
        if isinstance(value, str):
            digits = "".join(character for character in value if character.isdigit())
            if len(digits) >= 4:
                try:
                    year = int(digits[:4])
                except ValueError:
                    continue
                if 1800 <= year <= 2100:
                    return year
    return None
