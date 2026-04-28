"""Low-level clients for scholarly collection sources beyond OpenAlex."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.adapters.http import HttpClientError, JsonHttpClient
from backend.config import get_settings


class SemanticScholarClientError(RuntimeError):
    """Raised when a Semantic Scholar collection request fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        failure_kind: str | None = None,
        auth_fallback_attempted: bool = False,
        endpoint: str | None = None,
        response_body: str | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.failure_kind = failure_kind
        self.auth_fallback_attempted = auth_fallback_attempted
        self.endpoint = endpoint
        self.response_body = response_body
        self.raw_response = raw_response


class COREClientError(RuntimeError):
    """Raised when a CORE collection request fails."""


class ScopusClientError(RuntimeError):
    """Raised when a Scopus collection request fails."""


@dataclass(slots=True)
class ScholarlySearchRequest:
    """Serializable scholarly-search request envelope."""

    method: str
    url: str
    params: dict[str, Any]
    headers: dict[str, str]


@dataclass(slots=True)
class SemanticScholarClient:
    """Minimal synchronous client for Semantic Scholar paper search."""

    base_url: str
    api_key: str | None = None
    http_client: JsonHttpClient | None = None
    _api_key_rejected: bool = field(
        default=False,
        init=False,
        repr=False,
    )

    @classmethod
    def from_settings(cls) -> "SemanticScholarClient":
        settings = get_settings().semantic_scholar
        return cls(
            base_url=settings.base_url or "https://api.semanticscholar.org/graph/v1",
            api_key=settings.api_key,
            http_client=JsonHttpClient(
                timeout_seconds=settings.timeout_seconds,
                max_retries=settings.max_retries,
                rate_limit_seconds=settings.rate_limit_seconds,
            ),
        )

    def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
        fields = ",".join(
            [
                "paperId",
                "title",
                "abstract",
                "year",
                "url",
                "venue",
                "journal",
                "publicationVenue",
                "authors.name",
                "externalIds",
                "citationCount",
                "isOpenAccess",
                "openAccessPdf",
                "fieldsOfStudy",
                "s2FieldsOfStudy",
            ]
        )
        headers: dict[str, str] = {}
        if self.api_key and not self._api_key_rejected:
            headers["x-api-key"] = self.api_key
        return ScholarlySearchRequest(
            method="GET",
            url=f"{self.base_url.rstrip('/')}/paper/search",
            params={
                "query": query_text,
                "limit": per_page,
                "fields": fields,
            },
            headers=headers,
        )

    def search_papers(
        self,
        query_text: str,
        per_page: int,
        *,
        request: ScholarlySearchRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        request = request or self.build_search_request(query_text=query_text, per_page=per_page)
        if self._api_key_rejected and self._request_uses_api_key(request):
            request = self._without_api_key(request)
        try:
            payload = self._request_json(request)
        except HttpClientError as exc:
            error = self._classify_error(exc)
            if self._is_auth_error(exc) and self._request_uses_api_key(request):
                public_request = self._without_api_key(request)
                self._api_key_rejected = True
                try:
                    payload = self._request_json(public_request)
                except HttpClientError as public_exc:
                    public_failure_kind = _semantic_failure_kind(public_exc)
                    public_response_body = _response_excerpt(public_exc.response_text)
                    error = SemanticScholarClientError(
                        _semantic_error_message(
                            auth_api_key_rejected=True,
                            endpoint=public_request.url,
                            status_code=public_exc.status_code or error.status_code,
                            failure_kind=public_failure_kind,
                            response_body=public_response_body,
                        ),
                        status_code=public_exc.status_code or error.status_code,
                        failure_kind=public_failure_kind,
                        auth_fallback_attempted=True,
                        endpoint=public_request.url,
                        response_body=public_response_body,
                        raw_response={
                            "provider": "semantic_scholar",
                            "endpoint": public_request.url,
                            "status_code": public_exc.status_code or error.status_code,
                            "failure_kind": public_failure_kind,
                            "response_body": public_response_body,
                            "auth_fallback_attempted": True,
                            "attempts": [
                                _serialize_http_error_attempt(request, exc),
                                _serialize_http_error_attempt(public_request, public_exc),
                            ],
                        },
                    )
                    raise error from public_exc
                else:
                    payload = {
                        **payload,
                        "_client_meta": {
                            "auth_fallback_used": True,
                            "api_key_rejected": True,
                        },
                    }
            else:
                raise error from exc

        data = payload.get("data")
        if data is None and payload.get("total") == 0:
            results: list[dict[str, Any]] = []
            if include_raw:
                return results, payload
            return results
        if not isinstance(data, list):
            keys = ", ".join(sorted(str(key) for key in payload.keys()))
            raise SemanticScholarClientError(
                f"Semantic Scholar response did not include a valid data list (payload keys: {keys})",
                failure_kind="invalid_response",
                endpoint=request.url,
                response_body=_response_excerpt(json.dumps(payload, sort_keys=True)),
                raw_response={
                    "provider": "semantic_scholar",
                    "endpoint": request.url,
                    "failure_kind": "invalid_response",
                    "response_json": payload,
                },
            )
        results = [item for item in data if isinstance(item, dict)]
        if include_raw:
            return results, payload
        return results

    def _request_json(self, request: ScholarlySearchRequest) -> dict[str, Any]:
        return (self.http_client or JsonHttpClient()).request_json(
            method=request.method,
            url=request.url,
            params=request.params,
            headers=request.headers,
        )

    def _classify_error(self, exc: HttpClientError) -> SemanticScholarClientError:
        failure_kind = _semantic_failure_kind(exc)
        response_body = _response_excerpt(exc.response_text)
        return SemanticScholarClientError(
            _semantic_error_message(
                auth_api_key_rejected=False,
                endpoint=exc.url,
                status_code=exc.status_code,
                failure_kind=failure_kind,
                response_body=response_body,
            ),
            status_code=exc.status_code,
            failure_kind=failure_kind,
            endpoint=exc.url,
            response_body=response_body,
            raw_response={
                "provider": "semantic_scholar",
                "endpoint": exc.url,
                "status_code": exc.status_code,
                "failure_kind": failure_kind,
                "response_body": response_body,
            },
        )

    @staticmethod
    def _request_uses_api_key(request: ScholarlySearchRequest) -> bool:
        return any(key.lower() == "x-api-key" for key in request.headers)

    @staticmethod
    def _without_api_key(request: ScholarlySearchRequest) -> ScholarlySearchRequest:
        return ScholarlySearchRequest(
            method=request.method,
            url=request.url,
            params=dict(request.params),
            headers={
                key: value
                for key, value in request.headers.items()
                if key.lower() != "x-api-key"
            },
        )

    @staticmethod
    def _is_auth_error(exc: HttpClientError) -> bool:
        return exc.status_code in {401, 403}


def _semantic_failure_kind(exc: HttpClientError) -> str | None:
    if exc.status_code == 401:
        return "unauthorized"
    if exc.status_code == 403:
        return "forbidden"
    if exc.status_code == 429:
        return "rate_limited"
    if exc.status_code is not None and 500 <= exc.status_code <= 599:
        return "upstream_error"
    if exc.status_code is None:
        return "network_error"
    return "request_error"


def _serialize_http_error_attempt(
    request: ScholarlySearchRequest,
    exc: HttpClientError,
) -> dict[str, Any]:
    return {
        "request": asdict(request),
        "status_code": exc.status_code,
        "failure_kind": _semantic_failure_kind(exc),
        "response_body": _response_excerpt(exc.response_text),
    }


def _response_excerpt(value: str | None, *, limit: int = 240) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _semantic_error_message(
    *,
    auth_api_key_rejected: bool,
    endpoint: str | None,
    status_code: int | None,
    failure_kind: str | None,
    response_body: str | None,
) -> str:
    prefix = (
        "Semantic Scholar rejected the configured SEMANTIC_SCHOLAR_API_KEY; "
        "unauthenticated retry failed"
        if auth_api_key_rejected
        else "Semantic Scholar request failed"
    )
    details: list[str] = []
    if endpoint:
        details.append(f"endpoint={endpoint}")
    if status_code is not None:
        details.append(f"status={status_code}")
    if failure_kind:
        details.append(f"kind={failure_kind}")
    if response_body:
        details.append(f"body={response_body}")
    if not details:
        return prefix
    return f"{prefix} ({', '.join(details)})"


@dataclass(slots=True)
class COREClient:
    """Minimal synchronous client for CORE search."""

    base_url: str
    api_key: str | None = None
    http_client: JsonHttpClient | None = None

    @classmethod
    def from_settings(cls) -> "COREClient":
        settings = get_settings().core
        return cls(
            base_url=settings.base_url or "https://api.core.ac.uk/v3",
            api_key=settings.api_key,
            http_client=JsonHttpClient(
                timeout_seconds=settings.timeout_seconds,
                max_retries=settings.max_retries,
                rate_limit_seconds=settings.rate_limit_seconds,
            ),
        )

    def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return ScholarlySearchRequest(
            method="GET",
            url=f"{self.base_url.rstrip('/')}/search/works",
            params={"q": query_text, "limit": per_page},
            headers=headers,
        )

    def search_works(
        self,
        query_text: str,
        per_page: int,
        *,
        request: ScholarlySearchRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        request = request or self.build_search_request(query_text=query_text, per_page=per_page)
        try:
            payload = (self.http_client or JsonHttpClient()).request_json(
                method=request.method,
                url=request.url,
                params=request.params,
                headers=request.headers,
            )
        except HttpClientError as exc:
            raise COREClientError(str(exc)) from exc

        results = payload.get("results") or payload.get("data")
        if not isinstance(results, list):
            raise COREClientError("CORE response did not include a valid results list")
        items = [item for item in results if isinstance(item, dict)]
        if include_raw:
            return items, payload
        return items


@dataclass(slots=True)
class ScopusClient:
    """Minimal synchronous client for Elsevier Scopus search."""

    base_url: str
    api_key: str | None = None
    inst_token: str | None = None
    http_client: JsonHttpClient | None = None

    @classmethod
    def from_settings(cls) -> "ScopusClient":
        settings = get_settings().scopus
        return cls(
            base_url=settings.base_url or "https://api.elsevier.com",
            api_key=settings.api_key,
            inst_token=settings.extra_headers.get("X-ELS-Insttoken") or None,
            http_client=JsonHttpClient(
                timeout_seconds=settings.timeout_seconds,
                max_retries=settings.max_retries,
                rate_limit_seconds=settings.rate_limit_seconds,
            ),
        )

    def build_search_request(self, *, query_text: str, per_page: int) -> ScholarlySearchRequest:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-ELS-APIKey"] = self.api_key
        if self.inst_token:
            headers["X-ELS-Insttoken"] = self.inst_token
        return ScholarlySearchRequest(
            method="GET",
            url=f"{self.base_url.rstrip('/')}/content/search/scopus",
            params={"query": query_text, "count": per_page},
            headers=headers,
        )

    def search_works(
        self,
        query_text: str,
        per_page: int,
        *,
        request: ScholarlySearchRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        request = request or self.build_search_request(query_text=query_text, per_page=per_page)
        try:
            payload = (self.http_client or JsonHttpClient()).request_json(
                method=request.method,
                url=request.url,
                params=request.params,
                headers=request.headers,
            )
        except HttpClientError as exc:
            raise ScopusClientError(str(exc)) from exc

        entries = payload.get("search-results", {}).get("entry")
        if not isinstance(entries, list):
            raise ScopusClientError("Scopus response did not include a valid entry list")
        results = [item for item in entries if isinstance(item, dict)]
        if include_raw:
            return results, payload
        return results
