"""Low-level client for OpenAlex search and work lookups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.adapters.http import HttpClientError, JsonHttpClient
from backend.config import get_settings


OPENALEX_SELECT_FIELDS = (
    "id",
    "display_name",
    "title",
    "doi",
    "publication_year",
    "language",
    "abstract_inverted_index",
    "open_access",
    "cited_by_count",
    "type",
    "concepts",
    "authorships",
    "primary_location",
    "locations",
    "ids",
)


class OpenAlexClientError(RuntimeError):
    """Raised when an OpenAlex request or response cannot be handled."""


@dataclass(slots=True)
class OpenAlexRequest:
    """Serializable OpenAlex request envelope."""

    method: str
    url: str
    params: dict[str, Any]
    headers: dict[str, str]


@dataclass(slots=True)
class OpenAlexClient:
    """Minimal synchronous client for the OpenAlex API."""

    base_url: str
    api_key: str | None = None
    http_client: JsonHttpClient | None = None

    @classmethod
    def from_settings(cls) -> "OpenAlexClient":
        settings = get_settings()
        return cls(
            base_url=settings.openalex.base_url or "https://api.openalex.org",
            api_key=settings.openalex.api_key,
            http_client=JsonHttpClient(
                timeout_seconds=settings.openalex.timeout_seconds,
                max_retries=settings.openalex.max_retries,
                rate_limit_seconds=settings.openalex.rate_limit_seconds,
            ),
        )

    def search_works(
        self,
        query_text: str,
        per_page: int,
        *,
        request: OpenAlexRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search OpenAlex works for one query string."""

        request = request or self.build_search_works_request(query_text=query_text, per_page=per_page)
        return self._get_results(request, include_raw=include_raw)

    def lookup_by_doi(
        self,
        doi: str,
        *,
        request: OpenAlexRequest | None = None,
        include_raw: bool = False,
    ) -> dict[str, Any] | None | tuple[dict[str, Any] | None, dict[str, Any]]:
        """Look up one OpenAlex work by DOI when possible."""

        request = request or self.build_lookup_by_doi_request(doi)
        results = self._get_results(request, include_raw=include_raw)
        if include_raw:
            result_items, raw_payload = results
            return (result_items[0] if result_items else None, raw_payload)
        return results[0] if results else None

    def search_by_title(
        self,
        title: str,
        *,
        per_page: int = 5,
        request: OpenAlexRequest | None = None,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search OpenAlex by title-like text for enrichment fallback."""

        request = request or self.build_search_by_title_request(title=title, per_page=per_page)
        return self._get_results(request, include_raw=include_raw)

    def build_search_works_request(self, *, query_text: str, per_page: int) -> OpenAlexRequest:
        """Return the exact OpenAlex search request envelope."""

        params = {
            "search": query_text,
            "per_page": per_page,
            "select": ",".join(OPENALEX_SELECT_FIELDS),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return OpenAlexRequest(
            method="GET",
            url=f"{self.base_url.rstrip('/')}/works",
            params=params,
            headers={},
        )

    def build_lookup_by_doi_request(self, doi: str) -> OpenAlexRequest:
        """Return the exact OpenAlex DOI lookup request envelope."""

        normalized = doi.strip().lower()
        if normalized.startswith("https://doi.org/"):
            normalized = normalized.removeprefix("https://doi.org/")
        if normalized.startswith("http://doi.org/"):
            normalized = normalized.removeprefix("http://doi.org/")
        if normalized.startswith("doi:"):
            normalized = normalized[4:].strip()

        params = {
            "filter": f"doi:https://doi.org/{normalized}",
            "per_page": 1,
            "select": ",".join(OPENALEX_SELECT_FIELDS),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return OpenAlexRequest(
            method="GET",
            url=f"{self.base_url.rstrip('/')}/works",
            params=params,
            headers={},
        )

    def build_search_by_title_request(self, *, title: str, per_page: int = 5) -> OpenAlexRequest:
        """Return the exact OpenAlex title search request envelope."""

        params = {
            "search": title,
            "per_page": per_page,
            "select": ",".join(OPENALEX_SELECT_FIELDS),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return OpenAlexRequest(
            method="GET",
            url=f"{self.base_url.rstrip('/')}/works",
            params=params,
            headers={},
        )

    def _get_results(
        self,
        request: OpenAlexRequest,
        *,
        include_raw: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            payload = (self.http_client or JsonHttpClient()).request_json(
                method=request.method,
                url=request.url,
                params=request.params,
                headers=request.headers,
            )
        except HttpClientError as exc:
            raise OpenAlexClientError(str(exc)) from exc

        results = payload.get("results")
        if not isinstance(results, list):
            raise OpenAlexClientError("OpenAlex response did not include a valid results list")
        normalized_results = [result for result in results if isinstance(result, dict)]
        if include_raw:
            return normalized_results, payload
        return normalized_results
