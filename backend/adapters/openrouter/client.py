"""OpenRouter chat completions client."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from backend.adapters.http import HttpClientError, JsonHttpClient
from backend.config import get_settings


class OpenRouterError(RuntimeError):
    """Raised when an OpenRouter request fails."""

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        status_code: int | None = None,
        url: str | None = None,
        response_text: str | None = None,
        response_payload: dict[str, Any] | None = None,
        provider_error_code: str | None = None,
        failure_kind: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.status_code = status_code
        self.url = url
        self.response_text = response_text
        self.response_payload = response_payload
        self.provider_error_code = provider_error_code
        self.failure_kind = failure_kind
        self.latency_ms = latency_ms

    @property
    def is_model_unavailable(self) -> bool:
        return self.failure_kind == "model_unavailable"

    @property
    def should_skip_remaining_queries(self) -> bool:
        return self.status_code in {400, 401, 403, 404}


class OpenRouterModelDiscoveryError(RuntimeError):
    """Raised when the OpenRouter model discovery endpoint cannot be read."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


@dataclass(slots=True)
class OpenRouterRequest:
    """Serializable OpenRouter request envelope."""

    method: str
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]


@dataclass(slots=True)
class OpenRouterModelsRequest:
    """Serializable OpenRouter model-discovery request envelope."""

    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OpenRouterResponse:
    """Normalized OpenRouter completion payload."""

    model: str
    output_text: str
    request_payload: dict[str, Any]
    raw_response: dict[str, Any]
    latency_ms: int | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class OpenRouterClient:
    """Typed client wrapper around the OpenRouter chat completions API."""

    api_key: str
    base_url: str
    app_name: str
    site_url: str | None = None
    http_client: JsonHttpClient = field(default_factory=JsonHttpClient)

    @classmethod
    def from_settings(cls) -> "OpenRouterClient":
        settings = get_settings().openrouter
        if not settings.api_key:
            raise OpenRouterError("Set OPENROUTER_API_KEY to use llm_audit runs")
        return cls(
            api_key=settings.api_key,
            base_url=settings.base_url.rstrip("/"),
            app_name=settings.app_name,
            site_url=settings.site_url,
            http_client=JsonHttpClient(
                timeout_seconds=settings.timeout_seconds,
                max_retries=settings.max_retries,
                rate_limit_seconds=0.0,
            ),
        )

    def list_models(
        self,
        *,
        user_scoped: bool,
        request: OpenRouterModelsRequest | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw OpenRouter model objects from the discovery endpoint."""

        request = request or self.build_models_request(user_scoped=user_scoped)
        try:
            response = self.http_client.request_json(
                method=request.method,
                url=request.url,
                params=request.params,
                headers=request.headers,
            )
        except HttpClientError as exc:
            raise _classify_model_discovery_error(exc, request=request) from exc

        data = response.get("data")
        if not isinstance(data, list):
            raise OpenRouterModelDiscoveryError(
                "OpenRouter model discovery returned an unexpected payload shape",
                url=request.url,
            )
        return [item for item in data if isinstance(item, dict)]

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float = 0.2,
        top_p: float = 1.0,
        require_json: bool = True,
        request: OpenRouterRequest | None = None,
    ) -> OpenRouterResponse:
        """Execute a chat completion request."""

        request = request or self.build_completion_request(
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            require_json=require_json,
        )

        started = time.perf_counter()
        try:
            response = self.http_client.request_json(
                method=request.method,
                url=request.url,
                headers=request.headers,
                payload=request.payload,
            )
        except HttpClientError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            raise _classify_openrouter_error(
                exc,
                model=model,
                request=request,
                latency_ms=latency_ms,
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        choices = response.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else {}
        finish_reason = choices[0].get("finish_reason") if isinstance(choices, list) and choices else None
        output_text = _extract_output_text(message)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}

        return OpenRouterResponse(
            model=model,
            output_text=output_text,
            request_payload=request.payload,
            raw_response=response,
            latency_ms=latency_ms,
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            prompt_tokens=_as_int(usage.get("prompt_tokens")),
            completion_tokens=_as_int(usage.get("completion_tokens")),
            total_tokens=_as_int(usage.get("total_tokens")),
        )

    def build_completion_request(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float = 0.2,
        top_p: float = 1.0,
        require_json: bool = True,
    ) -> OpenRouterRequest:
        """Return the exact request envelope used for one completion call."""

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You return concise, valid JSON only. Do not add markdown, commentary, or preamble."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        if require_json:
            payload["response_format"] = {"type": "json_object"}

        return OpenRouterRequest(
            method="POST",
            url=f"{self.base_url}/chat/completions",
            headers=self._build_headers(include_json_content_type=True),
            payload=payload,
        )

    def build_models_request(self, *, user_scoped: bool) -> OpenRouterModelsRequest:
        """Return the request envelope used for OpenRouter model discovery."""

        endpoint = "/models/user" if user_scoped else "/models"
        return OpenRouterModelsRequest(
            method="GET",
            url=f"{self.base_url}{endpoint}",
            headers=self._build_headers(include_json_content_type=False),
        )

    def _build_headers(self, *, include_json_content_type: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Title": self.app_name,
        }
        if include_json_content_type:
            headers["Content-Type"] = "application/json"
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        return headers


def _extract_output_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            return "\n".join(parts)
    return ""


def extract_output_text_from_response_payload(response: dict[str, Any]) -> str:
    """Return the assistant text from a stored OpenRouter response payload."""

    choices = response.get("choices")
    message = choices[0].get("message") if isinstance(choices, list) and choices else {}
    return _extract_output_text(message)


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


_HTTP_ERROR_RE = re.compile(r"^HTTP (?P<status>\d{3}) for (?P<url>.+?): (?P<body>.*)$")
_NO_ENDPOINTS_PREFIX = "no endpoints found for "


def _classify_openrouter_error(
    exc: HttpClientError,
    *,
    model: str,
    request: OpenRouterRequest,
    latency_ms: int | None,
) -> OpenRouterError:
    raw_message = str(exc)
    status_code: int | None = None
    response_text: str | None = None
    response_payload: dict[str, Any] | None = None
    url = request.url
    provider_message = raw_message
    provider_error_code: str | None = None

    match = _HTTP_ERROR_RE.match(raw_message)
    if match is not None:
        status_code = int(match.group("status"))
        url = match.group("url")
        response_text = match.group("body")
        provider_message = response_text or raw_message
        try:
            decoded = json.loads(response_text)
        except (TypeError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            response_payload = decoded
            error_payload = decoded.get("error")
            if isinstance(error_payload, dict):
                error_message = error_payload.get("message")
                if isinstance(error_message, str) and error_message.strip():
                    provider_message = error_message.strip()
                provider_error_code = _stringify_error_code(error_payload.get("code"))

    failure_kind = _failure_kind(status_code=status_code, provider_message=provider_message, model=model)
    message = (
        f"OpenRouter model '{model}' is unavailable: {provider_message}"
        if failure_kind == "model_unavailable"
        else (
            f"OpenRouter request failed for model '{model}' with HTTP {status_code}: {provider_message}"
            if status_code is not None
            else raw_message
        )
    )
    return OpenRouterError(
        message,
        model=model,
        status_code=status_code,
        url=url,
        response_text=response_text,
        response_payload=response_payload,
        provider_error_code=provider_error_code,
        failure_kind=failure_kind,
        latency_ms=latency_ms,
    )


def _failure_kind(*, status_code: int | None, provider_message: str, model: str) -> str:
    if status_code == 404 and _message_indicates_unavailable_model(provider_message, model):
        return "model_unavailable"
    if status_code is not None and 400 <= status_code < 500:
        return "client_error"
    if status_code is not None and status_code >= 500:
        return "server_error"
    return "request_error"


def _message_indicates_unavailable_model(message: str, model: str) -> bool:
    if not message:
        return False
    normalized_message = message.strip()
    if not normalized_message.lower().startswith(_NO_ENDPOINTS_PREFIX):
        return False
    unavailable_model = normalized_message[len(_NO_ENDPOINTS_PREFIX):].strip().rstrip(".").lower()
    return unavailable_model == model.strip().lower()


def _stringify_error_code(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _classify_model_discovery_error(
    exc: HttpClientError,
    *,
    request: OpenRouterModelsRequest,
) -> OpenRouterModelDiscoveryError:
    raw_message = str(exc)
    match = _HTTP_ERROR_RE.match(raw_message)
    if match is not None:
        status_code = int(match.group("status"))
        url = match.group("url")
        body = match.group("body")
        message = (
            "OpenRouter model discovery was rejected by the upstream API"
            if status_code in {401, 403}
            else f"OpenRouter model discovery failed with HTTP {status_code}"
        )
        return OpenRouterModelDiscoveryError(message, status_code=status_code, url=url)

    return OpenRouterModelDiscoveryError(
        "OpenRouter model discovery failed because the upstream service could not be reached",
        url=request.url,
    )
