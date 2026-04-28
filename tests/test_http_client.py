from __future__ import annotations

from backend.adapters.http import JsonHttpClient


def test_json_http_client_initializes_internal_rate_limit_state() -> None:
    client = JsonHttpClient(timeout_seconds=5.0, max_retries=1, rate_limit_seconds=0.1)

    assert client._last_request_at is None
