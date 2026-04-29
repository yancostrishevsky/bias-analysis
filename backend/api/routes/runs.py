"""Run endpoints for the application API."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query as ApiQuery, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.application.run_artifacts import get_run_artifacts_writer
from backend.application.analysis.service import build_run_analysis
from backend.application.records.service import build_run_records_response, export_run_records
from backend.application.openrouter_models import (
    resolve_openrouter_model_selection,
    validate_openrouter_model_selection,
)
from backend.application.run_recovery import (
    recover_inactive_running_llm_run,
    recover_inactive_running_llm_runs,
)
from backend.application.run_executor import (
    InvalidRunModelSelectionError,
    UnsupportedArtifactReplayError,
    UnsupportedModelRetryError,
    UnsupportedRunSourceError,
    execute_run,
    normalize_run_sources,
    replay_llm_run_from_artifacts,
    retry_llm_model,
)
from backend.config import OpenRouterModelOption, ScholarlySourceOption, get_settings
from backend.domain import (
    CanonicalEnrichment,
    EnrichmentRecord,
    Query,
    ResultRecord,
    Run,
    RunAnalysis,
    RunDetail,
    RunRecordsResponse,
    RunType,
)
from backend.storage.repository import Repository, get_repository

router = APIRouter(prefix="/runs", tags=["runs"])
LOGGER = logging.getLogger(__name__)
_MAX_SELECTED_MODELS = 10


class RunCreateRequest(BaseModel):
    """Payload for creating a new run."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    run_type: RunType = RunType.SCHOLARLY
    sources: list[str] = Field(default_factory=list)
    selected_models: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=100)
    queries: list[str] = Field(min_length=1)

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("queries must not contain blank strings")
            cleaned.append(text)
        return cleaned


class RunOptionsResponse(BaseModel):
    """Frontend options for run creation."""

    model_config = ConfigDict(extra="forbid")

    supported_run_types: list[RunType]
    default_run_type: RunType
    available_models: list[str]
    default_models: list[str]
    model_catalog: list[OpenRouterModelOption]
    available_scholarly_sources: list[str]
    source_catalog: list[ScholarlySourceOption]
    enabled_enrichment_providers: list[str]
    enrichment_provider_order: list[str]


class ReplayStatusResponse(BaseModel):
    """Replay and downstream provenance metadata for one run."""

    model_config = ConfigDict(extra="forbid")

    replay_available: bool
    replay_summary: dict[str, Any] | None = None
    current_output_source: str | None = None
    current_output_generated_at: str | None = None


class ResultEnrichmentResponse(BaseModel):
    """Provider-specific and canonical enrichment data for one result."""

    model_config = ConfigDict(extra="forbid")

    result_record_id: UUID
    provider_records: list[EnrichmentRecord] = Field(default_factory=list)
    canonical_enrichment: CanonicalEnrichment | None = None


def _repository() -> Repository:
    return get_repository()


def _get_run_or_404(repository: Repository, run_id: UUID) -> Run:
    recover_inactive_running_llm_run(repository=repository, run_id=run_id)
    try:
        return repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        ) from exc


def _normalize_llm_selected_models(
    selected_models: list[str],
    *,
    repository: Repository,
    validate_against_catalog: bool,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for value in selected_models:
        if not isinstance(value, str):
            LOGGER.warning("LLM run validation failed because selected_models contained a non-string value")
            raise InvalidRunModelSelectionError("selected_models must contain only string model ids")

        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)

    if not normalized:
        LOGGER.warning("LLM run validation failed because no selected models were provided")
        raise InvalidRunModelSelectionError("Select at least one OpenRouter model for llm_audit runs")
    if len(normalized) > _MAX_SELECTED_MODELS:
        LOGGER.warning(
            "LLM run validation failed because too many models were selected count=%s max=%s",
            len(normalized),
            _MAX_SELECTED_MODELS,
        )
        raise InvalidRunModelSelectionError(
            f"Select at most {_MAX_SELECTED_MODELS} OpenRouter models for llm_audit runs"
        )

    if not validate_against_catalog:
        return normalized

    try:
        return validate_openrouter_model_selection(
            repository=repository,
            selected_models=normalized,
        )
    except ValueError as exc:
        LOGGER.warning("LLM run validation failed because unknown model ids were provided: %s", exc)
        raise InvalidRunModelSelectionError(str(exc)) from exc


def _normalize_create_payload(payload: RunCreateRequest, *, repository: Repository) -> RunCreateRequest:
    if payload.run_type == RunType.SCHOLARLY:
        try:
            sources = normalize_run_sources(payload.sources)
        except UnsupportedRunSourceError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return payload.model_copy(update={"sources": sources, "selected_models": []})

    try:
        models = _normalize_llm_selected_models(
            payload.selected_models,
            repository=repository,
            validate_against_catalog=True,
        )
    except InvalidRunModelSelectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return payload.model_copy(update={"sources": [], "selected_models": models})


@router.get("/options", response_model=RunOptionsResponse)
def get_run_options() -> RunOptionsResponse:
    """Return run-creation options for the frontend."""

    settings = get_settings()
    return RunOptionsResponse(
        supported_run_types=[RunType.SCHOLARLY, RunType.LLM_AUDIT],
        default_run_type=RunType(settings.default_run_type),
        available_models=settings.openrouter.available_models,
        default_models=settings.openrouter.default_models,
        model_catalog=settings.openrouter.model_catalog,
        available_scholarly_sources=settings.scholarly_sources,
        source_catalog=settings.source_catalog,
        enabled_enrichment_providers=settings.enabled_enrichment_providers,
        enrichment_provider_order=settings.enrichment_provider_order,
    )


@router.post("", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
def create_run(payload: RunCreateRequest) -> RunDetail:
    """Create a new run in the pending state."""

    repository = _repository()
    normalized = _normalize_create_payload(payload, repository=repository)
    run = Run(
        run_type=normalized.run_type,
        sources=normalized.sources,
        selected_models=normalized.selected_models,
        top_k=normalized.top_k,
    )
    queries = [
        Query(run_id=run.id, text=query_text, position=position)
        for position, query_text in enumerate(normalized.queries, start=1)
    ]
    detail = repository.create_run(run, queries)
    get_run_artifacts_writer(detail.run.id).initialize_run(
        run=detail.run,
        queries=detail.queries,
        raw_create_payload=payload.model_dump(mode="json"),
        normalized_payload=normalized.model_dump(mode="json"),
    )
    return detail


@router.get("", response_model=list[RunDetail])
def list_runs() -> list[RunDetail]:
    """Return all runs in insertion order."""

    repository = _repository()
    recover_inactive_running_llm_runs(repository=repository)
    return repository.list_runs()


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: UUID) -> RunDetail:
    """Return run details by identifier."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    return repository.get_run_detail(run_id)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_run(run_id: UUID) -> Response:
    """Delete one run and its persisted artifacts regardless of current status."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    deleted = repository.delete_run(run_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    get_run_artifacts_writer(run_id).delete_run_artifacts()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}/replay-status", response_model=ReplayStatusResponse)
def get_run_replay_status(run_id: UUID) -> ReplayStatusResponse:
    """Return replay summary and current downstream provenance for one run."""

    repository = _repository()
    run = _get_run_or_404(repository, run_id)
    artifacts = get_run_artifacts_writer(run_id)
    replay_summary = artifacts.read_replay_summary()
    analysis_metadata = artifacts.read_analysis_metadata()
    return ReplayStatusResponse(
        replay_available=run.run_type == RunType.LLM_AUDIT and artifacts.has_replayable_llm_artifacts(),
        replay_summary=replay_summary,
        current_output_source=(
            str(analysis_metadata.get("source"))
            if isinstance(analysis_metadata, dict) and analysis_metadata.get("source") is not None
            else None
        ),
        current_output_generated_at=(
            str(analysis_metadata.get("generated_at"))
            if isinstance(analysis_metadata, dict) and analysis_metadata.get("generated_at") is not None
            else None
        ),
    )


@router.post("/{run_id}/models/{model_id:path}/retry", response_model=RunDetail)
def retry_run_model(run_id: UUID, model_id: str) -> RunDetail:
    """Retry failed or missing query executions for one model in an llm_audit run."""

    repository = _repository()
    run = _get_run_or_404(repository, run_id)
    queries = repository.list_queries(run.id)
    if run.run_type != RunType.LLM_AUDIT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Model retry is only supported for llm_audit runs",
        )
    if run.status.value == "running":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Run {run_id} cannot retry a model while it is running",
        )
    if model_id not in run.selected_models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_id} not found in run {run_id}",
        )

    latest_calls = repository.list_latest_llm_calls_for_model(run.id, model_id)
    result_query_ids = {
        result.query_id
        for result in repository.list_results(run.id)
        if result.model_name == model_id
    }
    retryable = any(
        query.id not in latest_calls
        or latest_calls[query.id].status.value != "completed"
        or query.id not in result_query_ids
        for query in queries
    )
    if not retryable:
        get_run_artifacts_writer(run.id).append_event(
            stage="retry",
            message="Model retry request was idempotent; no failed or missing queries found",
            model=model_id,
        )
        return repository.get_run_detail(run.id)

    try:
        retry_llm_model(
            repository=repository,
            run=run,
            queries=queries,
            model_name=model_id,
        )
    except UnsupportedModelRetryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return repository.get_run_detail(run_id)


@router.get("/{run_id}/results", response_model=list[ResultRecord])
def get_run_results(run_id: UUID) -> list[ResultRecord]:
    """Return all stored result records for a run."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    return repository.list_results(run_id)


@router.get("/{run_id}/enrichments", response_model=list[ResultEnrichmentResponse])
def get_run_enrichments(run_id: UUID) -> list[ResultEnrichmentResponse]:
    """Return enrichment data for each stored result record in a run."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    enrichments = repository.list_enrichments_by_result(run_id)
    return [
        ResultEnrichmentResponse(
            result_record_id=result_id,
            provider_records=provider_records,
            canonical_enrichment=canonical_enrichment,
        )
        for result_id, (provider_records, canonical_enrichment) in enrichments.items()
    ]


@router.get("/{run_id}/analysis", response_model=RunAnalysis)
def get_run_analysis(run_id: UUID) -> RunAnalysis:
    """Return the dashboard payload for one run."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    return build_run_analysis(repository=repository, run_id=run_id)


@router.get("/{run_id}/records", response_model=RunRecordsResponse)
def get_run_records(
    run_id: UUID,
    query_id: str | None = None,
    entity: str | None = None,
    top_k: int | None = ApiQuery(default=None, ge=1),
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
    year_from: int | None = ApiQuery(default=None, ge=1800, le=2100),
    year_to: int | None = ApiQuery(default=None, ge=1800, le=2100),
    search: str | None = None,
    only_enriched: bool = False,
    only_verified: bool = False,
    only_conflicting: bool = False,
) -> RunRecordsResponse:
    """Return unified record rows for the separate records explorer."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    top_k_value = top_k if isinstance(top_k, int) else None
    year_from_value = year_from if isinstance(year_from, int) else None
    year_to_value = year_to if isinstance(year_to, int) else None
    return build_run_records_response(
        repository=repository,
        run_id=run_id,
        query_id=query_id,
        entity=entity,
        top_k=top_k_value,
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
        year_from=year_from_value,
        year_to=year_to_value,
        search=search,
        only_enriched=only_enriched,
        only_verified=only_verified,
        only_conflicting=only_conflicting,
    )


@router.get("/{run_id}/records/export")
def export_run_records_file(
    run_id: UUID,
    format: str = ApiQuery(default="csv", pattern="^(csv|json|jsonl)$"),
    view: str = ApiQuery(default="unified", pattern="^(raw|enriched|verification|unified)$"),
    query_id: str | None = None,
    entity: str | None = None,
    top_k: int | None = ApiQuery(default=None, ge=1),
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
    year_from: int | None = ApiQuery(default=None, ge=1800, le=2100),
    year_to: int | None = ApiQuery(default=None, ge=1800, le=2100),
    search: str | None = None,
    only_enriched: bool = False,
    only_verified: bool = False,
    only_conflicting: bool = False,
) -> Response:
    """Export filtered unified record rows in research-friendly formats."""

    repository = _repository()
    _get_run_or_404(repository, run_id)
    top_k_value = top_k if isinstance(top_k, int) else None
    year_from_value = year_from if isinstance(year_from, int) else None
    year_to_value = year_to if isinstance(year_to, int) else None
    content, media_type, filename = export_run_records(
        repository=repository,
        run_id=run_id,
        export_format=format,
        export_view=view,
        filters={
            "query_id": query_id,
            "entity": entity,
            "top_k": top_k_value,
            "rank_bucket": rank_bucket,
            "parse_status": parse_status,
            "matched": matched,
            "doi_valid": doi_valid,
            "conflicting": conflicting,
            "language": language,
            "publisher": publisher,
            "country": country,
            "oa_status": oa_status,
            "source_type": source_type,
            "risk_bucket": risk_bucket,
            "year_from": year_from_value,
            "year_to": year_to_value,
            "search": search,
            "only_enriched": only_enriched,
            "only_verified": only_verified,
            "only_conflicting": only_conflicting,
        },
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{run_id}/start", response_model=RunDetail)
def start_run(run_id: UUID) -> RunDetail:
    """Start a pending run and execute the selected mode."""

    repository = _repository()
    run = _get_run_or_404(repository, run_id)
    queries = repository.list_queries(run.id)
    if run.status.value != "pending":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Run {run_id} cannot be started from status '{run.status.value}'",
        )
    validation = None
    if run.run_type == RunType.LLM_AUDIT:
        validation = resolve_openrouter_model_selection(
            repository=repository,
            selected_models=list(run.selected_models),
        )
        if validation.unavailable_model_ids:
            detail = (
                "Selected OpenRouter models are unavailable in the current catalog: "
                f"{', '.join(validation.unavailable_model_ids)}"
            )
            LOGGER.warning(
                "LLM run start validation failed run_id=%s selection_source=persisted_run selected_models=%s unavailable=%s catalog_size=%s cached=%s",
                run.id,
                validation.selected_models,
                validation.unavailable_model_ids,
                validation.catalog.total,
                validation.catalog.cached,
            )
            get_run_artifacts_writer(run.id).append_event(
                stage="llm",
                message="Model validation failed before execution",
                selection_source="persisted_run",
                selected_models=validation.selected_models,
                unavailable_models=validation.unavailable_model_ids,
                catalog_size=validation.catalog.total,
                cached=validation.catalog.cached,
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
        try:
            run.selected_models = _normalize_llm_selected_models(
                validation.selected_models,
                repository=repository,
                validate_against_catalog=False,
            )
        except InvalidRunModelSelectionError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        LOGGER.info(
            "LLM run start validation passed run_id=%s selection_source=persisted_run selected_models=%s catalog_size=%s cached=%s",
            run.id,
            validation.selected_models,
            validation.catalog.total,
            validation.catalog.cached,
        )
        get_run_artifacts_writer(run.id).append_event(
            stage="llm",
            message="Model validation passed before execution",
            selection_source="persisted_run",
            selected_models=validation.selected_models,
            catalog_size=validation.catalog.total,
            cached=validation.catalog.cached,
            unavailable_models=[],
        )

    openrouter_model_catalog = validation.catalog if validation is not None else None

    try:
        execute_run(
            repository=repository,
            run=run,
            queries=queries,
            openrouter_model_catalog=openrouter_model_catalog,
        )
    except (UnsupportedRunSourceError, InvalidRunModelSelectionError) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if isinstance(exc, InvalidRunModelSelectionError)
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc
    return repository.get_run_detail(run_id)


@router.post("/{run_id}/replay-llm-artifacts", response_model=RunDetail)
def replay_llm_artifacts(run_id: UUID) -> RunDetail:
    """Replay llm_audit downstream processing from persisted artifacts."""

    repository = _repository()
    run = _get_run_or_404(repository, run_id)
    queries = repository.list_queries(run.id)
    if run.status.value == "running":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Run {run_id} cannot be replayed while it is running",
        )

    try:
        replay_llm_run_from_artifacts(repository=repository, run=run, queries=queries)
    except UnsupportedArtifactReplayError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return repository.get_run_detail(run_id)
