"""Domain models for run analysis payloads."""

from __future__ import annotations

from pydantic import Field

from backend.domain.models import DomainModel, RunType


class AnalysisFilterOption(DomainModel):
    """One selectable filter option."""

    value: str = Field(min_length=1)
    label: str = Field(min_length=1)


class RunAnalysisSummary(DomainModel):
    """Summary values for the run detail page."""

    run_id: str = Field(min_length=1)
    run_type: RunType
    status: str = Field(min_length=1)
    total_results: int = Field(ge=0)
    query_count: int = Field(ge=0)
    entity_label: str = Field(min_length=1)
    entity_count: int = Field(ge=0)
    completed_entity_count: int = Field(ge=0)
    failed_entity_count: int = Field(ge=0)


class AnalysisFilters(DomainModel):
    """Filter metadata for the frontend."""

    queries: list[AnalysisFilterOption] = Field(default_factory=list)
    entities: list[AnalysisFilterOption] = Field(default_factory=list)
    top_ks: list[int] = Field(default_factory=list)
    default_top_k: int = Field(ge=1)


class DistributionRow(DomainModel):
    """One distribution bucket row."""

    metric: str = Field(min_length=1)
    query_id: str | None = None
    entity: str = Field(min_length=1)
    label: str = Field(min_length=1)
    count: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)


class CoverageRow(DomainModel):
    """One metadata coverage row."""

    query_id: str | None = None
    entity: str = Field(min_length=1)
    field: str = Field(min_length=1)
    populated_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)


class BiasFieldSourceRow(DomainModel):
    """One source-count row for a bias-analysis field."""

    field: str = Field(min_length=1)
    source: str = Field(min_length=1)
    count: int = Field(ge=0)


class BiasFieldWarningRow(DomainModel):
    """One warning about a bias field that needed recovery or remained unknown."""

    result_id: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    field: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    upstream_source: str | None = None


class TopKComparisonRow(DomainModel):
    """One top-k versus overall comparison row."""

    query_id: str | None = None
    entity: str = Field(min_length=1)
    k: int = Field(ge=1)
    metric: str = Field(min_length=1)
    top_k_value: float | None = None
    overall_value: float | None = None
    delta: float | None = None


class OverlapRow(DomainModel):
    """One overlap/correlation row between two entities."""

    query_id: str | None = None
    left_entity: str = Field(min_length=1)
    right_entity: str = Field(min_length=1)
    jaccard: float | None = Field(default=None, ge=0.0, le=1.0)
    overlap_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    rank_biased_overlap: float | None = Field(default=None, ge=0.0, le=1.0)
    top_1_agreement: float | None = Field(default=None, ge=0.0, le=1.0)


class ConcentrationRow(DomainModel):
    """One concentration/diversity row."""

    query_id: str | None = None
    entity: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    value: float | None = Field(default=None, ge=0.0)


class LLMCallRow(DomainModel):
    """One llm execution row for the dashboard."""

    query_id: str
    model_name: str
    status: str
    parse_success: bool
    parse_mode: str | None = None
    partial_json_recovery: bool = False
    parsed_item_count: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class LLMMetricRow(DomainModel):
    """One llm-specific aggregate row."""

    query_id: str | None = None
    entity: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    value: float | None = None
    count: int | None = Field(default=None, ge=0)
    note: str | None = None


class LLMAnalysisSection(DomainModel):
    """LLM-specific analysis payload."""

    calls: list[LLMCallRow] = Field(default_factory=list)
    metrics: list[LLMMetricRow] = Field(default_factory=list)


class RunAnalysis(DomainModel):
    """Complete dashboard payload for one run."""

    summary: RunAnalysisSummary
    filters: AnalysisFilters
    distributions: list[DistributionRow] = Field(default_factory=list)
    coverage_rows: list[CoverageRow] = Field(default_factory=list)
    baseline_coverage_rows: list[CoverageRow] = Field(default_factory=list)
    bias_field_sources: list[BiasFieldSourceRow] = Field(default_factory=list)
    bias_field_warnings: list[BiasFieldWarningRow] = Field(default_factory=list)
    top_k_rows: list[TopKComparisonRow] = Field(default_factory=list)
    overlap_rows: list[OverlapRow] = Field(default_factory=list)
    concentration_rows: list[ConcentrationRow] = Field(default_factory=list)
    llm: LLMAnalysisSection | None = None
