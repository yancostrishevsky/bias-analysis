export type RunType = 'scholarly' | 'llm_audit';
export type RunStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed';
export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed' | 'skipped';
export type ResultOriginType = 'scholarly_source' | 'llm_response';
export type ModelValidationState = 'healthy' | 'preview' | 'deprecated' | 'custom';

export interface Run {
  id: string;
  run_type: RunType;
  status: RunStatus;
  stage: string;
  progress_current: number;
  progress_total: number;
  progress_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  finished_at: string | null;
  top_k: number;
  error_message: string | null;
  sources: string[];
  selected_models: string[];
}

export interface Query {
  id: string;
  run_id: string;
  text: string;
  position: number;
  language: string | null;
}

export interface EntityExecutionSummary {
  entity_type: string;
  name: string;
  status: ExecutionStatus;
  completed_count: number;
  failed_count: number;
  total_count: number;
  progress_current: number;
  progress_total: number;
  progress_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface RunDetail {
  run: Run;
  queries: Query[];
  entity_statuses: EntityExecutionSummary[];
}

export interface ResultRecord {
  id: string;
  run_id: string;
  query_id: string;
  llm_call_id: string | null;
  origin_type: ResultOriginType;
  source_name: string | null;
  model_name: string | null;
  provider_name: string | null;
  execution_status: ExecutionStatus;
  rank: number;
  canonical_identifier: string | null;
  title: string;
  doi: string | null;
  url: string | null;
  source_identifier: string | null;
  year: number | null;
  authors: string[];
  venue: string | null;
  publisher: string | null;
  language: string | null;
  raw_payload: Record<string, unknown>;
}

export type EnrichmentProvider = 'openalex' | 'core' | 'scopus' | 'semantic_scholar';
export type ScholarlySource = 'openalex' | 'semantic_scholar' | 'scopus' | 'core';
export type EnrichmentMatchStrategy =
  | 'source_identifier'
  | 'doi'
  | 'normalized_doi_url'
  | 'title_year'
  | 'title_authors_year';

export interface FieldProvenance {
  provider: EnrichmentProvider;
  enrichment_record_id: string;
  match_strategy: EnrichmentMatchStrategy | null;
}

export interface EnrichmentRecord {
  id: string;
  result_record_id: string;
  provider: EnrichmentProvider;
  provider_record_id: string;
  status: ExecutionStatus;
  enriched_at: string;
  match_strategy: EnrichmentMatchStrategy | null;
  external_ids: Record<string, string>;
  source_ids: Record<string, string>;
  doi: string | null;
  title: string | null;
  abstract: string | null;
  authors: string[];
  affiliations: string[];
  publication_year: number | null;
  language: string | null;
  is_open_access: boolean | null;
  open_access_status: string | null;
  citation_count: number | null;
  publisher: string | null;
  venue: string | null;
  fields_of_study: string[];
  subject_areas: string[];
  country_primary: string | null;
  country_dominant: string | null;
  countries: string[];
  urls: string[];
  landing_page_url: string | null;
  pdf_url: string | null;
  raw_payload: Record<string, unknown>;
  error_message: string | null;
}

export interface CanonicalEnrichment {
  id: string;
  result_record_id: string;
  updated_at: string;
  source_record_ids: string[];
  external_ids: Record<string, string>;
  source_ids: Record<string, string>;
  doi: string | null;
  title: string | null;
  abstract: string | null;
  authors: string[];
  affiliations: string[];
  publication_year: number | null;
  language: string | null;
  is_open_access: boolean | null;
  open_access_status: string | null;
  citation_count: number | null;
  publisher: string | null;
  venue: string | null;
  fields_of_study: string[];
  subject_areas: string[];
  country_primary: string | null;
  country_dominant: string | null;
  countries: string[];
  urls: string[];
  landing_page_url: string | null;
  pdf_url: string | null;
  field_provenance: Record<string, FieldProvenance>;
}

export interface ResultEnrichmentResponse {
  result_record_id: string;
  provider_records: EnrichmentRecord[];
  canonical_enrichment: CanonicalEnrichment | null;
}

export interface RunOptionsResponse {
  supported_run_types: RunType[];
  default_run_type: RunType;
  available_models: string[];
  default_models: string[];
  model_catalog: RunModelOption[];
  available_scholarly_sources: string[];
  source_catalog: ScholarlySourceOption[];
  enabled_enrichment_providers: string[];
  enrichment_provider_order: string[];
}

export interface ScholarlySourceOption {
  id: ScholarlySource | string;
  display_name: string;
  description: string | null;
  selectable: boolean;
  validation_state: 'healthy' | 'requires_configuration' | 'custom';
  validation_reason: string | null;
  credential_required: boolean;
}

export interface RunModelOption {
  id: string;
  display_name: string;
  provider: string;
  family: string;
  description: string | null;
  recommended: boolean;
  default_enabled: boolean;
  selectable: boolean;
  validation_state: ModelValidationState;
  validation_reason: string | null;
  replacement_model_id: string | null;
  source: 'curated' | 'configured_custom';
}

export interface OpenRouterModelSummary {
  id: string;
  name: string;
  description: string | null;
  context_length: number | null;
  prompt_price: number | null;
  completion_price: number | null;
  request_price: number | null;
  image_price: number | null;
  provider: string | null;
  canonical_slug: string | null;
  modality: string | null;
  input_modalities: string[];
  output_modalities: string[];
  supported_parameters: string[];
  is_moderated: boolean | null;
  max_completion_tokens: number | null;
  created: number | null;
}

export interface OpenRouterModelsResponse {
  models: OpenRouterModelSummary[];
  total: number;
  cached: boolean;
}

export interface AnalysisFilterOption {
  value: string;
  label: string;
}

export interface RunAnalysisSummary {
  run_id: string;
  run_type: RunType;
  status: string;
  total_results: number;
  query_count: number;
  entity_label: string;
  entity_count: number;
  completed_entity_count: number;
  failed_entity_count: number;
}

export interface AnalysisFilters {
  queries: AnalysisFilterOption[];
  entities: AnalysisFilterOption[];
  top_ks: number[];
  default_top_k: number;
}

export interface DistributionRow {
  metric: string;
  query_id: string | null;
  entity: string;
  label: string;
  count: number;
  ratio: number;
}

export interface CoverageRow {
  query_id: string | null;
  entity: string;
  field: string;
  populated_count: number;
  missing_count: number;
  total_count: number;
  coverage_ratio: number;
}

export interface TopKComparisonRow {
  query_id: string | null;
  entity: string;
  k: number;
  metric: string;
  top_k_value: number | null;
  overall_value: number | null;
  delta: number | null;
}

export interface OverlapRow {
  query_id: string | null;
  left_entity: string;
  right_entity: string;
  jaccard: number | null;
  overlap_at_k: number | null;
  rank_biased_overlap: number | null;
  top_1_agreement: number | null;
}

export interface ConcentrationRow {
  query_id: string | null;
  entity: string;
  metric: string;
  value: number | null;
}

export interface LLMCallRow {
  query_id: string;
  model_name: string;
  status: string;
  parse_success: boolean;
  parse_mode: string | null;
  partial_json_recovery: boolean;
  parsed_item_count: number | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  error_message: string | null;
}

export interface LLMMetricRow {
  query_id: string | null;
  entity: string;
  metric: string;
  value: number | null;
  count: number | null;
  note: string | null;
}

export interface ReplayStatusResponse {
  replay_available: boolean;
  replay_summary: Record<string, unknown> | null;
  current_output_source: string | null;
  current_output_generated_at: string | null;
}

export interface LLMAnalysisSection {
  calls: LLMCallRow[];
  metrics: LLMMetricRow[];
}

export interface RunAnalysis {
  summary: RunAnalysisSummary;
  filters: AnalysisFilters;
  distributions: DistributionRow[];
  coverage_rows: CoverageRow[];
  baseline_coverage_rows: CoverageRow[];
  top_k_rows: TopKComparisonRow[];
  overlap_rows: OverlapRow[];
  concentration_rows: ConcentrationRow[];
  llm: LLMAnalysisSection | null;
}

export interface RecordsFilterOption {
  value: string;
  label: string;
}

export interface RunRecordsSummary {
  run_id: string;
  run_type: RunType;
  total_rows: number;
  filtered_rows: number;
  export_formats: string[];
  export_views: string[];
}

export interface RunRecordsFilters {
  queries: RecordsFilterOption[];
  entities: RecordsFilterOption[];
  languages: RecordsFilterOption[];
  publishers: RecordsFilterOption[];
  countries: RecordsFilterOption[];
  oa_statuses: RecordsFilterOption[];
  source_types: RecordsFilterOption[];
  parse_statuses: RecordsFilterOption[];
  risk_buckets: RecordsFilterOption[];
}

export interface UnifiedRecordRow {
  run_id: string;
  run_mode: RunType;
  query_id: string;
  query_text: string;
  query_category: string | null;
  model_or_platform: string;
  provider: string | null;
  repeat_index: number | null;
  rank: number;
  rank_bucket: string;
  raw_title: string | null;
  raw_doi: string | null;
  raw_year: number | null;
  raw_journal: string | null;
  raw_authors: string[];
  raw_rationale: string | null;
  parsed_title: string | null;
  parsed_doi: string | null;
  parsed_year: number | null;
  parsed_journal: string | null;
  parsed_authors: string[];
  enriched_title: string | null;
  enriched_doi: string | null;
  enriched_year: number | null;
  enriched_journal: string | null;
  enriched_authors: string[];
  external_match_id: string | null;
  matched: boolean;
  match_strategy: string | null;
  doi_valid: boolean | null;
  title_match_status: string | null;
  year_conflict: boolean;
  journal_conflict: boolean;
  author_conflict: boolean;
  publisher_conflict: boolean;
  any_conflict: boolean;
  conflict_count: number;
  unmatched_reason: string | null;
  language: string | null;
  country_primary: string | null;
  countries: string[];
  publisher: string | null;
  source_type: string | null;
  is_oa: boolean | null;
  oa_status: string | null;
  oa_pathway: string | null;
  cited_by_count: number | null;
  topic: string | null;
  subfield: string | null;
  parse_status: string | null;
  parse_confidence: number | null;
  parse_strategy: string | null;
  parse_fallback_used: boolean;
  parse_errors: string | null;
  suspicious_completeness: boolean;
  hallucination_risk_bucket: string | null;
  risk_reasons: string[];
  provenance_summary: string | null;
  raw_payload: Record<string, unknown>;
  parsed_payload: Record<string, unknown>;
  enriched_payload: Record<string, unknown>;
  verification_trace: Record<string, unknown>;
}

export interface RunRecordsResponse {
  summary: RunRecordsSummary;
  filters: RunRecordsFilters;
  rows: UnifiedRecordRow[];
}

export interface CreateRunRequest {
  run_type: RunType;
  sources: string[];
  selected_models: string[];
  top_k: number;
  queries: string[];
}
