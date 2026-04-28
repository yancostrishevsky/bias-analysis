"""Pluggable enrichment provider implementations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from backend.adapters.http import HttpClientError, JsonHttpClient
from backend.adapters.openalex.client import OpenAlexClient, OpenAlexClientError
from backend.adapters.openalex.enrichment_mapper import map_openalex_payload_to_enrichment
from backend.adapters.scholarly import SemanticScholarClient, SemanticScholarClientError
from backend.application.run_artifacts import RunArtifactsWriter
from backend.config import ProviderSettings, get_settings
from backend.domain import (
    EnrichmentMatchStrategy,
    EnrichmentProvider,
    EnrichmentRecord,
    ExecutionStatus,
    ResultRecord,
)
from backend.storage.repository import Repository

_UNKNOWN_TEXT_MARKERS = {"unknown", "n/a", "na", "none", "null"}
_LANGUAGE_NAME_TO_CODE = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    lowered = cleaned.lower()
    if lowered.startswith("https://doi.org/"):
        cleaned = cleaned[16:]
    elif lowered.startswith("http://doi.org/"):
        cleaned = cleaned[15:]
    elif lowered.startswith("doi:"):
        cleaned = cleaned[4:].strip()
    cleaned = cleaned.strip().lower()
    return cleaned or None


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def _normalize_author_list(values: list[str]) -> set[str]:
    return {normalize_title(value) for value in values if normalize_title(value)}


def _title_year_match(result: ResultRecord, candidate_title: str | None, candidate_year: int | None) -> bool:
    if normalize_title(result.title) != normalize_title(candidate_title):
        return False
    if result.year is None or candidate_year is None:
        return False
    return result.year == candidate_year


def _title_authors_year_match(
    result: ResultRecord,
    candidate_title: str | None,
    candidate_authors: list[str],
    candidate_year: int | None,
) -> bool:
    if not _title_year_match(result, candidate_title, candidate_year):
        return False
    if not result.authors or not candidate_authors:
        return False
    return bool(_normalize_author_list(result.authors) & _normalize_author_list(candidate_authors))


class EnrichmentResolver(Protocol):
    """Protocol for enrichment providers."""

    provider: EnrichmentProvider

    def enrich(self, result: ResultRecord) -> EnrichmentRecord:
        """Resolve and normalize enrichment for a result."""


@dataclass(slots=True)
class EnrichmentAttemptInfo:
    """Structured provider-attempt diagnostics for artifact writing."""

    request: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None
    raw_payload: dict[str, Any] | None = None
    resolution_source: str = "unresolved"
    cache_key: str | None = None
    match_strategy: EnrichmentMatchStrategy | None = None
    message: str | None = None
    failure_kind: str | None = None
    status_code: int | None = None
    auth_fallback_used: bool = False
    endpoint: str | None = None
    response_body: str | None = None


@dataclass(slots=True)
class BaseEnrichmentProvider:
    """Base functionality shared by provider resolvers."""

    repository: Repository
    provider: EnrichmentProvider
    settings: ProviderSettings
    http_client: JsonHttpClient | None = None
    artifacts: RunArtifactsWriter | None = None
    result_ordinals: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.http_client is None:
            self.http_client = JsonHttpClient(
                timeout_seconds=self.settings.timeout_seconds,
                max_retries=self.settings.max_retries,
                rate_limit_seconds=self.settings.rate_limit_seconds,
            )

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def skipped_record(self, result: ResultRecord, message: str) -> EnrichmentRecord:
        return EnrichmentRecord(
            result_record_id=result.id,
            provider=self.provider,
            provider_record_id=f"{self.provider.value}:skipped",
            status=ExecutionStatus.SKIPPED,
            error_message=message,
        )

    def failed_record(self, result: ResultRecord, message: str) -> EnrichmentRecord:
        return EnrichmentRecord(
            result_record_id=result.id,
            provider=self.provider,
            provider_record_id=f"{self.provider.value}:failed",
            status=ExecutionStatus.FAILED,
            error_message=message,
        )

    def get_cached_payload(self, cache_key: str) -> dict[str, Any] | None:
        return self.repository.get_cache_payload(self.provider.value, cache_key)

    def set_cached_payload(self, cache_key: str, payload: dict[str, Any]) -> None:
        ttl = max(0, self.settings.cache_ttl_seconds)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl) if ttl else None
        self.repository.set_cache_payload(self.provider.value, cache_key, payload, expiry)

    def write_attempt_start(
        self,
        *,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
        message: str,
    ) -> None:
        self._write_attempt_artifact(
            result=result,
            attempt=attempt,
            status=ExecutionStatus.RUNNING,
            normalized_record=None,
            message=message,
        )

    def write_attempt_result(
        self,
        *,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
        normalized_record: EnrichmentRecord,
        message: str | None = None,
    ) -> None:
        self._write_attempt_artifact(
            result=result,
            attempt=attempt,
            status=normalized_record.status,
            normalized_record=normalized_record,
            message=message or normalized_record.error_message,
        )

    def _write_attempt_artifact(
        self,
        *,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
        status: ExecutionStatus,
        normalized_record: EnrichmentRecord | None,
        message: str | None,
    ) -> None:
        if self.artifacts is None or self.result_ordinals is None:
            return
        record_index = self.result_ordinals.get(str(result.id))
        if record_index is None:
            return

        payload = {
            "result_record_id": str(result.id),
            "record_index": record_index,
            "provider": self.provider.value,
            "attempt_index": 1,
            "status": status.value,
            "resolution_source": attempt.resolution_source,
            "cache_key": attempt.cache_key,
            "match_strategy": (
                normalized_record.match_strategy.value
                if normalized_record is not None and normalized_record.match_strategy is not None
                else attempt.match_strategy.value if attempt.match_strategy is not None else None
            ),
            "message": message,
            "failure_kind": attempt.failure_kind,
            "status_code": attempt.status_code,
            "auth_fallback_used": attempt.auth_fallback_used,
            "endpoint": attempt.endpoint,
            "response_body": attempt.response_body,
            "request": attempt.request,
            "raw_response": attempt.raw_response,
            "raw_payload": attempt.raw_payload,
            "result_context": {
                "result_record_id": str(result.id),
                "title": result.title,
                "doi": result.doi,
                "year": result.year,
                "source_name": result.source_name,
                "model_name": result.model_name,
            },
            "normalized_record": (
                normalized_record.model_dump(mode="json")
                if normalized_record is not None
                else None
            ),
        }
        self.artifacts.write_enrichment_attempt(
            record_index=record_index,
            provider_name=self.provider.value,
            attempt_index=1,
            payload=payload,
        )
        if status == ExecutionStatus.FAILED:
            self.artifacts.append_error(
                stage="enrichment",
                message=message or "Provider attempt failed",
                provider=self.provider.value,
                result_record_id=str(result.id),
                failure_kind=attempt.failure_kind,
                status_code=attempt.status_code,
                endpoint=attempt.endpoint,
                response_body=attempt.response_body,
                auth_fallback_used=attempt.auth_fallback_used,
            )
        elif status in {ExecutionStatus.COMPLETED, ExecutionStatus.SKIPPED, ExecutionStatus.PARTIAL}:
            self.artifacts.append_event(
                stage="enrichment",
                message=message or "Provider attempt completed",
                provider=self.provider.value,
                result_record_id=str(result.id),
                status=status.value,
            )


@dataclass(slots=True)
class OpenAlexEnrichmentProvider(BaseEnrichmentProvider):
    """Provider using OpenAlex lookups or direct payload reuse."""

    client: OpenAlexClient | None = None

    def __post_init__(self) -> None:
        BaseEnrichmentProvider.__post_init__(self)
        if self.client is None:
            self.client = OpenAlexClient.from_settings()

    def enrich(self, result: ResultRecord) -> EnrichmentRecord:
        attempt = EnrichmentAttemptInfo()
        if not self.enabled:
            attempt.resolution_source = "disabled"
            record = self.skipped_record(result, "OpenAlex enrichment disabled")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record

        try:
            payload, match_strategy = self._resolve_payload(result, attempt)
        except OpenAlexClientError as exc:
            record = self.failed_record(result, str(exc))
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record

        if payload is None:
            record = self.skipped_record(result, "OpenAlex did not match the record")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record

        record = map_openalex_payload_to_enrichment(
            result=result,
            payload=payload,
            match_strategy=match_strategy,
        )
        if record is None:
            record = self.skipped_record(result, "OpenAlex payload could not be normalized")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        attempt.match_strategy = match_strategy
        attempt.raw_payload = payload
        self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
        return record

    def _resolve_payload(
        self,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
    ) -> tuple[dict[str, Any] | None, EnrichmentMatchStrategy]:
        if result.source_name == EnrichmentProvider.OPENALEX.value and result.raw_payload:
            attempt.resolution_source = "source_payload_reuse"
            attempt.raw_payload = dict(result.raw_payload)
            attempt.message = "Reused scholarly source payload"
            return dict(result.raw_payload), EnrichmentMatchStrategy.SOURCE_IDENTIFIER

        normalized_doi = normalize_doi(result.doi)
        if normalized_doi:
            cache_key = f"doi:{normalized_doi}"
            cached = self.get_cached_payload(cache_key)
            if cached is not None:
                attempt.resolution_source = "cache"
                attempt.cache_key = cache_key
                attempt.raw_response = {"cache_hit": True, "payload": cached}
                attempt.raw_payload = cached
                return cached, EnrichmentMatchStrategy.DOI
            request = self.client.build_lookup_by_doi_request(normalized_doi)
            attempt.request = asdict(request)
            attempt.resolution_source = "network"
            attempt.cache_key = cache_key
            self.write_attempt_start(
                result=result,
                attempt=attempt,
                message="Looking up OpenAlex by DOI",
            )
            payload, raw_response = self.client.lookup_by_doi(
                normalized_doi,
                request=request,
                include_raw=True,
            )
            attempt.raw_response = raw_response
            attempt.raw_payload = payload
            if payload is not None:
                self.set_cached_payload(cache_key, payload)
                return payload, EnrichmentMatchStrategy.DOI

        cache_key = f"title:{normalize_title(result.title)}:{result.year or 'na'}"
        cached = self.get_cached_payload(cache_key)
        if cached is not None:
            attempt.resolution_source = "cache"
            attempt.cache_key = cache_key
            attempt.raw_response = {"cache_hit": True, "payload": cached}
            candidates = [cached]
        else:
            request = self.client.build_search_by_title_request(title=result.title, per_page=5)
            attempt.request = asdict(request)
            attempt.resolution_source = "network"
            attempt.cache_key = cache_key
            self.write_attempt_start(
                result=result,
                attempt=attempt,
                message="Searching OpenAlex by title",
            )
            candidates, raw_response = self.client.search_by_title(
                result.title,
                per_page=5,
                request=request,
                include_raw=True,
            )
            attempt.raw_response = raw_response
        if cached is None and candidates:
            self.set_cached_payload(cache_key, candidates[0])
        for candidate in candidates:
            if candidate is None:
                continue
            if _title_year_match(result, candidate.get("display_name"), candidate.get("publication_year")):
                attempt.raw_payload = candidate
                return candidate, EnrichmentMatchStrategy.TITLE_YEAR
            if _title_authors_year_match(
                result,
                candidate.get("display_name"),
                _openalex_authors(candidate.get("authorships")),
                candidate.get("publication_year"),
            ):
                attempt.raw_payload = candidate
                return candidate, EnrichmentMatchStrategy.TITLE_AUTHORS_YEAR
        return None, EnrichmentMatchStrategy.TITLE_YEAR


@dataclass(slots=True)
class SemanticScholarEnrichmentProvider(BaseEnrichmentProvider):
    """Provider using Semantic Scholar search."""

    client: SemanticScholarClient | None = None

    def __post_init__(self) -> None:
        BaseEnrichmentProvider.__post_init__(self)
        if self.client is None:
            self.client = SemanticScholarClient(
                base_url=self.settings.base_url or "https://api.semanticscholar.org/graph/v1",
                api_key=self.settings.api_key,
                http_client=self.http_client,
            )

    def enrich(self, result: ResultRecord) -> EnrichmentRecord:
        attempt = EnrichmentAttemptInfo()
        if not self.enabled:
            attempt.resolution_source = "disabled"
            record = self.skipped_record(result, "Semantic Scholar enrichment disabled")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if result.source_name == EnrichmentProvider.SEMANTIC_SCHOLAR.value and result.raw_payload:
            attempt.resolution_source = "source_payload_reuse"
            attempt.raw_payload = result.raw_payload
            attempt.message = "Reused scholarly source payload"
            record = _map_semantic_scholar_payload(result, result.raw_payload)
            attempt.match_strategy = record.match_strategy
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record

        try:
            payload = self._resolve_payload(result, attempt)
        except SemanticScholarClientError as exc:
            attempt.failure_kind = exc.failure_kind
            attempt.status_code = exc.status_code
            attempt.auth_fallback_used = exc.auth_fallback_attempted
            attempt.endpoint = exc.endpoint
            attempt.response_body = exc.response_body
            attempt.raw_response = exc.raw_response
            record = self.failed_record(result, str(exc))
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if payload is None:
            record = self.skipped_record(result, "Semantic Scholar did not match the record")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        record = _map_semantic_scholar_payload(result, payload)
        attempt.match_strategy = record.match_strategy
        attempt.raw_payload = payload
        self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
        return record

    def _resolve_payload(
        self,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
    ) -> dict[str, Any] | None:
        query = normalize_doi(result.doi) or result.title
        cache_key = f"search:{normalize_title(query)}:{result.year or 'na'}"
        cached = self.get_cached_payload(cache_key)
        if cached is not None:
            attempt.resolution_source = "cache"
            attempt.cache_key = cache_key
            attempt.raw_response = {"cache_hit": True, "payload": cached}
            attempt.raw_payload = cached
            return cached

        request = self.client.build_search_request(query_text=query, per_page=5)
        attempt.request = asdict(request)
        attempt.resolution_source = "network"
        attempt.cache_key = cache_key
        self.write_attempt_start(
            result=result,
            attempt=attempt,
            message="Searching Semantic Scholar",
        )
        candidates, response = self.client.search_papers(
            query,
            per_page=5,
            request=request,
            include_raw=True,
        )
        attempt.raw_response = response
        client_meta = response.get("_client_meta") if isinstance(response, dict) else None
        if isinstance(client_meta, dict):
            attempt.auth_fallback_used = bool(client_meta.get("auth_fallback_used"))
            if attempt.auth_fallback_used:
                attempt.message = "Configured API key rejected; retried Semantic Scholar without auth"

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if _match_payload_candidate(
                result,
                title=candidate.get("title"),
                authors=_semantic_authors(candidate.get("authors")),
                year=_coerce_year(candidate.get("year")),
                doi=_semantic_doi(candidate),
            ):
                self.set_cached_payload(cache_key, candidate)
                attempt.raw_payload = candidate
                return candidate
        return None


@dataclass(slots=True)
class CoreEnrichmentProvider(BaseEnrichmentProvider):
    """Provider using CORE v3 search."""

    def enrich(self, result: ResultRecord) -> EnrichmentRecord:
        attempt = EnrichmentAttemptInfo()
        if not self.enabled:
            attempt.resolution_source = "disabled"
            record = self.skipped_record(result, "CORE enrichment disabled")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if not self.settings.api_key:
            attempt.resolution_source = "unconfigured"
            record = self.skipped_record(result, "CORE credentials not configured")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if result.source_name == EnrichmentProvider.CORE.value and result.raw_payload:
            attempt.resolution_source = "source_payload_reuse"
            attempt.raw_payload = result.raw_payload
            attempt.message = "Reused scholarly source payload"
            record = _map_core_payload(result, result.raw_payload)
            attempt.match_strategy = record.match_strategy
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record

        try:
            payload = self._resolve_payload(result, attempt)
        except HttpClientError as exc:
            record = self.failed_record(result, str(exc))
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if payload is None:
            record = self.skipped_record(result, "CORE did not match the record")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        record = _map_core_payload(result, payload)
        attempt.match_strategy = record.match_strategy
        attempt.raw_payload = payload
        self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
        return record

    def _resolve_payload(
        self,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
    ) -> dict[str, Any] | None:
        base_url = (self.settings.base_url or "https://api.core.ac.uk/v3").rstrip("/")
        cache_key = f"search:{normalize_doi(result.doi) or normalize_title(result.title)}:{result.year or 'na'}"
        cached = self.get_cached_payload(cache_key)
        if cached is not None:
            attempt.resolution_source = "cache"
            attempt.cache_key = cache_key
            attempt.raw_response = {"cache_hit": True, "payload": cached}
            attempt.raw_payload = cached
            return cached

        request_headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        request_params = {
            "q": normalize_doi(result.doi) or result.title,
            "limit": 5,
        }
        attempt.request = {
            "method": "GET",
            "url": f"{base_url}/search/works",
            "params": request_params,
            "headers": request_headers,
        }
        attempt.resolution_source = "network"
        attempt.cache_key = cache_key
        self.write_attempt_start(
            result=result,
            attempt=attempt,
            message="Searching CORE",
        )
        response = self.http_client.request_json(
            method="GET",
            url=f"{base_url}/search/works",
            params=request_params,
            headers=request_headers,
        )
        attempt.raw_response = response

        candidates = response.get("results") or response.get("data")
        if not isinstance(candidates, list):
            return None
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if _match_payload_candidate(
                result,
                title=candidate.get("title"),
                authors=_core_authors(candidate),
                year=_coerce_year(candidate.get("year") or candidate.get("publishedDate")),
                doi=_core_doi(candidate),
            ):
                self.set_cached_payload(cache_key, candidate)
                attempt.raw_payload = candidate
                return candidate
        return None


@dataclass(slots=True)
class ScopusEnrichmentProvider(BaseEnrichmentProvider):
    """Provider using Elsevier Scopus search."""

    def enrich(self, result: ResultRecord) -> EnrichmentRecord:
        attempt = EnrichmentAttemptInfo()
        if not self.enabled:
            attempt.resolution_source = "disabled"
            record = self.skipped_record(result, "Scopus enrichment disabled")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if not self.settings.api_key:
            attempt.resolution_source = "unconfigured"
            record = self.skipped_record(result, "Scopus credentials not configured")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if result.source_name == EnrichmentProvider.SCOPUS.value and result.raw_payload:
            attempt.resolution_source = "source_payload_reuse"
            attempt.raw_payload = result.raw_payload
            attempt.message = "Reused scholarly source payload"
            record = _map_scopus_payload(result, result.raw_payload)
            attempt.match_strategy = record.match_strategy
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record

        try:
            payload = self._resolve_payload(result, attempt)
        except HttpClientError as exc:
            record = self.failed_record(result, str(exc))
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        if payload is None:
            record = self.skipped_record(result, "Scopus did not match the record")
            self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
            return record
        record = _map_scopus_payload(result, payload)
        attempt.match_strategy = record.match_strategy
        attempt.raw_payload = payload
        self.write_attempt_result(result=result, attempt=attempt, normalized_record=record)
        return record

    def _resolve_payload(
        self,
        result: ResultRecord,
        attempt: EnrichmentAttemptInfo,
    ) -> dict[str, Any] | None:
        base_url = (self.settings.base_url or "https://api.elsevier.com").rstrip("/")
        headers = {"X-ELS-APIKey": self.settings.api_key}
        if inst_token := self.settings.extra_headers.get("X-ELS-Insttoken"):
            headers["X-ELS-Insttoken"] = inst_token

        query = f'DOI("{normalize_doi(result.doi)}")' if normalize_doi(result.doi) else result.title
        cache_key = f"search:{normalize_title(query)}:{result.year or 'na'}"
        cached = self.get_cached_payload(cache_key)
        if cached is not None:
            attempt.resolution_source = "cache"
            attempt.cache_key = cache_key
            attempt.raw_response = {"cache_hit": True, "payload": cached}
            attempt.raw_payload = cached
            return cached

        request_params = {
            "query": query,
            "count": 5,
        }
        attempt.request = {
            "method": "GET",
            "url": f"{base_url}/content/search/scopus",
            "params": request_params,
            "headers": headers,
        }
        attempt.resolution_source = "network"
        attempt.cache_key = cache_key
        self.write_attempt_start(
            result=result,
            attempt=attempt,
            message="Searching Scopus",
        )
        response = self.http_client.request_json(
            method="GET",
            url=f"{base_url}/content/search/scopus",
            params=request_params,
            headers=headers,
        )
        attempt.raw_response = response

        entries = response.get("search-results", {}).get("entry")
        if not isinstance(entries, list):
            return None
        for candidate in entries:
            if not isinstance(candidate, dict):
                continue
            if _match_payload_candidate(
                result,
                title=candidate.get("dc:title"),
                authors=_scopus_authors(candidate),
                year=_coerce_year(candidate.get("prism:coverDate")),
                doi=normalize_doi(candidate.get("prism:doi")),
            ):
                self.set_cached_payload(cache_key, candidate)
                attempt.raw_payload = candidate
                return candidate
        return None


def build_enrichment_providers(
    repository: Repository,
    *,
    artifacts: RunArtifactsWriter | None = None,
    result_ordinals: dict[str, int] | None = None,
) -> list[EnrichmentResolver]:
    """Create the configured provider chain in precedence order."""

    settings = get_settings()
    providers: dict[str, EnrichmentResolver] = {
        EnrichmentProvider.OPENALEX.value: OpenAlexEnrichmentProvider(
            repository=repository,
            provider=EnrichmentProvider.OPENALEX,
            settings=settings.openalex,
            artifacts=artifacts,
            result_ordinals=result_ordinals,
        ),
        EnrichmentProvider.SEMANTIC_SCHOLAR.value: SemanticScholarEnrichmentProvider(
            repository=repository,
            provider=EnrichmentProvider.SEMANTIC_SCHOLAR,
            settings=settings.semantic_scholar,
            artifacts=artifacts,
            result_ordinals=result_ordinals,
        ),
        EnrichmentProvider.SCOPUS.value: ScopusEnrichmentProvider(
            repository=repository,
            provider=EnrichmentProvider.SCOPUS,
            settings=settings.scopus,
            artifacts=artifacts,
            result_ordinals=result_ordinals,
        ),
        EnrichmentProvider.CORE.value: CoreEnrichmentProvider(
            repository=repository,
            provider=EnrichmentProvider.CORE,
            settings=settings.core,
            artifacts=artifacts,
            result_ordinals=result_ordinals,
        ),
    }
    return [
        providers[name]
        for name in settings.enrichment_provider_order
        if name in providers
    ]


def _match_payload_candidate(
    result: ResultRecord,
    *,
    title: str | None,
    authors: list[str],
    year: int | None,
    doi: str | None,
) -> bool:
    result_doi = normalize_doi(result.doi)
    if result_doi and doi and result_doi == doi:
        return True
    if _title_year_match(result, title, year):
        return True
    return _title_authors_year_match(result, title, authors, year)


def _openalex_authors(authorships: Any) -> list[str]:
    if not isinstance(authorships, list):
        return []
    authors: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict):
            name = author.get("display_name")
            if isinstance(name, str) and name.strip():
                authors.append(name.strip())
    return authors


def _semantic_authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            authors.append(name.strip())
    return authors


def _core_authors(payload: dict[str, Any]) -> list[str]:
    authors = payload.get("authors") or payload.get("author")
    if isinstance(authors, list):
        output: list[str] = []
        for item in authors:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    output.append(name.strip())
            elif isinstance(item, str) and item.strip():
                output.append(item.strip())
        return output
    if isinstance(authors, str) and authors.strip():
        return [authors.strip()]
    return []


def _scopus_authors(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("author")
    if isinstance(raw, list):
        authors: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = item.get("authname") or item.get("ce:indexed-name")
                if isinstance(name, str) and name.strip():
                    authors.append(name.strip())
        return authors
    return []


def _semantic_doi(payload: dict[str, Any]) -> str | None:
    external_ids = payload.get("externalIds")
    if not isinstance(external_ids, dict):
        return None
    return normalize_doi(external_ids.get("DOI"))


def _core_doi(payload: dict[str, Any]) -> str | None:
    return normalize_doi(payload.get("doi"))


def _coerce_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) >= 4:
            try:
                return int(digits[:4])
            except ValueError:
                return None
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None
    return None


def _map_semantic_scholar_payload(result: ResultRecord, payload: dict[str, Any]) -> EnrichmentRecord:
    external_ids = payload.get("externalIds") if isinstance(payload.get("externalIds"), dict) else {}
    pdf = payload.get("openAccessPdf") if isinstance(payload.get("openAccessPdf"), dict) else {}
    journal = payload.get("journal") if isinstance(payload.get("journal"), dict) else {}
    publication_venue = (
        payload.get("publicationVenue") if isinstance(payload.get("publicationVenue"), dict) else {}
    )
    fields = payload.get("s2FieldsOfStudy") if isinstance(payload.get("s2FieldsOfStudy"), list) else []
    subjects = payload.get("fieldsOfStudy") if isinstance(payload.get("fieldsOfStudy"), list) else []

    return EnrichmentRecord(
        result_record_id=result.id,
        provider=EnrichmentProvider.SEMANTIC_SCHOLAR,
        provider_record_id=str(payload.get("paperId") or "semantic_scholar"),
        match_strategy=_provider_match_strategy(result, doi=_semantic_doi(payload), title=payload.get("title"), authors=_semantic_authors(payload.get("authors")), year=_coerce_year(payload.get("year"))),
        external_ids={
            key.lower(): value
            for key, value in external_ids.items()
            if isinstance(key, str) and isinstance(value, str)
        },
        source_ids={"semantic_scholar": str(payload.get("paperId") or "")},
        doi=_semantic_doi(payload),
        title=_safe_text(payload.get("title")),
        abstract=_safe_text(payload.get("abstract")),
        authors=_semantic_authors(payload.get("authors")),
        publication_year=_coerce_year(payload.get("year")),
        language=_normalize_language_value(payload.get("language"), result.language),
        is_open_access=payload.get("isOpenAccess") if isinstance(payload.get("isOpenAccess"), bool) else None,
        citation_count=payload.get("citationCount") if isinstance(payload.get("citationCount"), int) else None,
        publisher=_safe_text(journal.get("publisher"), publication_venue.get("publisher")),
        venue=_safe_text(publication_venue.get("name"), journal.get("name"), payload.get("venue")),
        fields_of_study=[str(item.get("category")).strip() for item in fields if isinstance(item, dict) and str(item.get("category")).strip()],
        subject_areas=[str(item).strip() for item in subjects if isinstance(item, str) and item.strip()],
        urls=[value for value in [_safe_text(payload.get("url")), _safe_text(pdf.get("url"))] if value],
        landing_page_url=_safe_text(payload.get("url")),
        pdf_url=_safe_text(pdf.get("url")),
        raw_payload=payload,
    )


def _map_core_payload(result: ResultRecord, payload: dict[str, Any]) -> EnrichmentRecord:
    return EnrichmentRecord(
        result_record_id=result.id,
        provider=EnrichmentProvider.CORE,
        provider_record_id=str(payload.get("id") or payload.get("coreId") or "core"),
        match_strategy=_provider_match_strategy(result, doi=_core_doi(payload), title=payload.get("title"), authors=_core_authors(payload), year=_coerce_year(payload.get("year") or payload.get("publishedDate"))),
        external_ids={"doi": normalize_doi(payload.get("doi")) or ""} if normalize_doi(payload.get("doi")) else {},
        source_ids={"core": str(payload.get("id") or payload.get("coreId") or "")},
        doi=_core_doi(payload),
        title=_safe_text(payload.get("title")),
        abstract=_safe_text(payload.get("abstract")),
        authors=_core_authors(payload),
        affiliations=_core_affiliations(payload),
        publication_year=_coerce_year(payload.get("year") or payload.get("publishedDate")),
        language=_normalize_language_value(payload.get("language")),
        is_open_access=_core_oa_flag(payload),
        citation_count=payload.get("citationCount") if isinstance(payload.get("citationCount"), int) else None,
        publisher=_safe_text(payload.get("publisher")),
        venue=_core_venue(payload),
        fields_of_study=_core_subjects(payload),
        subject_areas=_core_subjects(payload),
        urls=[value for value in [_safe_text(payload.get("url")), _safe_text(payload.get("downloadUrl"))] if value],
        landing_page_url=_safe_text(payload.get("url")),
        pdf_url=_safe_text(payload.get("downloadUrl")),
        raw_payload=payload,
    )


def _map_scopus_payload(result: ResultRecord, payload: dict[str, Any]) -> EnrichmentRecord:
    authors = _scopus_authors(payload)
    doi = normalize_doi(payload.get("prism:doi"))
    scopus_id = str(payload.get("dc:identifier") or payload.get("eid") or "scopus")
    return EnrichmentRecord(
        result_record_id=result.id,
        provider=EnrichmentProvider.SCOPUS,
        provider_record_id=scopus_id,
        match_strategy=_provider_match_strategy(result, doi=doi, title=payload.get("dc:title"), authors=authors, year=_coerce_year(payload.get("prism:coverDate"))),
        external_ids={"doi": doi} if doi else {},
        source_ids={"scopus": scopus_id},
        doi=doi,
        title=_safe_text(payload.get("dc:title")),
        authors=authors,
        publication_year=_coerce_year(payload.get("prism:coverDate")),
        language=_normalize_language_value(payload.get("prism:language"), payload.get("language")),
        is_open_access=_scopus_oa_flag(payload),
        citation_count=_coerce_int(payload.get("citedby-count")),
        publisher=_safe_text(payload.get("publishername"), payload.get("dc:publisher")),
        venue=_safe_text(payload.get("prism:publicationName")),
        country_primary=_country_primary_from_names(_scopus_affiliation_countries(payload)),
        country_dominant=_country_dominant_from_names(_scopus_affiliation_countries(payload)),
        countries=_scopus_affiliation_countries(payload),
        urls=[value for value in [_safe_text(payload.get("prism:url"))] if value],
        landing_page_url=_safe_text(payload.get("prism:url")),
        raw_payload=payload,
    )


def _provider_match_strategy(
    result: ResultRecord,
    *,
    doi: str | None,
    title: str | None,
    authors: list[str],
    year: int | None,
) -> EnrichmentMatchStrategy:
    result_doi = normalize_doi(result.doi)
    if result_doi and doi and result_doi == doi:
        return EnrichmentMatchStrategy.DOI
    if _title_authors_year_match(result, title, authors, year):
        return EnrichmentMatchStrategy.TITLE_AUTHORS_YEAR
    return EnrichmentMatchStrategy.TITLE_YEAR


def _safe_text(*values: Any) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
            cleaned = cleaned[1:-1].strip()
        if not cleaned or cleaned.lower() in _UNKNOWN_TEXT_MARKERS:
            continue
        if cleaned:
            return cleaned
    return None


def _normalize_language_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, dict):
            code = _safe_text(value.get("code"))
            if code:
                return code.lower()
            name = _safe_text(value.get("name"))
            if name:
                lowered_name = name.lower()
                return _LANGUAGE_NAME_TO_CODE.get(lowered_name, lowered_name)
        text = _safe_text(value)
        if text is None:
            continue
        lowered = text.lower()
        if lowered in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[lowered]
        if len(lowered) == 2 and lowered.isalpha():
            return lowered
        return lowered
    return None


def _core_venue(payload: dict[str, Any]) -> str | None:
    journals = payload.get("journals")
    if isinstance(journals, list):
        for journal in journals:
            if not isinstance(journal, dict):
                continue
            title = _safe_text(journal.get("title"))
            if title is not None:
                return title
    return _safe_text(payload.get("journal"), payload.get("venue"))


def _scopus_oa_flag(payload: dict[str, Any]) -> bool | None:
    for key in ("openaccessFlag", "openaccess"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if cleaned in {"1", "true", "yes", "open"}:
                return True
            if cleaned in {"0", "false", "no", "closed"}:
                return False
    return None


def _scopus_affiliation_countries(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("affiliation")
    if not isinstance(raw, list):
        return []
    countries: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        country = _safe_text(item.get("affiliation-country"))
        if country and country not in seen:
            seen.add(country)
            countries.append(country)
    return countries


def _country_primary_from_names(countries: list[str]) -> str | None:
    if not countries:
        return None
    if len(countries) == 1:
        return countries[0]
    return "MULTI"


def _country_dominant_from_names(countries: list[str]) -> str | None:
    if not countries:
        return None
    return countries[0]


def _core_affiliations(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("institutions")
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                output.append(name.strip())
    return output


def _core_subjects(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("subjects")
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _core_oa_flag(payload: dict[str, Any]) -> bool | None:
    for key in ("isOpenAccess", "downloadUrl"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip():
            return True
    return None
