# Target Architecture

This rewrite targets a local web application for PhD users. The frontend is Angular, the backend is FastAPI, and SQLite is the MVP storage layer. The legacy repository remains a requirements source only.

## Current Application Scope

The current rewrite supports two run modes:

- `scholarly`
  Query-aware scholarly collection using OpenAlex as the collection source.
- `llm_audit`
  Query-aware OpenRouter execution across a selected model set, followed by bibliographic enrichment and comparison.

Excluded architecture:

- CLI-first workflows
- static HTML report generation
- filesystem-first pipeline contracts
- direct frontend access to third-party APIs

## System Modules

- `frontend`
  Angular screens and interactive analytical components for runs, filters, tables, and comparison views
- `backend.api`
  FastAPI routes and response schemas
- `backend.application`
  run orchestration, enrichment coordination, parsing, and analysis builders
- `backend.domain`
  typed entities for runs, results, enrichments, provenance, and analysis payloads
- `backend.adapters`
  provider-specific HTTP clients and mappers for OpenAlex and OpenRouter
- `backend.storage`
  SQLite bootstrap, migration SQL, and repositories

## Core Domain Entities

- `Run`
  Top-level execution unit with `run_type`, timestamps, selected scholarly sources or selected models, and aggregate lifecycle state.
- `Query`
  Ordered user-provided input belonging to one run.
- `LLMCall`
  One query x model OpenRouter interaction with parse and latency metadata.
- `ResultRecord`
  Unified comparable result row attributed to run, query, rank, source/model, provider, and raw payload.
- `EnrichmentRecord`
  One provider-specific metadata resolution attempt for a result row.
- `CanonicalEnrichment`
  Merged provider output with field-level provenance.
- `RunAnalysis`
  On-demand analysis payload for the run detail surface.

## Backend Responsibilities

- create and persist runs in SQLite
- execute collection and llm_audit pipelines
- normalize result rows into one comparable shape
- resolve enrichment through a pluggable provider chain
- preserve provider provenance and raw payloads
- compute multi-model and multi-provider comparison metrics on demand
- expose interactive frontend endpoints instead of generating static reports

## Frontend Responsibilities

- create scholarly and llm_audit runs
- present backend-configured model choices
- display per-run execution state
- act as the main analytical surface for summary, comparison, missingness, overlap, and provenance views
- provide query/model/provider/top-k filtering without bypassing the backend API

## Persistence Model

SQLite tables currently used:

- `runs`
- `queries`
- `run_sources`
- `run_models`
- `llm_calls`
- `result_records`
- `enrichment_records`
- `canonical_enrichments`
- `provider_cache`

Storage rules:

- keep raw payloads for reproducibility and inspection
- keep result rows and enrichment rows distinct
- compute analysis from persisted facts rather than precomputed metric tables
- keep infrastructure-specific cache state inside SQLite instead of separate files

## Design Choices

- OpenAlex remains the scholarly collection source for now.
- Semantic Scholar, Scopus, and CORE are enrichment providers.
- OpenRouter is isolated behind an adapter so higher layers are model-oriented, not vendor-oriented.
- The legacy HTML report is treated as a structural reference for sections and summary logic, but the implementation target is reusable Angular views backed by FastAPI JSON.
