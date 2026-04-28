"""Domain models for unified record exploration and exports."""

from __future__ import annotations

from pydantic import Field

from backend.domain.models import DomainModel, RunType


class RecordsFilterOption(DomainModel):
    """One selectable filter option for the records explorer."""

    value: str = Field(min_length=1)
    label: str = Field(min_length=1)


class RunRecordsSummary(DomainModel):
    """Summary metadata for the records explorer response."""

    run_id: str = Field(min_length=1)
    run_type: RunType
    total_rows: int = Field(ge=0)
    filtered_rows: int = Field(ge=0)
    export_formats: list[str] = Field(default_factory=lambda: ["csv", "json", "jsonl"])
    export_views: list[str] = Field(default_factory=lambda: ["raw", "enriched", "verification", "unified"])


class RunRecordsFilters(DomainModel):
    """Available filter values for the records explorer."""

    queries: list[RecordsFilterOption] = Field(default_factory=list)
    entities: list[RecordsFilterOption] = Field(default_factory=list)
    languages: list[RecordsFilterOption] = Field(default_factory=list)
    publishers: list[RecordsFilterOption] = Field(default_factory=list)
    countries: list[RecordsFilterOption] = Field(default_factory=list)
    oa_statuses: list[RecordsFilterOption] = Field(default_factory=list)
    source_types: list[RecordsFilterOption] = Field(default_factory=list)
    parse_statuses: list[RecordsFilterOption] = Field(default_factory=list)
    risk_buckets: list[RecordsFilterOption] = Field(default_factory=list)


class UnifiedRecordRow(DomainModel):
    """One research-ready record row combining raw, parsed, enriched, and verification fields."""

    run_id: str = Field(min_length=1)
    run_mode: RunType
    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    query_category: str | None = None
    model_or_platform: str = Field(min_length=1)
    provider: str | None = None
    repeat_index: int | None = Field(default=None, ge=1)
    rank: int = Field(ge=1)
    rank_bucket: str = Field(min_length=1)

    raw_title: str | None = None
    raw_doi: str | None = None
    raw_year: int | None = Field(default=None, ge=1800, le=2100)
    raw_journal: str | None = None
    raw_authors: list[str] = Field(default_factory=list)
    raw_rationale: str | None = None

    parsed_title: str | None = None
    parsed_doi: str | None = None
    parsed_year: int | None = Field(default=None, ge=1800, le=2100)
    parsed_journal: str | None = None
    parsed_authors: list[str] = Field(default_factory=list)

    enriched_title: str | None = None
    enriched_doi: str | None = None
    enriched_year: int | None = Field(default=None, ge=1800, le=2100)
    enriched_journal: str | None = None
    enriched_authors: list[str] = Field(default_factory=list)
    external_match_id: str | None = None
    matched: bool = False
    match_strategy: str | None = None

    doi_valid: bool | None = None
    title_match_status: str | None = None
    year_conflict: bool = False
    journal_conflict: bool = False
    author_conflict: bool = False
    publisher_conflict: bool = False
    any_conflict: bool = False
    conflict_count: int = Field(default=0, ge=0)
    unmatched_reason: str | None = None

    language: str | None = None
    country_primary: str | None = None
    countries: list[str] = Field(default_factory=list)
    publisher: str | None = None
    source_type: str | None = None
    is_oa: bool | None = None
    oa_status: str | None = None
    oa_pathway: str | None = None
    cited_by_count: int | None = Field(default=None, ge=0)
    topic: str | None = None
    subfield: str | None = None

    parse_status: str | None = None
    parse_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    parse_strategy: str | None = None
    parse_fallback_used: bool = False
    parse_errors: str | None = None

    suspicious_completeness: bool = False
    hallucination_risk_bucket: str | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    provenance_summary: str | None = None

    raw_payload: dict = Field(default_factory=dict)
    parsed_payload: dict = Field(default_factory=dict)
    enriched_payload: dict = Field(default_factory=dict)
    verification_trace: dict = Field(default_factory=dict)


class RunRecordsResponse(DomainModel):
    """Complete records explorer payload for one run."""

    summary: RunRecordsSummary
    filters: RunRecordsFilters
    rows: list[UnifiedRecordRow] = Field(default_factory=list)
