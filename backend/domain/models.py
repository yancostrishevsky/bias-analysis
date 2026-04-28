"""Pydantic domain models for runs, execution, and persisted records."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    """Base model for domain objects."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunType(str, Enum):
    """Supported run modes."""

    SCHOLARLY = "scholarly"
    LLM_AUDIT = "llm_audit"


class RunStatus(str, Enum):
    """Lifecycle states for a run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ExecutionStatus(str, Enum):
    """Execution status for run entities and low-level calls."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResultOriginType(str, Enum):
    """Where a result row came from."""

    SCHOLARLY_SOURCE = "scholarly_source"
    LLM_RESPONSE = "llm_response"


class Run(DomainModel):
    """A user-triggered scholarly or llm-audit run."""

    id: UUID = Field(default_factory=uuid4)
    run_type: RunType = RunType.SCHOLARLY
    status: RunStatus = RunStatus.PENDING
    stage: str = "pending"
    progress_current: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    progress_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    finished_at: datetime | None = None
    top_k: int = Field(default=10, ge=1, le=100)
    error_message: str | None = None
    sources: list[str] = Field(default_factory=list)
    selected_models: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "Run":
        """Enforce mode-aware run semantics."""

        if self.run_type == RunType.SCHOLARLY:
            self.selected_models = []
        if self.run_type == RunType.LLM_AUDIT:
            self.sources = []
        return self


class Query(DomainModel):
    """A single search question belonging to a run."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    text: str = Field(min_length=1)
    position: int = Field(ge=1)
    language: str | None = None


class EntityExecutionSummary(DomainModel):
    """Aggregated status for a model or source inside a run."""

    entity_type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: ExecutionStatus
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    total_count: int = Field(default=0, ge=0)
    progress_current: int = Field(default=0, ge=0)
    progress_total: int = Field(default=0, ge=0)
    progress_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class LLMCall(DomainModel):
    """One provider call for query x model execution."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    query_id: UUID
    model_name: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    status: ExecutionStatus = ExecutionStatus.PENDING
    prompt_text: str = Field(min_length=1)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    response_text: str | None = None
    parse_success: bool = False
    parse_error: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResultRecord(DomainModel):
    """One comparable result row stored for scholarly and llm-audit runs."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    query_id: UUID
    llm_call_id: UUID | None = None
    origin_type: ResultOriginType
    source_name: str | None = None
    model_name: str | None = None
    provider_name: str | None = None
    execution_status: ExecutionStatus = ExecutionStatus.COMPLETED
    rank: int = Field(ge=1)
    canonical_identifier: str | None = None
    title: str = Field(min_length=1)
    doi: str | None = None
    url: str | None = None
    source_identifier: str | None = None
    year: int | None = Field(default=None, ge=1800, le=2100)
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    publisher: str | None = None
    language: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class RunDetail(DomainModel):
    """Run plus queries and execution summaries."""

    run: Run
    queries: list[Query] = Field(default_factory=list)
    entity_statuses: list[EntityExecutionSummary] = Field(default_factory=list)
