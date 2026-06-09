from __future__ import annotations

import httpx

from backend.adapters.http import JsonHttpClient


def test_json_http_client_initializes_internal_rate_limit_state() -> None:
    client = JsonHttpClient(timeout_seconds=5.0, max_retries=1, rate_limit_seconds=0.1)

    assert client._last_request_at is None


def test_json_http_client_uses_configured_timeout(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(**kwargs):
        seen.update(kwargs)
        request = httpx.Request(kwargs["method"], kwargs["url"])
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(httpx, "request", fake_request)

    payload = JsonHttpClient(timeout_seconds=3.5, max_retries=0).request_json(
        method="GET",
        url="https://example.test/items",
        params={"q": "x", "empty": None},
    )

    assert payload == {"ok": True}
    assert isinstance(seen["timeout"], httpx.Timeout)
    assert seen["params"] == {"q": "x"}


def test_json_http_client_max_retries_zero_makes_one_attempt(monkeypatch) -> None:
    calls = 0

    def fake_request(**kwargs):
        nonlocal calls
        calls += 1
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "request", fake_request)

    client = JsonHttpClient(timeout_seconds=1.0, max_retries=0)
    try:
        client.request_json(method="GET", url="https://example.test/items")
    except Exception as exc:
        assert "Timeout after 1s" in str(exc)

    assert calls == 1
