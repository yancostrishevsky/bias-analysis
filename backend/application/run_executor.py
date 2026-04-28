"""Application-layer orchestration for executing scholarly and llm-audit runs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from backend.adapters.openalex.client import OpenAlexClient, OpenAlexClientError
from backend.adapters.openalex.mapper import OpenAlexMappingError, map_openalex_work
from backend.adapters.openrouter.client import (
    OpenRouterClient,
    OpenRouterError,
    OpenRouterModelDiscoveryError,
    extract_output_text_from_response_payload,
)
from backend.adapters.scholarly import (
    COREClient,
    COREClientError,
    ScholarlySearchRequest,
    ScholarlySourceMappingError,
    ScopusClient,
    ScopusClientError,
    SemanticScholarClient,
    SemanticScholarClientError,
    map_core_work,
    map_scopus_entry,
    map_semantic_scholar_paper,
)
from backend.application.openrouter_models import OpenRouterModelCatalogSnapshot, load_openrouter_model_catalog_snapshot
from backend.application.run_recovery import track_active_run
from backend.application.run_artifacts import RunArtifactsWriter, get_run_artifacts_writer
from backend.application.enrichment.providers import normalize_doi, normalize_title
from backend.application.enrichment.service import enrich_results
from backend.application.llm_parser import (
    LLMParseError,
    build_article_retrieval_prompt,
    parse_article_recommendations,
    parse_article_recommendations_with_diagnostics,
)
from backend.config import get_settings
from backend.domain import (
    ExecutionStatus,
    LLMCall,
    Query,
    ResultOriginType,
    ResultRecord,
    Run,
    RunStatus,
    RunType,
)
from backend.storage.repository import Repository


DEFAULT_SCHOLARLY_SOURCE = "openalex"
_UNSET = object()
LOGGER = logging.getLogger(__name__)


class ScholarlySourceCollector(Protocol):
    """Adapter contract for one scholarly collection source."""

    name: str
    display_name: str

    def build_search_request(self, *, query_text: str, per_page: int) -> Any:
        """Return the source-specific search request envelope."""

    def search(
        self,
        query_text: str,
        per_page: int,
        *,
        request: Any | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search one source for one query string."""

    def map_result(
        self,
        *,
        run_id: Any,
        query_id: Any,
        rank: int,
        payload: dict[str, Any],
    ) -> ResultRecord:
        """Map one source payload into a persisted result row."""


class UnsupportedRunSourceError(ValueError):
    """Raised when a run references a source that is not implemented."""


class InvalidRunModelSelectionError(ValueError):
    """Raised when a run references LLM models outside the configured catalog."""


class UnsupportedArtifactReplayError(ValueError):
    """Raised when a run cannot be replayed from stored artifacts."""


class OpenAlexSourceCollector:
    """Collection adapter for OpenAlex."""

    name = "openalex"
    display_name = "OpenAlex"

    def __init__(self, client: OpenAlexClient | None = None) -> None:
        self.client = client or OpenAlexClient.from_settings()

    def build_search_request(self, *, query_text: str, per_page: int) -> Any:
        return self.client.build_search_works_request(query_text=query_text, per_page=per_page)

    def search(
        self,
        query_text: str,
        per_page: int,
        *,
        request: Any | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.client.search_works(
            query_text=query_text,
            per_page=per_page,
            request=request,
            include_raw=include_raw,
        )

    def map_result(
        self,
        *,
        run_id: Any,
        query_id: Any,
        rank: int,
        payload: dict[str, Any],
    ) -> ResultRecord:
        return map_openalex_work(run_id=run_id, query_id=query_id, rank=rank, work=payload)


class SemanticScholarSourceCollector:
    """Collection adapter for Semantic Scholar."""

    name = "semantic_scholar"
    display_name = "Semantic Scholar"

    def __init__(self, client: SemanticScholarClient | None = None) -> None:
        self.client = client or SemanticScholarClient.from_settings()

    def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
        return self.client.build_search_request(query_text=query_text, per_page=per_page)

    def search(
        self,
        query_text: str,
        per_page: int,
        *,
        request: ScholarlySearchRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.client.search_papers(
            query_text=query_text,
            per_page=per_page,
            request=request,
            include_raw=include_raw,
        )

    def map_result(
        self,
        *,
        run_id: Any,
        query_id: Any,
        rank: int,
        payload: dict[str, Any],
    ) -> ResultRecord:
        return map_semantic_scholar_paper(
            run_id=run_id,
            query_id=query_id,
            rank=rank,
            paper=payload,
        )


class CoreSourceCollector:
    """Collection adapter for CORE."""

    name = "core"
    display_name = "CORE"

    def __init__(self, client: COREClient | None = None) -> None:
        self.client = client or COREClient.from_settings()

    def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
        return self.client.build_search_request(query_text=query_text, per_page=per_page)

    def search(
        self,
        query_text: str,
        per_page: int,
        *,
        request: ScholarlySearchRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.client.search_works(
            query_text=query_text,
            per_page=per_page,
            request=request,
            include_raw=include_raw,
        )

    def map_result(
        self,
        *,
        run_id: Any,
        query_id: Any,
        rank: int,
        payload: dict[str, Any],
    ) -> ResultRecord:
        return map_core_work(run_id=run_id, query_id=query_id, rank=rank, work=payload)


class ScopusSourceCollector:
    """Collection adapter for Scopus."""

    name = "scopus"
    display_name = "Scopus"

    def __init__(self, client: ScopusClient | None = None) -> None:
        self.client = client or ScopusClient.from_settings()

    def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
        return self.client.build_search_request(query_text=query_text, per_page=per_page)

    def search(
        self,
        query_text: str,
        per_page: int,
        *,
        request: ScholarlySearchRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.client.search_works(
            query_text=query_text,
            per_page=per_page,
            request=request,
            include_raw=include_raw,
        )

    def map_result(
        self,
        *,
        run_id: Any,
        query_id: Any,
        rank: int,
        payload: dict[str, Any],
    ) -> ResultRecord:
        return map_scopus_entry(run_id=run_id, query_id=query_id, rank=rank, entry=payload)


def _build_scholarly_collectors() -> dict[str, ScholarlySourceCollector]:
    return {
        "openalex": OpenAlexSourceCollector(),
        "semantic_scholar": SemanticScholarSourceCollector(),
        "scopus": ScopusSourceCollector(),
        "core": CoreSourceCollector(),
    }


def normalize_run_sources(sources: Iterable[str]) -> list[str]:
    """Normalize user-provided sources and enforce the current source policy."""

    settings = get_settings()
    normalized: list[str] = []
    seen: set[str] = set()
    source_items = list(sources)
    configured_sources = list(settings.scholarly_sources)
    known_sources = set(configured_sources)

    if not source_items:
        if DEFAULT_SCHOLARLY_SOURCE in known_sources:
            return [DEFAULT_SCHOLARLY_SOURCE]
        if configured_sources:
            return [configured_sources[0]]
        raise UnsupportedRunSourceError("No scholarly sources are configured")

    for source in source_items:
        cleaned = source.strip().lower()
        if not cleaned:
            raise UnsupportedRunSourceError("sources must not contain blank strings")
        if cleaned not in known_sources:
            raise UnsupportedRunSourceError(
                f"Unsupported source '{source}'. Supported sources: {', '.join(configured_sources)}",
            )
        option = settings.source_option(cleaned)
        if option is not None and not option.selectable:
            reason = option.validation_reason or "Source is not currently selectable."
            raise UnsupportedRunSourceError(
                f"Source selection '{source}' is not currently selectable: {reason}",
            )
        if cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)

    return normalized


def normalize_run_sources_for_execution(sources: Iterable[str]) -> list[str]:
    """Normalize stored source selections for execution without catalog rejection."""

    normalized: list[str] = []
    seen: set[str] = set()
    for source in sources:
        cleaned = source.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    if normalized:
        return normalized
    settings = get_settings()
    if DEFAULT_SCHOLARLY_SOURCE in settings.scholarly_sources:
        return [DEFAULT_SCHOLARLY_SOURCE]
    return list(settings.scholarly_sources[:1])


def _preflight_source_skip_details(*, source_name: str) -> dict[str, Any] | None:
    settings = get_settings()
    option = settings.source_option(source_name)
    if option is None:
        return {
            "reason": (
                f"Skipped without API call because source '{source_name}' is not present "
                "in the current scholarly source catalog."
            ),
            "failure_kind": "preflight_validation",
            "validation_state": "unknown",
        }
    if option.selectable:
        return None
    reason = option.validation_reason or "Source is not currently selectable."
    return {
        "reason": f"Skipped without API call because source '{source_name}' is not selectable: {reason}",
        "failure_kind": "preflight_validation",
        "validation_state": option.validation_state,
    }


def normalize_selected_models(selected_models: Iterable[str]) -> list[str]:
    """Normalize and validate selected model names."""

    settings = get_settings().openrouter
    normalized = normalize_selected_models_for_execution(selected_models)
    invalid_messages = [
        _invalid_model_selection_message(model_name=model_name)
        for model_name in normalized
        if model_name not in settings.available_models
    ]
    if invalid_messages:
        raise InvalidRunModelSelectionError("; ".join(invalid_messages))
    return normalized


def normalize_selected_models_for_execution(selected_models: Iterable[str]) -> list[str]:
    """Normalize selected models for an existing run without catalog rejection."""

    settings = get_settings().openrouter
    normalized: list[str] = []
    seen: set[str] = set()

    for value in selected_models:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)

    return normalized or list(settings.default_models)


def _invalid_model_selection_message(*, model_name: str) -> str:
    settings = get_settings().openrouter
    option = settings.model_option(model_name)
    if option is None:
        return f"Unknown model selection: {model_name}"

    reason = option.validation_reason or "Model is not currently selectable."
    if option.replacement_model_id:
        return (
            f"Model selection '{model_name}' is not currently selectable: {reason} "
            f"Use '{option.replacement_model_id}' instead."
        )
    return f"Model selection '{model_name}' is not currently selectable: {reason}"


def _preflight_model_skip_details(
    *,
    model_name: str,
    catalog: OpenRouterModelCatalogSnapshot,
) -> dict[str, Any] | None:
    if model_name not in catalog.ids:
        return {
            "reason": (
                f"Skipped without API call because model '{model_name}' is not present "
                "in the current OpenRouter model catalog snapshot used for execution."
            ),
            "failure_kind": "preflight_validation",
            "validation_state": "unknown",
            "replacement_model_id": None,
        }
    return None


def execute_run(
    *,
    repository: Repository,
    run: Run,
    queries: Sequence[Query],
    openrouter_model_catalog: OpenRouterModelCatalogSnapshot | None = None,
) -> Run:
    """Execute one run end-to-end and persist results."""

    with track_active_run(run.id):
        if run.run_type == RunType.SCHOLARLY:
            run.sources = normalize_run_sources_for_execution(run.sources)
        else:
            run.selected_models = normalize_selected_models_for_execution(run.selected_models)

        artifacts = get_run_artifacts_writer(run.id)
        artifacts.clear_replay_artifacts()
        repository.reset_run_execution(run.id)
        started_at = datetime.now(timezone.utc)
        _update_run_state(
            repository=repository,
            run=run,
            status=RunStatus.RUNNING,
            stage="initializing",
            progress_current=0,
            progress_total=max(len(queries), 1),
            progress_message="Preparing run execution",
            started_at=started_at,
            completed_at=None,
            finished_at=None,
            error_message=None,
            artifacts=artifacts,
            query_count=len(queries),
        )
        artifacts.append_event(
            stage="run",
            message="Run started",
            run_type=run.run_type.value,
            query_count=len(queries),
        )

        try:
            if run.run_type == RunType.SCHOLARLY:
                return _execute_scholarly_run(
                    repository=repository,
                    run=run,
                    queries=queries,
                    artifacts=artifacts,
                )
            return _execute_llm_audit_run(
                repository=repository,
                run=run,
                queries=queries,
                artifacts=artifacts,
                openrouter_model_catalog=openrouter_model_catalog,
            )
        except Exception as exc:  # pragma: no cover - defensive containment for live runs
            finished_at = datetime.now(timezone.utc)
            artifacts.write_run_error(
                {
                    "run_id": str(run.id),
                    "run_type": run.run_type.value,
                    "status": RunStatus.FAILED.value,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "finished_at": finished_at,
                }
            )
            artifacts.append_error(
                stage="run",
                message=str(exc),
                error_type=type(exc).__name__,
            )
            _update_run_state(
                repository=repository,
                run=run,
                status=RunStatus.FAILED,
                stage="error",
                progress_message=str(exc),
                error_message=str(exc),
                completed_at=finished_at,
                finished_at=finished_at,
                artifacts=artifacts,
                query_count=len(queries),
            )
            return repository.get_run(run.id)


def _execute_scholarly_run(
    *,
    repository: Repository,
    run: Run,
    queries: Sequence[Query],
    artifacts: RunArtifactsWriter,
) -> Run:
    collectors = _build_scholarly_collectors()
    results: list[ResultRecord] = []
    failed_source_queries = 0
    skipped_source_queries = 0
    completed_source_queries = 0
    total_queries = max(len(queries), 1)
    total_source_queries = max(total_queries * max(len(run.sources), 1), 1)
    processed_source_queries = 0
    source_completed_counts = {source_name: 0 for source_name in run.sources}
    source_failed_counts = {source_name: 0 for source_name in run.sources}
    raw_results_by_query: dict[int, list[dict[str, Any]]] = {index: [] for index in range(1, total_queries + 1)}
    normalized_results_by_query: dict[int, list[ResultRecord]] = {
        index: [] for index in range(1, total_queries + 1)
    }

    _update_run_state(
        repository=repository,
        run=run,
        stage="collecting",
        progress_current=0,
        progress_total=total_source_queries,
        progress_message="Starting scholarly collection",
        artifacts=artifacts,
        query_count=len(queries),
    )

    for source_name in run.sources:
        skip_details = _preflight_source_skip_details(source_name=source_name)
        if skip_details is not None:
            skipped_source_queries += total_queries
            skipped_at = datetime.now(timezone.utc)
            artifacts.append_event(
                stage="scholarly",
                message="Collection source disabled before execution",
                source=source_name,
                reason=skip_details["reason"],
                failure_kind=skip_details["failure_kind"],
                validation_state=skip_details["validation_state"],
            )
            _update_run_source_state(
                repository=repository,
                run_id=run.id,
                source_name=source_name,
                status=ExecutionStatus.SKIPPED,
                completed_count=0,
                failed_count=total_queries,
                progress_current=total_queries,
                progress_total=total_queries,
                progress_message=skip_details["reason"],
                started_at=skipped_at,
                finished_at=skipped_at,
                error_message=skip_details["reason"],
            )
            continue

        collector = collectors[source_name]
        source_started_at = datetime.now(timezone.utc)
        _update_run_source_state(
            repository=repository,
            run_id=run.id,
            source_name=source_name,
            status=ExecutionStatus.RUNNING,
            completed_count=0,
            failed_count=0,
            progress_current=0,
            progress_total=total_queries,
            progress_message=f"Collecting from {collector.display_name}",
            started_at=source_started_at,
            finished_at=None,
            error_message=None,
        )

        for query_index, query in enumerate(queries, start=1):
            processed_source_queries += 1
            _update_run_state(
                repository=repository,
                run=run,
                stage="collecting",
                progress_current=processed_source_queries,
                progress_total=total_source_queries,
                progress_message=(
                    f"Query {query_index}/{total_queries}: collecting from {collector.display_name}"
                ),
                artifacts=artifacts,
                query_count=len(queries),
            )
            request = collector.build_search_request(query_text=query.text, per_page=run.top_k)
            artifacts.write_scholarly_request(
                query_index=query_index,
                source_name=source_name,
                request=asdict(request),
            )
            try:
                raw_results, raw_payload = collector.search(
                    query.text,
                    run.top_k,
                    request=request,
                    include_raw=True,
                )
                artifacts.write_scholarly_response(
                    query_index=query_index,
                    source_name=source_name,
                    response=raw_payload,
                )
                artifacts.write_scholarly_source_raw_results(
                    query_index=query_index,
                    source_name=source_name,
                    results=raw_results,
                )
                raw_results_by_query[query_index].append(
                    {
                        "source_name": source_name,
                        "results": raw_results,
                    }
                )
            except (
                OpenAlexClientError,
                SemanticScholarClientError,
                COREClientError,
                ScopusClientError,
            ) as exc:
                if isinstance(exc, SemanticScholarClientError) and exc.raw_response is not None:
                    artifacts.write_scholarly_response(
                        query_index=query_index,
                        source_name=source_name,
                        response=exc.raw_response,
                    )
                failed_source_queries += 1
                source_failed_counts[source_name] += 1
                error_extra: dict[str, object] = {
                    "query_index": query_index,
                    "query_text": query.text,
                    "source": source_name,
                }
                if isinstance(exc, SemanticScholarClientError):
                    error_extra.update(
                        {
                            "failure_kind": exc.failure_kind,
                            "status_code": exc.status_code,
                            "endpoint": exc.endpoint,
                            "response_body": exc.response_body,
                            "auth_fallback_used": exc.auth_fallback_attempted,
                        }
                    )
                artifacts.append_error(
                    stage="scholarly",
                    message=str(exc),
                    **error_extra,
                )
                _update_run_source_state(
                    repository=repository,
                    run_id=run.id,
                    source_name=source_name,
                    status=_final_source_status(
                        completed_count=source_completed_counts[source_name],
                        failed_count=source_failed_counts[source_name],
                        total_queries=total_queries,
                    ),
                    completed_count=source_completed_counts[source_name],
                    failed_count=source_failed_counts[source_name],
                    progress_current=source_completed_counts[source_name] + source_failed_counts[source_name],
                    progress_total=total_queries,
                    progress_message=f"Query {query_index}/{total_queries} failed",
                    started_at=source_started_at
                    if (source_completed_counts[source_name] + source_failed_counts[source_name]) == 1
                    else _UNSET,
                    finished_at=_UNSET,
                    error_message=str(exc),
                )
                continue

            query_source_results: list[ResultRecord] = []
            for rank, payload in enumerate(raw_results, start=1):
                try:
                    mapped_result = collector.map_result(
                        run_id=run.id,
                        query_id=query.id,
                        rank=rank,
                        payload=payload,
                    )
                    query_source_results.append(mapped_result)
                    normalized_results_by_query[query_index].append(mapped_result)
                    results.append(mapped_result)
                except (OpenAlexMappingError, ScholarlySourceMappingError) as exc:
                    failed_identifier = (
                        payload.get("id")
                        or payload.get("paperId")
                        or payload.get("coreId")
                        or payload.get("dc:identifier")
                        or payload.get("eid")
                    )
                    artifacts.append_error(
                        stage="scholarly",
                        message=str(exc),
                        query_index=query_index,
                        query_text=query.text,
                        source=source_name,
                        source_identifier=failed_identifier,
                    )
                    continue
            source_completed_counts[source_name] += 1
            completed_source_queries += 1
            artifacts.write_scholarly_normalized_results(
                query_index=query_index,
                source_name=source_name,
                results=query_source_results,
            )
            artifacts.append_event(
                stage="scholarly",
                message="Scholarly query collected",
                query_index=query_index,
                query_text=query.text,
                source=source_name,
                raw_result_count=len(raw_results),
                normalized_result_count=len(query_source_results),
            )
            _update_run_source_state(
                repository=repository,
                run_id=run.id,
                source_name=source_name,
                status=_final_source_status(
                    completed_count=source_completed_counts[source_name],
                    failed_count=source_failed_counts[source_name],
                    total_queries=total_queries,
                ),
                completed_count=source_completed_counts[source_name],
                failed_count=source_failed_counts[source_name],
                progress_current=source_completed_counts[source_name] + source_failed_counts[source_name],
                progress_total=total_queries,
                progress_message=(
                    f"Query {query_index}/{total_queries} collected"
                    if (source_completed_counts[source_name] + source_failed_counts[source_name]) < total_queries
                    else (
                        "Completed with failures"
                        if source_failed_counts[source_name]
                        else "Completed"
                    )
                ),
                started_at=source_started_at
                if (source_completed_counts[source_name] + source_failed_counts[source_name]) == 1
                else _UNSET,
                finished_at=datetime.now(timezone.utc)
                if (source_completed_counts[source_name] + source_failed_counts[source_name]) >= total_queries
                else _UNSET,
                error_message=(
                    f"{source_failed_counts[source_name]} query failures"
                    if source_failed_counts[source_name]
                    else None
                ),
            )

    for query_index in range(1, total_queries + 1):
        artifacts.write_scholarly_query_raw_results(
            query_index=query_index,
            payload=raw_results_by_query[query_index],
        )
        artifacts.write_scholarly_query_normalized_results(
            query_index=query_index,
            results=normalized_results_by_query[query_index],
        )

    repository.save_results(results)
    if results:
        _update_run_state(
            repository=repository,
            run=run,
            stage="enrichment",
            progress_current=0,
            progress_total=len(results),
            progress_message=f"Enriching 0/{len(results)}",
            artifacts=artifacts,
            query_count=len(queries),
        )
    enrich_results(
        repository=repository,
        results=results,
        progress_callback=lambda current, total, message: _update_run_state(
            repository=repository,
            run=run,
            stage="enrichment",
            progress_current=current,
            progress_total=total,
            progress_message=message,
            artifacts=artifacts,
            query_count=len(queries),
        ),
        artifacts=artifacts,
    )

    _update_run_state(
        repository=repository,
        run=run,
        stage="analysis",
        progress_current=0,
        progress_total=1,
        progress_message="Computing metrics",
        artifacts=artifacts,
        query_count=len(queries),
    )
    from backend.application.analysis.service import build_run_analysis

    analysis = build_run_analysis(repository=repository, run_id=run.id)
    artifacts.write_analysis_payloads(analysis)
    artifacts.append_event(
        stage="analysis",
        message="Analysis computed",
        total_results=len(results),
    )
    artifacts.write_analysis_metadata(
        source="fresh_execution",
        generated_at=datetime.now(timezone.utc),
        external_llm_calls=0,
    )

    issue_summary = _summarize_scholarly_issues(
        failed_source_queries=failed_source_queries,
        skipped_source_queries=skipped_source_queries,
    )
    if results and issue_summary is not None:
        final_status = RunStatus.PARTIAL
        error_message = issue_summary
    elif results:
        final_status = RunStatus.COMPLETED
        error_message = None
    else:
        final_status = RunStatus.FAILED
        error_message = (
            f"No scholarly results were collected. {issue_summary}"
            if issue_summary is not None
            else "No scholarly results were collected"
        )

    finished_at = datetime.now(timezone.utc)
    _update_run_state(
        repository=repository,
        run=run,
        status=final_status,
        stage="done" if final_status != RunStatus.FAILED else "error",
        progress_current=processed_source_queries or max(len(results), 1),
        progress_total=total_source_queries,
        progress_message="Run completed" if final_status != RunStatus.FAILED else error_message,
        error_message=error_message,
        completed_at=finished_at,
        finished_at=finished_at,
        artifacts=artifacts,
        query_count=len(queries),
    )
    if final_status == RunStatus.FAILED and error_message is not None:
        artifacts.write_run_error(
            {
                "run_id": str(run.id),
                "run_type": run.run_type.value,
                "status": final_status.value,
                "error_message": error_message,
                "finished_at": finished_at,
            }
        )
        artifacts.append_error(stage="run", message=error_message)
    return repository.get_run(run.id)


def _execute_llm_audit_run(
    *,
    repository: Repository,
    run: Run,
    queries: Sequence[Query],
    artifacts: RunArtifactsWriter,
    openrouter_model_catalog: OpenRouterModelCatalogSnapshot | None,
) -> Run:
    settings = get_settings().openrouter
    results: list[ResultRecord] = []
    failed_calls = 0
    skipped_calls = 0
    completed_calls = 0
    total_queries = len(queries)
    total_model_calls = max(total_queries * max(len(run.selected_models), 1), 1)
    processed_model_calls = 0
    model_completed_counts = {model_name: 0 for model_name in run.selected_models}
    model_failed_counts = {model_name: 0 for model_name in run.selected_models}
    model_skip_reasons: dict[str, str] = {}
    model_skip_metadata: dict[str, dict[str, Any]] = {}
    try:
        catalog = openrouter_model_catalog or load_openrouter_model_catalog_snapshot(repository=repository)
    except OpenRouterModelDiscoveryError as exc:
        message = (
            "Unable to validate the current OpenRouter model catalog before execution. "
            "Refresh the model list and try again."
        )
        LOGGER.warning(
            "LLM audit catalog validation failed run_id=%s selection_source=persisted_run selected_models=%s status_code=%s",
            run.id,
            list(run.selected_models),
            exc.status_code,
        )
        artifacts.append_event(
            stage="llm",
            message="Model validation failed before execution",
            selection_source="persisted_run",
            selected_models=list(run.selected_models),
            error_message=message,
            status_code=exc.status_code,
        )
        artifacts.append_error(stage="llm", message=message, error_type=type(exc).__name__)
        finished_at = datetime.now(timezone.utc)
        _update_run_state(
            repository=repository,
            run=run,
            status=RunStatus.FAILED,
            stage="error",
            progress_message=message,
            error_message=message,
            completed_at=finished_at,
            finished_at=finished_at,
            artifacts=artifacts,
            query_count=len(queries),
        )
        artifacts.write_run_error(
            {
                "run_id": str(run.id),
                "run_type": run.run_type.value,
                "status": RunStatus.FAILED.value,
                "error_type": type(exc).__name__,
                "error_message": message,
                "finished_at": finished_at,
            }
        )
        return repository.get_run(run.id)

    unavailable_models = [model_name for model_name in run.selected_models if model_name not in catalog.ids]
    LOGGER.info(
        "LLM audit execution catalog snapshot run_id=%s selection_source=persisted_run selected_models=%s catalog_size=%s cached=%s unavailable=%s",
        run.id,
        list(run.selected_models),
        catalog.total,
        catalog.cached,
        unavailable_models,
    )
    artifacts.append_event(
        stage="llm",
        message="Validated OpenRouter model catalog for execution",
        selection_source="persisted_run",
        selected_models=list(run.selected_models),
        catalog_size=catalog.total,
        cached=catalog.cached,
        unavailable_models=unavailable_models,
    )
    for model_name in run.selected_models:
        skip_details = _preflight_model_skip_details(model_name=model_name, catalog=catalog)
        if skip_details is None:
            continue
        model_skip_reasons[model_name] = str(skip_details["reason"])
        model_skip_metadata[model_name] = skip_details
        artifacts.append_event(
            stage="llm",
            message="Model disabled before execution",
            model=model_name,
            reason=skip_details["reason"],
            failure_kind=skip_details["failure_kind"],
            validation_state=skip_details["validation_state"],
            replacement_model_id=skip_details["replacement_model_id"],
        )

    request_builder = OpenRouterClient(
        api_key=settings.api_key or "missing-openrouter-api-key",
        base_url=settings.base_url.rstrip("/"),
        app_name=settings.app_name,
        site_url=settings.site_url,
    )
    client: OpenRouterClient | None = None
    if any(model_name not in model_skip_reasons for model_name in run.selected_models):
        try:
            client = OpenRouterClient.from_settings()
        except OpenRouterError as exc:
            finished_at = datetime.now(timezone.utc)
            _update_run_state(
                repository=repository,
                run=run,
                status=RunStatus.FAILED,
                stage="error",
                progress_message=str(exc),
                error_message=str(exc),
                completed_at=finished_at,
                finished_at=finished_at,
                artifacts=artifacts,
                query_count=len(queries),
            )
            artifacts.write_run_error(
                {
                    "run_id": str(run.id),
                    "run_type": run.run_type.value,
                    "status": RunStatus.FAILED.value,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "finished_at": finished_at,
                }
            )
            artifacts.append_error(stage="llm", message=str(exc), error_type=type(exc).__name__)
            return repository.get_run(run.id)

    for query_index, query in enumerate(queries, start=1):
        _update_run_state(
            repository=repository,
            run=run,
            stage="processing_queries",
            progress_current=query_index,
            progress_total=max(total_queries, 1),
            progress_message=f"Query {query_index}/{max(total_queries, 1)}",
            artifacts=artifacts,
            query_count=len(queries),
        )
        prompt = build_article_retrieval_prompt(query_text=query.text, top_k=run.top_k)
        for model_name in run.selected_models:
            processed_model_calls += 1
            request = request_builder.build_completion_request(
                model=model_name,
                prompt=prompt,
                max_tokens=settings.max_tokens,
                temperature=settings.temperature,
                top_p=settings.top_p,
                require_json=True,
            )
            artifacts.write_llm_request(
                query_index=query_index,
                model_name=model_name,
                request=asdict(request),
            )
            blocked_reason = model_skip_reasons.get(model_name)
            if blocked_reason is not None:
                blocked_metadata = model_skip_metadata.get(model_name, {})
                skipped_calls += 1
                model_failed_counts[model_name] += 1
                skipped_at = datetime.now(timezone.utc)
                llm_call = LLMCall(
                    run_id=run.id,
                    query_id=query.id,
                    model_name=model_name,
                    provider_name="openrouter",
                    status=ExecutionStatus.SKIPPED,
                    prompt_text=prompt,
                    request_payload=request.payload,
                    parse_success=False,
                    parse_error=blocked_reason,
                    error_message=blocked_reason,
                    started_at=skipped_at,
                    finished_at=skipped_at,
                )
                repository.save_llm_call(llm_call)
                _update_run_state(
                    repository=repository,
                    run=run,
                    stage="calling_models",
                    progress_current=processed_model_calls,
                    progress_total=total_model_calls,
                    progress_message=f"Model {model_name}: skipped",
                    artifacts=artifacts,
                    query_count=len(queries),
                )
                artifacts.write_llm_parse_error(
                    query_index=query_index,
                    model_name=model_name,
                    error_message=blocked_reason,
                )
                artifacts.write_llm_metadata(
                    query_index=query_index,
                    model_name=model_name,
                    metadata={
                        "status": ExecutionStatus.SKIPPED.value,
                        "started_at": skipped_at,
                        "finished_at": skipped_at,
                        "error_message": blocked_reason,
                        "failure_kind": blocked_metadata.get("failure_kind", "skipped"),
                        "validation_state": blocked_metadata.get("validation_state"),
                        "replacement_model_id": blocked_metadata.get("replacement_model_id"),
                    },
                )
                artifacts.append_event(
                    stage="llm",
                    message="Request skipped",
                    query_index=query_index,
                    query_text=query.text,
                    model=model_name,
                    reason=blocked_reason,
                    status=ExecutionStatus.SKIPPED.value,
                )
                _update_run_model_state(
                    repository=repository,
                    run_id=run.id,
                    model_name=model_name,
                    status=_final_model_status(
                        completed_count=model_completed_counts[model_name],
                        failed_count=model_failed_counts[model_name],
                        total_queries=total_queries,
                    ),
                    progress_total=max(total_queries, 1),
                    progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                    progress_message=(
                        f"Query {query_index}/{max(total_queries, 1)} skipped"
                        if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                        else "Completed with failures"
                    ),
                    started_at=skipped_at
                    if (model_completed_counts[model_name] + model_failed_counts[model_name]) == 1
                    else _UNSET,
                    finished_at=skipped_at
                    if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                    else _UNSET,
                    error_message=blocked_reason,
                )
                continue

            assert client is not None
            _update_run_model_state(
                repository=repository,
                run_id=run.id,
                model_name=model_name,
                status=ExecutionStatus.RUNNING,
                progress_total=max(total_queries, 1),
                progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                progress_message=f"Query {query_index}/{max(total_queries, 1)}: requesting",
                started_at=datetime.now(timezone.utc)
                if (model_completed_counts[model_name] + model_failed_counts[model_name]) == 0
                else _UNSET,
            )
            _update_run_state(
                repository=repository,
                run=run,
                stage="calling_models",
                progress_current=processed_model_calls,
                progress_total=total_model_calls,
                progress_message=f"Model {model_name}: requesting",
                artifacts=artifacts,
                query_count=len(queries),
            )
            artifacts.append_event(
                stage="llm",
                message="Request sent",
                query_index=query_index,
                query_text=query.text,
                model=model_name,
            )
            llm_call = LLMCall(
                run_id=run.id,
                query_id=query.id,
                model_name=model_name,
                provider_name="openrouter",
                status=ExecutionStatus.RUNNING,
                prompt_text=prompt,
                request_payload=request.payload,
                started_at=datetime.now(timezone.utc),
            )
            repository.save_llm_call(llm_call)

            try:
                completion = client.complete(
                    model=model_name,
                    prompt=prompt,
                    max_tokens=settings.max_tokens,
                    temperature=settings.temperature,
                    top_p=settings.top_p,
                    require_json=True,
                    request=request,
                )
                llm_call.request_payload = completion.request_payload
                llm_call.response_payload = completion.raw_response
                llm_call.response_text = completion.output_text
                llm_call.latency_ms = completion.latency_ms
                llm_call.prompt_tokens = completion.prompt_tokens
                llm_call.completion_tokens = completion.completion_tokens
                llm_call.total_tokens = completion.total_tokens
                artifacts.write_llm_response(
                    query_index=query_index,
                    model_name=model_name,
                    response=completion.raw_response,
                )
                _update_run_state(
                    repository=repository,
                    run=run,
                    stage="calling_models",
                    progress_current=processed_model_calls,
                    progress_total=total_model_calls,
                    progress_message=f"Model {model_name}: parsing",
                    artifacts=artifacts,
                    query_count=len(queries),
                )
                _update_run_model_state(
                    repository=repository,
                    run_id=run.id,
                    model_name=model_name,
                    status=ExecutionStatus.RUNNING,
                    progress_total=max(total_queries, 1),
                    progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                    progress_message=f"Query {query_index}/{max(total_queries, 1)}: parsing",
                )

                parse_result = parse_article_recommendations_with_diagnostics(completion.output_text)
                parsed_items = parse_result.items
            except OpenRouterError as exc:
                failed_calls += 1
                model_failed_counts[model_name] += 1
                llm_call.status = ExecutionStatus.FAILED
                llm_call.parse_success = False
                llm_call.parse_error = str(exc)
                llm_call.error_message = str(exc)
                llm_call.latency_ms = exc.latency_ms
                llm_call.finished_at = datetime.now(timezone.utc)
                repository.save_llm_call(llm_call)
                if exc.response_payload is not None:
                    artifacts.write_llm_response(
                        query_index=query_index,
                        model_name=model_name,
                        response=exc.response_payload,
                    )
                artifacts.write_llm_parse_error(
                    query_index=query_index,
                    model_name=model_name,
                    error_message=str(exc),
                )
                artifacts.write_llm_metadata(
                    query_index=query_index,
                    model_name=model_name,
                    metadata={
                        "status": ExecutionStatus.FAILED.value,
                        "started_at": llm_call.started_at,
                        "finished_at": llm_call.finished_at,
                        "latency_ms": exc.latency_ms,
                        "error_message": str(exc),
                        "failure_kind": exc.failure_kind,
                        "status_code": exc.status_code,
                        "provider_error_code": exc.provider_error_code,
                    },
                )
                artifacts.append_error(
                    stage="llm",
                    message=str(exc),
                    query_index=query_index,
                    query_text=query.text,
                    model=model_name,
                )
                if exc.should_skip_remaining_queries:
                    skip_reason = (
                        f"Skipped remaining queries after {str(exc)}"
                    )
                    model_skip_reasons[model_name] = skip_reason
                    model_skip_metadata[model_name] = {
                        "reason": skip_reason,
                        "failure_kind": "skipped_after_client_error",
                        "validation_state": None,
                        "replacement_model_id": None,
                    }
                    artifacts.append_event(
                        stage="llm",
                        message="Future requests will be skipped for this model",
                        query_index=query_index,
                        query_text=query.text,
                        model=model_name,
                        reason=skip_reason,
                    )
                _update_run_model_state(
                    repository=repository,
                    run_id=run.id,
                    model_name=model_name,
                    status=_final_model_status(
                        completed_count=model_completed_counts[model_name],
                        failed_count=model_failed_counts[model_name],
                        total_queries=total_queries,
                    ),
                    progress_total=max(total_queries, 1),
                    progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                    progress_message=(
                        f"Query {query_index}/{max(total_queries, 1)} failed"
                        if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                        else "Completed with failures"
                    ),
                    finished_at=datetime.now(timezone.utc)
                    if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                    else _UNSET,
                    error_message=str(exc),
                )
                continue
            except LLMParseError as exc:
                failed_calls += 1
                model_failed_counts[model_name] += 1
                llm_call.status = ExecutionStatus.FAILED
                llm_call.parse_success = False
                llm_call.parse_error = str(exc)
                llm_call.error_message = str(exc)
                llm_call.finished_at = datetime.now(timezone.utc)
                repository.save_llm_call(llm_call)
                artifacts.write_llm_parse_error(
                    query_index=query_index,
                    model_name=model_name,
                    error_message=str(exc),
                    response_text=llm_call.response_text,
                )
                artifacts.write_llm_metadata(
                    query_index=query_index,
                    model_name=model_name,
                    metadata={
                        "status": ExecutionStatus.FAILED.value,
                        "started_at": llm_call.started_at,
                        "finished_at": llm_call.finished_at,
                        "latency_ms": llm_call.latency_ms,
                        "prompt_tokens": llm_call.prompt_tokens,
                        "completion_tokens": llm_call.completion_tokens,
                        "total_tokens": llm_call.total_tokens,
                        "error_message": str(exc),
                        "finish_reason": completion.finish_reason,
                        "response_truncated": completion.finish_reason == "length",
                    },
                )
                artifacts.append_error(
                    stage="llm",
                    message=str(exc),
                    query_index=query_index,
                    query_text=query.text,
                    model=model_name,
                )
                _update_run_model_state(
                    repository=repository,
                    run_id=run.id,
                    model_name=model_name,
                    status=_final_model_status(
                        completed_count=model_completed_counts[model_name],
                        failed_count=model_failed_counts[model_name],
                        total_queries=total_queries,
                    ),
                    progress_total=max(total_queries, 1),
                    progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                    progress_message=(
                        f"Query {query_index}/{max(total_queries, 1)} failed"
                        if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                        else "Completed with failures"
                    ),
                    finished_at=datetime.now(timezone.utc)
                    if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                    else _UNSET,
                    error_message=str(exc),
                )
                continue

            artifacts.write_llm_parsed_output(
                query_index=query_index,
                model_name=model_name,
                parsed_items=parsed_items,
            )
            artifacts.write_llm_metadata(
                query_index=query_index,
                model_name=model_name,
                metadata={
                    "status": ExecutionStatus.COMPLETED.value,
                    "started_at": llm_call.started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "latency_ms": completion.latency_ms,
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                    "total_tokens": completion.total_tokens,
                    "finish_reason": completion.finish_reason,
                    "parse_mode": parse_result.parse_mode,
                    "parsed_item_count": len(parsed_items),
                    "partial_json_recovery": parse_result.recovered_partial_json,
                },
            )
            llm_call.status = ExecutionStatus.COMPLETED
            llm_call.parse_success = True
            llm_call.parse_error = None
            llm_call.finished_at = datetime.now(timezone.utc)
            repository.save_llm_call(llm_call)
            completed_calls += 1
            model_completed_counts[model_name] += 1
            _update_run_model_state(
                repository=repository,
                run_id=run.id,
                model_name=model_name,
                status=_final_model_status(
                    completed_count=model_completed_counts[model_name],
                    failed_count=model_failed_counts[model_name],
                    total_queries=total_queries,
                ),
                progress_total=max(total_queries, 1),
                progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                progress_message=(
                    f"Query {query_index}/{max(total_queries, 1)} completed"
                    if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                    else (
                        "Completed with failures"
                        if model_failed_counts[model_name]
                        else "Completed"
                    )
                ),
                finished_at=datetime.now(timezone.utc)
                if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                else _UNSET,
            )
            artifacts.append_event(
                stage="llm",
                message="Response parsed",
                query_index=query_index,
                query_text=query.text,
                model=model_name,
                article_count=len(parsed_items),
            )
            results.extend(
                _build_llm_result_records(
                    run=run,
                    query=query,
                    model_name=model_name,
                    llm_call=llm_call,
                    parsed_items=parsed_items,
                )
            )

    return _finalize_llm_audit_run(
        repository=repository,
        run=run,
        queries=queries,
        artifacts=artifacts,
        results=results,
        completed_calls=completed_calls,
        failed_calls=failed_calls,
        skipped_calls=skipped_calls,
        analysis_source="fresh_execution",
    )


def replay_llm_run_from_artifacts(
    *,
    repository: Repository,
    run: Run,
    queries: Sequence[Query],
) -> Run:
    """Rebuild llm_audit downstream state from stored run artifacts without new API calls."""

    if run.run_type != RunType.LLM_AUDIT:
        raise UnsupportedArtifactReplayError(
            "Artifact replay is only supported for llm_audit runs",
        )

    with track_active_run(run.id):
        run.selected_models = normalize_selected_models_for_execution(run.selected_models)
        artifacts = get_run_artifacts_writer(run.id)
        repository.reset_run_execution(run.id)
        started_at = datetime.now(timezone.utc)
        _update_run_state(
            repository=repository,
            run=run,
            status=RunStatus.RUNNING,
            stage="replaying_artifacts",
            progress_current=0,
            progress_total=max(len(queries), 1),
            progress_message="Preparing artifact replay",
            started_at=started_at,
            completed_at=None,
            finished_at=None,
            error_message=None,
            artifacts=artifacts,
            query_count=len(queries),
        )
        artifacts.append_event(
            stage="replay",
            message="Artifact replay started",
            source="llm_artifacts",
            query_count=len(queries),
            selected_model_count=len(run.selected_models),
            external_llm_calls=0,
        )

        try:
            return _replay_llm_audit_run_from_artifacts(
                repository=repository,
                run=run,
                queries=queries,
                artifacts=artifacts,
            )
        except Exception as exc:  # pragma: no cover - defensive containment for live runs
            finished_at = datetime.now(timezone.utc)
            artifacts.write_run_error(
                {
                    "run_id": str(run.id),
                    "run_type": run.run_type.value,
                    "status": RunStatus.FAILED.value,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "finished_at": finished_at,
                    "source": "artifact_replay",
                }
            )
            artifacts.append_error(
                stage="replay",
                message=str(exc),
                error_type=type(exc).__name__,
            )
            artifacts.write_replay_summary(
                {
                    "run_id": str(run.id),
                    "status": RunStatus.FAILED.value,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "source": "artifact_replay",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "external_llm_calls": 0,
                }
            )
            _update_run_state(
                repository=repository,
                run=run,
                status=RunStatus.FAILED,
                stage="error",
                progress_message=str(exc),
                error_message=str(exc),
                completed_at=finished_at,
                finished_at=finished_at,
                artifacts=artifacts,
                query_count=len(queries),
            )
            return repository.get_run(run.id)


def _replay_llm_audit_run_from_artifacts(
    *,
    repository: Repository,
    run: Run,
    queries: Sequence[Query],
    artifacts: RunArtifactsWriter,
) -> Run:
    results: list[ResultRecord] = []
    failed_calls = 0
    skipped_calls = 0
    completed_calls = 0
    total_queries = len(queries)
    total_model_calls = max(total_queries * max(len(run.selected_models), 1), 1)
    processed_model_calls = 0
    model_completed_counts = {model_name: 0 for model_name in run.selected_models}
    model_failed_counts = {model_name: 0 for model_name in run.selected_models}
    replay_source_counts = {
        "response_raw": 0,
        "parsed_output": 0,
        "metadata_only": 0,
        "missing": 0,
    }

    for query_index, query in enumerate(queries, start=1):
        _update_run_state(
            repository=repository,
            run=run,
            stage="replaying_artifacts",
            progress_current=query_index,
            progress_total=max(total_queries, 1),
            progress_message=f"Replay query {query_index}/{max(total_queries, 1)}",
            artifacts=artifacts,
            query_count=len(queries),
        )
        for model_name in run.selected_models:
            processed_model_calls += 1
            _update_run_state(
                repository=repository,
                run=run,
                stage="replaying_artifacts",
                progress_current=processed_model_calls,
                progress_total=total_model_calls,
                progress_message=f"Replay model {model_name}",
                artifacts=artifacts,
                query_count=len(queries),
            )

            model_dir = artifacts.run_dir / "llm" / f"query_{query_index:03d}" / (
                f"model_{artifacts.sanitize_path_component(model_name)}"
            )
            request_artifact = _load_json_artifact(model_dir / "request.json")
            metadata_artifact = _load_json_artifact(model_dir / "metadata.json")
            raw_response_artifact = _load_json_artifact(model_dir / "response_raw.json")
            parsed_output_artifact = _load_json_artifact(model_dir / "parsed_output.json")
            parse_error_artifact = _load_json_artifact(model_dir / "parse_error.json")
            prompt_text = (
                _extract_prompt_text_from_request_artifact(request_artifact)
                or build_article_retrieval_prompt(query_text=query.text, top_k=run.top_k)
            )
            request_payload = (
                request_artifact.get("payload")
                if isinstance(request_artifact, dict) and isinstance(request_artifact.get("payload"), dict)
                else {}
            )
            metadata_payload = metadata_artifact if isinstance(metadata_artifact, dict) else {}
            parse_error_payload = parse_error_artifact if isinstance(parse_error_artifact, dict) else {}

            replay_source = "missing"
            response_payload: dict[str, Any] = {}
            response_text: str | None = None
            error_message: str | None = None
            replay_status = ExecutionStatus.FAILED

            if isinstance(raw_response_artifact, dict):
                response_payload = raw_response_artifact
                extracted_text = extract_output_text_from_response_payload(raw_response_artifact).strip()
                if extracted_text:
                    replay_source = "response_raw"
                    response_text = extracted_text
                    try:
                        parsed_items = parse_article_recommendations(extracted_text)
                    except LLMParseError as exc:
                        error_message = str(exc)
                    else:
                        replay_source_counts[replay_source] += 1
                        replayed_at = datetime.now(timezone.utc)
                        llm_call = LLMCall(
                            run_id=run.id,
                            query_id=query.id,
                            model_name=model_name,
                            provider_name="openrouter",
                            status=ExecutionStatus.COMPLETED,
                            prompt_text=prompt_text,
                            request_payload=request_payload,
                            response_payload=response_payload,
                            response_text=response_text,
                            parse_success=True,
                            latency_ms=metadata_payload.get("latency_ms"),
                            prompt_tokens=metadata_payload.get("prompt_tokens"),
                            completion_tokens=metadata_payload.get("completion_tokens"),
                            total_tokens=metadata_payload.get("total_tokens"),
                            started_at=metadata_payload.get("started_at") or replayed_at,
                            finished_at=replayed_at,
                        )
                        repository.save_llm_call(llm_call)
                        completed_calls += 1
                        model_completed_counts[model_name] += 1
                        results.extend(
                            _build_llm_result_records(
                                run=run,
                                query=query,
                                model_name=model_name,
                                llm_call=llm_call,
                                parsed_items=parsed_items,
                            )
                        )
                        artifacts.write_replay_parsed_output(
                            query_index=query_index,
                            model_name=model_name,
                            parsed_items=parsed_items,
                        )
                        artifacts.write_replay_metadata(
                            query_index=query_index,
                            model_name=model_name,
                            metadata=_compact_mapping(
                                {
                                    "status": ExecutionStatus.COMPLETED.value,
                                    "source": "artifact_replay",
                                    "artifact_source": replay_source,
                                    "started_at": llm_call.started_at,
                                    "finished_at": llm_call.finished_at,
                                    "latency_ms": llm_call.latency_ms,
                                    "prompt_tokens": llm_call.prompt_tokens,
                                    "completion_tokens": llm_call.completion_tokens,
                                    "total_tokens": llm_call.total_tokens,
                                    "external_llm_call": False,
                                }
                            ),
                        )
                        artifacts.append_event(
                            stage="replay",
                            message="Stored LLM response replayed",
                            query_index=query_index,
                            query_text=query.text,
                            model=model_name,
                            artifact_source=replay_source,
                            article_count=len(parsed_items),
                            external_llm_call=False,
                        )
                        _update_run_model_state(
                            repository=repository,
                            run_id=run.id,
                            model_name=model_name,
                            status=_final_model_status(
                                completed_count=model_completed_counts[model_name],
                                failed_count=model_failed_counts[model_name],
                                total_queries=total_queries,
                            ),
                            progress_total=max(total_queries, 1),
                            progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                            progress_message=(
                                f"Replay query {query_index}/{max(total_queries, 1)} completed"
                                if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                                else (
                                    "Completed with failures"
                                    if model_failed_counts[model_name]
                                    else "Completed"
                                )
                            ),
                            started_at=llm_call.started_at
                            if (model_completed_counts[model_name] + model_failed_counts[model_name]) == 1
                            else _UNSET,
                            finished_at=llm_call.finished_at
                            if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                            else _UNSET,
                        )
                        continue

                else:
                    replay_source = "metadata_only"
                    error_message = (
                        str(metadata_payload.get("error_message") or "")
                        or str(parse_error_payload.get("error_message") or "")
                        or "Stored raw response did not contain replayable assistant content"
                    )
                    replay_status = (
                        ExecutionStatus.SKIPPED
                        if metadata_payload.get("status") == ExecutionStatus.SKIPPED.value
                        else ExecutionStatus.FAILED
                    )
            elif isinstance(parsed_output_artifact, list):
                replay_source = "parsed_output"
                try:
                    parsed_items = _validate_replayed_parsed_output(parsed_output_artifact)
                except LLMParseError as exc:
                    error_message = str(exc)
                else:
                    replay_source_counts[replay_source] += 1
                    replayed_at = datetime.now(timezone.utc)
                    llm_call = LLMCall(
                        run_id=run.id,
                        query_id=query.id,
                        model_name=model_name,
                        provider_name="openrouter",
                        status=ExecutionStatus.COMPLETED,
                        prompt_text=prompt_text,
                        request_payload=request_payload,
                        response_payload={},
                        response_text=None,
                        parse_success=True,
                        latency_ms=metadata_payload.get("latency_ms"),
                        prompt_tokens=metadata_payload.get("prompt_tokens"),
                        completion_tokens=metadata_payload.get("completion_tokens"),
                        total_tokens=metadata_payload.get("total_tokens"),
                        started_at=metadata_payload.get("started_at") or replayed_at,
                        finished_at=replayed_at,
                    )
                    repository.save_llm_call(llm_call)
                    completed_calls += 1
                    model_completed_counts[model_name] += 1
                    results.extend(
                        _build_llm_result_records(
                            run=run,
                            query=query,
                            model_name=model_name,
                            llm_call=llm_call,
                            parsed_items=parsed_items,
                        )
                    )
                    artifacts.write_replay_parsed_output(
                        query_index=query_index,
                        model_name=model_name,
                        parsed_items=parsed_items,
                    )
                    artifacts.write_replay_metadata(
                        query_index=query_index,
                        model_name=model_name,
                        metadata=_compact_mapping(
                            {
                                "status": ExecutionStatus.COMPLETED.value,
                                "source": "artifact_replay",
                                "artifact_source": replay_source,
                                "started_at": llm_call.started_at,
                                "finished_at": llm_call.finished_at,
                                "latency_ms": llm_call.latency_ms,
                                "prompt_tokens": llm_call.prompt_tokens,
                                "completion_tokens": llm_call.completion_tokens,
                                "total_tokens": llm_call.total_tokens,
                                "external_llm_call": False,
                            }
                        ),
                    )
                    artifacts.append_event(
                        stage="replay",
                        message="Stored parsed output replayed",
                        query_index=query_index,
                        query_text=query.text,
                        model=model_name,
                        artifact_source=replay_source,
                        article_count=len(parsed_items),
                        external_llm_call=False,
                    )
                    _update_run_model_state(
                        repository=repository,
                        run_id=run.id,
                        model_name=model_name,
                        status=_final_model_status(
                            completed_count=model_completed_counts[model_name],
                            failed_count=model_failed_counts[model_name],
                            total_queries=total_queries,
                        ),
                        progress_total=max(total_queries, 1),
                        progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                        progress_message=(
                            f"Replay query {query_index}/{max(total_queries, 1)} completed"
                            if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                            else (
                                "Completed with failures"
                                if model_failed_counts[model_name]
                                else "Completed"
                            )
                        ),
                        started_at=llm_call.started_at
                        if (model_completed_counts[model_name] + model_failed_counts[model_name]) == 1
                        else _UNSET,
                        finished_at=llm_call.finished_at
                        if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                        else _UNSET,
                    )
                    continue
            else:
                replay_source = "missing"
                error_message = (
                    str(parse_error_payload.get("error_message") or "")
                    or "Missing replayable artifacts: expected response_raw.json or parsed_output.json"
                )

            replay_source_counts[replay_source] += 1
            replayed_at = datetime.now(timezone.utc)
            llm_call = LLMCall(
                run_id=run.id,
                query_id=query.id,
                model_name=model_name,
                provider_name="openrouter",
                status=replay_status,
                prompt_text=prompt_text,
                request_payload=request_payload,
                response_payload=response_payload,
                response_text=response_text,
                parse_success=False,
                parse_error=error_message,
                error_message=error_message,
                latency_ms=metadata_payload.get("latency_ms"),
                prompt_tokens=metadata_payload.get("prompt_tokens"),
                completion_tokens=metadata_payload.get("completion_tokens"),
                total_tokens=metadata_payload.get("total_tokens"),
                started_at=metadata_payload.get("started_at") or replayed_at,
                finished_at=replayed_at,
            )
            repository.save_llm_call(llm_call)
            if replay_status == ExecutionStatus.SKIPPED:
                skipped_calls += 1
            else:
                failed_calls += 1
            model_failed_counts[model_name] += 1
            artifacts.write_replay_parse_error(
                query_index=query_index,
                model_name=model_name,
                error_message=error_message or "Artifact replay failed",
                source=replay_source,
                response_text=response_text or parse_error_payload.get("response_text"),
            )
            artifacts.write_replay_metadata(
                query_index=query_index,
                model_name=model_name,
                metadata=_compact_mapping(
                    {
                        "status": replay_status.value,
                        "source": "artifact_replay",
                        "artifact_source": replay_source,
                        "started_at": llm_call.started_at,
                        "finished_at": llm_call.finished_at,
                        "latency_ms": llm_call.latency_ms,
                        "prompt_tokens": llm_call.prompt_tokens,
                        "completion_tokens": llm_call.completion_tokens,
                        "total_tokens": llm_call.total_tokens,
                        "error_message": error_message,
                        "external_llm_call": False,
                    }
                ),
            )
            artifacts.append_error(
                stage="replay",
                message=error_message or "Artifact replay failed",
                query_index=query_index,
                query_text=query.text,
                model=model_name,
                artifact_source=replay_source,
                external_llm_call=False,
            )
            _update_run_model_state(
                repository=repository,
                run_id=run.id,
                model_name=model_name,
                status=_final_model_status(
                    completed_count=model_completed_counts[model_name],
                    failed_count=model_failed_counts[model_name],
                    total_queries=total_queries,
                ),
                progress_total=max(total_queries, 1),
                progress_current=model_completed_counts[model_name] + model_failed_counts[model_name],
                progress_message=(
                    f"Replay query {query_index}/{max(total_queries, 1)} failed"
                    if (model_completed_counts[model_name] + model_failed_counts[model_name]) < max(total_queries, 1)
                    else "Completed with failures"
                ),
                started_at=llm_call.started_at
                if (model_completed_counts[model_name] + model_failed_counts[model_name]) == 1
                else _UNSET,
                finished_at=llm_call.finished_at
                if (model_completed_counts[model_name] + model_failed_counts[model_name]) >= max(total_queries, 1)
                else _UNSET,
                error_message=error_message,
            )

    replayed_run = _finalize_llm_audit_run(
        repository=repository,
        run=run,
        queries=queries,
        artifacts=artifacts,
        results=results,
        completed_calls=completed_calls,
        failed_calls=failed_calls,
        skipped_calls=skipped_calls,
        analysis_source="artifact_replay",
    )
    artifacts.write_replay_summary(
        {
            "run_id": str(run.id),
            "status": replayed_run.status.value,
            "stage": replayed_run.stage,
            "source": "artifact_replay",
            "external_llm_calls": 0,
            "completed_calls": completed_calls,
            "failed_calls": failed_calls,
            "skipped_calls": skipped_calls,
            "total_results": len(results),
            "replay_source_counts": replay_source_counts,
            "started_at": run.started_at,
            "finished_at": replayed_run.finished_at,
        }
    )
    artifacts.append_event(
        stage="replay",
        message="Artifact replay completed",
        status=replayed_run.status.value,
        completed_calls=completed_calls,
        failed_calls=failed_calls,
        skipped_calls=skipped_calls,
        total_results=len(results),
        external_llm_calls=0,
    )
    return replayed_run


def _finalize_llm_audit_run(
    *,
    repository: Repository,
    run: Run,
    queries: Sequence[Query],
    artifacts: RunArtifactsWriter,
    results: list[ResultRecord],
    completed_calls: int,
    failed_calls: int,
    skipped_calls: int,
    analysis_source: str,
) -> Run:
    repository.save_results(results)
    if results:
        _update_run_state(
            repository=repository,
            run=run,
            stage="enrichment",
            progress_current=0,
            progress_total=len(results),
            progress_message=f"Enriching 0/{len(results)}",
            artifacts=artifacts,
            query_count=len(queries),
        )
    enrich_results(
        repository=repository,
        results=results,
        progress_callback=lambda current, total, message: _update_run_state(
            repository=repository,
            run=run,
            stage="enrichment",
            progress_current=current,
            progress_total=total,
            progress_message=message,
            artifacts=artifacts,
            query_count=len(queries),
        ),
        artifacts=artifacts,
    )

    _update_run_state(
        repository=repository,
        run=run,
        stage="analysis",
        progress_current=0,
        progress_total=1,
        progress_message="Computing metrics",
        artifacts=artifacts,
        query_count=len(queries),
    )
    from backend.application.analysis.service import build_run_analysis

    analysis = build_run_analysis(repository=repository, run_id=run.id)
    artifacts.write_analysis_payloads(analysis)
    artifacts.append_event(
        stage="analysis",
        message="Analysis computed",
        total_results=len(results),
    )
    artifacts.write_analysis_metadata(
        source=analysis_source,
        generated_at=datetime.now(timezone.utc),
        external_llm_calls=0 if analysis_source == "artifact_replay" else completed_calls + failed_calls + skipped_calls,
    )

    issue_summary = _summarize_llm_issues(
        failed_calls=failed_calls,
        skipped_calls=skipped_calls,
    )
    if completed_calls and issue_summary is not None:
        final_status = RunStatus.PARTIAL
        error_message = issue_summary
    elif completed_calls:
        final_status = RunStatus.COMPLETED
        error_message = None
    else:
        final_status = RunStatus.FAILED
        error_message = issue_summary or "All llm calls failed"

    finished_at = datetime.now(timezone.utc)
    failure_progress = failed_calls + skipped_calls
    _update_run_state(
        repository=repository,
        run=run,
        status=final_status,
        stage="done" if final_status != RunStatus.FAILED else "error",
        progress_current=len(results) if results else failure_progress,
        progress_total=max(len(results), failure_progress, 1),
        progress_message="Run completed" if final_status != RunStatus.FAILED else error_message,
        error_message=error_message,
        completed_at=finished_at,
        finished_at=finished_at,
        artifacts=artifacts,
        query_count=len(queries),
    )
    if final_status == RunStatus.FAILED and error_message is not None:
        artifacts.write_run_error(
            {
                "run_id": str(run.id),
                "run_type": run.run_type.value,
                "status": final_status.value,
                "error_message": error_message,
                "finished_at": finished_at,
            }
        )
        artifacts.append_error(stage="run", message=error_message)
    return repository.get_run(run.id)


def _build_llm_result_records(
    *,
    run: Run,
    query: Query,
    model_name: str,
    llm_call: LLMCall,
    parsed_items: Sequence[dict[str, Any]],
) -> list[ResultRecord]:
    results: list[ResultRecord] = []
    for item in parsed_items:
        canonical_identifier = normalize_doi(item.get("doi")) or _result_fallback_identifier(
            model_name=model_name,
            query_text=query.text,
            title=item["title"],
            rank=item["rank"],
        )
        results.append(
            ResultRecord(
                run_id=run.id,
                query_id=query.id,
                llm_call_id=llm_call.id,
                origin_type=ResultOriginType.LLM_RESPONSE,
                model_name=model_name,
                provider_name="openrouter",
                execution_status=ExecutionStatus.COMPLETED,
                rank=item["rank"],
                canonical_identifier=canonical_identifier,
                title=item["title"],
                doi=item.get("doi"),
                url=item.get("url"),
                source_identifier=None,
                year=item.get("publication_year") or item.get("year"),
                authors=list(item.get("authors", [])),
                venue=item.get("venue"),
                publisher=item.get("publisher"),
                language=item.get("language") or query.language,
                raw_payload={
                    "query_text": query.text,
                    "rationale": item.get("rationale"),
                    "bias_fields": {
                        "publication_year": item.get("publication_year") or item.get("year"),
                        "language": item.get("language"),
                        "is_open_access": item.get("is_open_access"),
                        "country_primary": item.get("country_primary"),
                        "publisher": item.get("publisher"),
                        "venue": item.get("venue"),
                    },
                    "raw_item": item.get("raw_item"),
                },
            )
        )
    return results


def _load_json_artifact(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_prompt_text_from_request_artifact(request_artifact: Any) -> str | None:
    if not isinstance(request_artifact, dict):
        return None
    payload = request_artifact.get("payload")
    if not isinstance(payload, dict):
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _validate_replayed_parsed_output(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise LLMParseError("Stored parsed_output.json did not contain a list")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        normalized.append(
            {
                "rank": _coerce_positive_int(item.get("rank"), fallback=index),
                "title": title.strip(),
                "doi": item.get("doi") if isinstance(item.get("doi"), str) else None,
                "year": _coerce_positive_int(item.get("year"), fallback=None),
                "venue": item.get("venue") if isinstance(item.get("venue"), str) else None,
                "authors": _normalize_replay_authors(item.get("authors")),
                "url": item.get("url") if isinstance(item.get("url"), str) else None,
                "rationale": item.get("rationale") if isinstance(item.get("rationale"), str) else None,
                "raw_item": item.get("raw_item") if item.get("raw_item") is not None else item,
            }
        )
    if not normalized:
        raise LLMParseError("Stored parsed_output.json did not contain any usable article items")
    return normalized


def _coerce_positive_int(value: Any, *, fallback: int | None) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else fallback
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return fallback
        return parsed if parsed > 0 else fallback
    return fallback


def _normalize_replay_authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            authors.append(item.strip())
    return authors


def _compact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _result_fallback_identifier(
    *,
    model_name: str,
    query_text: str,
    title: str,
    rank: int,
) -> str:
    return "::".join(
        [
            "llm",
            normalize_title(model_name),
            normalize_title(query_text),
            normalize_title(title),
            str(rank),
        ]
    )


def _update_run_state(
    *,
    repository: Repository,
    run: Run,
    status: RunStatus | object = _UNSET,
    stage: str | object = _UNSET,
    progress_current: int | object = _UNSET,
    progress_total: int | object = _UNSET,
    progress_message: str | None | object = _UNSET,
    started_at: datetime | None | object = _UNSET,
    completed_at: datetime | None | object = _UNSET,
    finished_at: datetime | None | object = _UNSET,
    error_message: str | None | object = _UNSET,
    artifacts: RunArtifactsWriter | None = None,
    query_count: int | None = None,
) -> None:
    previous_status = run.status.value
    previous_stage = run.stage
    previous_progress_current = run.progress_current
    previous_progress_total = run.progress_total
    previous_progress_message = run.progress_message
    if status is not _UNSET:
        run.status = status
    if stage is not _UNSET:
        run.stage = stage
    if progress_current is not _UNSET:
        run.progress_current = progress_current
    if progress_total is not _UNSET:
        run.progress_total = progress_total
    if progress_message is not _UNSET:
        run.progress_message = progress_message
    if started_at is not _UNSET:
        run.started_at = started_at
    if completed_at is not _UNSET:
        run.completed_at = completed_at
    if finished_at is not _UNSET:
        run.finished_at = finished_at
    if error_message is not _UNSET:
        run.error_message = error_message
    repository.update_run(run)
    if artifacts is not None and query_count is not None:
        artifacts.write_manifest(run=run, query_count=query_count)
        artifacts.write_run_snapshot(run=run)
        if (
            run.status.value != previous_status
            or run.stage != previous_stage
            or run.progress_current != previous_progress_current
            or run.progress_total != previous_progress_total
            or run.progress_message != previous_progress_message
        ):
            artifacts.append_event(
                stage=run.stage,
                message=run.progress_message or "Run state updated",
                status=run.status.value,
                progress_current=run.progress_current,
                progress_total=run.progress_total,
            )


def _update_run_model_state(
    *,
    repository: Repository,
    run_id: Any,
    model_name: str,
    status: ExecutionStatus | object = _UNSET,
    progress_current: int | object = _UNSET,
    progress_total: int | object = _UNSET,
    progress_message: str | None | object = _UNSET,
    started_at: datetime | None | object = _UNSET,
    finished_at: datetime | None | object = _UNSET,
    error_message: str | None | object = _UNSET,
) -> None:
    repository.update_run_model_status(
        run_id=run_id,
        model_name=model_name,
        status=None if status is _UNSET else status,
        progress_current=None if progress_current is _UNSET else progress_current,
        progress_total=None if progress_total is _UNSET else progress_total,
        progress_message=None if progress_message is _UNSET else progress_message,
        started_at=None if started_at is _UNSET else started_at,
        finished_at=None if finished_at is _UNSET else finished_at,
        error_message=None if error_message is _UNSET else error_message,
    )


def _update_run_source_state(
    *,
    repository: Repository,
    run_id: Any,
    source_name: str,
    status: ExecutionStatus | object = _UNSET,
    completed_count: int | object = _UNSET,
    failed_count: int | object = _UNSET,
    progress_current: int | object = _UNSET,
    progress_total: int | object = _UNSET,
    progress_message: str | None | object = _UNSET,
    started_at: datetime | None | object = _UNSET,
    finished_at: datetime | None | object = _UNSET,
    error_message: str | None | object = _UNSET,
) -> None:
    repository.update_run_source_status(
        run_id=run_id,
        source_name=source_name,
        status=None if status is _UNSET else status,
        completed_count=None if completed_count is _UNSET else completed_count,
        failed_count=None if failed_count is _UNSET else failed_count,
        progress_current=None if progress_current is _UNSET else progress_current,
        progress_total=None if progress_total is _UNSET else progress_total,
        progress_message=None if progress_message is _UNSET else progress_message,
        started_at=None if started_at is _UNSET else started_at,
        finished_at=None if finished_at is _UNSET else finished_at,
        error_message=None if error_message is _UNSET else error_message,
    )


def _final_model_status(
    *,
    completed_count: int,
    failed_count: int,
    total_queries: int,
) -> ExecutionStatus:
    processed = completed_count + failed_count
    if processed < max(total_queries, 1):
        return ExecutionStatus.RUNNING
    if completed_count and failed_count:
        return ExecutionStatus.PARTIAL
    if failed_count:
        return ExecutionStatus.FAILED
    return ExecutionStatus.COMPLETED


def _final_source_status(
    *,
    completed_count: int,
    failed_count: int,
    total_queries: int,
) -> ExecutionStatus:
    processed = completed_count + failed_count
    if processed < max(total_queries, 1):
        return ExecutionStatus.RUNNING
    if completed_count and failed_count:
        return ExecutionStatus.PARTIAL
    if failed_count:
        return ExecutionStatus.FAILED
    return ExecutionStatus.COMPLETED


def _summarize_scholarly_issues(
    *,
    failed_source_queries: int,
    skipped_source_queries: int,
) -> str | None:
    parts: list[str] = []
    if failed_source_queries:
        parts.append(f"{failed_source_queries} source queries failed")
    if skipped_source_queries:
        parts.append(f"{skipped_source_queries} source queries skipped")
    return "; ".join(parts) or None


def _summarize_llm_issues(*, failed_calls: int, skipped_calls: int) -> str | None:
    parts: list[str] = []
    if failed_calls:
        parts.append(f"{failed_calls} llm calls failed")
    if skipped_calls:
        parts.append(f"{skipped_calls} model executions skipped")
    return "; ".join(parts) or None
