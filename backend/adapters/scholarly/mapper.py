"""Mapping helpers for scholarly collection sources beyond OpenAlex."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.domain import ExecutionStatus, ResultOriginType, ResultRecord


class ScholarlySourceMappingError(ValueError):
    """Raised when a scholarly source payload cannot be mapped into a result row."""


def map_semantic_scholar_paper(
    *,
    run_id: UUID,
    query_id: UUID,
    rank: int,
    paper: dict[str, Any],
) -> ResultRecord:
    title = _required_text(paper.get("title"), "Semantic Scholar paper is missing a title")
    doi = _semantic_doi(paper)
    source_identifier = _optional_text(paper.get("paperId"))
    journal = paper.get("journal") if isinstance(paper.get("journal"), dict) else {}
    publication_venue = (
        paper.get("publicationVenue") if isinstance(paper.get("publicationVenue"), dict) else {}
    )

    return ResultRecord(
        run_id=run_id,
        query_id=query_id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="semantic_scholar",
        provider_name="semantic_scholar",
        execution_status=ExecutionStatus.COMPLETED,
        rank=rank,
        canonical_identifier=_canonical_identifier(doi=doi, source_identifier=source_identifier, title=title),
        title=title,
        doi=doi,
        url=_optional_text(paper.get("url")) or _optional_text((paper.get("openAccessPdf") or {}).get("url")),
        source_identifier=source_identifier,
        year=_coerce_year(paper.get("year")),
        authors=_semantic_authors(paper.get("authors")),
        venue=_safe_text(publication_venue.get("name"), journal.get("name"), paper.get("venue")),
        publisher=_safe_text(publication_venue.get("publisher"), journal.get("publisher")),
        language=_optional_text(paper.get("language")),
        raw_payload=paper,
    )


def map_core_work(
    *,
    run_id: UUID,
    query_id: UUID,
    rank: int,
    work: dict[str, Any],
) -> ResultRecord:
    title = _required_text(work.get("title"), "CORE work is missing a title")
    doi = _normalize_doi(work.get("doi"))
    source_identifier = _safe_text(work.get("id"), work.get("coreId"))

    return ResultRecord(
        run_id=run_id,
        query_id=query_id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="core",
        provider_name="core",
        execution_status=ExecutionStatus.COMPLETED,
        rank=rank,
        canonical_identifier=_canonical_identifier(doi=doi, source_identifier=source_identifier, title=title),
        title=title,
        doi=doi,
        url=_safe_text(work.get("url"), work.get("downloadUrl")),
        source_identifier=source_identifier,
        year=_coerce_year(work.get("year") or work.get("publishedDate")),
        authors=_core_authors(work),
        venue=_safe_text(work.get("journal"), work.get("venue")),
        publisher=_optional_text(work.get("publisher")),
        language=_optional_text(work.get("language")),
        raw_payload=work,
    )


def map_scopus_entry(
    *,
    run_id: UUID,
    query_id: UUID,
    rank: int,
    entry: dict[str, Any],
) -> ResultRecord:
    title = _required_text(entry.get("dc:title"), "Scopus entry is missing a title")
    doi = _normalize_doi(entry.get("prism:doi"))
    source_identifier = _safe_text(entry.get("dc:identifier"), entry.get("eid"))

    return ResultRecord(
        run_id=run_id,
        query_id=query_id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="scopus",
        provider_name="scopus",
        execution_status=ExecutionStatus.COMPLETED,
        rank=rank,
        canonical_identifier=_canonical_identifier(doi=doi, source_identifier=source_identifier, title=title),
        title=title,
        doi=doi,
        url=_optional_text(entry.get("prism:url")),
        source_identifier=source_identifier,
        year=_coerce_year(entry.get("prism:coverDate")),
        authors=_scopus_authors(entry),
        venue=_optional_text(entry.get("prism:publicationName")),
        publisher=_safe_text(entry.get("publishername"), entry.get("dc:publisher")),
        language=_safe_text(entry.get("prism:language"), entry.get("language")),
        raw_payload=entry,
    )


def _required_text(value: Any, message: str) -> str:
    cleaned = _optional_text(value)
    if cleaned:
        return cleaned
    raise ScholarlySourceMappingError(message)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _safe_text(*values: Any) -> str | None:
    for value in values:
        cleaned = _optional_text(value)
        if cleaned:
            return cleaned
    return None


def _normalize_doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    lowered = cleaned.lower()
    if lowered.startswith("https://doi.org/"):
        cleaned = cleaned[16:]
    elif lowered.startswith("http://doi.org/"):
        cleaned = cleaned[15:]
    elif lowered.startswith("doi:"):
        cleaned = cleaned[4:].strip()
    cleaned = cleaned.strip()
    return cleaned or None


def _coerce_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    if isinstance(value, str):
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) >= 4:
            try:
                year = int(digits[:4])
            except ValueError:
                return None
            return year if 1800 <= year <= 2100 else None
    return None


def _semantic_authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _optional_text(item.get("name"))
        if name:
            authors.append(name)
    return authors


def _semantic_doi(payload: dict[str, Any]) -> str | None:
    external_ids = payload.get("externalIds")
    if not isinstance(external_ids, dict):
        return None
    return _normalize_doi(external_ids.get("DOI"))


def _core_authors(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("authors") or payload.get("author")
    if isinstance(raw, list):
        authors: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = _optional_text(item.get("name"))
                if name:
                    authors.append(name)
            elif isinstance(item, str):
                cleaned = _optional_text(item)
                if cleaned:
                    authors.append(cleaned)
        return authors
    single = _optional_text(raw)
    return [single] if single else []


def _scopus_authors(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("author")
    if isinstance(raw, list):
        authors: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = _safe_text(item.get("authname"), item.get("ce:indexed-name"))
            if name:
                authors.append(name)
        return authors
    single = _optional_text(payload.get("dc:creator"))
    return [single] if single else []


def _canonical_identifier(*, doi: str | None, source_identifier: str | None, title: str) -> str:
    if doi:
        return doi.lower()
    if source_identifier:
        return source_identifier.lower()
    return title.strip().lower()
