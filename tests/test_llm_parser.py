from __future__ import annotations

import pytest

from backend.application.llm_parser import (
    LLMParseError,
    parse_article_recommendations,
    parse_article_recommendations_with_diagnostics,
)


def test_parse_article_recommendations_accepts_fenced_json() -> None:
    payload = """
    ```json
    {
      "articles": [
        {
          "rank": "1",
          "title": "Bias in Scholarly Retrieval",
          "doi": "10.1000/example",
          "publication_year": "2024",
          "language": "English",
          "is_open_access": "yes",
          "country_primary": "us",
          "publisher": "Journal Press",
          "venue": "Journal of Retrieval Studies",
          "authors": ["Ada Lovelace", "Grace Hopper"],
          "url": "https://example.org/paper",
          "rationale": "High relevance"
        }
      ]
    }
    ```
    """

    parsed = parse_article_recommendations(payload)

    assert len(parsed) == 1
    assert parsed[0]["rank"] == 1
    assert parsed[0]["year"] == 2024
    assert parsed[0]["publication_year"] == 2024
    assert parsed[0]["language"] == "en"
    assert parsed[0]["is_open_access"] is True
    assert parsed[0]["country_primary"] == "US"
    assert parsed[0]["publisher"] == "Journal Press"
    assert parsed[0]["authors"] == ["Ada Lovelace", "Grace Hopper"]
    assert parsed[0]["doi"] == "10.1000/example"


def test_parse_article_recommendations_raises_when_no_usable_articles_exist() -> None:
    with pytest.raises(LLMParseError, match="usable article items"):
        parse_article_recommendations('{"articles": [{"title": ""}]}')


def test_parse_article_recommendations_recovers_complete_items_from_truncated_json() -> None:
    payload = """
    {
      "articles": [
        {
          "rank": 1,
          "title": "Liquid biopsy in cancer diagnosis, staging, and treatment monitoring",
          "doi": "10.1038/s41568-019-0214-z",
          "year": 2019,
          "venue": "Nature Reviews Cancer",
          "authors": ["Catherine Alix-Panabieres", "Klaus Pantel"],
          "url": "https://www.nature.com/articles/s41568-019-0214-z",
          "rationale": "Comprehensive review of liquid biopsy applications."
        },
        {
          "rank": 2,
          "title": "Liquid Biopsy in Cancer Diagnosis and Treatment",
          "doi": "10.1002/cncr.32378",
          "year": 2019,
          "venue": "Cancer",
          "authors": ["A. Heitzer", "I. S. Haque"],
          "url": "https://acsjournals.onlinelibrary.wiley.com/doi/10.1002/cncr.32378",
          "rationale": "Clinical overview of cancer liquid biopsy use."
        },
        {
          "rank": 3,
          "title": "Truncated third record",
          "doi": "10.0000/truncated"
    """

    parsed = parse_article_recommendations_with_diagnostics(payload)

    assert parsed.parse_mode == "partial_array_recovery"
    assert parsed.recovered_partial_json is True
    assert [item["title"] for item in parsed.items] == [
        "Liquid biopsy in cancer diagnosis, staging, and treatment monitoring",
        "Liquid Biopsy in Cancer Diagnosis and Treatment",
    ]
    assert parsed.items[0]["doi"] == "10.1038/s41568-019-0214-z"
    assert parsed.items[1]["venue"] == "Cancer"


def test_parse_article_recommendations_keeps_missing_fields_unknown_without_guessing() -> None:
    payload = """
    {
      "articles": [
        {
          "rank": 1,
          "title": "Bias Signals in Discovery Systems",
          "doi": null,
          "publication_year": null,
          "language": "unknown",
          "is_open_access": "unknown",
          "country_primary": "unknown",
          "publisher": "unknown",
          "venue": "",
          "authors": ["Ada Lovelace", "", 42],
          "url": null,
          "rationale": "Relevant."
        }
      ]
    }
    """

    parsed = parse_article_recommendations(payload)

    assert parsed[0]["doi"] is None
    assert parsed[0]["year"] is None
    assert parsed[0]["publication_year"] is None
    assert parsed[0]["language"] is None
    assert parsed[0]["is_open_access"] is None
    assert parsed[0]["country_primary"] is None
    assert parsed[0]["publisher"] is None
    assert parsed[0]["venue"] is None
    assert parsed[0]["url"] is None
    assert parsed[0]["authors"] == ["Ada Lovelace"]
