import {
  CanonicalEnrichment,
  LLMCallRow,
  RunAnalysis,
  RunDetail,
  ResultEnrichmentResponse,
  ResultRecord,
  UnifiedRecordRow
} from '../models/run.models';

export interface ReportMetricCard {
  key: string;
  label: string;
  value: string;
  note?: string;
}

export interface ReportSeriesItem {
  key: string;
  label: string;
  valueLabel: string;
  value: number | null;
  count?: number;
  ratio?: number | null;
}

export interface ReportSeries {
  key: string;
  title: string;
  description?: string;
  items: ReportSeriesItem[];
}

export interface ReportHeatmapCell {
  key: string;
  rowKey: string;
  rowLabel: string;
  columnKey: string;
  columnLabel: string;
  value: number | null;
  valueLabel: string;
}

export interface ReportHeatmap {
  key: string;
  title: string;
  description?: string;
  cells: ReportHeatmapCell[];
}

export interface ReportTableColumn {
  key: string;
  label: string;
  align?: 'start' | 'end';
}

export interface ReportTableRow {
  key: string;
  values: Record<string, string>;
}

export interface ReportTable {
  key: string;
  title: string;
  columns: ReportTableColumn[];
  rows: ReportTableRow[];
  emptyMessage?: string;
}

export type ReportSectionStatus = 'available' | 'unavailable' | 'insufficient_coverage';

export interface ReportSection {
  key: string;
  eyebrow: string;
  title: string;
  description: string;
  status: ReportSectionStatus;
  reason?: string;
  cards?: ReportMetricCard[];
  series?: ReportSeries[];
  heatmaps?: ReportHeatmap[];
  tables?: ReportTable[];
  notes?: string[];
}

export interface RunReportView {
  sharedSections: ReportSection[];
  llmSections: ReportSection[];
  omittedSections: string[];
}

export interface EnrichmentRow {
  result: ResultRecord;
  providerRecords: ResultEnrichmentResponse['provider_records'];
  canonicalEnrichment: CanonicalEnrichment | null;
}

export interface ReportInput {
  detail: RunDetail;
  analysis: RunAnalysis;
  enrichmentRows: EnrichmentRow[];
  recordsRows: UnifiedRecordRow[];
  selectedQueryId: string;
  selectedEntity: string;
  selectedTopK: number;
}

export interface ReportMergedRow {
  queryId: string;
  queryLabel: string;
  entity: string;
  rank: number;
  resultId: string;
  title: string;
  doi: string | null;
  rawDoi: string | null;
  publicationYear: number | null;
  rawYear: number | null;
  language: string | null;
  isOpenAccess: boolean | null;
  openAccessStatus: string | null;
  publisher: string | null;
  venue: string | null;
  rawVenue: string | null;
  rawTitle: string;
  countryPrimary: string | null;
  countryDominant: string | null;
  countries: string[];
  affiliations: string[];
  fieldsOfStudy: string[];
  subjectAreas: string[];
  citationCount: number | null;
  verified: boolean;
}

export interface QueryModelDetailRow {
  queryId: string;
  queryLabel: string;
  modelName: string;
  status: string;
  parseSuccess: boolean;
  parseMode: string | null;
  parsedItemCount: number | null;
  resultCount: number;
  verifiedCount: number;
  unverifiedCount: number;
  latencyMs: number | null;
  totalTokens: number | null;
  errorMessage: string | null;
}

export type ReportLlmCall = LLMCallRow;
