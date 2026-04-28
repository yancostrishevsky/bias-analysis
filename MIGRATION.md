# Migration Notes

The legacy repository remains a requirements source only. Legacy connectors, evaluation logic, and report sections informed the new implementation, but they were re-expressed in the current FastAPI + Angular architecture rather than copied as CLI or static-report code.

## What Has Been Migrated

- SQLite-backed persistence replaced the previous in-memory MVP state
- dual run modes:
  `scholarly` and `llm_audit`
- OpenRouter-backed multi-model execution
- provider-based enrichment chain:
  `openalex`, `semantic_scholar`, `scopus`, `core`
- canonical enrichment with field-level provenance
- interactive run detail analysis replacing the standalone HTML report workflow

## What Was Preserved Conceptually

- run-centric provenance
- ordered queries as first-class inputs
- explicit separation between raw result rows and canonical enrichment
- overlap, ranking, concentration, recency, OA, language, and missingness analysis
- provider-aware metadata diagnostics and cross-entity comparison

## What Was Deliberately Dropped

- CLI orchestration as the primary application surface
- static report generation and embedded report templates
- filesystem-based pipeline artifacts as the system of record
- vendor-specific implementation details leaking into application services

## Current Migration Shape

1. `Run`, `Query`, `LLMCall`, `ResultRecord`, `EnrichmentRecord`, `CanonicalEnrichment`, and `RunAnalysis` are the current domain backbone.
2. SQLite stores persisted run facts and provider cache entries.
3. Scholarly collection currently uses OpenAlex.
4. LLM execution currently uses backend-configured OpenRouter models.
5. Enrichment fallback is provider-ordered and can partially succeed.
6. Analysis is built on demand from persisted facts for the Angular run detail surface.

## Setup Notes

- Copy [`.env.example`](.env.example) to `.env` and provide the required keys.
- The SQLite schema is initialized automatically from [`backend/storage/migrations/0001_initial.sql`](backend/storage/migrations/0001_initial.sql) on backend startup.
- Existing in-memory run data is not migrated because the previous storage layer was ephemeral.
