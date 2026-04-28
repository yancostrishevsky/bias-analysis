from __future__ import annotations

import pytest

from backend.adapters.http import HttpClientError
from backend.adapters.openrouter.client import OpenRouterClient, OpenRouterError


def test_openrouter_client_classifies_unavailable_model_404() -> None:
    class FakeHttpClient:
        def request_json(self, *, method, url, headers, payload):
            raise HttpClientError(
                'HTTP 404 for https://openrouter.ai/api/v1/chat/completions: '
                '{"error":{"message":"No endpoints found for anthropic/claude-3.5-sonnet.",'
                '"code":404},"user_id":"user_123"}'
            )

    client = OpenRouterClient(
        api_key="test-openrouter-key",
        base_url="https://openrouter.ai/api/v1",
        app_name="bias-analysis",
        http_client=FakeHttpClient(),
    )
    request = client.build_completion_request(
        model="anthropic/claude-3.5-sonnet",
        prompt="Return JSON only.\n\nQuery: artifact-backed test",
        max_tokens=32,
    )

    with pytest.raises(OpenRouterError) as exc_info:
        client.complete(
            model="anthropic/claude-3.5-sonnet",
            prompt="Return JSON only.\n\nQuery: artifact-backed test",
            max_tokens=32,
            request=request,
        )

    exc = exc_info.value
    assert exc.failure_kind == "model_unavailable"
    assert exc.status_code == 404
    assert exc.provider_error_code == "404"
    assert exc.response_payload == {
        "error": {
            "message": "No endpoints found for anthropic/claude-3.5-sonnet.",
            "code": 404,
        },
        "user_id": "user_123",
    }
    assert exc.should_skip_remaining_queries is True
