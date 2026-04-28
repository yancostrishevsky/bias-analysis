# AGENTS.md

## Project

This project is a clean rewrite of a legacy research pipeline into a local web application for PhD and research users.

The goal is not to reproduce the legacy system line-by-line, but to build a simpler, inspectable, and research-friendly application for:
- running literature-retrieval experiments,
- comparing scholarly sources and LLM-based retrieval,
- enriching and validating returned records,
- analyzing retrieval bias and bibliographic quality,
- exporting reusable research datasets.

---

## Product Principles

- The app is a research tool, not just a dashboard.
- Reproducibility, inspectability, and debuggability are first-class requirements.
- Every important analysis result should be traceable back to run artifacts and record-level evidence.
- The UI should separate:
  - **reporting/interpretation**
  - **record inspection/export**
- Avoid hiding important differences behind pooled aggregate metrics.

---

## Stack

- frontend: Angular
- backend: FastAPI
- storage: SQLite for MVP
- local run: Docker Compose

---

## Legacy Rewrite Policy

- Treat the legacy repository as a **requirements source**, not as trusted code.
- Do not copy legacy modules blindly.
- Re-implement functionality in a simpler and more explicit architecture.
- Migrate one feature at a time.
- Prefer small, reviewable changes.
- Preserve useful behavior, not legacy complexity.
- If legacy behavior is ambiguous, prefer the simplest implementation that matches current product goals.
- Explicitly identify what is:
  - migrated,
  - redesigned,
  - intentionally omitted.

---

## Architecture Rules

- Frontend talks only to backend API.
- Backend owns application logic, domain logic, analysis, and validation.
- Keep API, application logic, domain logic, and adapters separate.
- Avoid CLI-oriented design in the rewritten app.
- Do not leak provider-specific or artifact-specific structures directly into frontend unless intentionally exposed.
- Prefer typed, normalized API responses over ad hoc payloads.
- Reuse existing abstractions before introducing new ones.
- Avoid parallel systems when extending existing analysis/reporting flows.

---

## Reporting and Data UX Rules

- The app has two distinct surfaces:
  1. **Report** — interpretation, charts, comparisons, conclusions
  2. **Records Explorer / Export** — raw rows, enriched rows, validation/conflicts, downloadable datasets
- Do not overload the report page with raw record tables.
- Record-level data should live on a separate page or clearly separated surface.
- Charts should, where practical, link to the relevant filtered records view.

### Analytics Granularity Rules

Important bias and quality metrics must not exist only as pooled global aggregates.

For every major metric, prefer exposing:
- overall
- per model / platform
- per query
- per model × query

Where meaningful, also support:
- top-k vs overall
- top-k vs rest
- rank buckets (top-1, top-3, top-5, all)

If a metric only exists as a pooled aggregate, treat that as incomplete unless there is a strong methodological reason.

---

## Working Style

- Plan before implementation.
- Inspect existing code paths before adding new ones.
- Explain what should be migrated, rewritten, or dropped.
- Keep changes scoped and reviewable.
- Update README when setup, architecture, routes, exports, or workflows change.
- Prefer explicitness over cleverness.
- Prefer stable, debuggable code over compact code.

### Before changing code, always determine:
- what problem is actually being solved,
- whether the issue is UI-only, backend-only, or cross-layer,
- whether existing architecture already supports part of the solution,
- what artifacts or tests prove the issue.

---

## Iterative Debugging Workflow (MANDATORY)

All debugging and improvements MUST follow this loop:

1. Inspect run artifacts (**source of truth**)
2. Identify concrete failure cases
3. Locate the exact failure stage in the pipeline
4. Implement a targeted fix
5. Validate using artifacts and/or tests

DO NOT:
- guess based only on code
- implement speculative fixes
- ignore recorded run evidence
- “fix” symptoms without identifying the stage where the issue begins

---

## Artifacts as Primary Evidence

All runs generate artifacts in:

`data/run_artifacts/run_<RUN_ID>/`

These artifacts are the ground truth for:
- debugging failures
- understanding pipeline behavior
- validating fixes
- explaining unexpected metrics
- tracing outputs back to specific stages

Always inspect relevant artifact files before diagnosing pipeline issues.

Typical areas to inspect:
- `logs/errors.jsonl`
- `logs/events.jsonl`
- `llm/*` (raw responses, parsed outputs, call metadata)
- `enrichment/*`
- `analysis/*`
- `run.json`
- `manifest.json`

Use artifacts first, code second.

---

## Pipeline Stages

The system consists of multiple stages:

1. Collection / retrieval
2. LLM generation
3. Parsing / structured extraction
4. Enrichment / provider resolution
5. Analysis / metrics / report generation

When debugging, identify **exactly which stage fails**.

Never describe a bug vaguely as “the run is broken” if the real failure is, for example:
- bad model selection validation,
- parse drift,
- enrichment mismatch,
- metric aggregation bug,
- UI rendering mismatch,
- stale cached catalog,
- artifact/report inconsistency.

---

## Validation Rules

When fixing bugs or extending features:

- Validate backend behavior with tests where possible.
- Validate frontend behavior with the existing build pipeline and manual verification if no frontend test harness exists.
- Prefer regression tests for bugs that were observed in artifacts.
- Do not claim a bug is fixed unless you can point to:
  - a test,
  - a build,
  - or artifact-based validation.

---

## Analysis and Metrics Rules

- Metrics must be methodologically interpretable.
- Do not introduce charts that look impressive but cannot answer a research question.
- Every bias or quality section should clearly state:
  - what it measures,
  - what unit it is based on (overall / per model / per query / top-k),
  - what kind of skew or issue it may reveal,
  - what conditions make it reliable or unreliable.
- If coverage is insufficient, gate the metric explicitly instead of rendering misleading charts.
- Prefer transparent metrics over opaque composite scores.
- If a composite score is introduced, document exactly how it is computed.

### Hallucination / Verifiability Metrics

If hallucination-style metrics are implemented, they must be grounded in explicit evidence such as:
- unmatched records,
- invalid DOI,
- title mismatch,
- year conflict,
- journal conflict,
- author conflict,
- publisher conflict,
- unverifiable completeness.

Do not use vague “hallucination” wording without measurable bibliographic verification criteria.

---

## Records Explorer and Exports

- Raw/enriched/result rows should be treated as research data, not only debug data.
- Provide a separate records/data surface for:
  - raw records
  - parsed records
  - enriched records
  - verification/conflict rows
  - unified export-ready dataset
- Export formats should be research-friendly where possible:
  - CSV
  - JSON
  - JSONL
  - optionally Parquet
- Exported datasets should include enough metadata to be reusable in downstream studies.

---

## API and Schema Rules

- Keep schemas explicit and stable.
- Prefer additive schema evolution over breaking response shapes without need.
- Normalize provider-specific data before exposing it to the frontend.
- Keep naming consistent across:
  - artifacts
  - backend DTOs
  - API responses
  - frontend models

If the same concept appears in multiple layers, use one canonical name unless there is a very strong reason not to.

---

## UI Rules

- Prioritize clarity over visual density.
- Report pages should optimize interpretation.
- Records pages should optimize inspection and export.
- Use modular components for sections, charts, tables, and explanatory notes.
- Avoid giant page components with mixed data-fetching, transformation, and presentation logic.
- Every major report section should include a short explanation of what it reflects.

---

## Change Management

When implementing a feature, always be clear whether it is:
- new functionality,
- a migration from legacy,
- a redesign of an existing feature,
- a bug fix,
- or a methodological correction.

In summaries and PR-style notes, include:
- root cause or motivation,
- files changed,
- what behavior changed,
- what remains gated or unsupported,
- how the change was validated.

---

## Non-Goals

- Do not recreate legacy complexity for its own sake.
- Do not build features that are only useful in a CLI workflow unless they clearly support the web app.
- Do not optimize prematurely for distributed/cloud deployment if it makes the local research workflow harder to understand.
- Do not hide uncertainty in analysis outputs.

---

## Default Engineering Priorities

When tradeoffs are needed, prefer:

1. correctness
2. debuggability
3. methodological clarity
4. explicit architecture
5. reviewability
6. UI polish
7. performance micro-optimizations

Unless a task explicitly says otherwise.