"""Provider-agnostic enrichment domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from backend.domain.models import DomainModel, ExecutionStatus, utc_now


class EnrichmentProvider(str, Enum):
    """Supported enrichment providers."""

    OPENALEX = "openalex"
    CORE = "core"
    SCOPUS = "scopus"
    SEMANTIC_SCHOLAR = "semantic_scholar"


class EnrichmentMatchStrategy(str, Enum):
    """How a provider record was matched to a stored result."""

    SOURCE_IDENTIFIER = "source_identifier"
    DOI = "doi"
    NORMALIZED_DOI_URL = "normalized_doi_url"
    TITLE_YEAR = "title_year"
    TITLE_AUTHORS_YEAR = "title_authors_year"


class FieldProvenance(DomainModel):
    """Structured provenance for one canonical field."""

    provider: EnrichmentProvider
    enrichment_record_id: UUID
    match_strategy: EnrichmentMatchStrategy | None = None


class EnrichmentRecord(DomainModel):
    """One provider-specific enrichment snapshot for a collected result."""

    id: UUID = Field(default_factory=uuid4)
    result_record_id: UUID
    provider: EnrichmentProvider
    provider_record_id: str = Field(min_length=1)
    status: ExecutionStatus = ExecutionStatus.COMPLETED
    enriched_at: datetime = Field(default_factory=utc_now)
    match_strategy: EnrichmentMatchStrategy | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    source_ids: dict[str, str] = Field(default_factory=dict)
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    language: str | None = None
    is_open_access: bool | None = None
    open_access_status: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    publisher: str | None = None
    venue: str | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    subject_areas: list[str] = Field(default_factory=list)
    country_primary: str | None = None
    country_dominant: str | None = None
    countries: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    landing_page_url: str | None = None
    pdf_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class CanonicalEnrichment(DomainModel):
    """Canonical enrichment merged from provider-specific records."""

    id: UUID = Field(default_factory=uuid4)
    result_record_id: UUID
    updated_at: datetime = Field(default_factory=utc_now)
    source_record_ids: list[UUID] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    source_ids: dict[str, str] = Field(default_factory=dict)
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    language: str | None = None
    is_open_access: bool | None = None
    open_access_status: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    publisher: str | None = None
    venue: str | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    subject_areas: list[str] = Field(default_factory=list)
    country_primary: str | None = None
    country_dominant: str | None = None
    countries: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    landing_page_url: str | None = None
    pdf_url: str | None = None
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)


class EnrichmentAttempt(DomainModel):
    """Diagnostics row for provider attempts across a run."""

    result_record_id: UUID
    provider: EnrichmentProvider
    status: ExecutionStatus
    message: str | None = None
