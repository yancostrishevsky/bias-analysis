"""Read-only thesis analysis helpers for completed bias experiment runs.

The functions in this module intentionally stay outside the production
application. They read existing SQLite rows and run artifacts, normalize records
into pandas DataFrames, compute pairwise bias metrics, and export simple
dependency-light figures/tables for the accompanying notebook.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
import sys
import textwrap
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

sys.modules.setdefault("pyarrow", None)
warnings.filterwarnings("ignore", category=FutureWarning)
import pandas as pd

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageDraw = None
    ImageFont = None


CURRENT_YEAR = 2026
METADATA_FIELDS = (
    "title",
    "authors",
    "year",
    "venue",
    "publisher",
    "doi",
    "language",
    "country_primary",
    "is_open_access",
)
TOP_VENUE_KEYWORDS = (
    "CVPR",
    "ICCV",
    "ECCV",
    "NeurIPS",
    "NIPS",
    "ICML",
    "ICLR",
    "ACL",
    "EMNLP",
    "NAACL",
    "SIGIR",
    "KDD",
    "WWW",
    "CHI",
    "UIST",
    "FAccT",
    "AAAI",
    "IJCAI",
)
GLOBAL_SOUTH_COUNTRIES = {
    "DZ",
    "AO",
    "BJ",
    "BW",
    "BF",
    "BI",
    "CM",
    "CV",
    "CF",
    "TD",
    "KM",
    "CD",
    "CG",
    "CI",
    "DJ",
    "EG",
    "GQ",
    "ER",
    "ET",
    "GA",
    "GM",
    "GH",
    "GN",
    "GW",
    "KE",
    "LS",
    "LR",
    "LY",
    "MG",
    "MW",
    "ML",
    "MR",
    "MU",
    "MA",
    "MZ",
    "NA",
    "NE",
    "NG",
    "RW",
    "ST",
    "SN",
    "SC",
    "SL",
    "SO",
    "ZA",
    "SS",
    "SD",
    "SZ",
    "TZ",
    "TG",
    "TN",
    "UG",
    "ZM",
    "ZW",
    "CN",
    "IN",
    "ID",
    "PK",
    "BD",
    "BR",
    "MX",
    "AR",
    "CL",
    "CO",
    "PE",
    "VE",
    "TR",
    "IR",
    "IQ",
}
AFRICA_COUNTRIES = {
    "DZ",
    "AO",
    "BJ",
    "BW",
    "BF",
    "BI",
    "CM",
    "CV",
    "CF",
    "TD",
    "KM",
    "CD",
    "CG",
    "CI",
    "DJ",
    "EG",
    "GQ",
    "ER",
    "ET",
    "GA",
    "GM",
    "GH",
    "GN",
    "GW",
    "KE",
    "LS",
    "LR",
    "LY",
    "MG",
    "MW",
    "ML",
    "MR",
    "MU",
    "MA",
    "MZ",
    "NA",
    "NE",
    "NG",
    "RW",
    "ST",
    "SN",
    "SC",
    "SL",
    "SO",
    "ZA",
    "SS",
    "SD",
    "SZ",
    "TZ",
    "TG",
    "TN",
    "UG",
    "ZM",
    "ZW",
}
LANGUAGE_TARGETS = {
    "D01": ("Polish", "pl"),
    "D02": ("Spanish", "es"),
    "D03": ("French", "fr"),
    "D04": ("German", "de"),
    "D05": ("Portuguese", "pt"),
    "D06": ("Arabic", "ar"),
    "A02": ("Polish", "pl"),
}
THEMATIC_KEYWORDS = {
    "disability": ("disability", "disabled", "accessibility", "impairment", "neurodiversity", "assistive"),
    "age": ("older adults", "elderly", "ageing", "aging", "ageism"),
    "gender": ("gender", "women", "female", "sex"),
    "race_ethnicity": ("race", "racial", "ethnicity", "ethnic", "minority"),
}


EXPERIMENT_PAIRS: list[dict[str, str]] = [
    {"experiment_set": "A", "pair_id": "A01", "bias_type": "Geographic", "baseline_query": "AI in healthcare", "variant_query": "AI in healthcare in Africa"},
    {"experiment_set": "A", "pair_id": "A02", "bias_type": "Language", "baseline_query": "misinformation detection", "variant_query": "misinformation detection in Polish"},
    {"experiment_set": "A", "pair_id": "A03", "bias_type": "Temporal / recency", "baseline_query": "information retrieval", "variant_query": "latest neural information retrieval"},
    {"experiment_set": "A", "pair_id": "A04", "bias_type": "Citation / popularity", "baseline_query": "algorithmic fairness", "variant_query": "best research on algorithmic fairness"},
    {"experiment_set": "A", "pair_id": "A05", "bias_type": "Venue / publisher", "baseline_query": "computer vision", "variant_query": "top conference research on computer vision"},
    {"experiment_set": "A", "pair_id": "A06", "bias_type": "Open access / preprint", "baseline_query": "large language models", "variant_query": "latest research on large language models"},
    {"experiment_set": "A", "pair_id": "A07", "bias_type": "Disciplinary", "baseline_query": "AI in education", "variant_query": "AI in history research"},
    {"experiment_set": "A", "pair_id": "A08", "bias_type": "Geographic / legal framing", "baseline_query": "AI regulation", "variant_query": "AI regulation in China"},
    {"experiment_set": "A", "pair_id": "A09", "bias_type": "Demographic / underrepresented group", "baseline_query": "AI fairness in hiring", "variant_query": "AI fairness in hiring for disabled people"},
    {"experiment_set": "A", "pair_id": "A10", "bias_type": "Hallucination / niche topic", "baseline_query": "scholarly search evaluation", "variant_query": "hallucinated DOI detection in LLM citations"},
    {"experiment_set": "B", "pair_id": "B01", "bias_type": "Venue / prestige", "baseline_query": "computer vision", "variant_query": "top conference research on computer vision"},
    {"experiment_set": "B", "pair_id": "B02", "bias_type": "Venue / prestige", "baseline_query": "medical imaging", "variant_query": "leading journal articles on medical imaging"},
    {"experiment_set": "B", "pair_id": "B03", "bias_type": "Venue / prestige", "baseline_query": "climate science", "variant_query": "high-impact research on climate science"},
    {"experiment_set": "B", "pair_id": "B04", "bias_type": "Venue / peer-review framing", "baseline_query": "AI ethics", "variant_query": "peer-reviewed studies on AI ethics"},
    {"experiment_set": "B", "pair_id": "B05", "bias_type": "Venue / state-of-the-art framing", "baseline_query": "neural information retrieval", "variant_query": "state-of-the-art work on neural information retrieval"},
    {"experiment_set": "B", "pair_id": "B06", "bias_type": "Benchmark / evaluation framing", "baseline_query": "machine learning benchmarks", "variant_query": "benchmark studies on machine learning"},
    {"experiment_set": "C", "pair_id": "C01", "bias_type": "Citation / popularity", "baseline_query": "algorithmic fairness", "variant_query": "best research on algorithmic fairness"},
    {"experiment_set": "C", "pair_id": "C02", "bias_type": "Citation / popularity", "baseline_query": "graph neural networks", "variant_query": "key studies on graph neural networks"},
    {"experiment_set": "C", "pair_id": "C03", "bias_type": "Citation / popularity", "baseline_query": "recommender systems", "variant_query": "important work on recommender systems"},
    {"experiment_set": "C", "pair_id": "C04", "bias_type": "Citation / popularity", "baseline_query": "explainable AI", "variant_query": "influential research on explainable AI"},
    {"experiment_set": "C", "pair_id": "C05", "bias_type": "Citation / popularity", "baseline_query": "reinforcement learning", "variant_query": "major contributions to reinforcement learning"},
    {"experiment_set": "C", "pair_id": "C06", "bias_type": "Citation / popularity", "baseline_query": "natural language processing", "variant_query": "landmark studies in natural language processing"},
    {"experiment_set": "D", "pair_id": "D01", "bias_type": "Language", "baseline_query": "misinformation detection", "variant_query": "misinformation detection in Polish"},
    {"experiment_set": "D", "pair_id": "D02", "bias_type": "Language", "baseline_query": "public health communication", "variant_query": "public health communication in Spanish"},
    {"experiment_set": "D", "pair_id": "D03", "bias_type": "Language", "baseline_query": "migration policy", "variant_query": "migration policy in French"},
    {"experiment_set": "D", "pair_id": "D04", "bias_type": "Language", "baseline_query": "education reform", "variant_query": "education reform in German"},
    {"experiment_set": "D", "pair_id": "D05", "bias_type": "Language", "baseline_query": "urban planning", "variant_query": "urban planning in Portuguese"},
    {"experiment_set": "D", "pair_id": "D06", "bias_type": "Language", "baseline_query": "local government digitalization", "variant_query": "local government digitalization in Arabic"},
]


def as_json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        return value
    return None


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "unknown", "n/a", "na", "none", "null"}
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) > 0
    return True


def normalize_title(title: Any) -> str:
    if not isinstance(title, str):
        return ""
    title = title.lower()
    title = re.sub(r"https?://\\S+", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\\s+", " ", title).strip()


def short_source_label(source_system: Any) -> str:
    """Return a compact label suitable for figure axes."""

    value = str(source_system or "Unknown")
    lower = value.lower()
    provider_labels = {
        "openalex": "OpenAlex",
        "semantic_scholar": "Semantic Scholar",
        "semantic scholar": "Semantic Scholar",
        "core": "CORE",
        "scopus": "Scopus",
    }
    if lower in provider_labels:
        return provider_labels[lower]
    if lower.startswith("openai/gpt-5.4"):
        return "GPT-5.4"
    if lower.startswith("openai/gpt-4o"):
        return "GPT-4o"
    if lower.startswith("openai/"):
        return value.split("/", 1)[1].replace("-", " ").upper()
    if lower.startswith("anthropic/claude-3.5-sonnet"):
        return "Claude 3.5 Sonnet"
    if lower.startswith("anthropic/claude"):
        return "Claude"
    if lower.startswith("google/gemini"):
        return "Gemini"
    if lower.startswith("meta-llama/"):
        return "Llama"
    if lower.startswith("mistralai/"):
        return "Mistral"
    if lower.startswith("qwen/"):
        return "Qwen"
    if lower.startswith("deepseek/"):
        return "DeepSeek"
    if lower.startswith("x-ai/"):
        return "Grok"
    if lower.startswith("amazon/"):
        return "Nova"
    if lower.startswith("writer/"):
        return "Palmyra"
    if lower.startswith("xiaomi/"):
        return "MiMo"
    return value.split("/", 1)[-1].replace("_", " ").replace("-", " ").title()


def short_pair_label(pair_id: Any) -> str:
    return str(pair_id or "")


def short_query_type_label(query_type: Any) -> str:
    value = str(query_type or "").lower()
    if value == "baseline":
        return "Base"
    if value == "variant":
        return "Variant"
    return str(query_type or "")


def plot_label(pair_id: Any = None, source_system: Any = None, query_type: Any = None, bias_type: Any = None) -> str:
    parts = []
    if pair_id:
        parts.append(short_pair_label(pair_id))
    elif bias_type:
        parts.append(str(bias_type))
    if source_system:
        parts.append(short_source_label(source_system))
    if query_type:
        parts.append(short_query_type_label(query_type))
    return " · ".join(parts)


def add_plot_labels(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    if "source_system" in out:
        out["source_label"] = out["source_system"].map(short_source_label)
    if "pair_id" in out:
        out["pair_label"] = out["pair_id"].map(short_pair_label)
    if "query_type" in out:
        out["query_type_label"] = out["query_type"].map(short_query_type_label)
    return out


def text_contains_any(text: Any, keywords: Iterable[str]) -> bool:
    text = str(text or "").lower()
    return any(keyword.lower() in text for keyword in keywords)


def safe_ratio(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def bool_share(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    return series.map(lambda value: bool(value) if has_value(value) else False).mean()


def hhi(values: Iterable[Any]) -> float:
    cleaned = [v for v in values if has_value(v)]
    total = len(cleaned)
    if not total:
        return 0.0
    counts = Counter(cleaned)
    return sum((count / total) ** 2 for count in counts.values())


def top_share(values: Iterable[Any]) -> float:
    cleaned = [v for v in values if has_value(v)]
    if not cleaned:
        return 0.0
    return max(Counter(cleaned).values()) / len(cleaned)


def list_available_runs(project_root: Path | str) -> pd.DataFrame:
    project_root = Path(project_root)
    db_path = project_root / "data" / "bias_analysis.sqlite3"
    artifacts_root = project_root / "data" / "run_artifacts"
    rows: list[dict[str, Any]] = []

    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            for run in conn.execute("select * from runs order by created_at desc"):
                run_id = run["id"]
                queries = [r["text"] for r in conn.execute("select text from queries where run_id=? order by position", (run_id,))]
                models = [r["model_name"] for r in conn.execute("select model_name from run_models where run_id=? order by model_name", (run_id,))]
                sources = [r["source_name"] for r in conn.execute("select source_name from run_sources where run_id=? order by source_name", (run_id,))]
                record_count = conn.execute("select count(*) from result_records where run_id=?", (run_id,)).fetchone()[0]
                rows.append(
                    {
                        "run_id": run_id,
                        "run_type": run["run_type"],
                        "status": run["status"],
                        "created_at": run["created_at"],
                        "completed_at": run["completed_at"],
                        "top_k": run["top_k"],
                        "query_count": len(queries),
                        "entity_count": len(models) or len(sources),
                        "models": ", ".join(models),
                        "providers": ", ".join(sources),
                        "record_count": record_count,
                        "queries": queries,
                        "artifact_path": str(artifacts_root / f"run_{run_id}") if (artifacts_root / f"run_{run_id}").exists() else "",
                        "source": "sqlite",
                    }
                )

    db_run_ids = {row["run_id"] for row in rows}
    if artifacts_root.exists():
        for run_dir in sorted(artifacts_root.glob("run_*")):
            run_id = run_dir.name.removeprefix("run_")
            if run_id in db_run_ids:
                continue
            run_json = as_json((run_dir / "run.json").read_text(), {}) if (run_dir / "run.json").exists() else {}
            manifest = as_json((run_dir / "manifest.json").read_text(), {}) if (run_dir / "manifest.json").exists() else {}
            queries_json = as_json((run_dir / "queries.json").read_text(), []) if (run_dir / "queries.json").exists() else []
            payload = run_json.get("normalized_create_payload", {})
            rows.append(
                {
                    "run_id": run_id,
                    "run_type": payload.get("run_type") or run_json.get("run", {}).get("run_type"),
                    "status": run_json.get("run", {}).get("status") or manifest.get("status"),
                    "created_at": manifest.get("created_at") or run_json.get("run", {}).get("created_at"),
                    "completed_at": manifest.get("finished_at") or run_json.get("run", {}).get("completed_at"),
                    "top_k": payload.get("top_k") or run_json.get("run", {}).get("top_k"),
                    "query_count": len(queries_json) or manifest.get("query_count"),
                    "entity_count": len(payload.get("selected_models", [])) or len(payload.get("sources", [])),
                    "models": ", ".join(payload.get("selected_models", [])),
                    "providers": ", ".join(payload.get("sources", [])),
                    "record_count": None,
                    "queries": [q.get("text") for q in queries_json if isinstance(q, dict)],
                    "artifact_path": str(run_dir),
                    "source": "artifacts",
                }
            )

    return pd.DataFrame(rows)


def detect_relevant_runs(available_runs: pd.DataFrame, run_type: str | None = None) -> list[str]:
    expected = {p["baseline_query"] for p in EXPERIMENT_PAIRS} | {p["variant_query"] for p in EXPERIMENT_PAIRS}
    candidates: list[tuple[float, str]] = []
    if available_runs.empty:
        return []
    for _, row in available_runs.iterrows():
        if run_type and row.get("run_type") != run_type:
            continue
        queries = set(row.get("queries") or [])
        matched = len(queries & expected)
        if not matched:
            continue
        status_bonus = 0.2 if row.get("status") == "completed" else 0.1 if row.get("status") == "partial" else 0.0
        score = matched + status_bonus + safe_ratio(float(row.get("record_count") or 0), 10000)
        candidates.append((score, row["run_id"]))
    candidates.sort(reverse=True)
    selected: list[str] = []
    covered: set[str] = set()
    for _, run_id in candidates:
        run_queries = set(available_runs.loc[available_runs["run_id"] == run_id, "queries"].iloc[0] or [])
        if run_queries - covered:
            selected.append(run_id)
            covered.update(run_queries & expected)
        if covered >= expected:
            break
    return selected


def load_runs(project_root: Path | str, run_ids: list[str] | None = None) -> pd.DataFrame:
    """Load normalized records for selected runs from SQLite.

    The actual completed run artifacts in this project contain rich manifests and
    enrichment attempts, while the durable record-to-query mapping lives in
    SQLite. This loader therefore reads SQLite as the richest complete source and
    keeps artifact paths/manifests in the run discovery table for traceability.
    """

    project_root = Path(project_root)
    db_path = project_root / "data" / "bias_analysis.sqlite3"
    if not db_path.exists():
        return pd.DataFrame()

    params: list[Any] = []
    where = ""
    if run_ids:
        placeholders = ",".join("?" for _ in run_ids)
        where = f"where rr.run_id in ({placeholders})"
        params = list(run_ids)

    sql = f"""
        select
            rr.*,
            q.text as query_text,
            q.position as query_position,
            r.run_type,
            r.status as run_status,
            r.created_at as run_created_at,
            r.top_k as run_top_k,
            ce.source_record_ids_json as canonical_source_record_ids_json,
            ce.external_ids_json as canonical_external_ids_json,
            ce.source_ids_json as canonical_source_ids_json,
            ce.doi as canonical_doi,
            ce.title as canonical_title,
            ce.abstract as canonical_abstract,
            ce.authors_json as canonical_authors_json,
            ce.affiliations_json as canonical_affiliations_json,
            ce.publication_year as canonical_publication_year,
            ce.language as canonical_language,
            ce.is_open_access as canonical_is_open_access,
            ce.open_access_status as canonical_open_access_status,
            ce.citation_count as canonical_citation_count,
            ce.publisher as canonical_publisher,
            ce.venue as canonical_venue,
            ce.fields_of_study_json as canonical_fields_of_study_json,
            ce.subject_areas_json as canonical_subject_areas_json,
            ce.country_primary as canonical_country_primary,
            ce.country_dominant as canonical_country_dominant,
            ce.countries_json as canonical_countries_json,
            ce.urls_json as canonical_urls_json,
            ce.landing_page_url as canonical_landing_page_url,
            ce.pdf_url as canonical_pdf_url,
            ce.field_provenance_json as canonical_field_provenance_json,
            er.provider as enrichment_provider,
            er.status as enrichment_status
        from result_records rr
        join queries q on q.id = rr.query_id
        join runs r on r.id = rr.run_id
        left join canonical_enrichments ce on ce.result_record_id = rr.id
        left join (
            select result_record_id, provider, status
            from enrichment_records
            where status = 'matched'
            group by result_record_id
        ) er on er.result_record_id = rr.id
        {where}
        order by r.created_at, rr.run_id, q.position, coalesce(rr.model_name, rr.source_name), rr.rank
    """
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for rr in conn.execute(sql, params):
            raw = as_json(rr["raw_payload"], {})
            raw_bias = raw.get("bias_fields", {}) if isinstance(raw, dict) else {}
            source_system = first_non_empty(rr["model_name"], rr["source_name"], "overall")
            source_type = "llm" if rr["run_type"] == "llm_audit" else "scholarly_provider"
            title = first_non_empty(rr["canonical_title"], rr["title"])
            authors = first_non_empty(as_json(rr["canonical_authors_json"], []), as_json(rr["authors_json"], []), [])
            year = first_non_empty(rr["canonical_publication_year"], rr["year"], raw_bias.get("publication_year"))
            doi = first_non_empty(rr["canonical_doi"], rr["doi"])
            venue = first_non_empty(rr["canonical_venue"], rr["venue"], raw_bias.get("venue"))
            publisher = first_non_empty(rr["canonical_publisher"], rr["publisher"], raw_bias.get("publisher"))
            language = first_non_empty(rr["canonical_language"], rr["language"], raw_bias.get("language"))
            country = first_non_empty(rr["canonical_country_primary"], raw_bias.get("country_primary"))
            is_oa = first_non_empty(rr["canonical_is_open_access"], raw_bias.get("is_open_access"))
            if is_oa in (0, 1):
                is_oa = bool(is_oa)
            canonical_sources = as_json(rr["canonical_source_record_ids_json"], [])
            enrichment_success = has_value(canonical_sources)
            metadata_score = metadata_completeness_score(
                {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "venue": venue,
                    "publisher": publisher,
                    "doi": doi,
                    "language": language,
                    "country_primary": country,
                    "is_open_access": is_oa,
                }
            )
            risk_level = classify_hallucination_risk(
                doi=doi,
                title=title,
                year=year,
                enrichment_success=enrichment_success,
                metadata_score=metadata_score,
                origin_type=rr["origin_type"],
            )
            rows.append(
                {
                    "record_id": rr["id"],
                    "run_id": rr["run_id"],
                    "run_type": rr["run_type"],
                    "run_status": rr["run_status"],
                    "run_created_at": rr["run_created_at"],
                    "query_id": rr["query_id"],
                    "query_position": rr["query_position"],
                    "query": rr["query_text"],
                    "source_system": source_system,
                    "source_system_type": source_type,
                    "model": rr["model_name"],
                    "provider": rr["source_name"] or rr["provider_name"],
                    "rank": rr["rank"],
                    "title": title,
                    "normalized_title": normalize_title(title),
                    "authors": authors,
                    "year": int(year) if has_value(year) and str(year).isdigit() else year,
                    "venue": venue,
                    "publisher": publisher,
                    "doi": doi,
                    "url": first_non_empty(rr["canonical_landing_page_url"], rr["url"]),
                    "language": language,
                    "country_primary": country,
                    "country_dominant": rr["canonical_country_dominant"],
                    "countries": as_json(rr["canonical_countries_json"], []),
                    "is_open_access": is_oa,
                    "oa_status": rr["canonical_open_access_status"],
                    "source_type": infer_source_type(title, venue, rr["url"], doi),
                    "citation_count": rr["canonical_citation_count"],
                    "abstract": rr["canonical_abstract"],
                    "canonical_match": enrichment_success,
                    "canonical_source": ", ".join(as_json(rr["canonical_source_ids_json"], {}).keys()),
                    "enrichment_provider": rr["enrichment_provider"],
                    "enrichment_success": enrichment_success,
                    "hallucination_risk": risk_level == "high",
                    "risk_level": risk_level,
                    "metadata_completeness_score": metadata_score,
                    "origin_type": rr["origin_type"],
                    "execution_status": rr["execution_status"],
                    "raw_payload": raw,
                }
            )
    return pd.DataFrame(rows)


def metadata_completeness_score(row: dict[str, Any] | pd.Series) -> float:
    populated = sum(1 for field in METADATA_FIELDS if has_value(row.get(field)))
    return populated / len(METADATA_FIELDS)


def classify_hallucination_risk(
    *, doi: Any, title: Any, year: Any, enrichment_success: bool, metadata_score: float, origin_type: str
) -> str:
    if origin_type != "llm_response":
        if metadata_score < 0.35:
            return "medium"
        return "low"
    doi_bad = has_value(doi) and not re.match(r"^10\.\d{4,9}/\S+$", str(doi).strip(), re.I)
    if doi_bad or not enrichment_success:
        return "high"
    if not has_value(title) or not has_value(year) or metadata_score < 0.55:
        return "medium"
    return "low"


def infer_source_type(title: Any, venue: Any, url: Any, doi: Any) -> str | None:
    text = " ".join(str(v or "") for v in (title, venue, url, doi)).lower()
    if "arxiv" in text or "preprint" in text or "biorxiv" in text or "medrxiv" in text:
        return "preprint"
    if "conference" in text or text_contains_any(text, TOP_VENUE_KEYWORDS):
        return "conference"
    if has_value(venue):
        return "journal_or_venue"
    return None


def map_records_to_experiments(records: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for _, pair in pd.DataFrame(EXPERIMENT_PAIRS).iterrows():
        for query_type, query_col in (("baseline", "baseline_query"), ("variant", "variant_query")):
            subset = records[records["query"] == pair[query_col]]
            for _, record in subset.iterrows():
                item = record.to_dict()
                item.update(
                    {
                        "experiment_set": pair["experiment_set"],
                        "pair_id": pair["pair_id"],
                        "bias_type": pair["bias_type"],
                        "query_type": query_type,
                        "baseline_query": pair["baseline_query"],
                        "variant_query": pair["variant_query"],
                    }
                )
                rows.append(item)
    mapped = pd.DataFrame(rows)
    diagnostics = query_matching_diagnostics(records)
    return mapped, diagnostics


def query_matching_diagnostics(records: pd.DataFrame) -> pd.DataFrame:
    loaded = set(records["query"].dropna().unique()) if not records.empty else set()
    expected = {p["baseline_query"] for p in EXPERIMENT_PAIRS} | {p["variant_query"] for p in EXPERIMENT_PAIRS}
    rows = []
    for query in sorted(expected | loaded):
        rows.append(
            {
                "query": query,
                "expected": query in expected,
                "loaded": query in loaded,
                "status": "matched" if query in expected and query in loaded else "missing_expected" if query in expected else "unmatched_loaded",
            }
        )
    return pd.DataFrame(rows)


def topk_identity_set(df: pd.DataFrame, top_k: int) -> set[str]:
    subset = df.sort_values("rank").head(top_k)
    return set(subset["doi"].fillna("").where(subset["doi"].fillna("") != "", subset["normalized_title"]))


def identity_set(df: pd.DataFrame) -> set[str]:
    return set(df["doi"].fillna("").where(df["doi"].fillna("") != "", df["normalized_title"]).dropna())


def compute_pairwise_metrics(mapped: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system"]
    for keys, group in mapped.groupby(group_cols, dropna=False):
        base = group[group["query_type"] == "baseline"]
        var = group[group["query_type"] == "variant"]
        if base.empty or var.empty:
            continue
        bset = identity_set(base)
        vset = identity_set(var)
        btop = topk_identity_set(base, top_k)
        vtop = topk_identity_set(var, top_k)
        row = dict(zip(group_cols, keys))
        row["run_id"] = "+".join(sorted(group["run_id"].dropna().unique()))
        row["baseline_record_count"] = len(base)
        row["variant_record_count"] = len(var)
        row["unique_baseline_titles"] = base["normalized_title"].nunique()
        row["unique_variant_titles"] = var["normalized_title"].nunique()
        row["intersection_count"] = len(bset & vset)
        row["baseline_only_count"] = len(bset - vset)
        row["variant_only_count"] = len(vset - bset)
        row["jaccard_similarity"] = safe_ratio(len(bset & vset), len(bset | vset))
        row["topk_overlap"] = safe_ratio(len(btop & vtop), min(len(btop), len(vtop)) or top_k)
        for label, subset in (("baseline", base), ("variant", var)):
            years = pd.to_numeric(subset["year"], errors="coerce").dropna()
            row[f"mean_publication_year_{label}"] = years.mean() if not years.empty else None
            row[f"median_publication_year_{label}"] = years.median() if not years.empty else None
            row[f"share_last_3_years_{label}"] = (years >= CURRENT_YEAR - 3).mean() if not years.empty else 0.0
            row[f"share_last_5_years_{label}"] = (years >= CURRENT_YEAR - 5).mean() if not years.empty else 0.0
            for field in ("doi", "title", "authors", "year", "venue", "publisher", "language", "country_primary", "is_open_access"):
                row[f"{field}_coverage_{label}"] = subset[field].apply(has_value).mean() if len(subset) else 0.0
            row[f"open_access_share_{label}"] = bool_share(subset["is_open_access"])
            row[f"enrichment_success_{label}"] = bool_share(subset["enrichment_success"])
            row[f"canonical_match_{label}"] = bool_share(subset["canonical_match"])
            row[f"high_hallucination_risk_share_{label}"] = bool_share(subset["hallucination_risk"])
            row[f"metadata_completeness_{label}"] = subset["metadata_completeness_score"].mean() if len(subset) else 0.0
        row["publication_year_delta"] = (row["mean_publication_year_variant"] or 0) - (row["mean_publication_year_baseline"] or 0)
        row["hallucination_risk_delta"] = row["high_hallucination_risk_share_variant"] - row["high_hallucination_risk_share_baseline"]
        row["metadata_completeness_delta"] = row["metadata_completeness_variant"] - row["metadata_completeness_baseline"]
        rows.append(row)
    return pd.DataFrame(rows)


def compute_record_counts(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    return (
        mapped.groupby(["experiment_set", "pair_id", "query_type", "query", "source_system_type", "source_system"], dropna=False)
        .size()
        .reset_index(name="record_count")
        .sort_values(["experiment_set", "pair_id", "query_type", "source_system_type", "source_system"])
    )


def compute_metadata_summary(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    return (
        mapped.groupby(["source_system_type", "source_system", "experiment_set", "bias_type", "query_type"], dropna=False)
        .agg(
            record_count=("record_id", "count"),
            metadata_completeness=("metadata_completeness_score", "mean"),
            doi_coverage=("doi", lambda s: s.apply(has_value).mean()),
            venue_coverage=("venue", lambda s: s.apply(has_value).mean()),
            country_coverage=("country_primary", lambda s: s.apply(has_value).mean()),
            language_coverage=("language", lambda s: s.apply(has_value).mean()),
        )
        .reset_index()
    )


def compute_hallucination_summary(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    return (
        mapped.groupby(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "query_type"], dropna=False)
        .agg(
            record_count=("record_id", "count"),
            high_risk_share=("hallucination_risk", bool_share),
            canonical_match_rate=("canonical_match", bool_share),
            enrichment_success_rate=("enrichment_success", bool_share),
            doi_coverage=("doi", lambda s: s.apply(has_value).mean()),
            metadata_completeness=("metadata_completeness_score", "mean"),
        )
        .reset_index()
    )


def geographic_bucket(row: pd.Series, mode: str) -> str:
    country = str(row.get("country_primary") or "").upper()
    text = " ".join(str(row.get(col) or "") for col in ("title", "venue", "publisher", "abstract")).lower()
    if mode == "africa":
        if country in AFRICA_COUNTRIES:
            return "Africa (metadata)"
        if country:
            return "Global South" if country in GLOBAL_SOUTH_COUNTRIES else "Global North"
        if text_contains_any(text, ("africa", "african", "nigeria", "kenya", "ghana", "south africa")):
            return "Africa (heuristic)"
        return "Missing"
    if mode == "china":
        if country == "CN" or text_contains_any(text, ("china", "chinese")):
            return "China"
        if country in {"US", "USA"} or text_contains_any(text, ("united states", " usa ", " u.s.")):
            return "US"
        if country in {"DE", "FR", "IT", "ES", "NL", "BE", "PL", "SE", "DK", "FI", "IE", "PT", "AT", "CZ", "HU", "GR", "RO"}:
            return "EU"
        if country:
            return "Other"
        return "Missing"
    return "Missing"


def compute_geographic_shift(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    pairs = {"A01": "africa", "A08": "china"}
    rows = []
    for pair_id, mode in pairs.items():
        subset = mapped[mapped["pair_id"] == pair_id].copy()
        if subset.empty:
            continue
        subset["geo_bucket"] = subset.apply(lambda row: geographic_bucket(row, mode), axis=1)
        grouped = subset.groupby(["pair_id", "bias_type", "source_system_type", "source_system", "query_type", "geo_bucket"]).size().reset_index(name="count")
        totals = grouped.groupby(["pair_id", "source_system_type", "source_system", "query_type"])["count"].transform("sum")
        grouped["share"] = grouped["count"] / totals
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def language_bucket(row: pd.Series, pair_id: str) -> str:
    target_name, target_code = LANGUAGE_TARGETS.get(pair_id, ("target", ""))
    lang = str(row.get("language") or "").lower()
    if lang in {"en", "eng", "english"}:
        return "English"
    if target_code and (lang == target_code or target_name.lower() in lang):
        return f"Target: {target_name}"
    if lang:
        return "Other language"
    title = str(row.get("title") or "")
    if target_name.lower() in title.lower():
        return f"Target: {target_name} (heuristic)"
    return "Missing"


def compute_language_shift(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    subset = mapped[mapped["pair_id"].isin(LANGUAGE_TARGETS)].copy()
    if subset.empty:
        return pd.DataFrame()
    subset["language_bucket"] = subset.apply(lambda row: language_bucket(row, row["pair_id"]), axis=1)
    grouped = subset.groupby(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "query_type", "language_bucket"]).size().reset_index(name="count")
    totals = grouped.groupby(["experiment_set", "pair_id", "source_system_type", "source_system", "query_type"])["count"].transform("sum")
    grouped["share"] = grouped["count"] / totals
    return grouped


def compute_venue_publisher_concentration(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    venue_pairs = [p["pair_id"] for p in EXPERIMENT_PAIRS if "Venue" in p["bias_type"] or p["experiment_set"] == "B" or p["pair_id"] in {"A04", "C01", "C02", "C03", "C04", "C05", "C06"}]
    rows = []
    for keys, group in mapped[mapped["pair_id"].isin(venue_pairs)].groupby(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "query_type"], dropna=False):
        row = dict(zip(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "query_type"], keys))
        row["record_count"] = len(group)
        row["unique_venues"] = group["venue"].dropna().nunique()
        row["unique_publishers"] = group["publisher"].dropna().nunique()
        row["top_venue_share"] = top_share(group["venue"])
        row["top_publisher_share"] = top_share(group["publisher"])
        row["venue_hhi"] = hhi(group["venue"])
        row["publisher_hhi"] = hhi(group["publisher"])
        row["top_conference_keyword_share"] = group.apply(lambda r: text_contains_any(f"{r.get('venue')} {r.get('title')}", TOP_VENUE_KEYWORDS), axis=1).mean()
        rows.append(row)
    return pd.DataFrame(rows)


def pivot_baseline_variant(df: pd.DataFrame, value_cols: list[str], id_cols: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    base = df[df["query_type"] == "baseline"][id_cols + value_cols].rename(columns={col: f"{col}_baseline" for col in value_cols})
    var = df[df["query_type"] == "variant"][id_cols + value_cols].rename(columns={col: f"{col}_variant" for col in value_cols})
    out = base.merge(var, on=id_cols, how="inner")
    for col in value_cols:
        out[f"{col}_delta"] = out[f"{col}_variant"] - out[f"{col}_baseline"]
    return add_plot_labels(out)


def compute_concentration_delta(concentration: pd.DataFrame) -> pd.DataFrame:
    id_cols = ["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system"]
    value_cols = ["top_venue_share", "top_publisher_share", "venue_hhi", "publisher_hhi", "top_conference_keyword_share"]
    return pivot_baseline_variant(concentration, value_cols, id_cols)


def compute_open_access_preprint_delta(open_access: pd.DataFrame) -> pd.DataFrame:
    id_cols = ["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system"]
    value_cols = ["open_access_share", "preprint_share", "recent_3y_share", "recent_5y_share"]
    return pivot_baseline_variant(open_access, value_cols, id_cols)


def compute_metadata_risk_delta(pairwise: pd.DataFrame) -> pd.DataFrame:
    if pairwise is None or pairwise.empty:
        return pd.DataFrame()
    out = pairwise.copy()
    out["open_access_share_delta"] = out["open_access_share_variant"] - out["open_access_share_baseline"]
    out["last_3_years_share_delta"] = out["share_last_3_years_variant"] - out["share_last_3_years_baseline"]
    return add_plot_labels(out)


def compute_geographic_delta(geographic: pd.DataFrame) -> pd.DataFrame:
    if geographic is None or geographic.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in geographic.groupby(["pair_id", "bias_type", "source_system_type", "source_system", "geo_bucket"], dropna=False):
        base = group[group["query_type"] == "baseline"]["share"].sum()
        var = group[group["query_type"] == "variant"]["share"].sum()
        row = dict(zip(["pair_id", "bias_type", "source_system_type", "source_system", "geo_bucket"], keys))
        row.update({"share_baseline": base, "share_variant": var, "share_delta": var - base})
        rows.append(row)
    return add_plot_labels(pd.DataFrame(rows))


def compute_language_delta(language: pd.DataFrame) -> pd.DataFrame:
    if language is None or language.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in language.groupby(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "language_bucket"], dropna=False):
        base = group[group["query_type"] == "baseline"]["share"].sum()
        var = group[group["query_type"] == "variant"]["share"].sum()
        row = dict(zip(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "language_bucket"], keys))
        row.update({"share_baseline": base, "share_variant": var, "share_delta": var - base})
        rows.append(row)
    return add_plot_labels(pd.DataFrame(rows))


def compute_open_access_preprint_shift(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    subset = mapped[mapped["pair_id"].isin({"A06", "A03"})].copy()
    if subset.empty:
        return pd.DataFrame()
    return (
        subset.groupby(["experiment_set", "pair_id", "bias_type", "source_system_type", "source_system", "query_type"], dropna=False)
        .agg(
            record_count=("record_id", "count"),
            open_access_share=("is_open_access", bool_share),
            preprint_share=("source_type", lambda s: (s == "preprint").mean()),
            recent_3y_share=("year", lambda s: (pd.to_numeric(s, errors="coerce") >= CURRENT_YEAR - 3).mean()),
            recent_5y_share=("year", lambda s: (pd.to_numeric(s, errors="coerce") >= CURRENT_YEAR - 5).mean()),
        )
        .reset_index()
    )


def compute_model_provider_ranking(pairwise: pd.DataFrame, mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    base = (
        mapped.groupby(["source_system_type", "source_system"], dropna=False)
        .agg(
            record_count=("record_id", "count"),
            metadata_completeness=("metadata_completeness_score", "mean"),
            hallucination_risk=("hallucination_risk", bool_share),
            enrichment_success=("enrichment_success", bool_share),
        )
        .reset_index()
    )
    if not pairwise.empty:
        sens = pairwise.groupby(["source_system_type", "source_system"], dropna=False).agg(query_sensitivity=("jaccard_similarity", lambda s: 1 - s.mean())).reset_index()
        base = base.merge(sens, on=["source_system_type", "source_system"], how="left")
    else:
        base["query_sensitivity"] = None
    base["ranking_score"] = (
        base["metadata_completeness"].fillna(0)
        + base["enrichment_success"].fillna(0)
        + (1 - base["hallucination_risk"].fillna(1))
        + (1 - base["query_sensitivity"].fillna(0.5))
    )
    return base.sort_values("ranking_score", ascending=False)


def compute_llm_provider_overlap(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    rows = []
    for query, query_group in mapped.groupby("query"):
        llm = query_group[query_group["source_system_type"] == "llm"]
        prov = query_group[query_group["source_system_type"] == "scholarly_provider"]
        if llm.empty or prov.empty:
            continue
        for model, model_group in llm.groupby("source_system"):
            mset = identity_set(model_group)
            for provider, provider_group in prov.groupby("source_system"):
                pset = identity_set(provider_group)
                rows.append(
                    {
                        "query": query,
                        "model": model,
                        "provider": provider,
                        "intersection_count": len(mset & pset),
                        "union_count": len(mset | pset),
                        "jaccard_similarity": safe_ratio(len(mset & pset), len(mset | pset)),
                    }
                )
    return pd.DataFrame(rows)


def build_thesis_candidate_figures(
    *,
    pairwise: pd.DataFrame,
    metadata: pd.DataFrame,
    hallucination: pd.DataFrame,
    geographic: pd.DataFrame,
    language: pd.DataFrame,
    concentration_delta: pd.DataFrame,
    open_access_delta: pd.DataFrame,
    llm_provider_overlap: pd.DataFrame,
) -> pd.DataFrame:
    def completeness(df: pd.DataFrame, column: str | None = None) -> float:
        if df is None or df.empty:
            return 1.0
        if column and column in df:
            return min(5.0, max(1.0, 1 + 4 * df[column].notna().mean()))
        return 4.0

    def effect(df: pd.DataFrame, column: str) -> float:
        if df is None or df.empty or column not in df:
            return 1.0
        vals = pd.to_numeric(df[column], errors="coerce").dropna().abs()
        if vals.empty:
            return 1.0
        return min(5.0, max(1.0, 1 + 8 * vals.mean()))

    rows = [
        {
            "figure_file": "fig_core_jaccard_by_model_provider.png",
            "experiment_set": "A",
            "metric": "Jaccard similarity",
            "visual_readability_score": 5,
            "interpretability_score": 5,
            "data_completeness_score": completeness(pairwise, "jaccard_similarity"),
            "effect_score": 5 - effect(pairwise, "jaccard_similarity") + 2,
            "reason": "Directly shows whether bias-triggering variants changed retrieved/generated result sets.",
            "possible_thesis_claim": "Bias-triggering query variants changed result sets relative to baseline queries.",
        },
        {
            "figure_file": "fig_core_topk_overlap_by_model_provider.png",
            "experiment_set": "A",
            "metric": "Top-K overlap",
            "visual_readability_score": 5,
            "interpretability_score": 5,
            "data_completeness_score": completeness(pairwise, "topk_overlap"),
            "effect_score": 5 - effect(pairwise, "topk_overlap") + 2,
            "reason": "Focuses on the most visible records, which are most important for search user experience.",
            "possible_thesis_claim": "Top-ranked results are sensitive to bias-triggering query wording.",
        },
        {
            "figure_file": "fig_publication_year_shift.png",
            "experiment_set": "A/B/C/D",
            "metric": "Publication year delta",
            "visual_readability_score": 4,
            "interpretability_score": 5,
            "data_completeness_score": completeness(pairwise, "publication_year_delta"),
            "effect_score": effect(pairwise, "publication_year_delta") / 2,
            "reason": "Delta directly communicates whether variants shifted toward newer or older work.",
            "possible_thesis_claim": "Some query framings shift results toward newer or older publications.",
        },
        {
            "figure_file": "fig_metadata_completeness_delta.png",
            "experiment_set": "A/B/C/D",
            "metric": "Metadata completeness delta",
            "visual_readability_score": 5,
            "interpretability_score": 4,
            "data_completeness_score": completeness(pairwise, "metadata_completeness_delta"),
            "effect_score": effect(pairwise, "metadata_completeness_delta"),
            "reason": "Shows whether variant wording affects record inspectability and export quality.",
            "possible_thesis_claim": "Some variants reduce or improve metadata completeness compared with baselines.",
        },
        {
            "figure_file": "fig_hallucination_risk_delta.png",
            "experiment_set": "A/B/C/D",
            "metric": "High-risk share delta",
            "visual_readability_score": 5,
            "interpretability_score": 5,
            "data_completeness_score": completeness(hallucination, "high_risk_share"),
            "effect_score": effect(pairwise, "hallucination_risk_delta"),
            "reason": "Uses explicit bibliographic verification risk criteria rather than vague hallucination language.",
            "possible_thesis_claim": "Some query variants increase bibliographic verifiability risk for selected LLMs.",
        },
        {
            "figure_file": "fig_venue_concentration_delta.png",
            "experiment_set": "B/C",
            "metric": "Venue concentration delta",
            "visual_readability_score": 5,
            "interpretability_score": 5,
            "data_completeness_score": completeness(concentration_delta, "top_venue_share_delta"),
            "effect_score": effect(concentration_delta, "top_venue_share_delta"),
            "reason": "Delta view is more interpretable than raw venue concentration rows.",
            "possible_thesis_claim": "Prestige/popularity wording increases venue concentration for some systems.",
        },
        {
            "figure_file": "fig_publisher_concentration_delta.png",
            "experiment_set": "B/C",
            "metric": "Publisher concentration delta",
            "visual_readability_score": 5,
            "interpretability_score": 4,
            "data_completeness_score": completeness(concentration_delta, "top_publisher_share_delta"),
            "effect_score": effect(concentration_delta, "top_publisher_share_delta"),
            "reason": "Shows publisher concentration shifts without plotting every raw row.",
            "possible_thesis_claim": "Some query variants concentrate results around fewer publishers.",
        },
        {
            "figure_file": "fig_open_access_preprint_delta.png",
            "experiment_set": "A",
            "metric": "Open access/preprint delta",
            "visual_readability_score": 5,
            "interpretability_score": 4,
            "data_completeness_score": completeness(open_access_delta, "preprint_share_delta"),
            "effect_score": effect(open_access_delta, "preprint_share_delta"),
            "reason": "Useful for latest/preprint framing if OA/preprint metadata is populated.",
            "possible_thesis_claim": "Latest-style queries may shift preprint or open-access shares.",
        },
        {
            "figure_file": "fig_language_target_delta.png",
            "experiment_set": "D",
            "metric": "Target-language share delta",
            "visual_readability_score": 5,
            "interpretability_score": 4,
            "data_completeness_score": completeness(language, "share"),
            "effect_score": 4,
            "reason": "Directly tests whether language-specific wording changes language metadata.",
            "possible_thesis_claim": "Language-specific queries do not always shift records toward the target language.",
        },
        {
            "figure_file": "fig_geographic_africa_delta.png",
            "experiment_set": "A",
            "metric": "Africa/Global South share delta",
            "visual_readability_score": 5,
            "interpretability_score": 4,
            "data_completeness_score": completeness(geographic, "share"),
            "effect_score": 4,
            "reason": "Useful if country metadata or clearly marked geographic heuristics are present.",
            "possible_thesis_claim": "Geographic framing changes country/region indicators only where metadata supports it.",
        },
        {
            "figure_file": "fig_llm_provider_overlap_heatmap.png",
            "experiment_set": "A",
            "metric": "LLM-provider overlap",
            "visual_readability_score": 4,
            "interpretability_score": 5,
            "data_completeness_score": completeness(llm_provider_overlap, "jaccard_similarity"),
            "effect_score": effect(llm_provider_overlap, "jaccard_similarity"),
            "reason": "Connects LLM-generated citations to scholarly provider result sets.",
            "possible_thesis_claim": "LLM outputs resemble scholarly provider results unevenly across models and providers.",
        },
    ]
    out = pd.DataFrame(rows)
    out["thesis_usefulness_score"] = (
        out["visual_readability_score"]
        + out["interpretability_score"]
        + out["data_completeness_score"]
        + out["effect_score"].clip(1, 5)
    ) / 4
    out["recommended_for_thesis"] = out["thesis_usefulness_score"] >= 3.6
    return out.drop(columns=["effect_score"]).sort_values("thesis_usefulness_score", ascending=False)


def build_thesis_safe_claims(candidate_figures: pd.DataFrame) -> pd.DataFrame:
    recommended = set(candidate_figures.loc[candidate_figures["recommended_for_thesis"], "figure_file"]) if not candidate_figures.empty else set()

    def strength(fig: str) -> str:
        return "strong" if fig in recommended else "moderate"

    return pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "claim": "Bias-triggering query variants changed the retrieved or generated result sets compared with baseline queries.",
                "supporting_metric": "Jaccard similarity and top-K overlap",
                "supporting_figure": "fig_core_jaccard_by_model_provider.png; fig_core_topk_overlap_by_model_provider.png",
                "supporting_table": "table_pairwise_comparison_summary.csv",
                "strength": "strong",
                "limitations": "Overlap indicates result-set sensitivity; it does not identify the causal mechanism behind each shift.",
            },
            {
                "claim_id": "C2",
                "claim": "Prestige- and popularity-oriented wording increased venue concentration for some systems.",
                "supporting_metric": "Variant minus baseline top venue share",
                "supporting_figure": "fig_venue_concentration_delta.png",
                "supporting_table": "table_venue_publisher_concentration_delta.csv",
                "strength": strength("fig_venue_concentration_delta.png"),
                "limitations": "Venue concentration is a proxy for prestige bias when explicit venue-ranking metadata is unavailable.",
            },
            {
                "claim_id": "C3",
                "claim": "Some query variants increased bibliographic verifiability risk for selected LLMs.",
                "supporting_metric": "Variant minus baseline high-risk share",
                "supporting_figure": "fig_hallucination_risk_delta.png",
                "supporting_table": "table_pairwise_comparison_summary.csv",
                "strength": strength("fig_hallucination_risk_delta.png"),
                "limitations": "Risk is based on DOI validity, enrichment failure, canonical mismatch, and missing metadata; it is not a direct factuality judgment.",
            },
            {
                "claim_id": "C4",
                "claim": "Language-specific queries did not always shift results toward the requested language based on available language metadata.",
                "supporting_metric": "Target-language share delta",
                "supporting_figure": "fig_language_target_delta.png",
                "supporting_table": "table_language_shift_delta.csv",
                "strength": strength("fig_language_target_delta.png"),
                "limitations": "Language claims are weak where direct language metadata is missing and heuristic labels are used.",
            },
            {
                "claim_id": "C5",
                "claim": "LLM-generated literature lists overlap unevenly with scholarly provider result sets.",
                "supporting_metric": "Model-provider Jaccard similarity",
                "supporting_figure": "fig_llm_provider_overlap_heatmap.png",
                "supporting_table": "table_llm_provider_overlap.csv",
                "strength": strength("fig_llm_provider_overlap_heatmap.png"),
                "limitations": "Overlap is computed from DOI/title identity sets and depends on provider coverage and normalization quality.",
            },
            {
                "claim_id": "C6",
                "claim": "Latest-style query wording may shift results toward newer records and preprint/open-access indicators.",
                "supporting_metric": "Publication year, preprint share, and open-access share deltas",
                "supporting_figure": "fig_publication_year_shift.png; fig_open_access_preprint_delta.png",
                "supporting_table": "table_open_access_preprint_delta.csv",
                "strength": "moderate",
                "limitations": "Preprint and OA indicators depend on source type, URL, venue, DOI, and enrichment fields; missing fields weaken the claim.",
            },
        ]
    )


def export_selected_figures(candidate_figures: pd.DataFrame, figures_dir: Path | str, selected_dir: Path | str) -> pd.DataFrame:
    figures_dir = Path(figures_dir)
    selected_dir = Path(selected_dir)
    selected_dir.mkdir(parents=True, exist_ok=True)
    if candidate_figures is None or candidate_figures.empty:
        return pd.DataFrame()
    rows = []
    for _, row in candidate_figures[candidate_figures["recommended_for_thesis"]].iterrows():
        src = figures_dir / row["figure_file"]
        if not src.exists():
            continue
        dst = selected_dir / src.name
        shutil.copy2(src, dst)
        svg = src.with_suffix(".svg")
        if svg.exists():
            shutil.copy2(svg, selected_dir / svg.name)
        item = row.to_dict()
        item["selected_path"] = str(dst)
        rows.append(item)
    return pd.DataFrame(rows)


def compute_provider_comparison(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    return (
        mapped.groupby(["source_system_type", "source_system", "query"], dropna=False)
        .agg(
            record_count=("record_id", "count"),
            metadata_completeness=("metadata_completeness_score", "mean"),
            doi_coverage=("doi", lambda s: s.apply(has_value).mean()),
            venue_coverage=("venue", lambda s: s.apply(has_value).mean()),
            publisher_coverage=("publisher", lambda s: s.apply(has_value).mean()),
            mean_year=("year", lambda s: pd.to_numeric(s, errors="coerce").mean()),
            unique_venues=("venue", lambda s: s.dropna().nunique()),
            top_venue_share=("venue", top_share),
        )
        .reset_index()
    )


def compute_thematic_shift(mapped: pd.DataFrame) -> pd.DataFrame:
    if mapped.empty:
        return pd.DataFrame()
    subset = mapped[mapped["pair_id"].isin({"A09"})].copy()
    rows = []
    for keys, group in subset.groupby(["pair_id", "source_system_type", "source_system", "query_type"], dropna=False):
        text = group.apply(lambda r: " ".join(str(r.get(col) or "") for col in ("title", "abstract", "venue", "publisher")), axis=1)
        row = dict(zip(["pair_id", "source_system_type", "source_system", "query_type"], keys))
        row["record_count"] = len(group)
        for label, keywords in THEMATIC_KEYWORDS.items():
            row[f"{label}_keyword_share"] = text.apply(lambda value: text_contains_any(value, keywords)).mean() if len(text) else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def export_tables(tables: dict[str, pd.DataFrame], output_dir: Path | str, save: bool = True) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not save:
        return
    for name, df in tables.items():
        path = output_dir / f"{name}.csv"
        (df if df is not None else pd.DataFrame()).to_csv(path, index=False)


@dataclass
class PlotStyle:
    width: int = 1500
    height: int = 900
    margin_left: int = 260
    margin_right: int = 60
    margin_top: int = 120
    margin_bottom: int = 180
    bg: str = "white"
    fg: str = "#1f2933"
    grid: str = "#d9e2ec"
    accent: str = "#2f6f9f"
    accent_2: str = "#c2410c"
    accent_3: str = "#047857"


def apply_thesis_plot_style(ax, title=None, xlabel=None, ylabel=None):
    """Apply a thesis-friendly matplotlib style when matplotlib is available."""

    if ax is None:
        return ax
    if title:
        ax.set_title("\n".join(textwrap.wrap(str(title), 78)), fontsize=15, pad=14)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=12)
    ax.tick_params(axis="both", labelsize=10)
    ax.grid(axis="x", alpha=0.25)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    return ax


def _font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_text(draw, xy, text, fill="#1f2933", size=24, bold=False, anchor=None):
    text = str(text)
    font = _font(size, bold)
    if "\n" not in text:
        draw.text(xy, text, fill=fill, font=font, anchor=anchor)
        return
    # Older Pillow versions do not support anchors for multiline text.
    x, y = xy
    lines = text.splitlines()
    line_h = size + 3
    widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
    total_h = line_h * len(lines)
    if anchor and "m" in anchor:
        y -= total_h / 2
    if anchor and "r" in anchor:
        x -= max(widths)
    elif anchor and "m" in anchor:
        x -= max(widths) / 2
    draw.multiline_text((x, y), text, fill=fill, font=font, spacing=3)


def _wrap_label(text: str, width: int = 22) -> str:
    return "\n".join(textwrap.wrap(str(text), width=width)) or str(text)


def _save_svg_bar(
    df: pd.DataFrame,
    *,
    category: str,
    value: str,
    title: str,
    output_path: Path,
    max_items: int,
    diverging: bool = False,
) -> None:
    data = df[[category, value]].dropna(subset=[category, value]).head(max_items).copy()
    if data.empty:
        return
    data[value] = pd.to_numeric(data[value], errors="coerce").fillna(0)
    width, height = 1500, max(620, 130 + len(data) * 46)
    left, right, top, bottom = 320, 70, 92, 72
    plot_w = width - left - right
    values = data[value].astype(float)
    if diverging:
        vmax = max(abs(values.min()), abs(values.max()), 1e-9)
        zero_x = left + plot_w / 2
        scale = plot_w / 2 / vmax
    else:
        vmax = max(values.max(), 1e-9)
        zero_x = left
        scale = plot_w / vmax
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left}" y="44" font-family="Arial, sans-serif" font-size="30" font-weight="700" fill="#1f2933">{_xml(title)}</text>',
    ]
    if diverging:
        rows.append(f'<line x1="{zero_x:.1f}" y1="{top-20}" x2="{zero_x:.1f}" y2="{height-bottom+12}" stroke="#475569" stroke-width="2"/>')
    for i, item in data.reset_index(drop=True).iterrows():
        y = top + i * 46
        val = float(item[value])
        color = "#047857" if val >= 0 else "#c2410c"
        if diverging:
            x = zero_x if val >= 0 else zero_x + val * scale
            w = abs(val * scale)
        else:
            x = zero_x
            w = max(1, val * scale)
            color = "#2f6f9f"
        rows.append(f'<text x="{left-12}" y="{y+21}" text-anchor="end" font-family="Arial, sans-serif" font-size="17" fill="#1f2933">{_xml(str(item[category]))}</text>')
        rows.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="26" fill="{color}"/>')
        rows.append(f'<text x="{x + w + 8 if val >= 0 else x - 8:.1f}" y="{y+20}" text-anchor="{"start" if val >= 0 else "end"}" font-family="Arial, sans-serif" font-size="16" fill="#1f2933">{val:.2f}</text>')
    rows.append("</svg>")
    output_path.with_suffix(".svg").write_text("\n".join(rows), encoding="utf-8")


def _xml(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def bar_chart(
    df: pd.DataFrame,
    *,
    category: str,
    value: str,
    title: str,
    output_path: Path | str,
    color_by: str | None = None,
    max_items: int = 30,
    diverging: bool = False,
    style: PlotStyle | None = None,
) -> None:
    if df is None or df.empty or Image is None:
        return
    style = style or PlotStyle()
    data = df[[category, value] + ([color_by] if color_by else [])].dropna(subset=[category, value]).head(max_items).copy()
    if data.empty:
        return
    data[value] = pd.to_numeric(data[value], errors="coerce").fillna(0)
    img = Image.new("RGB", (style.width, style.height), style.bg)
    draw = ImageDraw.Draw(img)
    _draw_text(draw, (style.margin_left, 42), title, size=34, bold=True)
    plot_w = style.width - style.margin_left - style.margin_right
    plot_h = style.height - style.margin_top - style.margin_bottom
    y0 = style.margin_top
    if diverging:
        max_val = max(abs(float(data[value].min())), abs(float(data[value].max())), 1e-9)
        zero_x = style.margin_left + plot_w / 2
    else:
        max_val = max(float(data[value].max()), 1e-9)
        zero_x = style.margin_left
    n = len(data)
    bar_h = max(12, int(plot_h / max(n, 1) * 0.62))
    gap = max(6, int(plot_h / max(n, 1) * 0.38))
    colors = [style.accent, style.accent_2, style.accent_3, "#7c3aed", "#b45309", "#0f766e"]
    color_map = {}
    if color_by:
        for i, label in enumerate(sorted(data[color_by].dropna().unique())):
            color_map[label] = colors[i % len(colors)]
    for i, row in data.reset_index(drop=True).iterrows():
        y = y0 + i * (bar_h + gap)
        raw_value = float(row[value])
        if diverging:
            bar_w = int((plot_w / 2) * abs(raw_value) / max_val)
            bar_x = zero_x if raw_value >= 0 else zero_x - bar_w
            color = style.accent_3 if raw_value >= 0 else style.accent_2
        else:
            bar_w = int(plot_w * raw_value / max_val)
            bar_x = style.margin_left
            color = color_map.get(row.get(color_by), style.accent)
        draw.rectangle((bar_x, y, bar_x + bar_w, y + bar_h), fill=color)
        _draw_text(draw, (style.margin_left - 12, y + bar_h / 2), _wrap_label(row[category], 30), size=18, anchor="rm")
        label_x = bar_x + bar_w + 8 if raw_value >= 0 else bar_x - 8
        label_anchor = "lm" if raw_value >= 0 else "rm"
        _draw_text(draw, (label_x, y + bar_h / 2), f"{raw_value:.2f}", size=18, anchor=label_anchor)
    if diverging:
        draw.line((zero_x, y0 - 12, zero_x, y0 + plot_h), fill="#475569", width=2)
    draw.line((style.margin_left, y0, style.margin_left, y0 + plot_h), fill=style.fg, width=2)
    draw.line((style.margin_left, y0 + plot_h, style.width - style.margin_right, y0 + plot_h), fill=style.fg, width=2)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    _save_svg_bar(data, category=category, value=value, title=title, output_path=Path(output_path), max_items=max_items, diverging=diverging)


def heatmap_chart(
    df: pd.DataFrame,
    *,
    row: str,
    col: str,
    value: str,
    title: str,
    output_path: Path | str,
    style: PlotStyle | None = None,
) -> None:
    if df is None or df.empty or Image is None:
        return
    style = style or PlotStyle(width=1500, height=1000, margin_left=330, margin_bottom=260)
    pivot = df.pivot_table(index=row, columns=col, values=value, aggfunc="mean").fillna(0)
    if pivot.empty:
        return
    rows = list(pivot.index)
    cols = list(pivot.columns)
    cell_w = max(70, int((style.width - style.margin_left - style.margin_right) / max(len(cols), 1)))
    cell_h = max(42, int((style.height - style.margin_top - style.margin_bottom) / max(len(rows), 1)))
    img = Image.new("RGB", (style.width, style.height), style.bg)
    draw = ImageDraw.Draw(img)
    _draw_text(draw, (style.margin_left, 42), title, size=34, bold=True)
    max_val = max(float(pivot.max().max()), 1e-9)
    for c, col_name in enumerate(cols):
        x = style.margin_left + c * cell_w + cell_w / 2
        _draw_text(draw, (x, style.margin_top - 14), _wrap_label(col_name, 12), size=16, anchor="mb")
    for r, row_name in enumerate(rows):
        y = style.margin_top + r * cell_h
        _draw_text(draw, (style.margin_left - 12, y + cell_h / 2), _wrap_label(row_name, 34), size=17, anchor="rm")
        for c, col_name in enumerate(cols):
            x = style.margin_left + c * cell_w
            val = float(pivot.loc[row_name, col_name])
            intensity = int(245 - 170 * (val / max_val))
            color = (intensity, int(255 - 110 * (val / max_val)), 255)
            draw.rectangle((x, y, x + cell_w - 2, y + cell_h - 2), fill=color, outline=style.bg)
            _draw_text(draw, (x + cell_w / 2, y + cell_h / 2), f"{val:.2f}", size=15, anchor="mm")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)


def grouped_share_chart(
    df: pd.DataFrame,
    *,
    group_col: str,
    segment_col: str,
    share_col: str,
    title: str,
    output_path: Path | str,
) -> None:
    if df is None or df.empty or Image is None:
        return
    pivot = df.pivot_table(index=group_col, columns=segment_col, values=share_col, aggfunc="sum").fillna(0)
    if pivot.empty:
        return
    style = PlotStyle(width=1500, height=900, margin_left=320, margin_bottom=140)
    img = Image.new("RGB", (style.width, style.height), style.bg)
    draw = ImageDraw.Draw(img)
    _draw_text(draw, (style.margin_left, 42), title, size=34, bold=True)
    colors = ["#2f6f9f", "#c2410c", "#047857", "#7c3aed", "#b45309", "#475569", "#be123c"]
    plot_w = style.width - style.margin_left - style.margin_right
    plot_h = style.height - style.margin_top - style.margin_bottom
    bar_h = max(16, int(plot_h / len(pivot.index) * 0.60))
    gap = max(8, int(plot_h / len(pivot.index) * 0.40))
    for i, (idx, values) in enumerate(pivot.iterrows()):
        y = style.margin_top + i * (bar_h + gap)
        x = style.margin_left
        _draw_text(draw, (x - 12, y + bar_h / 2), _wrap_label(idx, 36), size=17, anchor="rm")
        for j, (segment, val) in enumerate(values.items()):
            w = int(plot_w * float(val))
            draw.rectangle((x, y, x + w, y + bar_h), fill=colors[j % len(colors)])
            if w > 55:
                _draw_text(draw, (x + w / 2, y + bar_h / 2), f"{val:.0%}", fill="white", size=14, bold=True, anchor="mm")
            x += w
    legend_y = style.height - 92
    x = style.margin_left
    for j, segment in enumerate(pivot.columns):
        draw.rectangle((x, legend_y, x + 24, legend_y + 24), fill=colors[j % len(colors)])
        _draw_text(draw, (x + 32, legend_y + 12), segment, size=17, anchor="lm")
        x += 32 + min(260, 10 * len(str(segment)))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)


def save_required_figures(
    *,
    figures_dir: Path | str,
    mapped: pd.DataFrame,
    pairwise: pd.DataFrame,
    metadata: pd.DataFrame,
    hallucination: pd.DataFrame,
    geographic: pd.DataFrame,
    language: pd.DataFrame,
    concentration: pd.DataFrame,
    open_access: pd.DataFrame,
    ranking: pd.DataFrame,
    llm_provider_overlap: pd.DataFrame,
    provider_comparison: pd.DataFrame,
    save: bool = True,
) -> list[Path]:
    figures_dir = Path(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)
    if not save:
        return []
    created: list[Path] = []

    def out(name: str) -> Path:
        path = figures_dir / name
        created.append(path)
        return path

    if not pairwise.empty:
        pairwise_labeled = add_plot_labels(pairwise)
        core = pairwise_labeled[pairwise_labeled["experiment_set"] == "A"].copy()
        if not core.empty:
            core_agg = core.groupby(["pair_id", "bias_type"], as_index=False).agg(
                jaccard_similarity=("jaccard_similarity", "median"),
                topk_overlap=("topk_overlap", "median"),
            )
            core_agg["label"] = core_agg["pair_id"] + " · " + core_agg["bias_type"]
            bar_chart(core_agg.sort_values("jaccard_similarity"), category="label", value="jaccard_similarity", title="Core Query Result-Set Shift (Median Jaccard)", output_path=out("fig_core_jaccard_by_model_provider.png"), max_items=20)
            bar_chart(core_agg.sort_values("topk_overlap"), category="label", value="topk_overlap", title="Core Query Top-K Overlap (Median)", output_path=out("fig_core_topk_overlap_by_model_provider.png"), max_items=20)
        year = pairwise_labeled.groupby(["pair_id", "bias_type"], as_index=False)["publication_year_delta"].median()
        year["label"] = year["pair_id"] + " · " + year["bias_type"]
        bar_chart(year.sort_values("publication_year_delta", ascending=False), category="label", value="publication_year_delta", title="Publication Year Shift: Variant Minus Baseline", output_path=out("fig_publication_year_shift.png"), max_items=28, diverging=True)
        deltas = add_plot_labels(pairwise)
        deltas["label"] = deltas.apply(lambda r: plot_label(r["pair_id"], r["source_system"]), axis=1)
        bar_chart(deltas.reindex(deltas["metadata_completeness_delta"].abs().sort_values(ascending=False).index), category="label", value="metadata_completeness_delta", title="Metadata Completeness Delta: Variant Minus Baseline", output_path=out("fig_metadata_completeness_delta.png"), max_items=20, diverging=True)
        bar_chart(deltas.reindex(deltas["hallucination_risk_delta"].abs().sort_values(ascending=False).index), category="label", value="hallucination_risk_delta", title="High-Risk Share Delta: Variant Minus Baseline", output_path=out("fig_hallucination_risk_delta.png"), max_items=20, diverging=True)
    if not metadata.empty:
        heat = metadata.copy()
        heat["row_label"] = heat["source_system_type"] + " | " + heat["source_system"].map(short_source_label)
        heatmap_chart(heat, row="row_label", col="query_type", value="metadata_completeness", title="Metadata Completeness by Source and Query Type", output_path=out("fig_metadata_completeness_heatmap.png"))
    if not hallucination.empty:
        hall = hallucination.copy()
        hall_agg = hall.groupby(["bias_type", "query_type"], as_index=False)["high_risk_share"].mean()
        hall_agg["label"] = hall_agg["bias_type"] + " · " + hall_agg["query_type"].map(short_query_type_label)
        bar_chart(hall_agg.sort_values("high_risk_share", ascending=False), category="label", value="high_risk_share", title="High Bibliographic Risk Share by Bias Type", output_path=out("fig_hallucination_risk_by_bias_type.png"), max_items=24)
    if not geographic.empty:
        africa = geographic[geographic["pair_id"] == "A01"].copy()
        if not africa.empty:
            africa["group"] = africa["source_system"].astype(str) + " | " + africa["query_type"]
            grouped_share_chart(africa, group_col="group", segment_col="geo_bucket", share_col="share", title="Geographic Shift: Healthcare Africa Query", output_path=out("fig_geographic_shift_africa.png"))
        china = geographic[geographic["pair_id"] == "A08"].copy()
        if not china.empty:
            china["group"] = china["source_system"].astype(str) + " | " + china["query_type"]
            grouped_share_chart(china, group_col="group", segment_col="geo_bucket", share_col="share", title="Geographic Shift: AI Regulation China Query", output_path=out("fig_geographic_shift_china_regulation.png"))
    if not language.empty:
        lang = language.copy()
        lang["group"] = lang["pair_id"] + " | " + lang["source_system"].astype(str) + " | " + lang["query_type"]
        grouped_share_chart(lang, group_col="group", segment_col="language_bucket", share_col="share", title="Language Metadata Shift", output_path=out("fig_language_shift.png"))
    if not concentration.empty:
        conc = add_plot_labels(concentration)
        conc_agg = conc.groupby(["pair_id", "bias_type", "query_type"], as_index=False).agg(
            top_venue_share=("top_venue_share", "median"),
            top_publisher_share=("top_publisher_share", "median"),
        )
        conc_agg["label"] = conc_agg["pair_id"] + " · " + conc_agg["query_type"].map(short_query_type_label)
        bar_chart(conc_agg.sort_values("top_venue_share", ascending=False), category="label", value="top_venue_share", title="Venue Concentration by Pair (Median Top Venue Share)", output_path=out("fig_venue_concentration.png"), max_items=24)
        bar_chart(conc_agg.sort_values("top_publisher_share", ascending=False), category="label", value="top_publisher_share", title="Publisher Concentration by Pair (Median Top Publisher Share)", output_path=out("fig_publisher_concentration.png"), max_items=24)
        by_bias = conc.groupby(["bias_type", "query_type"], as_index=False).agg(top_venue_share=("top_venue_share", "mean"))
        by_bias["label"] = by_bias["bias_type"] + " · " + by_bias["query_type"].map(short_query_type_label)
        bar_chart(by_bias.sort_values("top_venue_share", ascending=False), category="label", value="top_venue_share", title="Venue Concentration by Bias Type", output_path=out("fig_venue_concentration_by_bias_type.png"), max_items=20)
        top_cases = conc.copy()
        top_cases["label"] = top_cases.apply(lambda r: plot_label(r["pair_id"], r["source_system"], r["query_type"]), axis=1)
        bar_chart(top_cases.sort_values("top_venue_share", ascending=False), category="label", value="top_venue_share", title="Top Venue Concentration Cases", output_path=out("fig_venue_concentration_top_models.png"), max_items=15)
        conc_delta = compute_concentration_delta(concentration)
        if not conc_delta.empty:
            conc_delta["label"] = conc_delta.apply(lambda r: plot_label(r["pair_id"], r["source_system"]), axis=1)
            bar_chart(conc_delta.reindex(conc_delta["top_venue_share_delta"].abs().sort_values(ascending=False).index), category="label", value="top_venue_share_delta", title="Venue Concentration Delta: Variant Minus Baseline", output_path=out("fig_venue_concentration_delta.png"), max_items=20, diverging=True)
            bar_chart(conc_delta.reindex(conc_delta["top_publisher_share_delta"].abs().sort_values(ascending=False).index), category="label", value="top_publisher_share_delta", title="Publisher Concentration Delta: Variant Minus Baseline", output_path=out("fig_publisher_concentration_delta.png"), max_items=20, diverging=True)
    if not open_access.empty:
        oa = add_plot_labels(open_access)
        oa["label"] = oa.apply(lambda r: plot_label(r["pair_id"], r["source_system"], r["query_type"]), axis=1)
        bar_chart(oa.sort_values("preprint_share", ascending=False), category="label", value="preprint_share", title="Preprint Share for Latest/OA Pairs", output_path=out("fig_open_access_preprint_shift.png"), max_items=18)
        oa_delta = compute_open_access_preprint_delta(open_access)
        if not oa_delta.empty:
            oa_delta["label"] = oa_delta.apply(lambda r: plot_label(r["pair_id"], r["source_system"]), axis=1)
            bar_chart(oa_delta.reindex(oa_delta["preprint_share_delta"].abs().sort_values(ascending=False).index), category="label", value="preprint_share_delta", title="Preprint Share Delta: Variant Minus Baseline", output_path=out("fig_open_access_preprint_delta.png"), max_items=20, diverging=True)
    if not hallucination.empty:
        disc = hallucination[hallucination["pair_id"].isin({"A07"})].copy()
        if not disc.empty:
            disc["label"] = disc["source_system"].map(short_source_label) + " · " + disc["query_type"].map(short_query_type_label)
            bar_chart(disc.sort_values("metadata_completeness", ascending=False), category="label", value="metadata_completeness", title="Disciplinary Pair: Metadata Completeness", output_path=out("fig_disciplinary_metadata_risk.png"), max_items=25)
    if not ranking.empty:
        rank = ranking.copy()
        rank["label"] = rank["source_system_type"] + " | " + rank["source_system"].map(short_source_label)
        bar_chart(rank.sort_values("ranking_score", ascending=False), category="label", value="ranking_score", title="Model and Provider Summary Ranking", output_path=out("fig_model_provider_summary_ranking.png"), max_items=35)
    if not llm_provider_overlap.empty:
        overlap = llm_provider_overlap.groupby(["model", "provider"], dropna=False)["jaccard_similarity"].mean().reset_index()
        overlap["model"] = overlap["model"].map(short_source_label)
        overlap["provider"] = overlap["provider"].map(short_source_label)
        heatmap_chart(overlap, row="model", col="provider", value="jaccard_similarity", title="LLM to Scholarly Provider Overlap", output_path=out("fig_llm_provider_overlap_heatmap.png"))
    if not provider_comparison.empty:
        prov = provider_comparison.copy()
        prov["label"] = prov["source_system_type"] + " | " + prov["source_system"].map(short_source_label)
        bar_chart(prov.groupby("label", as_index=False)["metadata_completeness"].mean().sort_values("metadata_completeness", ascending=False), category="label", value="metadata_completeness", title="Provider Metadata Completeness", output_path=out("fig_provider_metadata_completeness.png"), max_items=30)
        coverage = prov.groupby("query", as_index=False)["doi_coverage"].mean().sort_values("doi_coverage")
        bar_chart(coverage, category="query", value="doi_coverage", title="Provider/Model DOI Coverage by Query", output_path=out("fig_provider_coverage_by_query.png"), max_items=30)
    geo_delta = compute_geographic_delta(geographic)
    if not geo_delta.empty:
        africa_delta = geo_delta[(geo_delta["pair_id"] == "A01") & (geo_delta["geo_bucket"].str.contains("Africa|Global South", na=False))].copy()
        if not africa_delta.empty:
            africa_delta["label"] = africa_delta.apply(lambda r: plot_label(r["pair_id"], r["source_system"]) + " · " + r["geo_bucket"], axis=1)
            bar_chart(africa_delta.reindex(africa_delta["share_delta"].abs().sort_values(ascending=False).index), category="label", value="share_delta", title="Africa / Global South Share Delta", output_path=out("fig_geographic_africa_delta.png"), max_items=20, diverging=True)
    lang_delta = compute_language_delta(language)
    if not lang_delta.empty:
        target = lang_delta[lang_delta["language_bucket"].str.contains("Target", na=False)].copy()
        if not target.empty:
            target["label"] = target.apply(lambda r: plot_label(r["pair_id"], r["source_system"]), axis=1)
            bar_chart(target.reindex(target["share_delta"].abs().sort_values(ascending=False).index), category="label", value="share_delta", title="Target-Language Share Delta", output_path=out("fig_language_target_delta.png"), max_items=20, diverging=True)
    return [path for path in created if path.exists()]


def build_all_outputs(project_root: Path | str, llm_run_ids: list[str] | None, scholarly_run_ids: list[str] | None, top_k: int = 10):
    project_root = Path(project_root)
    available = list_available_runs(project_root)
    if not llm_run_ids:
        llm_run_ids = detect_relevant_runs(available, "llm_audit")
    if not scholarly_run_ids:
        scholarly_run_ids = detect_relevant_runs(available, "scholarly")
    selected = list(dict.fromkeys([*(llm_run_ids or []), *(scholarly_run_ids or [])]))
    records = load_runs(project_root, selected)
    mapped, diagnostics = map_records_to_experiments(records)
    pairwise = compute_pairwise_metrics(mapped, top_k=top_k)
    metadata = compute_metadata_summary(mapped)
    hallucination = compute_hallucination_summary(mapped)
    geographic = compute_geographic_shift(mapped)
    language = compute_language_shift(mapped)
    concentration = compute_venue_publisher_concentration(mapped)
    open_access = compute_open_access_preprint_shift(mapped)
    concentration_delta = compute_concentration_delta(concentration)
    open_access_delta = compute_open_access_preprint_delta(open_access)
    metadata_risk_delta = compute_metadata_risk_delta(pairwise)
    geographic_delta = compute_geographic_delta(geographic)
    language_delta = compute_language_delta(language)
    ranking = compute_model_provider_ranking(pairwise, mapped)
    llm_provider_overlap = compute_llm_provider_overlap(mapped)
    provider_comparison = compute_provider_comparison(mapped)
    thematic = compute_thematic_shift(mapped)
    candidate_figures = build_thesis_candidate_figures(
        pairwise=pairwise,
        metadata=metadata,
        hallucination=hallucination,
        geographic=geographic,
        language=language,
        concentration_delta=concentration_delta,
        open_access_delta=open_access_delta,
        llm_provider_overlap=llm_provider_overlap,
    )
    safe_claims = build_thesis_safe_claims(candidate_figures)
    tables = {
        "table_experiment_query_pairs": pd.DataFrame(EXPERIMENT_PAIRS),
        "table_loaded_runs": available[available["run_id"].isin(selected)].drop(columns=["queries"], errors="ignore") if not available.empty else pd.DataFrame(),
        "table_record_counts_by_query": compute_record_counts(mapped),
        "table_pairwise_comparison_summary": pairwise,
        "table_metadata_completeness": metadata,
        "table_hallucination_risk_summary": hallucination,
        "table_geographic_shift": geographic,
        "table_language_shift": language,
        "table_venue_publisher_concentration": concentration,
        "table_venue_publisher_concentration_delta": concentration_delta,
        "table_open_access_preprint_shift": open_access,
        "table_open_access_preprint_delta": open_access_delta,
        "table_model_provider_ranking": ranking,
        "table_unmatched_or_missing_queries": diagnostics,
        "table_llm_provider_overlap": llm_provider_overlap,
        "table_provider_comparison_summary": provider_comparison,
        "table_thematic_keyword_shift": thematic,
        "table_metadata_risk_delta": metadata_risk_delta,
        "table_geographic_shift_delta": geographic_delta,
        "table_language_shift_delta": language_delta,
        "table_thesis_candidate_figures": candidate_figures,
        "table_thesis_safe_claims": safe_claims,
    }
    return {
        "available_runs": available,
        "selected_run_ids": selected,
        "records": records,
        "mapped_records": mapped,
        "query_diagnostics": diagnostics,
        "pairwise": pairwise,
        "metadata": metadata,
        "hallucination": hallucination,
        "geographic": geographic,
        "language": language,
        "concentration": concentration,
        "concentration_delta": concentration_delta,
        "open_access": open_access,
        "open_access_delta": open_access_delta,
        "metadata_risk_delta": metadata_risk_delta,
        "geographic_delta": geographic_delta,
        "language_delta": language_delta,
        "ranking": ranking,
        "llm_provider_overlap": llm_provider_overlap,
        "provider_comparison": provider_comparison,
        "thematic": thematic,
        "candidate_figures": candidate_figures,
        "safe_claims": safe_claims,
        "tables": tables,
    }
