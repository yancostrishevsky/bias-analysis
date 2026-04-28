"""Mapping helpers from OpenAlex works to domain result records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.domain import ExecutionStatus, ResultOriginType, ResultRecord


class OpenAlexMappingError(ValueError):
    """Raised when an OpenAlex work cannot be mapped into the domain model."""


def map_openalex_work(
    *,
    run_id: UUID,
    query_id: UUID,
    rank: int,
    work: dict[str, Any],
) -> ResultRecord:
    """Map one OpenAlex work payload into a ResultRecord."""

    title = _extract_title(work)
    doi = _optional_text(work.get("doi"))
    source_identifier = _optional_text(work.get("id"))
    publication_year = _normalize_publication_year(work.get("publication_year"))
    primary_location = _dict_or_empty(work.get("primary_location"))
    language = _optional_text(work.get("language"))
    publisher = _extract_publisher(primary_location)
    venue = _extract_venue(primary_location)

    return ResultRecord(
        run_id=run_id,
        query_id=query_id,
        origin_type=ResultOriginType.SCHOLARLY_SOURCE,
        source_name="openalex",
        provider_name="openalex",
        execution_status=ExecutionStatus.COMPLETED,
        rank=rank,
        canonical_identifier=_canonical_identifier(doi=doi, source_identifier=source_identifier, title=title),
        title=title,
        doi=doi,
        url=_select_url(primary_location=primary_location, doi=doi, openalex_id=source_identifier),
        source_identifier=source_identifier,
        year=publication_year,
        authors=_extract_authors(work.get("authorships")),
        venue=venue,
        publisher=publisher,
        language=language,
        raw_payload=_build_raw_payload(
            source_identifier=source_identifier,
            title=title,
            doi=doi,
            publication_year=publication_year,
            language=language,
            cited_by_count=work.get("cited_by_count"),
            document_type=work.get("type"),
            concepts=work.get("concepts"),
            authorships=work.get("authorships"),
            primary_location=primary_location,
            open_access=work.get("open_access"),
            abstract_inverted_index=work.get("abstract_inverted_index"),
            locations=work.get("locations"),
            ids=work.get("ids"),
        ),
    )


def _extract_title(work: dict[str, Any]) -> str:
    title = _optional_text(work.get("display_name"))
    if title:
        return title
    title = _optional_text(work.get("title"))
    if title:
        return title
    raise OpenAlexMappingError("OpenAlex work is missing required title fields")


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_publication_year(value: Any) -> int | None:
    if not isinstance(value, int):
        return None
    if 1800 <= value <= 2100:
        return value
    return None


def _extract_authors(authorships: Any) -> list[str]:
    if not isinstance(authorships, list):
        return []

    authors: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if not isinstance(author, dict):
            continue
        display_name = _optional_text(author.get("display_name"))
        if display_name:
            authors.append(display_name)
    return authors


def _extract_venue(primary_location: dict[str, Any]) -> str | None:
    source = primary_location.get("source")
    if not isinstance(source, dict):
        return None
    return _optional_text(source.get("display_name"))


def _extract_publisher(primary_location: dict[str, Any]) -> str | None:
    source = primary_location.get("source")
    if not isinstance(source, dict):
        return None
    for candidate in (
        source.get("host_organization_name"),
        source.get("publisher"),
        source.get("display_name"),
    ):
        cleaned = _optional_text(candidate)
        if cleaned:
            return cleaned
    return None


def _select_url(*, primary_location: dict[str, Any], doi: str | None, openalex_id: str | None) -> str | None:
    landing_page_url = _optional_text(primary_location.get("landing_page_url"))
    if landing_page_url:
        return landing_page_url
    if doi:
        return _normalize_doi_url(doi)
    return openalex_id


def _normalize_doi_url(doi: str) -> str:
    cleaned = doi.strip()
    lowered = cleaned.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return cleaned
    if lowered.startswith("doi:"):
        cleaned = cleaned[4:].strip()
    return f"https://doi.org/{cleaned}"


def _canonical_identifier(*, doi: str | None, source_identifier: str | None, title: str) -> str:
    if doi:
        return doi.lower()
    if source_identifier:
        return source_identifier.lower()
    return title.strip().lower()


def _build_raw_payload(
    *,
    source_identifier: str | None,
    title: str,
    doi: str | None,
    publication_year: int | None,
    language: str | None,
    cited_by_count: Any,
    document_type: Any,
    concepts: Any,
    authorships: Any,
    primary_location: dict[str, Any],
    open_access: Any,
    abstract_inverted_index: Any,
    locations: Any,
    ids: Any,
) -> dict[str, Any]:
    return {
        "id": source_identifier,
        "display_name": title,
        "doi": doi,
        "publication_year": publication_year,
        "language": language,
        "cited_by_count": cited_by_count,
        "type": document_type,
        "concepts": concepts if isinstance(concepts, list) else [],
        "authorships": authorships if isinstance(authorships, list) else [],
        "primary_location": primary_location,
        "open_access": open_access if isinstance(open_access, dict) else {},
        "abstract_inverted_index": (
            abstract_inverted_index if isinstance(abstract_inverted_index, dict) else {}
        ),
        "locations": locations if isinstance(locations, list) else [],
        "ids": ids if isinstance(ids, dict) else {},
    }

