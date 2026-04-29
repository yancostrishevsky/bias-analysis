"""Filesystem artifact writer for per-run debug and audit outputs."""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from backend.config import get_settings
from backend.domain import CanonicalEnrichment, EnrichmentRecord, Query, ResultRecord, Run, RunAnalysis, RunType


LOGGER = logging.getLogger(__name__)
_SENSITIVE_KEY_RE = re.compile(
    r"(^|[_-])(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|insttoken|secret|password)([_-]|$)",
    re.IGNORECASE,
)
_PATH_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REDACTED = "[REDACTED]"


def get_run_artifacts_writer(run_id: UUID | str) -> "RunArtifactsWriter":
    """Return a writer configured from the current application settings."""

    settings = get_settings().run_artifacts
    return RunArtifactsWriter(
        run_id=str(run_id),
        root_dir=settings.path,
        enabled=settings.enabled,
        pretty_json=settings.pretty_json,
    )


class RunArtifactsWriter:
    """Best-effort writer for structured per-run filesystem artifacts."""

    def __init__(
        self,
        *,
        run_id: UUID | str,
        root_dir: Path,
        enabled: bool = True,
        pretty_json: bool = True,
    ) -> None:
        self.run_id = str(run_id)
        self.root_dir = root_dir
        self.enabled = enabled
        self.pretty_json = pretty_json

    @property
    def run_dir(self) -> Path:
        return self.root_dir / f"run_{self.run_id}"

    def initialize_run(
        self,
        *,
        run: Run,
        queries: Sequence[Query],
        raw_create_payload: dict[str, Any],
        normalized_payload: dict[str, Any],
    ) -> None:
        """Create the run folder and initial input artifacts."""

        if not self.enabled:
            return

        self._safe(
            "initialize run artifacts",
            lambda: self._initialize_run(
                run=run,
                queries=queries,
                raw_create_payload=raw_create_payload,
                normalized_payload=normalized_payload,
            ),
        )

    def write_manifest(self, *, run: Run, query_count: int) -> None:
        """Write or refresh the top-level manifest file."""

        self._write_json(
            Path("manifest.json"),
            {
                "run_id": self.run_id,
                "run_type": run.run_type.value,
                "created_at": run.created_at,
                "started_at": run.started_at,
                "finished_at": run.finished_at or run.completed_at,
                "status": run.status.value,
                "stage": run.stage,
                "selected_models": list(run.selected_models),
                "sources": list(run.sources),
                "provider_order": list(get_settings().enrichment_provider_order),
                "top_k": run.top_k,
                "query_count": query_count,
                "progress_current": run.progress_current,
                "progress_total": run.progress_total,
                "progress_message": run.progress_message,
                "error_message": run.error_message,
            },
        )

    def write_run_snapshot(self, *, run: Run) -> None:
        """Refresh the persisted run snapshot without dropping inputs or config."""

        if not self.enabled:
            return

        payload = self._load_existing_json(Path("run.json"))
        payload["run"] = run.model_dump(mode="json")
        self._write_json(Path("run.json"), payload)

    def delete_run_artifacts(self) -> None:
        """Best-effort removal of one run's artifact directory."""

        if not self.enabled:
            return

        self._safe(
            "delete run artifacts",
            lambda: shutil.rmtree(self.run_dir, ignore_errors=False) if self.run_dir.exists() else None,
        )

    def clear_replay_artifacts(self) -> None:
        """Best-effort removal of replay-only artifacts before a fresh execution."""

        if not self.enabled:
            return

        self._safe(
            "clear replay artifacts",
            lambda: shutil.rmtree(self.run_dir / "replay", ignore_errors=False)
            if (self.run_dir / "replay").exists()
            else None,
        )

    def append_event(
        self,
        *,
        stage: str,
        message: str,
        level: str = "INFO",
        **extra: Any,
    ) -> None:
        """Append one machine-readable event line."""

        self._append_jsonl(
            Path("logs/events.jsonl"),
            {
                "ts": self._timestamp(),
                "level": level,
                "stage": stage,
                "message": message,
                "run_id": self.run_id,
                **self._redact(extra),
            },
        )

    def append_error(
        self,
        *,
        stage: str,
        message: str,
        **extra: Any,
    ) -> None:
        """Append one machine-readable error line."""

        payload = {
            "ts": self._timestamp(),
            "level": "ERROR",
            "stage": stage,
            "message": message,
            "run_id": self.run_id,
            **self._redact(extra),
        }
        self._append_jsonl(Path("logs/errors.jsonl"), payload)
        self._append_jsonl(Path("logs/events.jsonl"), payload)

    def write_run_error(self, payload: dict[str, Any]) -> None:
        """Persist a top-level run failure payload."""

        self._write_json(Path("run_error.json"), payload)

    def write_scholarly_request(
        self,
        *,
        query_index: int,
        source_name: str,
        request: dict[str, Any],
    ) -> None:
        """Persist the exact scholarly request envelope."""

        query_dir = self._query_dir("scholarly", query_index)
        filename = f"source_{self.sanitize_path_component(source_name)}_request.json"
        self._write_json(query_dir / filename, request)

    def write_scholarly_response(
        self,
        *,
        query_index: int,
        source_name: str,
        response: dict[str, Any],
    ) -> None:
        """Persist the raw scholarly response and extracted result list."""

        query_dir = self._query_dir("scholarly", query_index)
        filename = f"source_{self.sanitize_path_component(source_name)}_response.json"
        self._write_json(query_dir / filename, response)

    def write_scholarly_normalized_results(
        self,
        *,
        query_index: int,
        source_name: str,
        results: Sequence[ResultRecord],
    ) -> None:
        """Persist normalized scholarly result payloads for one query x source."""

        self._write_json(
            self._query_dir("scholarly", query_index)
            / f"source_{self.sanitize_path_component(source_name)}_results_normalized.json",
            [result.model_dump(mode="json") for result in results],
        )

    def write_scholarly_source_raw_results(
        self,
        *,
        query_index: int,
        source_name: str,
        results: Sequence[dict[str, Any]],
    ) -> None:
        """Persist raw result items for one query x source."""

        self._write_json(
            self._query_dir("scholarly", query_index)
            / f"source_{self.sanitize_path_component(source_name)}_results_raw.json",
            list(results),
        )

    def write_scholarly_query_raw_results(
        self,
        *,
        query_index: int,
        payload: Sequence[dict[str, Any]],
    ) -> None:
        """Persist the query-level raw result bundle across all selected sources."""

        self._write_json(
            self._query_dir("scholarly", query_index) / "results_raw.json",
            list(payload),
        )

    def write_scholarly_query_normalized_results(
        self,
        *,
        query_index: int,
        results: Sequence[ResultRecord],
    ) -> None:
        """Persist the combined normalized result rows for one query."""

        self._write_json(
            self._query_dir("scholarly", query_index) / "results_normalized.json",
            [result.model_dump(mode="json") for result in results],
        )

    def write_llm_request(
        self,
        *,
        query_index: int,
        model_name: str,
        request: dict[str, Any],
    ) -> None:
        """Persist the exact sanitized LLM request envelope."""

        self._write_json(self._llm_model_dir(query_index, model_name) / "request.json", request)

    def write_llm_response(
        self,
        *,
        query_index: int,
        model_name: str,
        response: dict[str, Any],
    ) -> None:
        """Persist the raw LLM response payload."""

        self._write_json(
            self._llm_model_dir(query_index, model_name) / "response_raw.json",
            response,
        )

    def write_llm_parsed_output(
        self,
        *,
        query_index: int,
        model_name: str,
        parsed_items: Sequence[dict[str, Any]],
    ) -> None:
        """Persist normalized parsed output for one query x model."""

        self._write_json(
            self._llm_model_dir(query_index, model_name) / "parsed_output.json",
            list(parsed_items),
        )

    def write_llm_parse_error(
        self,
        *,
        query_index: int,
        model_name: str,
        error_message: str,
        response_text: str | None = None,
    ) -> None:
        """Persist parse failure details for one query x model."""

        self._write_json(
            self._llm_model_dir(query_index, model_name) / "parse_error.json",
            {
                "error_message": error_message,
                "response_text": response_text,
            },
        )

    def write_llm_metadata(
        self,
        *,
        query_index: int,
        model_name: str,
        metadata: dict[str, Any],
    ) -> None:
        """Persist LLM execution timing and token metadata."""

        self._write_json(
            self._llm_model_dir(query_index, model_name) / "metadata.json",
            metadata,
        )

    def write_retry_summary(
        self,
        *,
        model_name: str,
        attempt: int,
        payload: dict[str, Any],
    ) -> None:
        """Persist metadata for one targeted model retry attempt."""

        self._write_json(self._retry_attempt_dir(model_name, attempt) / "summary.json", payload)

    def write_retry_request(
        self,
        *,
        model_name: str,
        attempt: int,
        query_index: int,
        request: dict[str, Any],
    ) -> None:
        self._write_json(
            self._retry_model_query_dir(model_name, attempt, query_index) / "request.json",
            request,
        )

    def write_retry_response(
        self,
        *,
        model_name: str,
        attempt: int,
        query_index: int,
        response: dict[str, Any],
    ) -> None:
        self._write_json(
            self._retry_model_query_dir(model_name, attempt, query_index) / "response_raw.json",
            response,
        )

    def write_retry_parsed_output(
        self,
        *,
        model_name: str,
        attempt: int,
        query_index: int,
        parsed_items: Sequence[dict[str, Any]],
    ) -> None:
        self._write_json(
            self._retry_model_query_dir(model_name, attempt, query_index) / "parsed_output.json",
            list(parsed_items),
        )

    def write_retry_parse_error(
        self,
        *,
        model_name: str,
        attempt: int,
        query_index: int,
        error_message: str,
        response_text: str | None = None,
    ) -> None:
        self._write_json(
            self._retry_model_query_dir(model_name, attempt, query_index) / "parse_error.json",
            {
                "error_message": error_message,
                "response_text": response_text,
            },
        )

    def write_retry_metadata(
        self,
        *,
        model_name: str,
        attempt: int,
        query_index: int,
        metadata: dict[str, Any],
    ) -> None:
        self._write_json(
            self._retry_model_query_dir(model_name, attempt, query_index) / "metadata.json",
            metadata,
        )

    def next_retry_attempt_number(self, model_name: str) -> int:
        """Return the next filesystem attempt number for a model retry."""

        if not self.enabled:
            return 1
        retry_dir = Path("retries") / self.sanitize_path_component(model_name)
        absolute_dir = self.run_dir / retry_dir
        if not absolute_dir.is_dir():
            return 1
        attempts: list[int] = []
        for path in absolute_dir.iterdir():
            if not path.is_dir() or not path.name.startswith("attempt_"):
                continue
            try:
                attempts.append(int(path.name.removeprefix("attempt_")))
            except ValueError:
                continue
        return max(attempts, default=0) + 1

    def write_replay_summary(self, payload: dict[str, Any]) -> None:
        """Persist one artifact-replay summary payload."""

        self._write_json(Path("replay/summary.json"), payload)

    def write_replay_metadata(
        self,
        *,
        query_index: int,
        model_name: str,
        metadata: dict[str, Any],
    ) -> None:
        """Persist replay-specific execution metadata for one query x model."""

        self._write_json(
            self._replay_model_dir(query_index, model_name) / "metadata.json",
            metadata,
        )

    def write_replay_parsed_output(
        self,
        *,
        query_index: int,
        model_name: str,
        parsed_items: Sequence[dict[str, Any]],
    ) -> None:
        """Persist replay-generated parsed output for one query x model."""

        self._write_json(
            self._replay_model_dir(query_index, model_name) / "parsed_output.json",
            list(parsed_items),
        )

    def write_replay_parse_error(
        self,
        *,
        query_index: int,
        model_name: str,
        error_message: str,
        source: str,
        response_text: str | None = None,
    ) -> None:
        """Persist replay parse or artifact-loading failures for one query x model."""

        self._write_json(
            self._replay_model_dir(query_index, model_name) / "parse_error.json",
            {
                "error_message": error_message,
                "source": source,
                "response_text": response_text,
            },
        )

    def write_enrichment_attempt(
        self,
        *,
        record_index: int,
        provider_name: str,
        attempt_index: int,
        payload: dict[str, Any],
    ) -> None:
        """Persist one provider attempt payload for a result record."""

        filename = (
            f"provider_{self.sanitize_path_component(provider_name)}"
            f"_attempt_{attempt_index:03d}.json"
        )
        self._write_json(
            self._record_dir(record_index) / filename,
            payload,
        )

    def write_canonical_enrichment(
        self,
        *,
        record_index: int,
        canonical_enrichment: CanonicalEnrichment | None,
    ) -> None:
        """Persist the canonical enrichment payload for one result record."""

        self._write_json(
            self._record_dir(record_index) / "canonical_enrichment.json",
            canonical_enrichment.model_dump(mode="json") if canonical_enrichment is not None else None,
        )

    def write_provenance(
        self,
        *,
        record_index: int,
        canonical_enrichment: CanonicalEnrichment | None,
    ) -> None:
        """Persist field provenance for one canonical enrichment."""

        self._write_json(
            self._record_dir(record_index) / "provenance.json",
            (
                canonical_enrichment.field_provenance
                if canonical_enrichment is not None
                else {}
            ),
        )

    def write_analysis_payloads(self, analysis: RunAnalysis) -> None:
        """Persist split analysis payloads for backend/frontend debugging."""

        analysis_dir = Path("analysis")
        self._write_json(analysis_dir / "summary.json", analysis.summary.model_dump(mode="json"))
        self._write_json(
            analysis_dir / "distributions.json",
            [row.model_dump(mode="json") for row in analysis.distributions],
        )
        self._write_json(
            analysis_dir / "coverage.json",
            [row.model_dump(mode="json") for row in analysis.coverage_rows],
        )
        self._write_json(
            analysis_dir / "coverage_baseline.json",
            [row.model_dump(mode="json") for row in analysis.baseline_coverage_rows],
        )
        self._write_json(
            analysis_dir / "bias_field_sources.json",
            [row.model_dump(mode="json") for row in analysis.bias_field_sources],
        )
        self._write_json(
            analysis_dir / "bias_field_warnings.json",
            [row.model_dump(mode="json") for row in analysis.bias_field_warnings],
        )
        self._write_json(
            analysis_dir / "ranking.json",
            [row.model_dump(mode="json") for row in analysis.top_k_rows],
        )
        self._write_json(
            analysis_dir / "overlap.json",
            [row.model_dump(mode="json") for row in analysis.overlap_rows],
        )
        self._write_json(
            analysis_dir / "concentration.json",
            [row.model_dump(mode="json") for row in analysis.concentration_rows],
        )
        if analysis.llm is not None:
            self._write_json(
                analysis_dir / "llm_audit.json",
                analysis.llm.model_dump(mode="json"),
            )

    def write_analysis_metadata(
        self,
        *,
        source: str,
        generated_at: datetime,
        external_llm_calls: int,
    ) -> None:
        """Persist lightweight provenance for the latest analysis output set."""

        self._write_json(
            Path("analysis/metadata.json"),
            {
                "source": source,
                "generated_at": generated_at,
                "external_llm_calls": external_llm_calls,
            },
        )

    def read_replay_summary(self) -> dict[str, Any] | None:
        """Read the persisted replay summary when present."""

        payload = self._load_any_json(Path("replay/summary.json"))
        return payload if isinstance(payload, dict) else None

    def read_analysis_metadata(self) -> dict[str, Any] | None:
        """Read analysis provenance metadata when present."""

        payload = self._load_any_json(Path("analysis/metadata.json"))
        return payload if isinstance(payload, dict) else None

    def has_replayable_llm_artifacts(self) -> bool:
        """Return whether persisted llm artifacts can drive replay without new API calls."""

        if not self.enabled:
            return False
        llm_dir = self.run_dir / "llm"
        if not llm_dir.is_dir():
            return False
        return any(llm_dir.rglob("response_raw.json")) or any(llm_dir.rglob("parsed_output.json"))

    @staticmethod
    def sanitize_path_component(value: str) -> str:
        """Return a filesystem-safe path component."""

        cleaned = _PATH_SEGMENT_RE.sub("_", value.strip())
        cleaned = cleaned.strip("._")
        return cleaned or "unknown"

    def _initialize_run(
        self,
        *,
        run: Run,
        queries: Sequence[Query],
        raw_create_payload: dict[str, Any],
        normalized_payload: dict[str, Any],
    ) -> None:
        self._ensure_base_dirs()
        self.write_manifest(run=run, query_count=len(queries))
        self._write_json(
            Path("run.json"),
            {
                "run": run.model_dump(mode="json"),
                "raw_create_payload": raw_create_payload,
                "normalized_create_payload": normalized_payload,
                "resolved_config": self._build_run_config_snapshot(run.run_type),
            },
        )
        self._write_json(
            Path("queries.json"),
            [
                {
                    **query.model_dump(mode="json"),
                    "artifact_folder": f"query_{query.position:03d}",
                }
                for query in queries
            ],
        )
        self.append_event(stage="run", message="Run created", status=run.status.value)

    def _build_run_config_snapshot(self, run_type: RunType) -> dict[str, Any]:
        settings = get_settings()
        payload: dict[str, Any] = {
            "database": settings.database.model_dump(mode="json"),
            "run_artifacts": settings.run_artifacts.model_dump(mode="json"),
            "scholarly_sources": list(settings.scholarly_sources),
            "enrichment_provider_order": list(settings.enrichment_provider_order),
            "enabled_enrichment_providers": list(settings.enabled_enrichment_providers),
            "openalex": settings.openalex.model_dump(mode="json"),
            "semantic_scholar": settings.semantic_scholar.model_dump(mode="json"),
            "scopus": settings.scopus.model_dump(mode="json"),
            "core": settings.core.model_dump(mode="json"),
        }
        if run_type == RunType.LLM_AUDIT:
            payload["openrouter"] = settings.openrouter.model_dump(mode="json")
        return payload

    def _query_dir(self, category: str, query_index: int) -> Path:
        return Path(category) / f"query_{query_index:03d}"

    def _llm_model_dir(self, query_index: int, model_name: str) -> Path:
        return self._query_dir("llm", query_index) / f"model_{self.sanitize_path_component(model_name)}"

    def _replay_model_dir(self, query_index: int, model_name: str) -> Path:
        return (
            Path("replay")
            / "llm"
            / f"query_{query_index:03d}"
            / f"model_{self.sanitize_path_component(model_name)}"
        )

    def _retry_attempt_dir(self, model_name: str, attempt: int) -> Path:
        return (
            Path("retries")
            / self.sanitize_path_component(model_name)
            / f"attempt_{attempt:03d}"
        )

    def _retry_model_query_dir(self, model_name: str, attempt: int, query_index: int) -> Path:
        return self._retry_attempt_dir(model_name, attempt) / f"query_{query_index:03d}"

    def _record_dir(self, record_index: int) -> Path:
        return Path("enrichment") / f"record_{record_index:03d}"

    def _ensure_base_dirs(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "logs").mkdir(parents=True, exist_ok=True)

    def _write_json(self, relative_path: Path, payload: Any) -> None:
        if not self.enabled:
            return
        self._safe(
            f"write {relative_path}",
            lambda: self._write_json_atomic(relative_path, self._redact(payload)),
        )

    def _append_jsonl(self, relative_path: Path, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._safe(
            f"append {relative_path}",
            lambda: self._append_jsonl_entry(relative_path, self._redact(payload)),
        )

    def _write_json_atomic(self, relative_path: Path, payload: Any) -> None:
        self._ensure_base_dirs()
        target = self.run_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=True,
                indent=2 if self.pretty_json else None,
                sort_keys=True,
                default=self._json_default,
            )
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(target)

    def _append_jsonl_entry(self, relative_path: Path, payload: dict[str, Any]) -> None:
        self._ensure_base_dirs()
        target = self.run_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    default=self._json_default,
                )
            )
            handle.write("\n")

    def _load_existing_json(self, relative_path: Path) -> dict[str, Any]:
        target = self.run_dir / relative_path
        if not target.is_file():
            return {}
        try:
            content = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return content if isinstance(content, dict) else {}

    def _load_any_json(self, relative_path: Path) -> Any | None:
        target = self.run_dir / relative_path
        if not target.is_file():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _safe(self, action: str, fn: callable) -> None:
        try:
            fn()
        except Exception as exc:  # pragma: no cover - defensive containment
            LOGGER.warning("Artifact write failed for run %s during %s: %s", self.run_id, action, exc)

    def _redact(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key)
                if normalized_key.lower() == "authorization":
                    continue
                if _SENSITIVE_KEY_RE.search(normalized_key):
                    redacted[normalized_key] = _REDACTED
                    continue
                redacted[normalized_key] = self._redact(item)
            return redacted
        if hasattr(value, "model_dump"):
            return self._redact(value.model_dump(mode="json"))
        if hasattr(value, "__dataclass_fields__"):
            return self._redact(asdict(value))
        return str(value)

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return str(value)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
