"""Recovery helpers for interrupted run execution."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Iterator
from uuid import UUID

from backend.application.run_artifacts import get_run_artifacts_writer
from backend.domain import ExecutionStatus, RunStatus, RunType
from backend.storage.repository import Repository

_ACTIVE_RUN_IDS: set[str] = set()
_ACTIVE_RUN_IDS_LOCK = Lock()


@contextmanager
def track_active_run(run_id: UUID | str) -> Iterator[None]:
    """Register one run as active in the current process for the context lifetime."""

    key = str(run_id)
    with _ACTIVE_RUN_IDS_LOCK:
        _ACTIVE_RUN_IDS.add(key)
    try:
        yield
    finally:
        with _ACTIVE_RUN_IDS_LOCK:
            _ACTIVE_RUN_IDS.discard(key)


def is_run_active(run_id: UUID | str) -> bool:
    """Return whether this process currently executes the given run."""

    with _ACTIVE_RUN_IDS_LOCK:
        return str(run_id) in _ACTIVE_RUN_IDS


def recover_inactive_running_llm_run(
    *,
    repository: Repository,
    run_id: UUID,
) -> bool:
    """Recover one interrupted llm_audit run after a process restart.

    This path is intentionally conservative. It only touches runs that are still
    marked as ``running`` in the database but are not active in the current
    process anymore. That makes it safe to call from read/replay endpoints after
    a server restart without racing a live in-process execution.
    """

    try:
        run = repository.get_run(run_id)
    except KeyError:
        return False
    if run.run_type != RunType.LLM_AUDIT or run.status != RunStatus.RUNNING:
        return False
    if is_run_active(run_id):
        return False

    queries = repository.list_queries(run.id)
    llm_calls = repository.list_llm_calls(run.id)
    running_calls = [call for call in llm_calls if call.status == ExecutionStatus.RUNNING]
    if not running_calls:
        return False

    artifacts = get_run_artifacts_writer(run.id)
    recovered_at = datetime.now(timezone.utc)
    recovery_message = (
        "Recovered inactive LLM run after process interruption. "
        "Replay stored artifacts to rebuild downstream outputs."
    )
    query_positions = {query.id: query.position for query in queries}

    for call in running_calls:
        if call.started_at is not None and call.latency_ms is None:
            call.latency_ms = max(
                int((recovered_at - call.started_at).total_seconds() * 1000),
                0,
            )
        call.status = ExecutionStatus.FAILED
        call.parse_success = False
        call.parse_error = recovery_message
        call.error_message = recovery_message
        call.finished_at = recovered_at
        repository.save_llm_call(call)

        query_index = query_positions.get(call.query_id)
        if query_index is not None:
            artifacts.write_llm_parse_error(
                query_index=query_index,
                model_name=call.model_name,
                error_message=recovery_message,
                response_text=call.response_text,
            )
            artifacts.write_llm_metadata(
                query_index=query_index,
                model_name=call.model_name,
                metadata={
                    "status": ExecutionStatus.FAILED.value,
                    "started_at": call.started_at,
                    "finished_at": call.finished_at,
                    "latency_ms": call.latency_ms,
                    "prompt_tokens": call.prompt_tokens,
                    "completion_tokens": call.completion_tokens,
                    "total_tokens": call.total_tokens,
                    "error_message": recovery_message,
                    "recovered_after_process_interruption": True,
                },
            )
        artifacts.append_error(
            stage="llm",
            message=recovery_message,
            query_index=query_index,
            model=call.model_name,
            recovered_after_process_interruption=True,
        )

    llm_calls = repository.list_llm_calls(run.id)
    total_queries = len(queries)
    progress_total = max(total_queries, 1)

    completed_calls = 0
    failed_calls = 0
    skipped_calls = 0
    for model_name in run.selected_models:
        model_calls = [call for call in llm_calls if call.model_name == model_name]
        completed = sum(1 for call in model_calls if call.status == ExecutionStatus.COMPLETED)
        skipped = sum(1 for call in model_calls if call.status == ExecutionStatus.SKIPPED)
        failed = sum(1 for call in model_calls if call.status == ExecutionStatus.FAILED) + skipped
        completed_calls += completed
        failed_calls += failed - skipped
        skipped_calls += skipped

        status = _recovered_model_status(
            completed_count=completed,
            failed_count=failed,
            total_queries=total_queries,
        )
        model_started_at = min(
            (call.started_at for call in model_calls if call.started_at is not None),
            default=run.started_at,
        )
        model_error = recovery_message if status != ExecutionStatus.COMPLETED else None
        if failed and completed:
            model_progress_message = "Recovered with failures"
        elif failed:
            model_progress_message = "Recovered as failed"
        elif completed >= progress_total:
            model_progress_message = "Completed"
        else:
            model_progress_message = "Recovered as incomplete"
        repository.update_run_model_status(
            run_id=run.id,
            model_name=model_name,
            status=status,
            progress_current=completed + failed,
            progress_total=progress_total,
            progress_message=model_progress_message,
            started_at=model_started_at,
            finished_at=recovered_at,
            error_message=model_error,
        )

    total_model_calls = max(total_queries * max(len(run.selected_models), 1), 1)
    processed_model_calls = len(llm_calls)
    unreached_calls = max(total_model_calls - processed_model_calls, 0)

    issue_parts: list[str] = []
    if failed_calls:
        issue_parts.append(f"{failed_calls} llm calls failed")
    if skipped_calls:
        issue_parts.append(f"{skipped_calls} model executions skipped")
    if unreached_calls:
        issue_parts.append(f"{unreached_calls} model executions were never reached")
    issue_summary = "; ".join(issue_parts) if issue_parts else "LLM execution was interrupted"
    error_message = f"{issue_summary}; replay stored artifacts to rebuild downstream outputs"

    run.status = RunStatus.PARTIAL if completed_calls else RunStatus.FAILED
    run.stage = "error"
    run.progress_current = processed_model_calls
    run.progress_total = total_model_calls
    run.progress_message = recovery_message
    run.error_message = error_message
    run.completed_at = recovered_at
    run.finished_at = recovered_at
    repository.update_run(run)

    artifacts.write_manifest(run=run, query_count=len(queries))
    artifacts.write_run_snapshot(run=run)
    artifacts.write_run_error(
        {
            "run_id": str(run.id),
            "run_type": run.run_type.value,
            "status": run.status.value,
            "error_message": error_message,
            "finished_at": recovered_at,
            "recovered_after_process_interruption": True,
        }
    )
    artifacts.append_error(
        stage="run",
        message=error_message,
        recovered_after_process_interruption=True,
    )
    return True


def recover_inactive_running_llm_runs(*, repository: Repository) -> int:
    """Recover every inactive running llm_audit run visible in the repository."""

    with repository.database.connect() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM runs
            WHERE run_type = ? AND status = ?
            ORDER BY created_at ASC, id ASC
            """,
            (RunType.LLM_AUDIT.value, RunStatus.RUNNING.value),
        ).fetchall()

    recovered = 0
    for row in rows:
        if recover_inactive_running_llm_run(
            repository=repository,
            run_id=UUID(row["id"]),
        ):
            recovered += 1
    return recovered


def _recovered_model_status(
    *,
    completed_count: int,
    failed_count: int,
    total_queries: int,
) -> ExecutionStatus:
    processed = completed_count + failed_count
    expected = max(total_queries, 1)
    if processed >= expected:
        if completed_count and failed_count:
            return ExecutionStatus.PARTIAL
        if failed_count:
            return ExecutionStatus.FAILED
        return ExecutionStatus.COMPLETED
    if completed_count:
        return ExecutionStatus.PARTIAL
    return ExecutionStatus.FAILED
