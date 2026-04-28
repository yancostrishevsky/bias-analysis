"""Normalization helpers for llm_audit article recommendations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


class LLMParseError(ValueError):
    """Raised when an LLM response cannot be normalized."""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_ARTICLES_ARRAY_RE = re.compile(r'"articles"\s*:\s*\[', re.IGNORECASE)
_JSON_DECODER = json.JSONDecoder()
_UNKNOWN_MARKERS = {"unknown", "n/a", "na", "none", "null"}
_LANGUAGE_ALIASES = {
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


@dataclass(frozen=True, slots=True)
class ArticleRecommendationParseResult:
    """Normalized items plus lightweight parser diagnostics."""

    items: list[dict[str, Any]]
    parse_mode: str
    recovered_partial_json: bool = False


def parse_article_recommendations(raw_text: str) -> list[dict[str, Any]]:
    """Parse an OpenRouter response into normalized article recommendation items."""

    return parse_article_recommendations_with_diagnostics(raw_text).items


def parse_article_recommendations_with_diagnostics(
    raw_text: str,
) -> ArticleRecommendationParseResult:
    """Parse an OpenRouter response and return diagnostics alongside the items."""

    if not raw_text.strip():
        raise LLMParseError("Response text was empty")

    payload, parse_mode = _load_json_payload(raw_text)
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise LLMParseError("Response JSON did not contain an 'articles' list")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(articles, start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        if not title:
            continue
        authors = _normalize_authors(item.get("authors"))
        publication_year = _coerce_year(item.get("publication_year"), item.get("year"))
        normalized.append(
            {
                "rank": _coerce_rank(item.get("rank"), fallback=index),
                "title": title,
                "doi": _clean_optional_text(item.get("doi")),
                "publication_year": publication_year,
                "year": publication_year,
                "language": _normalize_language_code(item.get("language")),
                "is_open_access": _coerce_optional_bool(
                    item.get("is_open_access"),
                    item.get("open_access"),
                ),
                "country_primary": _normalize_country_value(item.get("country_primary")),
                "publisher": _clean_optional_text(item.get("publisher")),
                "venue": _clean_optional_text(item.get("venue"), item.get("journal")),
                "authors": authors,
                "url": _clean_optional_text(item.get("url")),
                "rationale": _clean_optional_text(item.get("rationale")),
                "raw_item": item,
            }
        )

    if not normalized:
        raise LLMParseError("Response JSON did not contain any usable article items")
    return ArticleRecommendationParseResult(
        items=normalized,
        parse_mode=parse_mode,
        recovered_partial_json=parse_mode == "partial_array_recovery",
    )


def build_article_retrieval_prompt(*, query_text: str, top_k: int) -> str:
    """Return the JSON-only prompt used for llm_audit runs."""

    return (
        "Return a JSON object with one key named 'articles'. "
        f"Provide exactly {top_k} scholarly article recommendations for the query below. "
        "Each article must be an object with: rank, title, doi, publication_year, language, is_open_access, "
        "country_primary, publisher, venue, authors, url, rationale. "
        "Use exact published metadata only. Do not paraphrase titles or invent doi, publication_year, language, "
        "is_open_access, country_primary, publisher, venue, authors, or url. "
        "Use ISO 639-1 language codes when known. Use ISO 3166-1 alpha-2 country codes for country_primary when known. "
        "Every object must include every key; use null for any unknown field instead of omitting it. "
        "Keep each rationale to one short sentence under 18 words. "
        "Do not include commentary.\n\n"
        f"Query: {query_text}"
    )


def _load_json_payload(raw_text: str) -> tuple[dict[str, Any], str]:
    text = raw_text.strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload, "full_json"
    except json.JSONDecodeError:
        pass

    fenced_match = _JSON_BLOCK_RE.search(text)
    if fenced_match is not None:
        try:
            payload = json.loads(fenced_match.group(1))
        except json.JSONDecodeError as exc:
            raise LLMParseError("Response contained fenced JSON but it was invalid") from exc
        if isinstance(payload, dict):
            return payload, "fenced_json"

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            partial_payload = _recover_partial_payload(text)
            if partial_payload is not None:
                return partial_payload, "partial_array_recovery"
            raise LLMParseError("Response did not contain valid JSON") from exc
        if isinstance(payload, dict):
            return payload, "brace_slice"

    partial_payload = _recover_partial_payload(text)
    if partial_payload is not None:
        return partial_payload, "partial_array_recovery"

    raise LLMParseError("Response did not contain JSON")


def _recover_partial_payload(raw_text: str) -> dict[str, Any] | None:
    match = _ARTICLES_ARRAY_RE.search(raw_text)
    if match is None:
        return None

    index = match.end()
    articles: list[dict[str, Any]] = []
    length = len(raw_text)
    while index < length:
        character = raw_text[index]
        if character in " \t\r\n,":
            index += 1
            continue
        if character == "]":
            break
        if character != "{":
            break
        try:
            article, consumed = _JSON_DECODER.raw_decode(raw_text[index:])
        except json.JSONDecodeError:
            break
        if isinstance(article, dict):
            articles.append(article)
        index += consumed

    if not articles:
        return None
    return {"articles": articles}


def _normalize_authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                authors.append(cleaned)
    return authors


def _coerce_rank(value: Any, *, fallback: int) -> int:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            rank = int(value)
        except ValueError:
            return fallback
        return rank if rank > 0 else fallback
    return fallback


def _coerce_year(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned or cleaned.lower() in _UNKNOWN_MARKERS:
                continue
            digits = "".join(character for character in cleaned if character.isdigit())
            if len(digits) >= 4:
                try:
                    return int(digits[:4])
                except ValueError:
                    continue
    return None


def _clean_text(*values: Any) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _clean_optional_text(*values: Any) -> str | None:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned is None:
            continue
        if cleaned.lower() in _UNKNOWN_MARKERS:
            continue
        return cleaned
    return None


def _coerce_optional_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if cleaned in {"true", "yes", "open", "oa", "1"}:
                return True
            if cleaned in {"false", "no", "closed", "0"}:
                return False
            if cleaned in _UNKNOWN_MARKERS:
                continue
    return None


def _normalize_language_code(value: Any) -> str | None:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    if lowered in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[lowered]
    if len(lowered) == 2 and lowered.isalpha():
        return lowered
    return lowered


def _normalize_country_value(value: Any) -> str | None:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return None
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned.upper()
    return cleaned
