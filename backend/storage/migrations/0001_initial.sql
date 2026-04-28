CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'pending',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT,
    top_k INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    finished_at TEXT,
    error_message TEXT
);

CREATE TABLE queries (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    position INTEGER NOT NULL,
    language TEXT
);

CREATE TABLE run_sources (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    PRIMARY KEY (run_id, source_name)
);

CREATE TABLE run_models (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    PRIMARY KEY (run_id, model_name)
);

CREATE TABLE llm_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    query_id TEXT NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    status TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    request_payload TEXT NOT NULL,
    response_payload TEXT NOT NULL,
    response_text TEXT,
    parse_success INTEGER NOT NULL DEFAULT 0,
    parse_error TEXT,
    latency_ms INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE result_records (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    query_id TEXT NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    llm_call_id TEXT REFERENCES llm_calls(id) ON DELETE SET NULL,
    origin_type TEXT NOT NULL,
    source_name TEXT,
    model_name TEXT,
    provider_name TEXT,
    execution_status TEXT NOT NULL,
    rank INTEGER NOT NULL,
    canonical_identifier TEXT,
    title TEXT NOT NULL,
    doi TEXT,
    url TEXT,
    source_identifier TEXT,
    year INTEGER,
    authors_json TEXT NOT NULL,
    venue TEXT,
    publisher TEXT,
    language TEXT,
    raw_payload TEXT NOT NULL
);

CREATE TABLE enrichment_records (
    id TEXT PRIMARY KEY,
    result_record_id TEXT NOT NULL REFERENCES result_records(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_record_id TEXT NOT NULL,
    status TEXT NOT NULL,
    enriched_at TEXT NOT NULL,
    match_strategy TEXT,
    external_ids_json TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    authors_json TEXT NOT NULL,
    affiliations_json TEXT NOT NULL,
    publication_year INTEGER,
    language TEXT,
    is_open_access INTEGER,
    open_access_status TEXT,
    citation_count INTEGER,
    publisher TEXT,
    venue TEXT,
    fields_of_study_json TEXT NOT NULL,
    subject_areas_json TEXT NOT NULL,
    country_primary TEXT,
    country_dominant TEXT,
    countries_json TEXT NOT NULL,
    urls_json TEXT NOT NULL,
    landing_page_url TEXT,
    pdf_url TEXT,
    raw_payload TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE canonical_enrichments (
    id TEXT PRIMARY KEY,
    result_record_id TEXT NOT NULL UNIQUE REFERENCES result_records(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL,
    source_record_ids_json TEXT NOT NULL,
    external_ids_json TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    authors_json TEXT NOT NULL,
    affiliations_json TEXT NOT NULL,
    publication_year INTEGER,
    language TEXT,
    is_open_access INTEGER,
    open_access_status TEXT,
    citation_count INTEGER,
    publisher TEXT,
    venue TEXT,
    fields_of_study_json TEXT NOT NULL,
    subject_areas_json TEXT NOT NULL,
    country_primary TEXT,
    country_dominant TEXT,
    countries_json TEXT NOT NULL,
    urls_json TEXT NOT NULL,
    landing_page_url TEXT,
    pdf_url TEXT,
    field_provenance_json TEXT NOT NULL
);

CREATE TABLE provider_cache (
    provider TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    PRIMARY KEY (provider, cache_key)
);

CREATE INDEX idx_queries_run_id ON queries(run_id);
CREATE INDEX idx_llm_calls_run_id ON llm_calls(run_id);
CREATE INDEX idx_result_records_run_id ON result_records(run_id);
CREATE INDEX idx_result_records_query_id ON result_records(query_id);
CREATE INDEX idx_result_records_model_name ON result_records(model_name);
CREATE INDEX idx_enrichment_records_result_record_id ON enrichment_records(result_record_id);
