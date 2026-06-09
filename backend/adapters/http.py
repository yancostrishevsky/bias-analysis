"""Small synchronous JSON HTTP client with retry and rate limiting."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class HttpClientError(RuntimeError):
    """Raised when an HTTP request cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
        response_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.response_text = response_text


@dataclass(slots=True)
class JsonHttpClient:
    """Minimal JSON-oriented HTTP client."""

    timeout_seconds: float = 20.0
    max_retries: int = 3
    rate_limit_seconds: float = 0.0
    user_agent: str = "bias-analysis/0.1"
    _last_request_at: float | None = field(default=None, init=False, repr=False)

    def request_json(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a JSON request with basic retry handling."""

        last_error: Exception | None = None
        attempts = max(0, self.max_retries) + 1
        for attempt in range(attempts):
            try:
                self._sleep_for_rate_limit()
                response = httpx.request(
                    method=method.upper(),
                    url=url,
                    params={
                        key: value
                        for key, value in (params or {}).items()
                        if value is not None
                    },
                    headers=self._build_headers(headers or {}, payload=payload),
                    json=payload,
                    timeout=httpx.Timeout(self.timeout_seconds),
                    follow_redirects=True,
                )
                if response.status_code >= 400:
                    body = response.text[:500]
                    if (
                        self._is_retryable_http_status(response.status_code)
                        and attempt < attempts - 1
                    ):
                        self._sleep_after_failure(
                            attempt=attempt,
                            retry_after=response.headers.get("Retry-After"),
                        )
                        last_error = HttpClientError(
                            f"HTTP {response.status_code} for {url}: {body or response.reason_phrase}",
                            status_code=response.status_code,
                            url=url,
                            response_text=body or response.reason_phrase,
                        )
                        continue
                    raise HttpClientError(
                        f"HTTP {response.status_code} for {url}: {body or response.reason_phrase}",
                        status_code=response.status_code,
                        url=url,
                        response_text=body or response.reason_phrase,
                    )
                return self._decode_json(response.text)
            except httpx.TimeoutException as exc:
                if attempt >= attempts - 1:
                    raise HttpClientError(
                        f"Timeout after {self.timeout_seconds:g}s for {url}",
                        url=url,
                    ) from exc
                self._sleep_after_failure(attempt=attempt, retry_after=None)
                last_error = exc
            except httpx.HTTPError as exc:
                if attempt >= attempts - 1:
                    raise HttpClientError(
                        f"Network error for {url}: {exc}",
                        url=url,
                    ) from exc
                self._sleep_after_failure(attempt=attempt, retry_after=None)
                last_error = exc
            except HttpClientError:
                raise
            except Exception as exc:  # pragma: no cover - defensive path
                if attempt >= attempts - 1:
                    raise HttpClientError(
                        f"Unexpected HTTP client error for {url}: {exc}",
                        url=url,
                    ) from exc
                self._sleep_after_failure(attempt=attempt, retry_after=None)
                last_error = exc

        if last_error is not None:  # pragma: no cover - loop already raises on final failure
            raise HttpClientError(str(last_error))
        raise HttpClientError(f"Request failed for {url}")

    def _build_headers(
        self,
        headers: dict[str, str],
        payload: dict[str, Any] | None,
    ) -> dict[str, str]:
        resolved_headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            **headers,
        }
        if payload is not None:
            resolved_headers.setdefault("Content-Type", "application/json")
        return resolved_headers

    def _decode_json(self, raw_body: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HttpClientError("Response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise HttpClientError("JSON response must be an object")
        return payload

    def _sleep_for_rate_limit(self) -> None:
        if self.rate_limit_seconds <= 0:
            self._last_request_at = time.monotonic()
            return

        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self.rate_limit_seconds - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _sleep_after_failure(self, *, attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                time.sleep(float(retry_after))
                return
            except ValueError:
                pass
        time.sleep(min(8.0, 0.75 * (2**attempt)))

    @staticmethod
    def _is_retryable_http_status(status_code: int) -> bool:
        return status_code in {408, 409, 425, 429} or 500 <= status_code <= 599
