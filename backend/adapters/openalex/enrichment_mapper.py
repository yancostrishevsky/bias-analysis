"""OpenAlex-specific mapping into provider-agnostic enrichment records."""

from __future__ import annotations

from collections import Counter
from typing import Any

from backend.domain import (
    EnrichmentMatchStrategy,
    EnrichmentProvider,
    EnrichmentRecord,
    ResultRecord,
)


def map_openalex_payload_to_enrichment(
    *,
    result: ResultRecord,
    payload: dict[str, Any],
    match_strategy: EnrichmentMatchStrategy,
) -> EnrichmentRecord | None:
    """Build an OpenAlex enrichment record from a payload."""

    provider_record_id = _first_text(result.source_identifier, payload.get("id"))
    if provider_record_id is None:
        return None
    primary_location = _source_or_empty(payload)

    return EnrichmentRecord(
        result_record_id=result.id,
        provider=EnrichmentProvider.OPENALEX,
        provider_record_id=provider_record_id,
        match_strategy=match_strategy,
        external_ids=_build_external_ids(payload=payload, provider_record_id=provider_record_id),
        source_ids={
            key: value
            for key, value in {
                "openalex": provider_record_id,
                "doi": _normalize_doi_url(_provider_doi(payload)),
            }.items()
            if value is not None
        },
        doi=_provider_doi(payload),
        title=_first_text(payload.get("display_name"), payload.get("title"), result.title),
        abstract=_extract_abstract(payload.get("abstract_inverted_index")),
        authors=_extract_authors(payload.get("authorships")),
        affiliations=_extract_affiliations(payload.get("authorships")),
        publication_year=_normalize_non_negative_int(payload.get("publication_year")),
        language=_normalize_language(payload.get("language"), result.language),
        is_open_access=_extract_is_open_access(payload.get("open_access")),
        open_access_status=_extract_open_access_status(payload.get("open_access")),
        citation_count=_normalize_non_negative_int(payload.get("cited_by_count")),
        publisher=_extract_publisher(primary_location),
        venue=_extract_venue(primary_location, result.venue),
        fields_of_study=_extract_fields_of_study(payload.get("concepts")),
        subject_areas=_extract_fields_of_study(payload.get("concepts")),
        country_primary=_extract_country_primary(payload.get("authorships")),
        country_dominant=_extract_country_dominant(payload.get("authorships")),
        countries=_extract_countries(payload.get("authorships")),
        urls=_extract_urls(payload),
        landing_page_url=_extract_landing_page_url(payload),
        pdf_url=_extract_pdf_url(payload),
        raw_payload=payload,
    )


def _build_external_ids(
    *,
    payload: dict[str, Any],
    provider_record_id: str,
) -> dict[str, str]:
    ids = payload.get("ids") if isinstance(payload.get("ids"), dict) else {}
    external_ids = {"openalex": provider_record_id}
    for key in ("doi", "pmid", "pmcid", "mag"):
        value = _first_text(ids.get(key))
        if value:
            external_ids[key] = value
    normalized_doi = _normalize_doi_url(_provider_doi(payload))
    if normalized_doi is not None:
        external_ids["doi"] = normalized_doi
    return external_ids


def _provider_doi(payload: dict[str, Any]) -> str | None:
    ids = payload.get("ids") if isinstance(payload.get("ids"), dict) else {}
    return _normalize_doi_value(payload.get("doi") or ids.get("doi"))


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
        name = _first_text(author.get("display_name"))
        if name:
            authors.append(name)
    return authors


def _extract_affiliations(authorships: Any) -> list[str]:
    if not isinstance(authorships, list):
        return []
    affiliations: list[str] = []
    seen: set[str] = set()
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        institutions = authorship.get("institutions")
        if not isinstance(institutions, list):
            continue
        for institution in institutions:
            if not isinstance(institution, dict):
                continue
            name = _first_text(institution.get("display_name"))
            if name and name not in seen:
                seen.add(name)
                affiliations.append(name)
    return affiliations


def _extract_abstract(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    pairs: list[tuple[int, str]] = []
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                pairs.append((position, token))
    if not pairs:
        return None
    return " ".join(token for _, token in sorted(pairs, key=lambda item: item[0]))


def _extract_fields_of_study(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    fields: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _first_text(item.get("display_name"))
        if label and label not in seen:
            seen.add(label)
            fields.append(label)
    return fields


def _extract_is_open_access(value: Any) -> bool | None:
    if not isinstance(value, dict):
        return None
    is_oa = value.get("is_oa")
    return is_oa if isinstance(is_oa, bool) else None


def _extract_open_access_status(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _first_text(value.get("oa_status"), value.get("status"))


def _extract_publisher(source: dict[str, Any]) -> str | None:
    return _first_text(
        source.get("host_organization_name"),
        source.get("publisher"),
        source.get("display_name"),
    )


def _extract_venue(source: dict[str, Any], fallback: str | None) -> str | None:
    return _first_text(source.get("display_name"), fallback)


def _extract_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in (
        _extract_landing_page_url(payload),
        _extract_pdf_url(payload),
        _first_text(payload.get("id")),
    ):
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _extract_landing_page_url(payload: dict[str, Any]) -> str | None:
    primary_location = payload.get("primary_location")
    if isinstance(primary_location, dict):
        return _first_text(primary_location.get("landing_page_url"))
    return None


def _extract_pdf_url(payload: dict[str, Any]) -> str | None:
    open_access = payload.get("open_access")
    if isinstance(open_access, dict):
        return _first_text(open_access.get("oa_url"))
    return None


def _extract_countries(authorships: Any) -> list[str]:
    counts = _country_counts(authorships)
    return sorted(counts.keys())


def _extract_country_primary(authorships: Any) -> str | None:
    countries = _extract_countries(authorships)
    if not countries:
        return None
    if len(countries) == 1:
        return countries[0]
    return "MULTI"


def _extract_country_dominant(authorships: Any) -> str | None:
    counts = _country_counts(authorships)
    if not counts:
        return None
    country, _ = min(counts.items(), key=lambda item: (-item[1], item[0]))
    return country


def _country_counts(authorships: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not isinstance(authorships, list):
        return counts
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        institutions = authorship.get("institutions")
        if not isinstance(institutions, list):
            continue
        for institution in institutions:
            if not isinstance(institution, dict):
                continue
            country_code = _normalize_country_code(institution.get("country_code"))
            if country_code is not None:
                counts[country_code] += 1
    return counts


def _source_or_empty(payload: dict[str, Any]) -> dict[str, Any]:
    primary_location = payload.get("primary_location")
    if not isinstance(primary_location, dict):
        return {}
    source = primary_location.get("source")
    if not isinstance(source, dict):
        return {}
    return source


def _first_text(*values: Any) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _normalize_language(*values: Any) -> str | None:
    for value in values:
        language = _first_text(value)
        if language is not None:
            return language.lower()
    return None


def _normalize_non_negative_int(value: Any) -> int | None:
    if not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _normalize_country_code(value: Any) -> str | None:
    code = _first_text(value)
    if code is None:
        return None
    code = code.upper()
    if len(code) != 2 or not code.isalpha():
        return None
    return code


def _normalize_doi_url(value: str | None) -> str | None:
    cleaned = _first_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return cleaned
    if lowered.startswith("doi:"):
        cleaned = cleaned[4:].strip()
    return f"https://doi.org/{cleaned}"


def _normalize_doi_value(value: Any) -> str | None:
    cleaned = _first_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    if lowered.startswith("https://doi.org/"):
        cleaned = cleaned[16:]
    elif lowered.startswith("http://doi.org/"):
        cleaned = cleaned[15:]
    elif lowered.startswith("doi:"):
        cleaned = cleaned[4:].strip()
    cleaned = cleaned.strip().lower()
    return cleaned or None
