"""SQLite repository layer for runs, results, enrichments, and llm calls."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from backend.domain import (
    CanonicalEnrichment,
    EnrichmentProvider,
    EnrichmentRecord,
    EntityExecutionSummary,
    ExecutionStatus,
    FieldProvenance,
    LLMCall,
    Query,
    ResultOriginType,
    ResultRecord,
    Run,
    RunDetail,
    RunType,
)
from backend.storage.database import Database, get_database


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_loads(value: str | None, *, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def _bool_to_db(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _bool_from_db(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _dt_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class Repository:
    """Persistence façade for the application layer."""

    def __init__(self, database: Database | None = None) -> None:
        self.database = database or get_database()

    def create_run(self, run: Run, queries: list[Query]) -> RunDetail:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, run_type, status, stage, progress_current, progress_total, progress_message,
                    top_k, created_at, started_at, completed_at, finished_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id),
                    run.run_type.value,
                    run.status.value,
                    run.stage,
                    run.progress_current,
                    run.progress_total,
                    run.progress_message,
                    run.top_k,
                    _dt_to_str(run.created_at),
                    _dt_to_str(run.started_at),
                    _dt_to_str(run.completed_at),
                    _dt_to_str(run.finished_at),
                    run.error_message,
                ),
            )
            for source in run.sources:
                connection.execute(
                    """
                    INSERT INTO run_sources (
                        run_id, source_name, status, completed_count, failed_count,
                        progress_current, progress_total, progress_message, started_at,
                        finished_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run.id),
                        source,
                        ExecutionStatus.PENDING.value,
                        0,
                        0,
                        0,
                        len(queries),
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            for model_name in run.selected_models:
                connection.execute(
                    """
                    INSERT INTO run_models (
                        run_id, model_name, status, progress_current, progress_total,
                        progress_message, started_at, finished_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run.id),
                        model_name,
                        ExecutionStatus.PENDING.value,
                        0,
                        len(queries),
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            for query in queries:
                connection.execute(
                    """
                    INSERT INTO queries (id, run_id, text, position, language)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(query.id),
                        str(query.run_id),
                        query.text,
                        query.position,
                        query.language,
                    ),
                )
        return self.get_run_detail(run.id)

    def list_runs(self) -> list[RunDetail]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM runs ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self.get_run_detail(UUID(row["id"])) for row in rows]

    def get_run_detail(self, run_id: UUID) -> RunDetail:
        run = self.get_run(run_id)
        queries = self.list_queries(run_id)
        return RunDetail(
            run=run,
            queries=queries,
            entity_statuses=self.list_entity_statuses(run_id),
        )

    def get_run(self, run_id: UUID) -> Run:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(run_id))

            sources = [
                item["source_name"]
                for item in connection.execute(
                    "SELECT source_name FROM run_sources WHERE run_id = ? ORDER BY source_name",
                    (str(run_id),),
                ).fetchall()
            ]
            models = [
                item["model_name"]
                for item in connection.execute(
                    "SELECT model_name FROM run_models WHERE run_id = ? ORDER BY model_name",
                    (str(run_id),),
                ).fetchall()
            ]

        return Run(
            id=UUID(row["id"]),
            run_type=RunType(row["run_type"]),
            status=row["status"],
            stage=row["stage"] if "stage" in row.keys() else "pending",
            progress_current=row["progress_current"] if "progress_current" in row.keys() else 0,
            progress_total=row["progress_total"] if "progress_total" in row.keys() else 0,
            progress_message=row["progress_message"] if "progress_message" in row.keys() else None,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            finished_at=row["finished_at"] if "finished_at" in row.keys() else row["completed_at"],
            top_k=row["top_k"],
            error_message=row["error_message"],
            sources=sources,
            selected_models=models,
        )

    def list_queries(self, run_id: UUID) -> list[Query]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM queries
                WHERE run_id = ?
                ORDER BY position ASC
                """,
                (str(run_id),),
            ).fetchall()
        return [
            Query(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                text=row["text"],
                position=row["position"],
                language=row["language"],
            )
            for row in rows
        ]

    def update_run(self, run: Run) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET run_type = ?, status = ?, stage = ?, progress_current = ?, progress_total = ?,
                    progress_message = ?, top_k = ?, started_at = ?, completed_at = ?, finished_at = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    run.run_type.value,
                    run.status.value,
                    run.stage,
                    run.progress_current,
                    run.progress_total,
                    run.progress_message,
                    run.top_k,
                    _dt_to_str(run.started_at),
                    _dt_to_str(run.completed_at),
                    _dt_to_str(run.finished_at),
                    run.error_message,
                    str(run.id),
                ),
            )

    def delete_run(self, run_id: UUID) -> bool:
        """Delete one run and all cascading child rows."""

        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM runs WHERE id = ?",
                (str(run_id),),
            )
        return cursor.rowcount > 0

    def reset_run_execution(self, run_id: UUID) -> None:
        with self.database.connect() as connection:
            connection.execute("DELETE FROM llm_calls WHERE run_id = ?", (str(run_id),))
            connection.execute("DELETE FROM result_records WHERE run_id = ?", (str(run_id),))
            connection.execute(
                """
                UPDATE run_sources
                SET status = ?, completed_count = 0, failed_count = 0, progress_current = 0,
                    progress_message = NULL, started_at = NULL, finished_at = NULL, error_message = NULL
                WHERE run_id = ?
                """,
                (ExecutionStatus.PENDING.value, str(run_id)),
            )
            connection.execute(
                """
                UPDATE run_models
                SET status = ?, progress_current = 0, progress_message = NULL,
                    started_at = NULL, finished_at = NULL, error_message = NULL
                WHERE run_id = ?
                """,
                (ExecutionStatus.PENDING.value, str(run_id)),
            )

    def update_run_source_status(
        self,
        *,
        run_id: UUID,
        source_name: str,
        status: ExecutionStatus | None = None,
        completed_count: int | None = None,
        failed_count: int | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        progress_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            existing = connection.execute(
                """
                SELECT status, completed_count, failed_count, progress_current, progress_total,
                       progress_message, started_at, finished_at, error_message
                FROM run_sources
                WHERE run_id = ? AND source_name = ?
                """,
                (str(run_id), source_name),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Source {source_name} not found for run {run_id}")

            connection.execute(
                """
                UPDATE run_sources
                SET status = ?, completed_count = ?, failed_count = ?, progress_current = ?,
                    progress_total = ?, progress_message = ?, started_at = ?, finished_at = ?, error_message = ?
                WHERE run_id = ? AND source_name = ?
                """,
                (
                    status.value if status is not None else existing["status"],
                    completed_count if completed_count is not None else existing["completed_count"],
                    failed_count if failed_count is not None else existing["failed_count"],
                    progress_current if progress_current is not None else existing["progress_current"],
                    progress_total if progress_total is not None else existing["progress_total"],
                    progress_message if progress_message is not None else existing["progress_message"],
                    _dt_to_str(started_at) if started_at is not None else existing["started_at"],
                    _dt_to_str(finished_at) if finished_at is not None else existing["finished_at"],
                    error_message if error_message is not None else existing["error_message"],
                    str(run_id),
                    source_name,
                ),
            )

    def update_run_model_status(
        self,
        *,
        run_id: UUID,
        model_name: str,
        status: ExecutionStatus | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        progress_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            existing = connection.execute(
                """
                SELECT status, progress_current, progress_total, progress_message, started_at, finished_at, error_message
                FROM run_models
                WHERE run_id = ? AND model_name = ?
                """,
                (str(run_id), model_name),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Model {model_name} not found for run {run_id}")

            connection.execute(
                """
                UPDATE run_models
                SET status = ?, progress_current = ?, progress_total = ?, progress_message = ?,
                    started_at = ?, finished_at = ?, error_message = ?
                WHERE run_id = ? AND model_name = ?
                """,
                (
                    status.value if status is not None else existing["status"],
                    progress_current if progress_current is not None else existing["progress_current"],
                    progress_total if progress_total is not None else existing["progress_total"],
                    progress_message if progress_message is not None else existing["progress_message"],
                    _dt_to_str(started_at) if started_at is not None else existing["started_at"],
                    _dt_to_str(finished_at) if finished_at is not None else existing["finished_at"],
                    error_message if error_message is not None else existing["error_message"],
                    str(run_id),
                    model_name,
                ),
            )

    def save_llm_call(self, call: LLMCall) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO llm_calls (
                    id, run_id, query_id, model_name, provider_name, status, prompt_text,
                    request_payload, response_payload, response_text, parse_success, parse_error,
                    latency_ms, prompt_tokens, completion_tokens, total_tokens, error_message,
                    created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(call.id),
                    str(call.run_id),
                    str(call.query_id),
                    call.model_name,
                    call.provider_name,
                    call.status.value,
                    call.prompt_text,
                    _json_dumps(call.request_payload),
                    _json_dumps(call.response_payload),
                    call.response_text,
                    1 if call.parse_success else 0,
                    call.parse_error,
                    call.latency_ms,
                    call.prompt_tokens,
                    call.completion_tokens,
                    call.total_tokens,
                    call.error_message,
                    _dt_to_str(call.created_at),
                    _dt_to_str(call.started_at),
                    _dt_to_str(call.finished_at),
                ),
            )

    def list_llm_calls(self, run_id: UUID) -> list[LLMCall]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM llm_calls
                WHERE run_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (str(run_id),),
            ).fetchall()
        return [
            LLMCall(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                query_id=UUID(row["query_id"]),
                model_name=row["model_name"],
                provider_name=row["provider_name"],
                status=row["status"],
                prompt_text=row["prompt_text"],
                request_payload=_json_loads(row["request_payload"], default={}),
                response_payload=_json_loads(row["response_payload"], default={}),
                response_text=row["response_text"],
                parse_success=bool(row["parse_success"]),
                parse_error=row["parse_error"],
                latency_ms=row["latency_ms"],
                prompt_tokens=row["prompt_tokens"],
                completion_tokens=row["completion_tokens"],
                total_tokens=row["total_tokens"],
                error_message=row["error_message"],
                created_at=row["created_at"],
                started_at=row["started_at"] if "started_at" in row.keys() else None,
                finished_at=row["finished_at"] if "finished_at" in row.keys() else None,
            )
            for row in rows
        ]

    def list_latest_llm_calls_for_model(self, run_id: UUID, model_name: str) -> dict[UUID, LLMCall]:
        """Return the newest stored LLM call for each query for one model."""

        calls: dict[UUID, LLMCall] = {}
        for call in self.list_llm_calls(run_id):
            if call.model_name != model_name:
                continue
            calls[call.query_id] = call
        return calls

    def delete_llm_results_for_query_model(self, *, run_id: UUID, query_id: UUID, model_name: str) -> int:
        """Delete result rows for one LLM query/model pair before replacing retry output."""

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM result_records
                WHERE run_id = ?
                  AND query_id = ?
                  AND model_name = ?
                  AND origin_type = ?
                """,
                (
                    str(run_id),
                    str(query_id),
                    model_name,
                    ResultOriginType.LLM_RESPONSE.value,
                ),
            )
        return cursor.rowcount

    def save_results(self, results: list[ResultRecord]) -> None:
        if not results:
            return
        with self.database.connect() as connection:
            for result in results:
                connection.execute(
                    """
                    INSERT INTO result_records (
                        id, run_id, query_id, llm_call_id, origin_type, source_name, model_name,
                        provider_name, execution_status, rank, canonical_identifier, title, doi, url,
                        source_identifier, year, authors_json, venue, publisher, language, raw_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(result.id),
                        str(result.run_id),
                        str(result.query_id),
                        str(result.llm_call_id) if result.llm_call_id else None,
                        result.origin_type.value,
                        result.source_name,
                        result.model_name,
                        result.provider_name,
                        result.execution_status.value,
                        result.rank,
                        result.canonical_identifier,
                        result.title,
                        result.doi,
                        result.url,
                        result.source_identifier,
                        result.year,
                        _json_dumps(result.authors),
                        result.venue,
                        result.publisher,
                        result.language,
                        _json_dumps(result.raw_payload),
                    ),
                )

    def list_results(self, run_id: UUID) -> list[ResultRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM result_records
                WHERE run_id = ?
                ORDER BY query_id ASC, model_name ASC, source_name ASC, rank ASC, id ASC
                """,
                (str(run_id),),
            ).fetchall()
        return [
            ResultRecord(
                id=UUID(row["id"]),
                run_id=UUID(row["run_id"]),
                query_id=UUID(row["query_id"]),
                llm_call_id=UUID(row["llm_call_id"]) if row["llm_call_id"] else None,
                origin_type=row["origin_type"],
                source_name=row["source_name"],
                model_name=row["model_name"],
                provider_name=row["provider_name"],
                execution_status=row["execution_status"],
                rank=row["rank"],
                canonical_identifier=row["canonical_identifier"],
                title=row["title"],
                doi=row["doi"],
                url=row["url"],
                source_identifier=row["source_identifier"],
                year=row["year"],
                authors=_json_loads(row["authors_json"], default=[]),
                venue=row["venue"],
                publisher=row["publisher"],
                language=row["language"],
                raw_payload=_json_loads(row["raw_payload"], default={}),
            )
            for row in rows
        ]

    def replace_enrichments(
        self,
        result_record_id: UUID,
        provider_records: list[EnrichmentRecord],
        canonical_enrichment: CanonicalEnrichment | None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM enrichment_records WHERE result_record_id = ?",
                (str(result_record_id),),
            )
            connection.execute(
                "DELETE FROM canonical_enrichments WHERE result_record_id = ?",
                (str(result_record_id),),
            )
            for record in provider_records:
                connection.execute(
                    """
                    INSERT INTO enrichment_records (
                        id, result_record_id, provider, provider_record_id, status, enriched_at,
                        match_strategy, external_ids_json, source_ids_json, doi, title, abstract,
                        authors_json, affiliations_json, publication_year, language, is_open_access,
                        open_access_status, citation_count, publisher, venue, fields_of_study_json,
                        subject_areas_json, country_primary, country_dominant, countries_json,
                        urls_json, landing_page_url, pdf_url, raw_payload, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(record.id),
                        str(record.result_record_id),
                        record.provider.value,
                        record.provider_record_id,
                        record.status.value,
                        _dt_to_str(record.enriched_at),
                        record.match_strategy.value if record.match_strategy else None,
                        _json_dumps(record.external_ids),
                        _json_dumps(record.source_ids),
                        record.doi,
                        record.title,
                        record.abstract,
                        _json_dumps(record.authors),
                        _json_dumps(record.affiliations),
                        record.publication_year,
                        record.language,
                        _bool_to_db(record.is_open_access),
                        record.open_access_status,
                        record.citation_count,
                        record.publisher,
                        record.venue,
                        _json_dumps(record.fields_of_study),
                        _json_dumps(record.subject_areas),
                        record.country_primary,
                        record.country_dominant,
                        _json_dumps(record.countries),
                        _json_dumps(record.urls),
                        record.landing_page_url,
                        record.pdf_url,
                        _json_dumps(record.raw_payload),
                        record.error_message,
                    ),
                )
            if canonical_enrichment is not None:
                connection.execute(
                    """
                    INSERT INTO canonical_enrichments (
                        id, result_record_id, updated_at, source_record_ids_json, external_ids_json,
                        source_ids_json, doi, title, abstract, authors_json, affiliations_json,
                        publication_year, language, is_open_access, open_access_status,
                        citation_count, publisher, venue, fields_of_study_json, subject_areas_json,
                        country_primary, country_dominant, countries_json, urls_json,
                        landing_page_url, pdf_url, field_provenance_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(canonical_enrichment.id),
                        str(canonical_enrichment.result_record_id),
                        _dt_to_str(canonical_enrichment.updated_at),
                        _json_dumps([str(value) for value in canonical_enrichment.source_record_ids]),
                        _json_dumps(canonical_enrichment.external_ids),
                        _json_dumps(canonical_enrichment.source_ids),
                        canonical_enrichment.doi,
                        canonical_enrichment.title,
                        canonical_enrichment.abstract,
                        _json_dumps(canonical_enrichment.authors),
                        _json_dumps(canonical_enrichment.affiliations),
                        canonical_enrichment.publication_year,
                        canonical_enrichment.language,
                        _bool_to_db(canonical_enrichment.is_open_access),
                        canonical_enrichment.open_access_status,
                        canonical_enrichment.citation_count,
                        canonical_enrichment.publisher,
                        canonical_enrichment.venue,
                        _json_dumps(canonical_enrichment.fields_of_study),
                        _json_dumps(canonical_enrichment.subject_areas),
                        canonical_enrichment.country_primary,
                        canonical_enrichment.country_dominant,
                        _json_dumps(canonical_enrichment.countries),
                        _json_dumps(canonical_enrichment.urls),
                        canonical_enrichment.landing_page_url,
                        canonical_enrichment.pdf_url,
                        _json_dumps(
                            {
                                key: value.model_dump(mode="json")
                                for key, value in canonical_enrichment.field_provenance.items()
                            }
                        ),
                    ),
                )

    def list_enrichments_by_result(
        self,
        run_id: UUID,
    ) -> dict[UUID, tuple[list[EnrichmentRecord], CanonicalEnrichment | None]]:
        with self.database.connect() as connection:
            result_rows = connection.execute(
                "SELECT id FROM result_records WHERE run_id = ?",
                (str(run_id),),
            ).fetchall()
            result_ids = [row["id"] for row in result_rows]
            enrichment_rows = connection.execute(
                """
                SELECT * FROM enrichment_records
                WHERE result_record_id IN (
                    SELECT id FROM result_records WHERE run_id = ?
                )
                ORDER BY provider ASC, enriched_at ASC
                """,
                (str(run_id),),
            ).fetchall()
            canonical_rows = connection.execute(
                """
                SELECT * FROM canonical_enrichments
                WHERE result_record_id IN (
                    SELECT id FROM result_records WHERE run_id = ?
                )
                """,
                (str(run_id),),
            ).fetchall()

        enrichments_by_result: dict[UUID, list[EnrichmentRecord]] = defaultdict(list)
        for row in enrichment_rows:
            result_id = UUID(row["result_record_id"])
            enrichments_by_result[result_id].append(
                EnrichmentRecord(
                    id=UUID(row["id"]),
                    result_record_id=result_id,
                    provider=EnrichmentProvider(row["provider"]),
                    provider_record_id=row["provider_record_id"],
                    status=row["status"],
                    enriched_at=row["enriched_at"],
                    match_strategy=row["match_strategy"],
                    external_ids=_json_loads(row["external_ids_json"], default={}),
                    source_ids=_json_loads(row["source_ids_json"], default={}),
                    doi=row["doi"],
                    title=row["title"],
                    abstract=row["abstract"],
                    authors=_json_loads(row["authors_json"], default=[]),
                    affiliations=_json_loads(row["affiliations_json"], default=[]),
                    publication_year=row["publication_year"],
                    language=row["language"],
                    is_open_access=_bool_from_db(row["is_open_access"]),
                    open_access_status=row["open_access_status"],
                    citation_count=row["citation_count"],
                    publisher=row["publisher"],
                    venue=row["venue"],
                    fields_of_study=_json_loads(row["fields_of_study_json"], default=[]),
                    subject_areas=_json_loads(row["subject_areas_json"], default=[]),
                    country_primary=row["country_primary"],
                    country_dominant=row["country_dominant"],
                    countries=_json_loads(row["countries_json"], default=[]),
                    urls=_json_loads(row["urls_json"], default=[]),
                    landing_page_url=row["landing_page_url"],
                    pdf_url=row["pdf_url"],
                    raw_payload=_json_loads(row["raw_payload"], default={}),
                    error_message=row["error_message"],
                )
            )

        canonical_by_result: dict[UUID, CanonicalEnrichment] = {}
        for row in canonical_rows:
            result_id = UUID(row["result_record_id"])
            provenance_payload = _json_loads(row["field_provenance_json"], default={})
            canonical_by_result[result_id] = CanonicalEnrichment(
                id=UUID(row["id"]),
                result_record_id=result_id,
                updated_at=row["updated_at"],
                source_record_ids=[
                    UUID(value) for value in _json_loads(row["source_record_ids_json"], default=[])
                ],
                external_ids=_json_loads(row["external_ids_json"], default={}),
                source_ids=_json_loads(row["source_ids_json"], default={}),
                doi=row["doi"],
                title=row["title"],
                abstract=row["abstract"],
                authors=_json_loads(row["authors_json"], default=[]),
                affiliations=_json_loads(row["affiliations_json"], default=[]),
                publication_year=row["publication_year"],
                language=row["language"],
                is_open_access=_bool_from_db(row["is_open_access"]),
                open_access_status=row["open_access_status"],
                citation_count=row["citation_count"],
                publisher=row["publisher"],
                venue=row["venue"],
                fields_of_study=_json_loads(row["fields_of_study_json"], default=[]),
                subject_areas=_json_loads(row["subject_areas_json"], default=[]),
                country_primary=row["country_primary"],
                country_dominant=row["country_dominant"],
                countries=_json_loads(row["countries_json"], default=[]),
                urls=_json_loads(row["urls_json"], default=[]),
                landing_page_url=row["landing_page_url"],
                pdf_url=row["pdf_url"],
                field_provenance={
                    key: FieldProvenance.model_validate(value)
                    for key, value in provenance_payload.items()
                },
            )

        output: dict[UUID, tuple[list[EnrichmentRecord], CanonicalEnrichment | None]] = {}
        for result_id in result_ids:
            parsed_id = UUID(result_id)
            output[parsed_id] = (
                enrichments_by_result.get(parsed_id, []),
                canonical_by_result.get(parsed_id),
            )
        return output

    def get_cache_payload(self, provider: str, cache_key: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, expires_at
                FROM provider_cache
                WHERE provider = ? AND cache_key = ?
                """,
                (provider, cache_key),
            ).fetchone()
            if row is None:
                return None

            expires_at = row["expires_at"]
            if expires_at:
                expiry = datetime.fromisoformat(expires_at)
                if expiry <= datetime.now(timezone.utc):
                    connection.execute(
                        "DELETE FROM provider_cache WHERE provider = ? AND cache_key = ?",
                        (provider, cache_key),
                    )
                    return None
            return _json_loads(row["payload_json"], default={})

    def peek_cache_payload(self, provider: str, cache_key: str) -> tuple[dict[str, Any] | None, datetime | None]:
        """Return one cached payload and expiry without deleting expired rows."""

        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, expires_at
                FROM provider_cache
                WHERE provider = ? AND cache_key = ?
                """,
                (provider, cache_key),
            ).fetchone()
            if row is None:
                return None, None

        expires_at = row["expires_at"]
        expiry = datetime.fromisoformat(expires_at) if expires_at else None
        return _json_loads(row["payload_json"], default={}), expiry

    def set_cache_payload(
        self,
        provider: str,
        cache_key: str,
        payload: dict[str, Any],
        expires_at: datetime | None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO provider_cache (
                    provider, cache_key, payload_json, created_at, expires_at
                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    provider,
                    cache_key,
                    _json_dumps(payload),
                    _dt_to_str(expires_at),
                ),
            )

    def list_entity_statuses(self, run_id: UUID) -> list[EntityExecutionSummary]:
        run = self.get_run(run_id)
        if run.run_type == RunType.LLM_AUDIT:
            return self._list_model_statuses(run_id)
        return self._list_source_statuses(run_id)

    def _list_model_statuses(self, run_id: UUID) -> list[EntityExecutionSummary]:
        with self.database.connect() as connection:
            model_rows = connection.execute(
                """
                SELECT model_name, status, progress_current, progress_total, progress_message,
                       started_at, finished_at, error_message
                FROM run_models
                WHERE run_id = ?
                ORDER BY model_name
                """,
                (str(run_id),),
            ).fetchall()
            query_total = connection.execute(
                "SELECT COUNT(*) AS query_count FROM queries WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()["query_count"]
            rows = connection.execute(
                """
                SELECT c.model_name, c.status, COUNT(*) AS total_count
                FROM llm_calls c
                WHERE c.run_id = ?
                  AND c.created_at = (
                    SELECT MAX(newer.created_at)
                    FROM llm_calls newer
                    WHERE newer.run_id = c.run_id
                      AND newer.model_name = c.model_name
                      AND newer.query_id = c.query_id
                  )
                GROUP BY c.model_name, c.status
                """,
                (str(run_id),),
            ).fetchall()

        counts_by_model: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            counts_by_model[row["model_name"]][row["status"]] = row["total_count"]

        summaries: list[EntityExecutionSummary] = []
        for model_row in model_rows:
            model_name = model_row["model_name"]
            counts = counts_by_model.get(model_name, {})
            completed = counts.get(ExecutionStatus.COMPLETED.value, 0)
            skipped = counts.get(ExecutionStatus.SKIPPED.value, 0)
            failed = counts.get(ExecutionStatus.FAILED.value, 0) + skipped
            running = counts.get(ExecutionStatus.RUNNING.value, 0)
            derived_total = max(sum(counts.values()), int(query_total or 0))
            progress_total = model_row["progress_total"] or derived_total
            progress_current = model_row["progress_current"] or (completed + failed)
            if model_row["status"]:
                status = ExecutionStatus(model_row["status"])
            elif running:
                status = ExecutionStatus.RUNNING
            elif derived_total == 0:
                status = ExecutionStatus.PENDING
            elif failed and completed:
                status = ExecutionStatus.PARTIAL
            elif skipped and not completed:
                status = ExecutionStatus.SKIPPED
            elif failed:
                status = ExecutionStatus.FAILED
            else:
                status = ExecutionStatus.COMPLETED
            summaries.append(
                EntityExecutionSummary(
                    entity_type="model",
                    name=model_name,
                    status=status,
                    completed_count=completed,
                    failed_count=failed,
                    total_count=progress_total,
                    progress_current=progress_current,
                    progress_total=progress_total,
                    progress_message=model_row["progress_message"],
                    started_at=model_row["started_at"],
                    finished_at=model_row["finished_at"],
                    error_message=model_row["error_message"],
                )
            )
        return summaries

    def _list_source_statuses(self, run_id: UUID) -> list[EntityExecutionSummary]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_name, status, completed_count, failed_count, progress_current,
                       progress_total, progress_message, started_at, finished_at, error_message
                FROM run_sources
                WHERE run_id = ?
                ORDER BY source_name
                """,
                (str(run_id),),
            ).fetchall()

        summaries: list[EntityExecutionSummary] = []
        for row in rows:
            total = row["progress_total"] or 0
            summaries.append(
                EntityExecutionSummary(
                    entity_type="source",
                    name=row["source_name"],
                    status=ExecutionStatus(row["status"]),
                    completed_count=row["completed_count"] or 0,
                    failed_count=row["failed_count"] or 0,
                    total_count=total,
                    progress_current=row["progress_current"] or 0,
                    progress_total=total,
                    progress_message=row["progress_message"],
                    started_at=row["started_at"],
                    finished_at=row["finished_at"],
                    error_message=row["error_message"],
                )
            )
        return summaries


def get_repository() -> Repository:
    """Return the default repository."""

    return Repository()
