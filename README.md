# Bias Analysis Web App

Local Angular + FastAPI application for retrieval bias analysis across scholarly search results and OpenRouter-backed LLM article recommendation runs.

## Current Scope

The rewrite now supports two persisted run modes:

- `scholarly`
  Query one or more configured scholarly collection sources (`openalex`, `semantic_scholar`, `scopus`, `core`), persist ranked results with per-source provenance, enrich them through the configured provider chain, and expose source-aware bias analysis in the run detail view.
- `llm_audit`
  Query one or more user-selected OpenRouter models per query, parse structured article recommendations, enrich those recommendations through the same metadata chain, and compare model behavior side by side.

Key implemented capabilities:

- SQLite-backed persistence for runs, queries, sources, models, LLM calls, result rows, enrichment records, canonical enrichments, and provider cache entries
- Config-driven enrichment provider ordering and enablement
- Multi-provider enrichment via `openalex`, `semantic_scholar`, `scopus`, and `core`
- OpenRouter client integration with per-model execution and partial-failure handling
- Interactive run detail analysis inspired by the legacy HTML report:
  a shared scholarly/llm report structure with summary, overview, coverage, missingness, enrichment gain, overlap, ranking, geo, language, venue diversity, additional bias audits, llm-only parse/divergence/quality panels, and provenance inspection

## Repository Layout

- `backend/`
  FastAPI API, application services, domain models, adapters, SQLite storage, and migration SQL
- `frontend/`
  Angular application for run creation, run listing, and analytical run detail views
- `data/`
  Default SQLite database location and per-run debug artifacts
- `tests/`
  Backend-focused regression tests for parsing, enrichment canonicalization, API contracts, and analysis

## Backend API

Main run endpoints:

- `GET /openrouter/models`
- `GET /runs/options`
- `POST /runs`
- `GET /runs`
- `GET /runs/{id}`
- `DELETE /runs/{id}`
- `POST /runs/{id}/start`
- `GET /runs/{id}/replay-status`
- `POST /runs/{id}/replay-llm-artifacts`
- `GET /runs/{id}/results`
- `GET /runs/{id}/enrichments`
- `GET /runs/{id}/analysis`

`POST /runs` accepts:

- `run_type`
- `queries`
- `top_k`
- `sources` for `scholarly`
- `selected_models` for `llm_audit`

## Configuration

The backend loads the repo-root `.env` automatically on startup. Start from [`.env.example`](.env.example).

Important variables:

- `DATABASE_PATH`
- `RUN_ARTIFACTS_DIR`
- `RUN_ARTIFACTS_ENABLED`
- `RUN_ARTIFACTS_PRETTY_JSON`
- `SCHOLARLY_SOURCES`
- `ENRICHMENT_PROVIDER_ORDER`
- `ENRICHMENT_ENABLED_PROVIDERS`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL_DISCOVERY_ENDPOINT`
- `OPENROUTER_MODEL_DISCOVERY_TTL_SECONDS`
- `OPENROUTER_AVAILABLE_MODELS`
- `OPENROUTER_DEFAULT_MODELS`
- `OPENALEX_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`
- `SCOPUS_API_KEY`
- `SCOPUS_INSTTOKEN`
- `CORE_API_KEY`

OpenRouter model selection:

- The run-creation UI loads model choices dynamically from `GET /openrouter/models`, which proxies OpenRouter model discovery through the backend with a short TTL cache.
- By default the backend prefers OpenRouter's user-aware `/api/v1/models/user` endpoint so the picker reflects the configured account's provider preferences, privacy settings, and guardrails. Set `OPENROUTER_MODEL_DISCOVERY_ENDPOINT=catalog` to use the broader `/api/v1/models` catalog instead.
- The frontend and backend both enforce the app rule of selecting 1 to 10 models for `llm_audit` runs.
- `OPENROUTER_AVAILABLE_MODELS` and `OPENROUTER_DEFAULT_MODELS` remain as curated metadata for existing options responses and historical run explainability; they no longer drive the main model picker.
- Known stale ids such as `anthropic/claude-3.5-sonnet` are kept only as deprecated, non-selectable entries so older runs remain explainable without exposing the slug as healthy for new runs.
- Unsupported or unavailable model ids are recorded as failed model executions, their raw error payloads are preserved in run artifacts, and the remaining queries for that model are skipped instead of being retried blindly.

Provider behavior:

- `SCHOLARLY_SOURCES` controls which scholarly collection sources are exposed in the UI and accepted by the API.
- OpenAlex and Semantic Scholar can be used as collection sources without additional credentials. Scopus and CORE require their respective API credentials before they become selectable.
- The provider chain is ordered by `ENRICHMENT_PROVIDER_ORDER`.
- Disabled or unconfigured providers are skipped without failing the whole run.
- Provider lookups are cached in SQLite through `provider_cache`.
- Canonical enrichments preserve per-field provenance including provider and match strategy.

Run artifacts:

- Every created run gets a filesystem folder under `RUN_ARTIFACTS_DIR` such as `data/run_artifacts/run_<RUN_ID>/`.
- Artifacts are written incrementally during execution so partial runs still keep requests, responses, parsed payloads, enrichment attempts, analysis payloads, and error logs.
- `POST /runs/{id}/replay-llm-artifacts` rebuilds llm_audit parsing, enrichment, and analysis from persisted artifacts without calling the LLM provider again. Replay traces are written under `replay/` inside the existing run artifact folder.
- Secrets are redacted before writing. Authorization headers are never persisted.

## Local Development

Backend:

```bash
python3 -m uvicorn backend.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm start
```

The Angular app proxies `/api` to `http://localhost:8000`.

## Tests And Validation

Backend tests:

```bash
python3 -m pytest
```

Frontend build validation:

```bash
cd frontend
npm run build
```

## Notes

- The OpenRouter picker is backend-driven and does not hardcode a frontend model catalog.
- Analysis is computed on demand from persisted run facts instead of stored metric snapshots.
- The legacy hallucination / verifiability panel is intentionally not migrated into the new UI.
