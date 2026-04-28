from __future__ import annotations

import pytest

from backend.adapters.http import HttpClientError
from backend.adapters.scholarly.client import (
    SemanticScholarClient,
    SemanticScholarClientError,
)


class SequenceHttpClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request_json(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
                "payload": dict(payload or {}),
            }
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_semantic_scholar_retries_without_api_key_after_forbidden_key() -> None:
    http_client = SequenceHttpClient(
        [
            HttpClientError(
                "HTTP 403 for https://api.semanticscholar.org/graph/v1/paper/search: {\"message\":\"Forbidden\"}",
                status_code=403,
                url="https://api.semanticscholar.org/graph/v1/paper/search",
                response_text='{"message":"Forbidden"}',
            ),
            {
                "data": [
                    {
                        "paperId": "S2-123",
                        "title": "Liquid biopsy in cancer diagnosis, staging, and treatment monitoring",
                    }
                ]
            },
            {
                "data": [
                    {
                        "paperId": "S2-456",
                        "title": "Follow-up public request",
                    }
                ]
            },
        ]
    )
    client = SemanticScholarClient(
        base_url="https://api.semanticscholar.org/graph/v1",
        api_key="bad-key",
        http_client=http_client,
    )

    request = client.build_search_request(query_text="10.1038/s41568-019-0214-z", per_page=5)
    results, raw_payload = client.search_papers(
        "10.1038/s41568-019-0214-z",
        per_page=5,
        request=request,
        include_raw=True,
    )

    assert len(results) == 1
    assert results[0]["paperId"] == "S2-123"
    assert len(http_client.calls) == 2
    assert http_client.calls[0]["headers"] == {"x-api-key": "bad-key"}
    assert http_client.calls[1]["headers"] == {}
    assert raw_payload["_client_meta"] == {
        "auth_fallback_used": True,
        "api_key_rejected": True,
    }

    second_request = client.build_search_request(query_text="another query", per_page=5)
    second_results = client.search_papers(
        "another query",
        per_page=5,
        request=second_request,
    )

    assert len(second_results) == 1
    assert second_results[0]["paperId"] == "S2-456"
    assert len(http_client.calls) == 3
    assert http_client.calls[2]["headers"] == {}


def test_semantic_scholar_rate_limit_error_keeps_context_and_allows_later_public_retry() -> None:
    http_client = SequenceHttpClient(
        [
            HttpClientError(
                "HTTP 403 for https://api.semanticscholar.org/graph/v1/paper/search: {\"message\":\"Forbidden\"}",
                status_code=403,
                url="https://api.semanticscholar.org/graph/v1/paper/search",
                response_text='{"message":"Forbidden"}',
            ),
            HttpClientError(
                "HTTP 429 for https://api.semanticscholar.org/graph/v1/paper/search: {\"message\":\"Too Many Requests\"}",
                status_code=429,
                url="https://api.semanticscholar.org/graph/v1/paper/search",
                response_text='{"message":"Too Many Requests"}',
            ),
            {
                "data": [
                    {
                        "paperId": "S2-789",
                        "title": "Recovered public request",
                    }
                ]
            },
        ]
    )
    client = SemanticScholarClient(
        base_url="https://api.semanticscholar.org/graph/v1",
        api_key="bad-key",
        http_client=http_client,
    )

    with pytest.raises(SemanticScholarClientError) as exc_info:
        client.search_papers("liquid biopsy cancer detection review", per_page=5)

    error = exc_info.value
    assert error.failure_kind == "rate_limited"
    assert error.status_code == 429
    assert error.auth_fallback_attempted is True
    assert error.endpoint == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert error.response_body == '{"message":"Too Many Requests"}'
    assert error.raw_response is not None
    assert error.raw_response["attempts"][0]["status_code"] == 403
    assert error.raw_response["attempts"][1]["status_code"] == 429
    assert "SEMANTIC_SCHOLAR_API_KEY" in str(error)
    assert len(http_client.calls) == 2

    second_request = client.build_search_request(query_text="another query", per_page=5)
    second_results = client.search_papers(
        "another query",
        per_page=5,
        request=second_request,
    )

    assert len(second_results) == 1
    assert second_results[0]["paperId"] == "S2-789"
    assert len(http_client.calls) == 3
    assert http_client.calls[2]["headers"] == {}


def test_semantic_scholar_invalid_response_includes_raw_payload_context() -> None:
    http_client = SequenceHttpClient(
        [
            {
                "message": "Too Many Requests",
                "code": "429",
            }
        ]
    )
    client = SemanticScholarClient(
        base_url="https://api.semanticscholar.org/graph/v1",
        http_client=http_client,
    )

    with pytest.raises(SemanticScholarClientError) as exc_info:
        client.search_papers("liquid biopsy cancer detection review", per_page=5)

    error = exc_info.value
    assert error.failure_kind == "invalid_response"
    assert error.endpoint == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert error.raw_response is not None
    assert error.raw_response["response_json"] == {
        "message": "Too Many Requests",
        "code": "429",
    }
    assert "valid data list" in str(error)
