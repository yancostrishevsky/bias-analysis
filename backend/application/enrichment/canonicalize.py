"""Canonicalization helpers for provider-specific enrichment records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from backend.domain import (
    CanonicalEnrichment,
    EnrichmentRecord,
    ExecutionStatus,
    FieldProvenance,
)


_SCALAR_FIELDS = (
    "doi",
    "title",
    "abstract",
    "publication_year",
    "language",
    "is_open_access",
    "open_access_status",
    "citation_count",
    "publisher",
    "venue",
    "country_primary",
    "country_dominant",
    "landing_page_url",
    "pdf_url",
)
_LIST_FIELDS = (
    "authors",
    "affiliations",
    "fields_of_study",
    "subject_areas",
    "countries",
    "urls",
)


def canonicalize_enrichment_records(
    *,
    result_record_id: UUID,
    records: Sequence[EnrichmentRecord],
) -> CanonicalEnrichment | None:
    """Build a canonical enrichment from the available provider records."""

    completed_records = [
        record
        for record in records
        if record.status == ExecutionStatus.COMPLETED
    ]
    if not completed_records:
        return None

    canonical = CanonicalEnrichment(
        result_record_id=result_record_id,
        source_record_ids=[record.id for record in completed_records],
    )

    for record in completed_records:
        _merge_external_maps(canonical, record, "external_ids")
        _merge_external_maps(canonical, record, "source_ids")
        _merge_scalar_fields(canonical, record)
        _merge_list_fields(canonical, record)

    return canonical


def _merge_external_maps(
    canonical: CanonicalEnrichment,
    record: EnrichmentRecord,
    field_name: str,
) -> None:
    current_map = getattr(canonical, field_name)
    provider_map = getattr(record, field_name)
    if not provider_map:
        return

    changed = False
    for key, value in provider_map.items():
        if key not in current_map and _has_value(value):
            current_map[key] = value
            changed = True
    if changed and field_name not in canonical.field_provenance:
        canonical.field_provenance[field_name] = FieldProvenance(
            provider=record.provider,
            enrichment_record_id=record.id,
            match_strategy=record.match_strategy,
        )


def _merge_scalar_fields(canonical: CanonicalEnrichment, record: EnrichmentRecord) -> None:
    for field_name in _SCALAR_FIELDS:
        current_value = getattr(canonical, field_name)
        if _has_value(current_value):
            continue
        candidate_value = getattr(record, field_name)
        if not _has_value(candidate_value):
            continue
        setattr(canonical, field_name, candidate_value)
        canonical.field_provenance[field_name] = FieldProvenance(
            provider=record.provider,
            enrichment_record_id=record.id,
            match_strategy=record.match_strategy,
        )


def _merge_list_fields(canonical: CanonicalEnrichment, record: EnrichmentRecord) -> None:
    for field_name in _LIST_FIELDS:
        current_value = getattr(canonical, field_name)
        if current_value:
            continue
        candidate_value = list(getattr(record, field_name))
        if not candidate_value:
            continue
        setattr(canonical, field_name, candidate_value)
        canonical.field_provenance[field_name] = FieldProvenance(
            provider=record.provider,
            enrichment_record_id=record.id,
            match_strategy=record.match_strategy,
        )


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True
