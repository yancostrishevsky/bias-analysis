import {
  CoverageRow,
  LLMMetricRow,
  OverlapRow,
  UnifiedRecordRow
} from '../models/run.models';
import {
  QueryModelDetailRow,
  ReportHeatmap,
  ReportHeatmapCell,
  ReportInput,
  ReportMergedRow,
  ReportMetricCard,
  ReportSection,
  ReportSeries,
  ReportTable,
  ReportTableColumn,
  ReportTableRow,
  RunReportView
} from './run-report.models';

const COVERAGE_FIELDS = [
  'doi',
  'abstract',
  'publication_year',
  'language',
  'is_open_access',
  'citation_count',
  'publisher',
  'venue',
  'country_primary',
  'affiliations',
  'fields_of_study',
  'landing_page_url',
  'pdf_url'
] as const;

const CORE_METADATA_FIELDS = [
  'doi',
  'publicationYear',
  'language',
  'isOpenAccess',
  'publisher',
  'venue',
  'countryPrimary'
] as const;

const FALLBACK_PARSE_MODES = ['fenced_json', 'brace_slice', 'partial_array_recovery'];

export function buildRunReportView(input: ReportInput): RunReportView {
  const mergedRows = mergeRows(input);
  const recordRows = scopedRecordRows(input);
  const topRecordRows = recordRows.filter((row) => row.rank <= input.selectedTopK);
  const restRecordRows = recordRows.filter((row) => row.rank > input.selectedTopK);
  const queryId = input.selectedQueryId || null;
  const entityKey = input.selectedEntity || '';

  const sharedSections: ReportSection[] = [
    buildSummarySection(input, recordRows),
    buildEntitySummarySection(input, recordRows),
    buildCrossModelCompareSection(input, recordRows),
    buildPerQueryDiagnosticsSection(input, recordRows),
    buildOverviewSection(recordRows, topRecordRows),
    buildCoverageSection(input, queryId),
    buildMissingnessSection(input, queryId),
    buildEnrichmentGainSection(input, queryId),
    buildOverlapSection(input, queryId),
    buildRankingBiasSection(recordRows, topRecordRows, restRecordRows, input.selectedTopK),
    buildLanguageBiasSection(recordRows, topRecordRows),
    buildPublisherBiasSection(recordRows, topRecordRows),
    buildVenueDiversitySection(recordRows),
    buildGeoBiasSection(recordRows, topRecordRows),
    buildOaBiasSection(recordRows, topRecordRows),
    buildRecencyBiasSection(recordRows, topRecordRows),
    buildCitationBiasSection(recordRows, topRecordRows),
    buildSourceTypeBiasSection(recordRows, topRecordRows),
    buildTopicDriftSection(recordRows, topRecordRows),
    buildAdditionalBiasSection(recordRows, topRecordRows, restRecordRows, input.selectedTopK)
  ];

  const llmSections =
    input.detail.run.run_type === 'llm_audit'
      ? [
          buildLlmParseSection(input),
          buildLlmDivergenceSection(input, queryId, entityKey),
          buildLlmStabilitySection(input),
          buildLlmQualitySection(recordRows),
          buildLlmConflictsSection(recordRows),
          buildLlmHallucinationSection(recordRows),
          buildLlmQueryDetailsSection(input, recordRows)
        ]
      : [];

  return {
    sharedSections,
    llmSections,
    omittedSections: []
  };
}

function buildSummarySection(input: ReportInput, rows: UnifiedRecordRow[]): ReportSection {
  const matchedCount = rows.filter((row) => row.matched).length;
  const doiValidCount = rows.filter((row) => row.doi_valid === true).length;
  const enrichedCount = rows.filter((row) => Object.keys(row.enriched_payload || {}).length > 0).length;
  const uniqueCount = new Set(rows.map(uniqueRecordKey)).size;
  const entities = new Set(rows.map((row) => row.model_or_platform)).size;
  const publishers = new Set(rows.map((row) => row.publisher).filter((value): value is string => Boolean(value))).size;
  const completeness = mean(rows.map(recordCompleteness));

  return {
    key: 'summary',
    eyebrow: 'Overview',
    title: 'Experiment Overview',
    description: 'This summary reflects the current run scope and the core data quality context needed to interpret the bias panels below. Higher matched, DOI-valid, and completeness values generally indicate stronger downstream reliability.',
    status: rows.length ? 'available' : 'unavailable',
    reason: rows.length ? undefined : 'No result rows are available for the current filters.',
    cards: rows.length
      ? [
          card('run-type', 'Run type', input.detail.run.run_type === 'llm_audit' ? 'LLM audit' : 'Scholarly'),
          card('queries', 'Queries', integerLabel(input.detail.queries.length)),
          card('entities', input.analysis.summary.entity_label + 's', integerLabel(entities)),
          card('records', 'Total records', integerLabel(rows.length)),
          card('unique', 'Unique records', integerLabel(uniqueCount)),
          card('topk', 'Configured top-k', integerLabel(input.detail.run.top_k)),
          card('matched', 'Matched / verified', percentageLabel(ratio(matchedCount, rows.length))),
          card('doi', 'DOI-valid share', percentageLabel(ratio(doiValidCount, rows.length))),
          card('enriched', 'Enriched rows', percentageLabel(ratio(enrichedCount, rows.length))),
          card('metadata', 'Metadata completeness', percentageLabel(completeness)),
          card('publishers', 'Distinct publishers', integerLabel(publishers)),
          card('llm-calls', 'LLM calls', input.detail.run.run_type === 'llm_audit' ? integerLabel(input.analysis.llm?.calls.length ?? 0) : '—')
        ]
      : [],
    notes: [
      `${input.analysis.summary.entity_label}-level and query-level sections below use the same run, but expose grouped slices instead of relying only on pooled totals.`,
      input.detail.run.run_type === 'llm_audit'
        ? 'LLM-only diagnostics below depend on parse, enrichment, and verification coverage from unified record rows.'
        : 'Scholarly runs share the same report structure where the underlying metrics exist.'
    ]
  };
}

function buildOverviewSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const sections: ReportSeries[] = [];
  if (rows.length) {
    sections.push(
      buildRecordDistributionSeries('entities', 'Records by model / platform', rows, (row) => row.model_or_platform),
      buildRecordDistributionSeries('recency-overall', 'Recency distribution', rows, (row) => yearBucket(row.enriched_year ?? row.parsed_year)),
      buildRecordDistributionSeries('open-overall', 'Open access status', rows, (row) => oaStatusLabel(row)),
      buildRecordDistributionSeries('source-type', 'Source type distribution', rows, (row) => row.source_type || 'unknown'),
      buildRecordDistributionSeries('recency-topk', 'Top-k recency', topRows, (row) => yearBucket(row.enriched_year ?? row.parsed_year))
    );
  }

  return {
    key: 'overview',
    eyebrow: 'Overview',
    title: 'Overview',
    description: 'These overview charts summarize the active scope before drilling into specific bias dimensions. They combine overall and top-k slices so it is easier to see whether the most highly ranked records differ from the full result set.',
    status: rows.length ? 'available' : 'unavailable',
    reason: rows.length ? undefined : 'No records are available for the current filters.',
    series: sections.filter((series) => series.items.length)
  };
}

function buildEntitySummarySection(input: ReportInput, rows: UnifiedRecordRow[]): ReportSection {
  const grouped = sortedGroups(rows, (row) => row.model_or_platform);
  if (!grouped.length) {
    return unavailableSection(
      'entity-summary',
      'Per-Model Dashboard',
      'Per-Model / Per-Platform Summary',
      'This section summarizes the retrieval and metadata profile of each model or platform so quality, completeness, and risk can be compared quickly.',
      'No grouped record rows are available for the current filters.'
    );
  }

  return {
    key: 'entity-summary',
    eyebrow: 'Per-Model Dashboard',
    title: 'Per-Model / Per-Platform Summary',
    description: 'This section summarizes the retrieval and metadata profile of each model or platform and supports fast comparison of quality, completeness, and verification risk.',
    status: 'available',
    tables: [
      buildTable(
        'entity-summary-table',
        'Comparative profile',
        [
          column('entity', input.analysis.summary.entity_label),
          column('records', 'Records', 'end'),
          column('unique', 'Unique', 'end'),
          column('per_query', 'Avg / query', 'end'),
          column('doi', 'DOI-valid', 'end'),
          column('matched', 'Matched', 'end'),
          column('metadata', 'Metadata', 'end'),
          column('missing', 'Missingness', 'end'),
          column('language', 'Language known', 'end'),
          column('country', 'Country known', 'end'),
          column('publisher', 'Publisher known', 'end'),
          column('oa', 'OA known', 'end'),
          column('conflict', 'Conflict rate', 'end'),
          column('risk', input.detail.run.run_type === 'llm_audit' ? 'High risk' : 'Risk', 'end')
        ],
        grouped.map(([entity, entityRows]) => {
          const queryCount = new Set(entityRows.map((row) => row.query_id)).size;
          const uniqueCount = new Set(entityRows.map(uniqueRecordKey)).size;
          return {
            key: entity,
            values: {
              entity,
              records: integerLabel(entityRows.length),
              unique: integerLabel(uniqueCount),
              per_query: numberLabel(ratio(entityRows.length, queryCount)),
              doi: percentageLabel(ratio(entityRows.filter((row) => row.doi_valid === true).length, entityRows.length)),
              matched: percentageLabel(ratio(entityRows.filter((row) => row.matched).length, entityRows.length)),
              metadata: percentageLabel(mean(entityRows.map(recordCompleteness))),
              missing: percentageLabel(difference(1, mean(entityRows.map(recordCompleteness)))),
              language: percentageLabel(ratio(entityRows.filter((row) => Boolean(row.language)).length, entityRows.length)),
              country: percentageLabel(ratio(entityRows.filter((row) => Boolean(row.country_primary)).length, entityRows.length)),
              publisher: percentageLabel(ratio(entityRows.filter((row) => Boolean(row.publisher)).length, entityRows.length)),
              oa: percentageLabel(ratio(entityRows.filter((row) => row.is_oa !== null || Boolean(row.oa_status)).length, entityRows.length)),
              conflict: percentageLabel(ratio(entityRows.filter((row) => row.any_conflict).length, entityRows.length)),
              risk: input.detail.run.run_type === 'llm_audit'
                ? percentageLabel(ratio(entityRows.filter((row) => row.hallucination_risk_bucket === 'high').length, entityRows.length))
                : '—'
            }
          };
        })
      )
    ]
  };
}

function buildCrossModelCompareSection(input: ReportInput, rows: UnifiedRecordRow[]): ReportSection {
  const grouped = sortedGroups(rows, (row) => row.model_or_platform);
  if (grouped.length < 2) {
    return insufficientSection(
      'cross-model-compare',
      'Cross-Model Compare',
      'Cross-Model Compare',
      'This section compares model- or platform-level slices instead of pooled totals.',
      `At least two ${input.analysis.summary.entity_label.toLowerCase()}s are required for cross-comparison.`
    );
  }

  return {
    key: 'cross-model-compare',
    eyebrow: 'Cross-Model Compare',
    title: 'Cross-Model Compare',
    description: 'These comparison rows show how each model or platform differs on retrieval volume, verification coverage, metadata completeness, concentration, and ranking sensitivity.',
    status: 'available',
    tables: [
      buildTable(
        'cross-model-table',
        'Cross-model comparison',
        [
          column('entity', input.analysis.summary.entity_label),
          column('records', 'Records', 'end'),
          column('matched', 'Matched', 'end'),
          column('metadata', 'Metadata', 'end'),
          column('publisher_hhi', 'Publisher HHI', 'end'),
          column('venue_hhi', 'Venue HHI', 'end'),
          column('topk_citations', 'Top-k citation delta', 'end'),
          column('topk_recency', 'Top-k recency delta', 'end')
        ],
        grouped.map(([entity, entityRows]) => {
          const topRows = entityRows.filter((row) => row.rank <= input.selectedTopK);
          const restRows = entityRows.filter((row) => row.rank > input.selectedTopK);
          return {
            key: entity,
            values: {
              entity,
              records: integerLabel(entityRows.length),
              matched: percentageLabel(ratio(entityRows.filter((row) => row.matched).length, entityRows.length)),
              metadata: percentageLabel(mean(entityRows.map(recordCompleteness))),
              publisher_hhi: numberLabel(hhi(entityRows.map((row) => row.publisher).filter((value): value is string => Boolean(value)))),
              venue_hhi: numberLabel(hhi(entityRows.map((row) => row.enriched_journal || row.parsed_journal).filter((value): value is string => Boolean(value)))),
              topk_citations: signedNumberLabel(difference(mean(topRows.map((row) => numberOrNull(row.cited_by_count))), mean(restRows.map((row) => numberOrNull(row.cited_by_count))))),
              topk_recency: signedNumberLabel(difference(mean(topRows.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year))), mean(restRows.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year)))))
            }
          };
        })
      )
    ]
  };
}

function buildPerQueryDiagnosticsSection(input: ReportInput, rows: UnifiedRecordRow[]): ReportSection {
  const queryGroups = sortedGroups(rows, (row) => `${row.query_id}::${row.model_or_platform}`);
  if (!queryGroups.length) {
    return unavailableSection(
      'query-diagnostics',
      'Per-Query Diagnostics',
      'Per-Query Diagnostics',
      'This section helps determine whether observed behavior is stable across queries or driven by a few prompts.',
      'No query-level rows are available for the current filters.'
    );
  }

  return {
    key: 'query-diagnostics',
    eyebrow: 'Per-Query Diagnostics',
    title: 'Per-Query Diagnostics',
    description: 'These grouped rows expose per-query and per-model slices so it is easier to see whether the observed biases are consistent across prompts or dominated by specific cases.',
    status: 'available',
    tables: [
      buildTable(
        'query-diagnostics-table',
        'Query × model summary',
        [
          column('query', 'Query'),
          column('entity', input.analysis.summary.entity_label),
          column('records', 'Records', 'end'),
          column('unique', 'Unique', 'end'),
          column('matched', 'Matched', 'end'),
          column('metadata', 'Metadata', 'end'),
          column('conflicts', 'Conflicts', 'end'),
          column('risk', input.detail.run.run_type === 'llm_audit' ? 'High risk' : 'Risk', 'end')
        ],
        queryGroups.map(([key, queryRows]) => {
          const [queryId, entity] = key.split('::');
          return {
            key,
            values: {
              query: queryLabelFromId(input, queryId),
              entity,
              records: integerLabel(queryRows.length),
              unique: integerLabel(new Set(queryRows.map(uniqueRecordKey)).size),
              matched: percentageLabel(ratio(queryRows.filter((row) => row.matched).length, queryRows.length)),
              metadata: percentageLabel(mean(queryRows.map(recordCompleteness))),
              conflicts: percentageLabel(ratio(queryRows.filter((row) => row.any_conflict).length, queryRows.length)),
              risk: input.detail.run.run_type === 'llm_audit'
                ? percentageLabel(ratio(queryRows.filter((row) => row.hallucination_risk_bucket === 'high').length, queryRows.length))
                : '—'
            }
          };
        })
      )
    ]
  };
}

function buildCoverageSection(input: ReportInput, queryId: string | null): ReportSection {
  const scopeRows = selectCoverageScope(input.analysis.coverage_rows, queryId, input.selectedEntity || 'overall');
  const heatmap = buildCoverageHeatmap(input.analysis.coverage_rows, input, queryId, false);

  return {
    key: 'metadata-coverage',
    eyebrow: 'Metadata Coverage',
    title: 'Metadata Coverage',
    description: 'Overall field coverage plus a coverage-by-entity heatmap on the current query slice.',
    status: scopeRows.length ? 'available' : 'unavailable',
    reason: scopeRows.length ? undefined : 'Coverage rows are not available for the current filters.',
    cards: scopeRows.length
      ? scopeRows.slice(0, 6).map((row) =>
          card(row.field, fieldLabel(row.field), percentageLabel(row.coverage_ratio), `${row.populated_count}/${row.total_count}`)
        )
      : [],
    heatmaps: heatmap.cells.length ? [heatmap] : [],
    tables: scopeRows.length
      ? [
          {
            key: 'coverage-breakdown',
            title: 'Coverage breakdown',
            columns: [
              { key: 'field', label: 'Field' },
              { key: 'populated', label: 'Populated', align: 'end' },
              { key: 'missing', label: 'Missing', align: 'end' },
              { key: 'coverage', label: 'Coverage', align: 'end' }
            ],
            rows: scopeRows.map((row) => ({
              key: row.field,
              values: {
                field: fieldLabel(row.field),
                populated: integerLabel(row.populated_count),
                missing: integerLabel(row.missing_count),
                coverage: percentageLabel(row.coverage_ratio)
              }
            }))
          }
        ]
      : []
  };
}

function buildMissingnessSection(input: ReportInput, queryId: string | null): ReportSection {
  const heatmap = buildCoverageHeatmap(input.analysis.coverage_rows, input, queryId, true);
  return {
    key: 'missingness',
    eyebrow: 'Missingness',
    title: 'Missingness',
    description: 'Field missingness across sources or models, rendered as a heatmap instead of a flat table.',
    status: heatmap.cells.length ? 'available' : 'unavailable',
    reason: heatmap.cells.length ? undefined : 'Missingness rows are not available for the current filters.',
    heatmaps: heatmap.cells.length ? [heatmap] : []
  };
}

function buildEnrichmentGainSection(input: ReportInput, queryId: string | null): ReportSection {
  const enrichedRows = selectCoverageScope(input.analysis.coverage_rows, queryId, input.selectedEntity || 'overall');
  const baselineRows = selectCoverageScope(input.analysis.baseline_coverage_rows, queryId, input.selectedEntity || 'overall');
  const baselineByField = new Map(baselineRows.map((row) => [row.field, row]));
  const gainRows = enrichedRows.map((row) => {
    const baseline = baselineByField.get(row.field);
    const before = baseline?.coverage_ratio ?? 0;
    const delta = row.coverage_ratio - before;
    return {
      field: row.field,
      before,
      after: row.coverage_ratio,
      delta
    };
  });
  const improved = gainRows.filter((row) => row.delta > 0.0001);
  const heatmap = buildEnrichmentGainHeatmap(input, queryId);

  return {
    key: 'enrichment-gain',
    eyebrow: 'Enrichment Gain',
    title: 'Enrichment Gain',
    description: 'Before-versus-after coverage to show which metadata fields improved after enrichment.',
    status: gainRows.length ? 'available' : 'unavailable',
    reason: gainRows.length ? undefined : 'Baseline and enriched coverage rows are not both available.',
    cards: gainRows.length
      ? [
          card('improved', 'Improved fields', integerLabel(improved.length)),
          card('largest', 'Largest gain', percentageLabel(maxValue(gainRows.map((row) => row.delta)))),
          card('doi', 'DOI gain', percentageLabel(fieldDelta(gainRows, 'doi'))),
          card('country', 'Country gain', percentageLabel(fieldDelta(gainRows, 'country_primary')))
        ]
      : [],
    heatmaps: heatmap.cells.length ? [heatmap] : [],
    tables: gainRows.length
      ? [
          {
            key: 'gain-table',
            title: 'Field improvement',
            columns: [
              { key: 'field', label: 'Field' },
              { key: 'before', label: 'Before', align: 'end' },
              { key: 'after', label: 'After', align: 'end' },
              { key: 'delta', label: 'Delta', align: 'end' }
            ],
            rows: gainRows.map((row) => ({
              key: row.field,
              values: {
                field: fieldLabel(row.field),
                before: percentageLabel(row.before),
                after: percentageLabel(row.after),
                delta: signedPercentageLabel(row.delta)
              }
            }))
          }
        ]
      : []
  };
}

function buildOverlapSection(input: ReportInput, queryId: string | null): ReportSection {
  const rows = filterOverlapRows(input.analysis.overlap_rows, queryId, input.selectedEntity);
  const heatmap = buildOverlapHeatmap(rows);
  if (!rows.length) {
    return unavailableSection(
      'record-overlap',
      'Record Overlap',
      'Record Overlap',
      'Pairwise overlap across models or sources.',
      'At least two sources or models with comparable results are required.'
    );
  }

  return {
    key: 'record-overlap',
    eyebrow: 'Record Overlap',
    title: 'Record Overlap',
    description: 'Pairwise overlap heatmaps and comparison tables aligned across run modes.',
    status: 'available',
    cards: [
      card('jaccard', 'Mean Jaccard', percentageLabel(mean(rows.map((row) => row.jaccard)))),
      card('overlap', 'Mean overlap@k', percentageLabel(mean(rows.map((row) => row.overlap_at_k)))),
      card('rbo', 'Mean RBO', percentageLabel(mean(rows.map((row) => row.rank_biased_overlap)))),
      card('top1', 'Top-1 agreement', percentageLabel(mean(rows.map((row) => row.top_1_agreement ?? null))))
    ],
    heatmaps: heatmap.cells.length ? [heatmap] : [],
    tables: [
      buildTable(
        'overlap-table',
        'Pairwise overlap',
        [
          column('pair', 'Pair'),
          column('jaccard', 'Jaccard', 'end'),
          column('overlap', 'Overlap@k', 'end'),
          column('rbo', 'RBO', 'end'),
          column('top1', 'Top-1', 'end')
        ],
        rows.map((row) => ({
          key: `${row.left_entity}-${row.right_entity}`,
          values: {
            pair: `${row.left_entity} vs ${row.right_entity}`,
            jaccard: percentageLabel(row.jaccard),
            overlap: percentageLabel(row.overlap_at_k),
            rbo: percentageLabel(row.rank_biased_overlap),
            top1: percentageLabel(row.top_1_agreement)
          }
        }))
      )
    ]
  };
}

function buildRankingBiasSection(
  rows: UnifiedRecordRow[],
  topRows: UnifiedRecordRow[],
  restRows: UnifiedRecordRow[],
  selectedTopK: number
): ReportSection {
  if (!topRows.length || !restRows.length) {
    return unavailableSection(
      'ranking-bias',
      'Ranking Bias',
      'Ranking Bias',
      'Top-k versus rest comparisons for the current selection.',
      `Need more than ${selectedTopK} ranked records to compare the top slice against the remainder.`
    );
  }

  const topCitation = mean(topRows.map((row) => numberOrNull(row.cited_by_count)));
  const restCitation = mean(restRows.map((row) => numberOrNull(row.cited_by_count)));
  const topYear = mean(topRows.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year)));
  const restYear = mean(restRows.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year)));
  const topOa = ratio(topRows.filter((row) => row.is_oa === true).length, topRows.filter((row) => row.is_oa !== null).length);
  const restOa = ratio(restRows.filter((row) => row.is_oa === true).length, restRows.filter((row) => row.is_oa !== null).length);
  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);

  return {
    key: 'ranking-bias',
    eyebrow: 'Ranking Bias',
    title: 'Ranking Bias',
    description: 'Ranking bias shows whether higher-ranked positions systematically favor certain citation, recency, or access characteristics. Values below compare the selected top-k slice against the remaining results.',
    status: 'available',
    cards: [
      card('oa-delta', 'OA delta', signedPercentageLabel(difference(topOa, restOa))),
      card('citation-delta', 'Citation delta', signedNumberLabel(difference(topCitation, restCitation))),
      card('year-delta', 'Recency delta', signedNumberLabel(difference(topYear, restYear))),
      card('slice', 'Top-k slice', integerLabel(topRows.length))
    ],
    tables: [
      buildTable(
        'ranking-table',
        'Top-k versus rest',
        [
          column('metric', 'Metric'),
          column('top', 'Top-k', 'end'),
          column('rest', 'Rest', 'end'),
          column('delta', 'Delta', 'end')
        ],
        [
          rankingRow('open-access', 'Open access share', topOa, restOa, true),
          rankingRow('citation', 'Citation mean', topCitation, restCitation, false),
          rankingRow('recency', 'Publication year mean', topYear, restYear, false)
        ]
      ),
      buildTable(
        'ranking-by-entity',
        'Per-model top-k versus rest',
        [
          column('entity', 'Model / platform'),
          column('oa', 'OA delta', 'end'),
          column('citation', 'Citation delta', 'end'),
          column('recency', 'Recency delta', 'end')
        ],
        byEntity.map(([entity, entityRows]) => {
          const entityTop = entityRows.filter((row) => row.rank <= selectedTopK);
          const entityRest = entityRows.filter((row) => row.rank > selectedTopK);
          return {
            key: entity,
            values: {
              entity,
              oa: signedPercentageLabel(
                difference(
                  ratio(entityTop.filter((row) => row.is_oa === true).length, entityTop.filter((row) => row.is_oa !== null).length),
                  ratio(entityRest.filter((row) => row.is_oa === true).length, entityRest.filter((row) => row.is_oa !== null).length)
                )
              ),
              citation: signedNumberLabel(
                difference(
                  mean(entityTop.map((row) => numberOrNull(row.cited_by_count))),
                  mean(entityRest.map((row) => numberOrNull(row.cited_by_count)))
                )
              ),
              recency: signedNumberLabel(
                difference(
                  mean(entityTop.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year))),
                  mean(entityRest.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year)))
                )
              )
            }
          };
        })
      )
    ],
    notes: [
      'CORE rank and JIF quartile panels remain gated because the current data model does not provide those venue prestige fields.'
    ]
  };
}

function buildGeoBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const knownRows = rows.filter((row) => Boolean(row.country_primary));
  const coverage = ratio(knownRows.length, rows.length);
  if (!rows.length) {
    return unavailableSection('geo-bias', 'Geo Bias', 'Geo Bias', 'Country representation and over/under-indexing.', 'No records are available for the current filters.');
  }
  if (knownRows.length < 3 || (coverage ?? 0) < 0.35) {
    return insufficientSection(
      'geo-bias',
      'Geo Bias',
      'Geo Bias',
      'Country representation and over/under-indexing.',
      `Known country coverage is ${percentageLabel(coverage)} across ${knownRows.length} records, which is too low for a stable geo panel.`
    );
  }

  const overallCounts = countBy(knownRows, (row) => row.country_primary || 'unknown');
  const topCounts = countBy(topRows.filter((row) => row.country_primary), (row) => row.country_primary || 'unknown');
  const topCountry = firstKey(overallCounts);
  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);
  return {
    key: 'geo-bias',
    eyebrow: 'Geo Bias',
    title: 'Geo Bias',
    description: 'Geo bias shows whether certain countries are overrepresented in the returned literature. Coverage cards summarize how much of the panel depends on verified or enriched country metadata.',
    status: 'available',
    cards: [
      card('coverage', 'Country coverage', percentageLabel(coverage)),
      card('countries', 'Distinct countries', integerLabel(overallCounts.size)),
      card('top', 'Top country share', percentageLabel(shareFromMap(overallCounts, topCountry))),
      card('topk', 'Top-k country share', percentageLabel(shareFromMap(topCounts, topCountry)))
    ],
    series: [
      mapToSeries('geo-overall', 'Overall geography', overallCounts, knownRows.length),
      mapToSeries('geo-topk', 'Top-k geography', topCounts, Math.max(topRows.filter((row) => row.country_primary).length, 1))
    ],
    heatmaps: [
      buildRecordHeatmap(
        'geo-heatmap',
        'Country distribution by model / platform',
        'This heatmap shows country share for each model or platform. Darker cells indicate stronger representation within that model-specific slice.',
        byEntity,
        rows,
        (row) => row.country_primary || 'unknown',
        8
      )
    ],
    tables: [
      buildTable(
        'geo-representation',
        'Representation delta',
        [
          column('country', 'Country'),
          column('overall', 'Overall share', 'end'),
          column('topk', 'Top-k share', 'end'),
          column('delta', 'Delta', 'end')
        ],
        representationRows(overallCounts, topCounts, knownRows.length, Math.max(topRows.filter((row) => row.country_primary).length, 1))
      ),
      buildTable(
        'geo-by-entity',
        'Country coverage by model / platform',
        [
          column('entity', 'Model / platform'),
          column('coverage', 'Country coverage', 'end'),
          column('dominant', 'Dominant country'),
          column('dominant_share', 'Dominant share', 'end'),
          column('multi', 'Multi-country share', 'end')
        ],
        byEntity.map(([entity, entityRows]) => {
          const entityCounts = countBy(entityRows.filter((row) => row.country_primary), (row) => row.country_primary || 'unknown');
          const dominant = firstKey(entityCounts);
          return {
            key: entity,
            values: {
              entity,
              coverage: percentageLabel(ratio(entityRows.filter((row) => Boolean(row.country_primary)).length, entityRows.length)),
              dominant,
              dominant_share: percentageLabel(shareFromMap(entityCounts, dominant)),
              multi: percentageLabel(ratio(entityRows.filter((row) => row.countries.length > 1).length, entityRows.length))
            }
          };
        })
      )
    ]
  };
}

function buildLanguageBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const knownRows = rows.filter((row) => row.language && row.language !== 'unknown');
  const coverage = ratio(knownRows.length, rows.length);
  if (!rows.length) {
    return unavailableSection('language-bias', 'Language Bias', 'Language Bias', 'Language distribution and language-specific top-k shifts.', 'No records are available for the current filters.');
  }
  if (knownRows.length < 3 || (coverage ?? 0) < 0.35) {
    return insufficientSection(
      'language-bias',
      'Language Bias',
      'Language Bias',
      'Language distribution and language-specific top-k shifts.',
      `Known language coverage is ${percentageLabel(coverage)} across ${knownRows.length} records, which is too low for a stable language panel.`
    );
  }

  const overallCounts = countBy(knownRows, (row) => row.language || 'unknown');
  const topCounts = countBy(topRows.filter((row) => row.language), (row) => row.language || 'unknown');
  const englishCount = overallCounts.get('en') ?? 0;
  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);

  return {
    key: 'language-bias',
    eyebrow: 'Language Bias',
    title: 'Language Bias',
    description: 'Language bias reflects whether models disproportionately surface certain languages and suppress others. The heatmap and table below expose that pattern per model or platform instead of only as a pooled aggregate.',
    status: 'available',
    cards: [
      card('coverage', 'Known language share', percentageLabel(coverage)),
      card('unknown', 'Unknown language share', percentageLabel(ratio(rows.length - knownRows.length, rows.length))),
      card('english', 'English share of known', percentageLabel(ratio(englishCount, knownRows.length))),
      card('languages', 'Distinct languages', integerLabel(overallCounts.size))
    ],
    series: [
      mapToSeries('language-overall', 'Overall languages', overallCounts, knownRows.length),
      mapToSeries('language-topk', 'Top-k languages', topCounts, Math.max(topRows.filter((row) => row.language).length, 1))
    ],
    heatmaps: [
      buildRecordHeatmap(
        'language-heatmap',
        'Language share by model / platform',
        'This heatmap shows which languages each model or platform surfaces most often. Darker cells indicate higher share within that model-specific slice.',
        byEntity,
        rows,
        (row) => row.language || 'unknown',
        8
      )
    ],
    tables: [
      buildTable(
        'language-table',
        'Language counts and shares',
        [
          column('language', 'Language'),
          column('count', 'Count', 'end'),
          column('share', 'Share', 'end')
        ],
        Array.from(overallCounts.entries()).map(([label, count]) => ({
          key: label,
          values: {
            language: label,
            count: integerLabel(count),
            share: percentageLabel(ratio(count, knownRows.length))
          }
        }))
      ),
      buildTable(
        'language-by-entity',
        'Per-model language summary',
        [
          column('entity', 'Model / platform'),
          column('english', 'English share', 'end'),
          column('non_english', 'Non-English share', 'end'),
          column('unknown', 'Unknown share', 'end')
        ],
        byEntity.map(([entity, entityRows]) => {
          const knownCount = entityRows.filter((row) => Boolean(row.language) && row.language !== 'unknown').length;
          const english = entityRows.filter((row) => row.language === 'en').length;
          return {
            key: entity,
            values: {
              entity,
              english: percentageLabel(ratio(english, knownCount)),
              non_english: percentageLabel(ratio(Math.max(knownCount - english, 0), knownCount)),
              unknown: percentageLabel(ratio(entityRows.length - knownCount, entityRows.length))
            }
          };
        })
      )
    ]
  };
}

function buildPublisherBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const knownRows = rows.filter((row) => Boolean(row.publisher));
  if (knownRows.length < 3) {
    return insufficientSection(
      'publisher-bias',
      'Publisher Bias',
      'Publisher Bias',
      'Publisher bias reflects whether a model disproportionately favors outputs from certain publishers or publisher groups.',
      'Publisher metadata coverage is too low for a stable publisher-bias panel.'
    );
  }

  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);
  const overallCounts = countBy(knownRows, (row) => row.publisher || 'unknown');
  const topCounts = countBy(topRows.filter((row) => row.publisher), (row) => row.publisher || 'unknown');

  return {
    key: 'publisher-bias',
    eyebrow: 'Publisher Bias',
    title: 'Publisher Bias',
    description: 'This section shows whether each model or platform concentrates retrieval among a narrow set of publishers. Higher concentration and larger top-k deltas suggest stronger publisher preference.',
    status: 'available',
    cards: [
      card('coverage', 'Publisher coverage', percentageLabel(ratio(knownRows.length, rows.length))),
      card('publishers', 'Distinct publishers', integerLabel(overallCounts.size)),
      card('top_share', 'Top publisher share', percentageLabel(shareFromMap(overallCounts, firstKey(overallCounts)))),
      card('top5_share', 'Top 5 share', percentageLabel(topNShare(overallCounts, 5)))
    ],
    heatmaps: [
      buildRecordHeatmap(
        'publisher-heatmap',
        'Publisher share by model / platform',
        'This heatmap shows the relative share of the most common publishers within each model or platform.',
        byEntity,
        rows,
        (row) => row.publisher || 'unknown',
        8
      )
    ],
    tables: [
      buildTable(
        'publisher-by-entity',
        'Per-model publisher concentration',
        [
          column('entity', 'Model / platform'),
          column('top_publisher', 'Top publisher'),
          column('top_share', 'Top share', 'end'),
          column('top5_share', 'Top 5 share', 'end'),
          column('hhi', 'Publisher HHI', 'end')
        ],
        byEntity.map(([entity, entityRows]) => {
          const counts = countBy(entityRows.filter((row) => row.publisher), (row) => row.publisher || 'unknown');
          return {
            key: entity,
            values: {
              entity,
              top_publisher: firstKey(counts),
              top_share: percentageLabel(shareFromMap(counts, firstKey(counts))),
              top5_share: percentageLabel(topNShare(counts, 5)),
              hhi: numberLabel(hhi(entityRows.map((row) => row.publisher).filter((value): value is string => Boolean(value))))
            }
          };
        })
      ),
      buildTable(
        'publisher-topk',
        'Overall versus top-k publisher skew',
        [
          column('publisher', 'Publisher'),
          column('overall', 'Overall share', 'end'),
          column('topk', 'Top-k share', 'end'),
          column('delta', 'Delta', 'end')
        ],
        representationRows(overallCounts, topCounts, knownRows.length, Math.max(topRows.filter((row) => row.publisher).length, 1), 'publisher')
      )
    ]
  };
}

function buildOaBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const knownRows = rows.filter((row) => row.is_oa !== null || Boolean(row.oa_status));
  if (knownRows.length < 3) {
    return insufficientSection(
      'oa-bias',
      'OA Bias',
      'OA Bias',
      'OA bias reflects whether models prefer open-access, closed, or specific OA pathway records.',
      'OA coverage is too low for a stable OA-bias panel.'
    );
  }

  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);
  return {
    key: 'oa-bias',
    eyebrow: 'OA Bias',
    title: 'OA Bias',
    description: 'This section compares open-access, closed, and unknown shares by model or platform. It also shows whether the selected top-k slice is more open or more closed than the full result set.',
    status: 'available',
    heatmaps: [
      buildRecordHeatmap(
        'oa-heatmap',
        'OA status by model / platform',
        'This heatmap shows OA status shares for each model or platform. Darker cells indicate higher within-model share.',
        byEntity,
        rows,
        (row) => oaStatusLabel(row),
        4
      )
    ],
    tables: [
      buildTable(
        'oa-by-entity',
        'Per-model OA summary',
        [
          column('entity', 'Model / platform'),
          column('known', 'Known OA', 'end'),
          column('open', 'Open share', 'end'),
          column('closed', 'Closed share', 'end'),
          column('unknown', 'Unknown share', 'end'),
          column('topk_delta', 'Top-k open delta', 'end')
        ],
        byEntity.map(([entity, entityRows]) => {
          const entityTop = entityRows.filter((row) => row.rank <= topRows.reduce((max, row) => Math.max(max, row.rank), 0));
          const openKnown = entityRows.filter((row) => row.is_oa !== null);
          return {
            key: entity,
            values: {
              entity,
              known: percentageLabel(ratio(knownRows.filter((row) => row.model_or_platform === entity).length, entityRows.length)),
              open: percentageLabel(ratio(openKnown.filter((row) => row.is_oa === true).length, openKnown.length)),
              closed: percentageLabel(ratio(openKnown.filter((row) => row.is_oa === false).length, openKnown.length)),
              unknown: percentageLabel(ratio(entityRows.length - knownRows.filter((row) => row.model_or_platform === entity).length, entityRows.length)),
              topk_delta: signedPercentageLabel(
                difference(
                  ratio(entityTop.filter((row) => row.is_oa === true).length, entityTop.filter((row) => row.is_oa !== null).length),
                  ratio(entityRows.filter((row) => row.is_oa === true).length, entityRows.filter((row) => row.is_oa !== null).length)
                )
              )
            }
          };
        })
      )
    ]
  };
}

function buildRecencyBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const yearRows = rows.filter((row) => (row.enriched_year ?? row.parsed_year) !== null);
  if (yearRows.length < 3) {
    return insufficientSection(
      'recency-bias',
      'Recency Bias',
      'Recency Bias',
      'Recency bias shows whether a model systematically prefers newer or older literature.',
      'Publication year coverage is too low for a stable recency panel.'
    );
  }

  return {
    key: 'recency-bias',
    eyebrow: 'Recency Bias',
    title: 'Recency Bias',
    description: 'This section shows publication year distributions per model or platform. Higher recent-share values suggest a stronger preference for newer literature.',
    status: 'available',
    series: [
      buildRecordDistributionSeries('recency-all', 'Overall recency', yearRows, (row) => yearBucket(row.enriched_year ?? row.parsed_year)),
      buildRecordDistributionSeries('recency-topk', 'Top-k recency', topRows.filter((row) => (row.enriched_year ?? row.parsed_year) !== null), (row) => yearBucket(row.enriched_year ?? row.parsed_year))
    ],
    tables: [
      buildTable(
        'recency-by-entity',
        'Per-model recency summary',
        [
          column('entity', 'Model / platform'),
          column('mean_year', 'Mean year', 'end'),
          column('median_year', 'Median year', 'end'),
          column('recent', 'Recent share', 'end'),
          column('old', 'Older share', 'end'),
          column('topk_delta', 'Top-k year delta', 'end')
        ],
        sortedGroups(rows, (row) => row.model_or_platform).map(([entity, entityRows]) => {
          const years = entityRows.map((row) => row.enriched_year ?? row.parsed_year).filter((value): value is number => value !== null);
          const entityTop = entityRows.filter((row) => row.rank <= inferTopKFromRows(topRows));
          return {
            key: entity,
            values: {
              entity,
              mean_year: numberLabel(mean(years)),
              median_year: numberLabel(median(years)),
              recent: percentageLabel(ratio(years.filter((year) => new Date().getUTCFullYear() - year <= 5).length, years.length)),
              old: percentageLabel(ratio(years.filter((year) => new Date().getUTCFullYear() - year > 10).length, years.length)),
              topk_delta: signedNumberLabel(
                difference(
                  mean(entityTop.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year))),
                  mean(entityRows.map((row) => numberOrNull(row.enriched_year ?? row.parsed_year)))
                )
              )
            }
          };
        })
      )
    ]
  };
}

function buildCitationBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const citationRows = rows.filter((row) => row.cited_by_count !== null);
  if (citationRows.length < 3) {
    return insufficientSection(
      'citation-bias',
      'Citation Bias',
      'Citation Bias',
      'Citation bias reflects whether a model privileges highly cited literature over less cited work.',
      'Citation coverage is too low for a stable citation-bias panel.'
    );
  }

  return {
    key: 'citation-bias',
    eyebrow: 'Citation Bias',
    title: 'Citation Bias',
    description: 'This section compares citation distributions by model or platform and shows whether top-ranked records are more highly cited than the overall set.',
    status: 'available',
    tables: [
      buildTable(
        'citation-by-entity',
        'Per-model citation summary',
        [
          column('entity', 'Model / platform'),
          column('median', 'Median citations', 'end'),
          column('high', 'Highly cited share', 'end'),
          column('low', 'Low / uncited share', 'end'),
          column('topk_delta', 'Top-k citation delta', 'end')
        ],
        sortedGroups(rows, (row) => row.model_or_platform).map(([entity, entityRows]) => {
          const citations = entityRows.map((row) => row.cited_by_count).filter((value): value is number => value !== null);
          const entityTop = entityRows.filter((row) => row.rank <= inferTopKFromRows(topRows));
          return {
            key: entity,
            values: {
              entity,
              median: numberLabel(median(citations)),
              high: percentageLabel(ratio(citations.filter((count) => count >= 100).length, citations.length)),
              low: percentageLabel(ratio(citations.filter((count) => count <= 5).length, citations.length)),
              topk_delta: signedNumberLabel(
                difference(
                  mean(entityTop.map((row) => numberOrNull(row.cited_by_count))),
                  mean(entityRows.map((row) => numberOrNull(row.cited_by_count)))
                )
              )
            }
          };
        })
      )
    ]
  };
}

function buildSourceTypeBiasSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const knownRows = rows.filter((row) => Boolean(row.source_type));
  if (knownRows.length < 3) {
    return insufficientSection(
      'source-type-bias',
      'Source-Type Bias',
      'Source-Type Bias',
      'Source-type bias captures whether a system favors certain publication formats over others.',
      'Source type coverage is too low for a stable source-type panel.'
    );
  }

  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);
  const overallCounts = countBy(knownRows, (row) => row.source_type || 'unknown');
  const topCounts = countBy(topRows.filter((row) => row.source_type), (row) => row.source_type || 'unknown');
  return {
    key: 'source-type-bias',
    eyebrow: 'Source-Type Bias',
    title: 'Source-Type Bias',
    description: 'This section compares publication-format shares across models or platforms and shows whether top-ranked results tilt toward journals, repositories, preprints, conferences, or other source types.',
    status: 'available',
    heatmaps: [
      buildRecordHeatmap(
        'source-type-heatmap',
        'Source type share by model / platform',
        'This heatmap shows how strongly each model or platform favors specific source types.',
        byEntity,
        rows,
        (row) => row.source_type || 'unknown',
        6
      )
    ],
    tables: [
      buildTable(
        'source-type-skew',
        'Overall versus top-k source-type skew',
        [
          column('source_type', 'Source type'),
          column('overall', 'Overall share', 'end'),
          column('topk', 'Top-k share', 'end'),
          column('delta', 'Delta', 'end')
        ],
        representationRows(overallCounts, topCounts, knownRows.length, Math.max(topRows.filter((row) => row.source_type).length, 1), 'source_type')
      )
    ]
  };
}

function buildTopicDriftSection(rows: UnifiedRecordRow[], topRows: UnifiedRecordRow[]): ReportSection {
  const topicRows = rows.filter((row) => Boolean(row.topic || row.subfield));
  if (topicRows.length < 3) {
    return insufficientSection(
      'topic-drift',
      'Topic Drift',
      'Topic / Subfield Drift',
      'Topic drift captures whether a model narrows retrieval into specific subfields instead of covering the broader intended topic.',
      'Topic or subfield metadata is too sparse for a stable topic-drift panel.'
    );
  }

  const byEntity = sortedGroups(topicRows, (row) => row.model_or_platform);
  const overallCounts = countBy(topicRows, (row) => row.topic || row.subfield || 'unknown');
  const topCounts = countBy(topRows.filter((row) => row.topic || row.subfield), (row) => row.topic || row.subfield || 'unknown');

  return {
    key: 'topic-drift',
    eyebrow: 'Topic Drift',
    title: 'Topic / Subfield Drift',
    description: 'This section shows whether retrieval narrows into a small subset of topics or subfields. Higher concentration and larger top-k deltas suggest stronger topic drift.',
    status: 'available',
    heatmaps: [
      buildRecordHeatmap(
        'topic-heatmap',
        'Topic share by model / platform',
        'This heatmap shows the most common topics or subfields within each model-specific slice.',
        byEntity,
        topicRows,
        (row) => row.topic || row.subfield || 'unknown',
        8
      )
    ],
    tables: [
      buildTable(
        'topic-by-entity',
        'Per-model topic concentration',
        [
          column('entity', 'Model / platform'),
          column('topics', 'Distinct topics', 'end'),
          column('top_topic', 'Top topic'),
          column('top_share', 'Top share', 'end')
        ],
        byEntity.map(([entity, entityRows]) => {
          const counts = countBy(entityRows, (row) => row.topic || row.subfield || 'unknown');
          return {
            key: entity,
            values: {
              entity,
              topics: integerLabel(counts.size),
              top_topic: firstKey(counts),
              top_share: percentageLabel(shareFromMap(counts, firstKey(counts)))
            }
          };
        })
      ),
      buildTable(
        'topic-overall-vs-topk',
        'Overall versus top-k topic drift',
        [
          column('topic', 'Topic'),
          column('overall', 'Overall share', 'end'),
          column('topk', 'Top-k share', 'end'),
          column('delta', 'Delta', 'end')
        ],
        representationRows(overallCounts, topCounts, topicRows.length, Math.max(topRows.filter((row) => row.topic || row.subfield).length, 1), 'topic')
      )
    ]
  };
}

function buildVenueDiversitySection(rows: UnifiedRecordRow[]): ReportSection {
  const venues = rows.map((row) => row.enriched_journal || row.parsed_journal).filter((value): value is string => Boolean(value));
  const publishers = rows.map((row) => row.publisher).filter((value): value is string => Boolean(value));
  if (venues.length < 3 && publishers.length < 3) {
    return unavailableSection(
      'venue-diversity',
      'Venue Diversity',
      'Venue Diversity',
      'Venue and publisher concentration metrics for the active scope.',
      'Need at least three venue or publisher observations to assess concentration.'
    );
  }

  const venueCounts = countLabels(venues);
  const publisherCounts = countLabels(publishers);
  return {
    key: 'venue-diversity',
    eyebrow: 'Venue Diversity',
    title: 'Venue Diversity',
    description: 'Venue diversity evaluates whether retrieved literature is spread across many venues or concentrated in a narrow subset. Higher concentration values suggest narrower venue diversity.',
    status: 'available',
    cards: [
      card('venue-hhi', 'Venue concentration', numberLabel(hhi(venues))),
      card('publisher-hhi', 'Publisher concentration', numberLabel(hhi(publishers))),
      card('venues', 'Distinct venues', integerLabel(venueCounts.size)),
      card('publishers', 'Distinct publishers', integerLabel(publisherCounts.size))
    ],
    series: [
      mapToSeries('venues', 'Top venues', venueCounts, Math.max(venues.length, 1)),
      mapToSeries('publishers', 'Top publishers', publisherCounts, Math.max(publishers.length, 1))
    ],
    tables: [
      buildTable(
        'venue-diversity-by-entity',
        'Per-model venue concentration',
        [
          column('entity', 'Model / platform'),
          column('unique_venues', 'Unique venues', 'end'),
          column('venue_hhi', 'Venue HHI', 'end'),
          column('top_venue', 'Top venue share', 'end'),
          column('top5_venue', 'Top 5 share', 'end')
        ],
        sortedGroups(rows, (row) => row.model_or_platform).map(([entity, entityRows]) => {
          const entityVenues = entityRows
            .map((row) => row.enriched_journal || row.parsed_journal)
            .filter((value): value is string => Boolean(value));
          const counts = countLabels(entityVenues);
          return {
            key: entity,
            values: {
              entity,
              unique_venues: integerLabel(new Set(entityVenues).size),
              venue_hhi: numberLabel(hhi(entityVenues)),
              top_venue: percentageLabel(shareFromMap(counts, firstKey(counts))),
              top5_venue: percentageLabel(topNShare(counts, 5))
            }
          };
        })
      )
    ]
  };
}

function buildAdditionalBiasSection(
  rows: UnifiedRecordRow[],
  topRows: UnifiedRecordRow[],
  restRows: UnifiedRecordRow[],
  selectedTopK: number
): ReportSection {
  if (!rows.length) {
    return unavailableSection(
      'additional-bias-audits',
      'Additional Bias Audits',
      'Additional Bias Audits',
      'Secondary audits supported by the current metadata model.',
      'No records are available for the current filters.'
    );
  }

  const openStatusCounts = countBy(rows.filter((row) => row.oa_pathway), (row) => row.oa_pathway || 'unknown');
  const openStatusTop = countBy(topRows.filter((row) => row.oa_pathway), (row) => row.oa_pathway || 'unknown');
  const affiliationValues = rows.flatMap((row) => {
    const payload = row.enriched_payload as Record<string, unknown>;
    const affiliations = payload['affiliations'];
    return Array.isArray(affiliations) ? affiliations.filter((value): value is string => typeof value === 'string') : [];
  });
  const fieldValues = rows.map((row) => row.topic).filter((value): value is string => Boolean(value));
  const topFieldValues = topRows.map((row) => row.topic).filter((value): value is string => Boolean(value));
  const languageOpenRows = rows.filter((row) => row.language && row.is_oa !== null);
  const yearVerificationRows = rows.filter((row) => (row.enriched_year ?? row.parsed_year) !== null);

  const notes = [
    'Institution-type bias remains gated because the current enrichment model stores affiliation names but not institution taxonomy.',
    rows.length <= selectedTopK ? `Top-k versus rest comparisons are limited because the active selection has ${rows.length} records.` : undefined
  ].filter((note): note is string => Boolean(note));

  const tables: ReportTable[] = [];
  if (openStatusCounts.size) {
    tables.push(
      buildTable(
        'oa-pathway',
        'OA pathway bias',
        [
          column('status', 'OA pathway'),
          column('overall', 'Overall share', 'end'),
          column('topk', 'Top-k share', 'end'),
          column('delta', 'Delta', 'end')
        ],
        representationRows(openStatusCounts, openStatusTop, rows.filter((row) => row.oa_pathway).length, Math.max(topRows.filter((row) => row.oa_pathway).length, 1), 'status')
      )
    );
  }
  if (fieldValues.length) {
    tables.push(
      buildTable(
        'topic-drift',
        'Topic / subfield drift',
        [
          column('field', 'Field'),
          column('overall', 'Overall share', 'end'),
          column('topk', 'Top-k share', 'end'),
          column('delta', 'Delta', 'end')
        ],
        representationRows(countLabels(fieldValues), countLabels(topFieldValues), Math.max(fieldValues.length, 1), Math.max(topFieldValues.length, 1), 'field')
      )
    );
  }
  if (languageOpenRows.length) {
    const byLanguage = groupBy(languageOpenRows, (row) => row.language || 'unknown');
    tables.push(
      buildTable(
        'language-oa',
        'Language × OA interaction',
        [
          column('language', 'Language'),
          column('records', 'Records', 'end'),
          column('open', 'Open share', 'end')
        ],
        Object.entries(byLanguage).map(([language, items]) => ({
          key: language,
          values: {
            language,
            records: integerLabel(items.length),
            open: percentageLabel(ratio(items.filter((item) => item.is_oa === true).length, items.filter((item) => item.is_oa !== null).length))
          }
        }))
      )
    );
  }
  if (yearVerificationRows.length) {
    const byBucket = groupBy(yearVerificationRows, (row) => yearBucket(row.enriched_year ?? row.parsed_year));
    tables.push(
      buildTable(
        'recency-verification',
        'Recency × verification coverage',
        [
          column('bucket', 'Recency'),
          column('records', 'Records', 'end'),
          column('verified', 'Verified share', 'end')
        ],
        Object.entries(byBucket).map(([bucket, items]) => ({
          key: bucket,
          values: {
            bucket,
            records: integerLabel(items.length),
            verified: percentageLabel(ratio(items.filter((item) => item.matched).length, items.length))
          }
        }))
      )
    );
  }

  return {
    key: 'additional-bias-audits',
    eyebrow: 'Additional Bias Audits',
    title: 'Additional Bias Audits',
    description: 'Supported secondary audits from the current metadata model, with unsupported panels gated explicitly.',
    status: tables.length || affiliationValues.length ? 'available' : 'unavailable',
    reason: tables.length || affiliationValues.length ? undefined : 'The current filters do not expose enough metadata for the supported secondary audits.',
    cards: [
      card('affiliation-hhi', 'Affiliation concentration', numberLabel(hhi(affiliationValues))),
      card('top-affiliation', 'Top affiliation share', percentageLabel(shareFromMap(countLabels(affiliationValues), firstKey(countLabels(affiliationValues))))),
      card('topic-count', 'Distinct fields', integerLabel(new Set(fieldValues).size)),
      card('publisher-hhi', 'Publisher bias proxy', numberLabel(hhi(rows.map((row) => row.publisher).filter((value): value is string => Boolean(value)))))
    ],
    tables,
    notes
  };
}

function buildLlmParseSection(input: ReportInput): ReportSection {
  const calls = filterCalls(input);
  if (!calls.length) {
    return unavailableSection('llm-parse', 'LLM Audit', 'Parse Robustness', 'Parse quality diagnostics for llm_audit runs.', 'No LLM call rows are available for the current filters.');
  }

  const strictCount = calls.filter((call) => call.parseMode === 'full_json').length;
  const fallbackCount = calls.filter((call) => call.parseMode && FALLBACK_PARSE_MODES.includes(call.parseMode)).length;
  const recoveryCount = calls.filter((call) => call.partialJsonRecovery).length;
  const completedCount = calls.filter((call) => call.status === 'completed').length;
  const failureCount = calls.filter((call) => !call.parseSuccess).length;
  const perModel = groupBy(calls, (call) => call.modelName);

  return {
    key: 'llm-parse',
    eyebrow: 'LLM Audit',
    title: 'Parse Robustness',
    description: 'Call counts, strict JSON success, fallback parsing, and explicit parse failures.',
    status: 'available',
    cards: [
      card('calls', 'Calls', integerLabel(calls.length)),
      card('raw', 'Raw success', integerLabel(completedCount)),
      card('strict', 'Strict JSON', integerLabel(strictCount)),
      card('fallback', 'Fallback parse', integerLabel(fallbackCount)),
      card('recovery', 'Partial recovery', integerLabel(recoveryCount)),
      card('failure', 'Parse failure', integerLabel(failureCount))
    ],
    tables: [
      buildTable(
        'parse-models',
        'Per-model parse diagnostics',
        [
          column('model', 'Model'),
          column('calls', 'Calls', 'end'),
          column('strict', 'Strict JSON', 'end'),
          column('fallback', 'Fallback', 'end'),
          column('recovery', 'Partial recovery', 'end'),
          column('failure', 'Failures', 'end')
        ],
        Object.entries(perModel).map(([model, modelCalls]) => ({
          key: model,
          values: {
            model,
            calls: integerLabel(modelCalls.length),
            strict: integerLabel(modelCalls.filter((call) => call.parseMode === 'full_json').length),
            fallback: integerLabel(modelCalls.filter((call) => call.parseMode && FALLBACK_PARSE_MODES.includes(call.parseMode)).length),
            recovery: integerLabel(modelCalls.filter((call) => call.partialJsonRecovery).length),
            failure: integerLabel(modelCalls.filter((call) => !call.parseSuccess).length)
          }
        }))
      )
    ]
  };
}

function buildLlmDivergenceSection(input: ReportInput, queryId: string | null, entityKey: string): ReportSection {
  const rows = filterOverlapRows(input.analysis.overlap_rows, queryId, entityKey === 'overall' ? '' : entityKey);
  if (!rows.length) {
    return unavailableSection('llm-divergence', 'LLM Audit', 'Cross-Model Divergence', 'Pairwise divergence metrics between llm_audit models.', 'At least two comparable models are required for divergence metrics.');
  }

  return {
    key: 'llm-divergence',
    eyebrow: 'LLM Audit',
    title: 'Cross-Model Divergence',
    description: 'Pairwise mean Jaccard, overlap@k, and top-1 agreement for the active LLM selection.',
    status: 'available',
    cards: [
      card('jaccard', 'Mean Jaccard', percentageLabel(mean(rows.map((row) => row.jaccard)))),
      card('overlap', 'Mean overlap@k', percentageLabel(mean(rows.map((row) => row.overlap_at_k)))),
      card('top1', 'Top-1 agreement', percentageLabel(mean(rows.map((row) => row.top_1_agreement ?? null)))),
      card('pairs', 'Pairwise rows', integerLabel(rows.length))
    ],
    heatmaps: [buildOverlapHeatmap(rows)],
    tables: [
      buildTable(
        'divergence',
        'Pairwise model divergence',
        [
          column('pair', 'Pair'),
          column('jaccard', 'Jaccard', 'end'),
          column('overlap', 'Overlap@k', 'end'),
          column('top1', 'Top-1', 'end')
        ],
        rows.map((row) => ({
          key: `${row.left_entity}-${row.right_entity}`,
          values: {
            pair: `${row.left_entity} vs ${row.right_entity}`,
            jaccard: percentageLabel(row.jaccard),
            overlap: percentageLabel(row.overlap_at_k),
            top1: percentageLabel(row.top_1_agreement)
          }
        }))
      )
    ]
  };
}

function buildLlmStabilitySection(input: ReportInput): ReportSection {
  const calls = filterCalls(input);
  const grouped = groupBy(calls, (call) => `${call.queryId}::${call.modelName}`);
  const hasRepeats = Object.values(grouped).some((items) => items.length > 1);
  if (!hasRepeats) {
    return insufficientSection(
      'llm-stability',
      'LLM Audit',
      'Repeatability / Stability',
      'Repeated query-model executions are required for stability metrics.',
      'Current llm_audit runs execute one call per query-model pair, so repeatability metrics are intentionally gated.'
    );
  }

  return unavailableSection(
    'llm-stability',
    'LLM Audit',
    'Repeatability / Stability',
    'Repeated query-model executions are required for stability metrics.',
    'Repeat executions exist but no stability reducer is implemented yet.'
  );
}

function buildLlmQualitySection(rows: UnifiedRecordRow[]): ReportSection {
  if (!rows.length) {
    return unavailableSection('llm-quality', 'LLM Audit', 'Bibliographic Quality', 'Neutral bibliographic quality and retrieval usefulness metrics.', 'No LLM result rows are available for the current filters.');
  }

  const evaluable = rows.filter((row) => Boolean(row.parsed_title) && (row.parsed_year !== null || row.parsed_doi)).length;
  const byEntity = groupBy(rows, (row) => row.model_or_platform);

  return {
    key: 'llm-quality',
    eyebrow: 'LLM Audit',
    title: 'Bibliographic Quality',
    description: 'Bibliographic quality measures how usable the returned records are for research workflows. Higher verified, DOI-valid, and completeness values suggest more reusable outputs.',
    status: 'available',
    cards: [
      card('doi', 'Valid DOI rate', percentageLabel(ratio(rows.filter((row) => row.doi_valid === true).length, rows.length))),
      card('verified', 'Verified record rate', percentageLabel(ratio(rows.filter((row) => row.matched).length, rows.length))),
      card('metadata', 'Metadata completeness', percentageLabel(mean(rows.map(recordCompleteness)))),
      card('evaluable', 'Evaluable records', integerLabel(evaluable))
    ],
    tables: [
      buildTable(
        'quality-models',
        'Per-model quality',
        [
          column('model', 'Model'),
          column('records', 'Records', 'end'),
          column('doi', 'Valid DOI', 'end'),
          column('verified', 'Verified', 'end'),
          column('metadata', 'Metadata completeness', 'end')
        ],
        Object.entries(byEntity).map(([entity, entityRows]) => ({
          key: entity,
          values: {
            model: entity,
            records: integerLabel(entityRows.length),
            doi: percentageLabel(ratio(entityRows.filter((row) => row.doi_valid === true).length, entityRows.length)),
            verified: percentageLabel(ratio(entityRows.filter((row) => row.matched).length, entityRows.length)),
            metadata: percentageLabel(mean(entityRows.map(recordCompleteness)))
          }
        }))
      )
    ]
  };
}

function buildLlmConflictsSection(rows: UnifiedRecordRow[]): ReportSection {
  const comparableRows = rows.filter((row) => row.matched);
  if (!comparableRows.length) {
    return insufficientSection(
      'llm-conflicts',
      'LLM Audit',
      'Metadata Conflicts',
      'Canonical metadata is required before conflict rates are meaningful.',
      'No verified records are available for the current filters.'
    );
  }

  const byEntity = groupBy(comparableRows, (row) => row.model_or_platform);
  return {
    key: 'llm-conflicts',
    eyebrow: 'LLM Audit',
    title: 'Metadata Conflicts',
    description: 'Metadata conflict rates show how often model-claimed metadata disagrees with external reference metadata. Higher rates suggest weaker bibliographic consistency.',
    status: 'available',
    cards: [
      card('any', 'Any conflict', percentageLabel(ratio(comparableRows.filter((row) => row.any_conflict).length, comparableRows.length))),
      card('doi', 'DOI conflict', percentageLabel(ratio(comparableRows.filter((row) => row.verification_trace['doi_conflict'] === true).length, comparableRows.length))),
      card('year', 'Year conflict', percentageLabel(ratio(comparableRows.filter((row) => row.year_conflict).length, comparableRows.length))),
      card('venue', 'Journal conflict', percentageLabel(ratio(comparableRows.filter((row) => row.journal_conflict).length, comparableRows.length)))
    ],
    tables: [
      buildTable(
        'conflicts-by-model',
        'Per-model conflicts',
        [
          column('model', 'Model'),
          column('any', 'Any', 'end'),
          column('doi', 'DOI', 'end'),
          column('year', 'Year', 'end'),
          column('venue', 'Journal', 'end'),
          column('author', 'Author', 'end'),
          column('publisher', 'Publisher', 'end')
        ],
        Object.entries(byEntity).map(([entity, entityRows]) => ({
          key: entity,
          values: {
            model: entity,
            any: percentageLabel(ratio(entityRows.filter((row) => row.any_conflict).length, entityRows.length)),
            doi: percentageLabel(ratio(entityRows.filter((row) => row.verification_trace['doi_conflict'] === true).length, entityRows.length)),
            year: percentageLabel(ratio(entityRows.filter((row) => row.year_conflict).length, entityRows.length)),
            venue: percentageLabel(ratio(entityRows.filter((row) => row.journal_conflict).length, entityRows.length)),
            author: percentageLabel(ratio(entityRows.filter((row) => row.author_conflict).length, entityRows.length)),
            publisher: percentageLabel(ratio(entityRows.filter((row) => row.publisher_conflict).length, entityRows.length))
          }
        }))
      )
    ]
  };
}

function buildLlmHallucinationSection(rows: UnifiedRecordRow[]): ReportSection {
  if (!rows.length) {
    return unavailableSection(
      'llm-hallucination',
      'LLM Audit',
      'Bibliographic Verifiability / Hallucination Risk',
      'This section reflects the tendency to return unverifiable, fabricated, or internally inconsistent bibliographic records or metadata.',
      'No LLM result rows are available for the current filters.'
    );
  }

  const byEntity = sortedGroups(rows, (row) => row.model_or_platform);
  const heatmapRows = byEntity;
  const errorColumns = [
    'unmatched',
    'invalid_doi',
    'title_mismatch',
    'year_conflict',
    'journal_conflict',
    'author_conflict',
    'publisher_conflict',
    'high_risk'
  ];
  const heatmapCells: ReportHeatmapCell[] = [];
  for (const [entity, entityRows] of heatmapRows) {
    for (const errorType of errorColumns) {
      const value = hallucinationErrorShare(entityRows, errorType);
      heatmapCells.push({
        key: `${entity}-${errorType}`,
        rowKey: entity,
        rowLabel: entity,
        columnKey: errorType,
        columnLabel: errorType.replace(/_/g, ' '),
        value,
        valueLabel: percentageLabel(value)
      });
    }
  }

  return {
    key: 'llm-hallucination',
    eyebrow: 'LLM Audit',
    title: 'Bibliographic Verifiability / Hallucination Risk',
    description: 'This panel shows how often returned records could not be matched, carried invalid DOI structure, or disagreed with external metadata. Higher unmatched, invalid, conflict, or high-risk shares suggest greater bibliographic fabrication or unverifiability risk.',
    status: 'available',
    cards: [
      card('matched', 'Matched rate', percentageLabel(ratio(rows.filter((row) => row.matched).length, rows.length))),
      card('unmatched', 'Unmatched rate', percentageLabel(ratio(rows.filter((row) => !row.matched).length, rows.length))),
      card('invalid', 'Invalid DOI rate', percentageLabel(ratio(rows.filter((row) => row.doi_valid === false).length, rows.length))),
      card('high', 'High-risk share', percentageLabel(ratio(rows.filter((row) => row.hallucination_risk_bucket === 'high').length, rows.length)))
    ],
    heatmaps: [
      {
        key: 'hallucination-errors',
        title: 'Model × error type',
        description: 'This heatmap shows the share of each verifiability error type within each model-specific slice.',
        cells: heatmapCells
      }
    ],
    tables: [
      buildTable(
        'hallucination-by-model',
        'Per-model verifiability summary',
        [
          column('model', 'Model'),
          column('matched', 'Matched', 'end'),
          column('unmatched', 'Unmatched', 'end'),
          column('invalid_doi', 'Invalid DOI', 'end'),
          column('any_conflict', 'Any conflict', 'end'),
          column('high', 'High risk', 'end')
        ],
        byEntity.map(([entity, entityRows]) => ({
          key: entity,
          values: {
            model: entity,
            matched: percentageLabel(ratio(entityRows.filter((row) => row.matched).length, entityRows.length)),
            unmatched: percentageLabel(ratio(entityRows.filter((row) => !row.matched).length, entityRows.length)),
            invalid_doi: percentageLabel(ratio(entityRows.filter((row) => row.doi_valid === false).length, entityRows.length)),
            any_conflict: percentageLabel(ratio(entityRows.filter((row) => row.any_conflict).length, entityRows.length)),
            high: percentageLabel(ratio(entityRows.filter((row) => row.hallucination_risk_bucket === 'high').length, entityRows.length))
          }
        }))
      ),
      buildTable(
        'hallucination-worst-records',
        'Worst offending records',
        [
          column('model', 'Model'),
          column('query', 'Query'),
          column('title', 'Title'),
          column('risk', 'Risk'),
          column('reasons', 'Reasons'),
          column('matched', 'Matched'),
          column('doi', 'DOI valid'),
          column('conflicts', 'Conflict count', 'end')
        ],
        rows
          .slice()
          .sort((left, right) => {
            const riskScore = riskBucketScore(right.hallucination_risk_bucket) - riskBucketScore(left.hallucination_risk_bucket);
            if (riskScore !== 0) {
              return riskScore;
            }
            return right.conflict_count - left.conflict_count;
          })
          .slice(0, 10)
          .map((row) => ({
            key: `${row.query_id}-${row.model_or_platform}-${row.rank}`,
            values: {
              model: row.model_or_platform,
              query: row.query_text,
              title: row.parsed_title || row.raw_title || '—',
              risk: row.hallucination_risk_bucket || '—',
              reasons: row.risk_reasons.join(', ') || '—',
              matched: row.matched ? 'yes' : 'no',
              doi: row.doi_valid === null ? '—' : row.doi_valid ? 'yes' : 'no',
              conflicts: integerLabel(row.conflict_count)
            }
          }))
      )
    ],
    notes: [
      'Risk buckets are rule-based, not model-learned: unmatched records, invalid DOI structure, title mismatch, suspicious completeness, and multiple metadata conflicts increase the assigned risk level.'
    ]
  };
}

function buildLlmQueryDetailsSection(input: ReportInput, rows: UnifiedRecordRow[]): ReportSection {
  const calls = filterCalls(input);
  if (!calls.length) {
    return unavailableSection('llm-query-details', 'LLM Audit', 'Query Details', 'Per-query and per-model drilldowns.', 'No LLM call rows are available for the current filters.');
  }

  const details = buildQueryModelDetails(calls, rows);
  return {
    key: 'llm-query-details',
    eyebrow: 'LLM Audit',
    title: 'Query Details',
    description: 'Query-level drilldown helps determine whether observed patterns are consistent across prompts or driven by specific cases. Rows below combine call metadata with returned-record verification outcomes.',
    status: details.length ? 'available' : 'unavailable',
    reason: details.length ? undefined : 'No query-level rows are available for the current filters.',
    tables: [
      buildTable(
        'query-details',
        'Per-query drilldown',
        [
          column('query', 'Query'),
          column('model', 'Model'),
          column('status', 'Status'),
          column('parse', 'Parse mode'),
          column('results', 'Results', 'end'),
          column('verified', 'Verified', 'end'),
          column('high_risk', 'High risk', 'end'),
          column('latency', 'Latency', 'end'),
          column('tokens', 'Tokens', 'end')
        ],
        details.map((row) => ({
          key: `${row.queryId}-${row.modelName}`,
          values: {
            query: row.queryLabel,
            model: row.modelName,
            status: row.status,
            parse: row.parseMode || (row.parseSuccess ? 'parsed' : 'failed'),
            results: integerLabel(row.resultCount),
            verified: integerLabel(row.verifiedCount),
            high_risk: integerLabel(row.highRiskCount),
            latency: row.latencyMs !== null ? integerLabel(row.latencyMs) : '—',
            tokens: row.totalTokens !== null ? integerLabel(row.totalTokens) : '—'
          }
        }))
      )
    ]
  };
}

function mergeRows(input: ReportInput): ReportMergedRow[] {
  const queryLabels = new Map(input.detail.queries.map((query) => [query.id, `Q${query.position}`]));
  return input.enrichmentRows
    .map((row) => {
      const canonical = row.canonicalEnrichment;
      const result = row.result;
      const entity = result.model_name || result.source_name || 'overall';
      if (input.selectedQueryId && result.query_id !== input.selectedQueryId) {
        return null;
      }
      if (input.selectedEntity && entity !== input.selectedEntity) {
        return null;
      }
      return {
        queryId: result.query_id,
        queryLabel: queryLabels.get(result.query_id) || result.query_id,
        entity,
        rank: result.rank,
        resultId: result.id,
        title: canonical?.title || result.title,
        doi: canonical?.doi || result.doi,
        rawDoi: result.doi,
        publicationYear: canonical?.publication_year ?? result.year,
        rawYear: result.year,
        language: canonical?.language || result.language,
        isOpenAccess: canonical?.is_open_access ?? null,
        openAccessStatus: canonical?.open_access_status || null,
        publisher: canonical?.publisher || result.publisher,
        venue: canonical?.venue || result.venue,
        rawVenue: result.venue,
        rawTitle: result.title,
        countryPrimary: canonical?.country_primary || null,
        countryDominant: canonical?.country_dominant || null,
        countries: canonical?.countries ?? [],
        affiliations: canonical?.affiliations ?? [],
        fieldsOfStudy: canonical?.fields_of_study ?? [],
        subjectAreas: canonical?.subject_areas ?? [],
        citationCount: canonical?.citation_count ?? null,
        verified: Boolean(canonical?.source_record_ids?.length)
      } satisfies ReportMergedRow;
    })
    .filter((row): row is ReportMergedRow => row !== null);
}

function scopedRecordRows(input: ReportInput): UnifiedRecordRow[] {
  return input.recordsRows
    .filter((row) => !input.selectedQueryId || row.query_id === input.selectedQueryId)
    .filter((row) => !input.selectedEntity || row.model_or_platform === input.selectedEntity);
}

function filterCalls(input: ReportInput) {
  return (input.analysis.llm?.calls ?? [])
    .filter((call) => !input.selectedQueryId || call.query_id === input.selectedQueryId)
    .filter((call) => !input.selectedEntity || call.model_name === input.selectedEntity)
    .map((call) => ({
      queryId: call.query_id,
      modelName: call.model_name,
      status: call.status,
      parseSuccess: call.parse_success,
      parseMode: call.parse_mode,
      partialJsonRecovery: call.partial_json_recovery,
      parsedItemCount: call.parsed_item_count,
      latencyMs: call.latency_ms,
      totalTokens: call.total_tokens,
      errorMessage: call.error_message
    }));
}

function buildQueryModelDetails(calls: ReturnType<typeof filterCalls>, rows: UnifiedRecordRow[]): QueryModelDetailRow[] {
  const rowsByQueryModel = groupBy(rows, (row) => `${row.query_id}::${row.model_or_platform}`);
  return calls.map((call) => {
    const matchedRows = rowsByQueryModel[`${call.queryId}::${call.modelName}`] ?? [];
    return {
      queryId: call.queryId,
      queryLabel: matchedRows[0]?.query_text || call.queryId,
      modelName: call.modelName,
      status: call.status,
      parseSuccess: call.parseSuccess,
      parseMode: call.parseMode,
      parsedItemCount: call.parsedItemCount,
      resultCount: matchedRows.length,
      verifiedCount: matchedRows.filter((row) => row.matched).length,
      highRiskCount: matchedRows.filter((row) => row.hallucination_risk_bucket === 'high').length,
      latencyMs: call.latencyMs,
      totalTokens: call.totalTokens,
      errorMessage: call.errorMessage
    };
  });
}

function queryLabelFromId(input: ReportInput, queryId: string): string {
  const query = input.detail.queries.find((item) => item.id === queryId);
  return query ? `Q${query.position}: ${query.text}` : queryId;
}

function sortedGroups<T>(items: T[], selector: (item: T) => string): Array<[string, T[]]> {
  return Object.entries(groupBy(items, selector)).sort((left, right) => left[0].localeCompare(right[0]));
}

function buildCoverageHeatmap(
  rows: CoverageRow[],
  input: ReportInput,
  queryId: string | null,
  missingness: boolean
): ReportHeatmap {
  const filtered = rows.filter((row) => row.query_id === queryId);
  const columns = input.selectedEntity ? [input.selectedEntity] : input.analysis.filters.entities.map((entity) => entity.value);
  const cells: ReportHeatmapCell[] = [];
  for (const field of COVERAGE_FIELDS) {
    for (const column of columns) {
      const row = filtered.find((item) => item.entity === column && item.field === field);
      const value = row ? (missingness ? 1 - row.coverage_ratio : row.coverage_ratio) : null;
      cells.push({
        key: `${field}-${column}`,
        rowKey: field,
        rowLabel: fieldLabel(field),
        columnKey: column,
        columnLabel: column,
        value,
        valueLabel: value === null ? '—' : percentageLabel(value)
      });
    }
  }
  return {
    key: missingness ? 'missingness-heatmap' : 'coverage-heatmap',
    title: missingness ? 'Missingness heatmap' : 'Coverage by model / platform',
    description: missingness ? 'Higher values indicate more missing metadata.' : 'Coverage ratios for major fields across the active entities.',
    cells
  };
}

function buildEnrichmentGainHeatmap(input: ReportInput, queryId: string | null): ReportHeatmap {
  const enriched = input.analysis.coverage_rows.filter((row) => row.query_id === queryId);
  const baseline = input.analysis.baseline_coverage_rows.filter((row) => row.query_id === queryId);
  const columns = input.selectedEntity ? [input.selectedEntity] : input.analysis.filters.entities.map((entity) => entity.value);
  const cells: ReportHeatmapCell[] = [];

  for (const field of COVERAGE_FIELDS) {
    for (const column of columns) {
      const afterRow = enriched.find((row) => row.entity === column && row.field === field);
      const beforeRow = baseline.find((row) => row.entity === column && row.field === field);
      const value =
        afterRow && beforeRow
          ? afterRow.coverage_ratio - beforeRow.coverage_ratio
          : null;
      cells.push({
        key: `${field}-${column}`,
        rowKey: field,
        rowLabel: fieldLabel(field),
        columnKey: column,
        columnLabel: column,
        value,
        valueLabel: value === null ? '—' : signedPercentageLabel(value)
      });
    }
  }
  return {
    key: 'gain-heatmap',
    title: 'Coverage gain by model / platform',
    description: 'Positive values indicate that enrichment filled previously missing metadata.',
    cells
  };
}

function buildOverlapHeatmap(rows: OverlapRow[]): ReportHeatmap {
  const entities = Array.from(new Set(rows.flatMap((row) => [row.left_entity, row.right_entity]))).sort();
  const cells: ReportHeatmapCell[] = [];
  for (const rowEntity of entities) {
    for (const columnEntity of entities) {
      if (rowEntity === columnEntity) {
        cells.push({
          key: `${rowEntity}-${columnEntity}`,
          rowKey: rowEntity,
          rowLabel: rowEntity,
          columnKey: columnEntity,
          columnLabel: columnEntity,
          value: 1,
          valueLabel: '100.0%'
        });
        continue;
      }
      const match = rows.find((row) =>
        (row.left_entity === rowEntity && row.right_entity === columnEntity) ||
        (row.left_entity === columnEntity && row.right_entity === rowEntity)
      );
      cells.push({
        key: `${rowEntity}-${columnEntity}`,
        rowKey: rowEntity,
        rowLabel: rowEntity,
        columnKey: columnEntity,
        columnLabel: columnEntity,
        value: match?.jaccard ?? null,
        valueLabel: percentageLabel(match?.jaccard ?? null)
      });
    }
  }
  return {
    key: 'overlap-heatmap',
    title: 'Jaccard heatmap',
    description: 'Pairwise overlap strength across sources or models.',
    cells
  };
}

function filterOverlapRows(rows: OverlapRow[], queryId: string | null, selectedEntity: string): OverlapRow[] {
  return rows.filter((row) => row.query_id === queryId)
    .filter((row) => !selectedEntity || row.left_entity === selectedEntity || row.right_entity === selectedEntity);
}

function selectCoverageScope(rows: CoverageRow[], queryId: string | null, entity: string): CoverageRow[] {
  return rows
    .filter((row) => row.query_id === queryId && row.entity === entity)
    .filter((row) => COVERAGE_FIELDS.includes(row.field as (typeof COVERAGE_FIELDS)[number]));
}

function representationRows(
  overall: Map<string, number>,
  top: Map<string, number>,
  overallTotal: number,
  topTotal: number,
  labelKey = 'country'
): ReportTableRow[] {
  const labels = Array.from(new Set([...overall.keys(), ...top.keys()])).slice(0, 8);
  return labels.map((label) => {
    const overallShare = ratio(overall.get(label) ?? 0, overallTotal);
    const topShare = ratio(top.get(label) ?? 0, topTotal);
    return {
      key: label,
      values: {
        [labelKey]: label,
        overall: percentageLabel(overallShare),
        topk: percentageLabel(topShare),
        delta: signedPercentageLabel(difference(topShare, overallShare))
      }
    };
  });
}

function buildDistributionSeries(
  key: string,
  title: string,
  rows: ReportMergedRow[],
  selector: (row: ReportMergedRow) => string
): ReportSeries {
  const counts = countBy(rows, selector);
  return mapToSeries(key, title, counts, Math.max(rows.length, 1));
}

function buildRecordDistributionSeries(
  key: string,
  title: string,
  rows: UnifiedRecordRow[],
  selector: (row: UnifiedRecordRow) => string
): ReportSeries {
  const counts = countBy(rows, selector);
  return mapToSeries(key, title, counts, Math.max(rows.length, 1));
}

function buildRecordHeatmap(
  key: string,
  title: string,
  description: string,
  groupedRows: Array<[string, UnifiedRecordRow[]]>,
  rows: UnifiedRecordRow[],
  selector: (row: UnifiedRecordRow) => string,
  maxColumns: number,
): ReportHeatmap {
  const columnCounts = countBy(rows, selector);
  const columns = Array.from(columnCounts.keys()).slice(0, maxColumns);
  const cells: ReportHeatmapCell[] = [];

  for (const [entity, entityRows] of groupedRows) {
    const entityCounts = countBy(entityRows, selector);
    for (const column of columns) {
      const value = ratio(entityCounts.get(column) ?? 0, entityRows.length);
      cells.push({
        key: `${entity}-${column}`,
        rowKey: entity,
        rowLabel: entity,
        columnKey: column,
        columnLabel: column,
        value,
        valueLabel: percentageLabel(value)
      });
    }
  }

  return { key, title, description, cells };
}

function mapToSeries(key: string, title: string, counts: Map<string, number>, total: number): ReportSeries {
  return {
    key,
    title,
    items: Array.from(counts.entries())
      .slice(0, 8)
      .map(([label, count]) => ({
        key: label,
        label,
        count,
        ratio: ratio(count, total),
        value: ratio(count, total),
        valueLabel: `${integerLabel(count)} · ${percentageLabel(ratio(count, total))}`
      }))
  };
}

function rankingRow(key: string, label: string, top: number | null, rest: number | null, percent: boolean): ReportTableRow {
  return {
    key,
    values: {
      metric: label,
      top: percent ? percentageLabel(top) : numberLabel(top),
      rest: percent ? percentageLabel(rest) : numberLabel(rest),
      delta: percent ? signedPercentageLabel(difference(top, rest)) : signedNumberLabel(difference(top, rest))
    }
  };
}

function fieldDelta(rows: Array<{ field: string; delta: number }>, field: string): number | null {
  return rows.find((row) => row.field === field)?.delta ?? null;
}

function firstKey(counts: Map<string, number>): string {
  return Array.from(counts.keys())[0] || 'unknown';
}

function shareFromMap(counts: Map<string, number>, label: string): number | null {
  const total = Array.from(counts.values()).reduce((sum, count) => sum + count, 0);
  return ratio(counts.get(label) ?? 0, total);
}

function countBy<T>(items: T[], selector: (item: T) => string): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const label = selector(item);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return new Map(Array.from(counts.entries()).sort((left, right) => right[1] - left[1]));
}

function countLabels(items: string[]): Map<string, number> {
  return countBy(items, (item) => item);
}

function groupBy<T>(items: T[], selector: (item: T) => string): Record<string, T[]> {
  return items.reduce<Record<string, T[]>>((groups, item) => {
    const key = selector(item);
    groups[key] ??= [];
    groups[key].push(item);
    return groups;
  }, {});
}

function yearBucket(year: number | null): string {
  if (year === null) {
    return 'unknown';
  }
  const age = new Date().getUTCFullYear() - year;
  if (age <= 2) {
    return '0-2 years';
  }
  if (age <= 5) {
    return '3-5 years';
  }
  if (age <= 10) {
    return '6-10 years';
  }
  return '>10 years';
}

function inferTopKFromRows(rows: UnifiedRecordRow[]): number {
  return rows.length ? Math.max(...rows.map((row) => row.rank)) : 0;
}

function median(values: number[]): number | null {
  if (!values.length) {
    return null;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[middle - 1] + sorted[middle]) / 2;
  }
  return sorted[middle];
}

function topNShare(counts: Map<string, number>, count: number): number | null {
  const total = Array.from(counts.values()).reduce((sum, value) => sum + value, 0);
  if (total <= 0) {
    return null;
  }
  const top = Array.from(counts.values())
    .slice(0, count)
    .reduce((sum, value) => sum + value, 0);
  return top / total;
}

function uniqueRecordKey(row: UnifiedRecordRow): string {
  const title = (row.enriched_title || row.parsed_title || row.raw_title || '').trim().toLowerCase();
  return row.external_match_id || row.enriched_doi || row.parsed_doi || `${row.model_or_platform}:${title}`;
}

function recordCompleteness(row: UnifiedRecordRow): number | null {
  const fields = [
    row.parsed_title,
    row.parsed_doi,
    row.parsed_year,
    row.parsed_journal,
    row.parsed_authors.length ? row.parsed_authors : null,
    row.language,
    row.country_primary,
    row.publisher,
    row.source_type,
    row.is_oa,
    row.cited_by_count,
  ];
  return ratio(fields.filter((value) => hasValue(value)).length, fields.length);
}

function oaStatusLabel(row: UnifiedRecordRow): string {
  if (row.oa_pathway) {
    return row.oa_pathway;
  }
  if (row.oa_status) {
    return row.oa_status.toLowerCase();
  }
  if (row.is_oa === true) {
    return 'open';
  }
  if (row.is_oa === false) {
    return 'closed';
  }
  return 'unknown';
}

function hallucinationErrorShare(rows: UnifiedRecordRow[], errorType: string): number | null {
  if (!rows.length) {
    return null;
  }
  const count = rows.filter((row) => {
    if (errorType === 'unmatched') {
      return !row.matched;
    }
    if (errorType === 'invalid_doi') {
      return row.doi_valid === false;
    }
    if (errorType === 'title_mismatch') {
      return row.title_match_status === 'no';
    }
    if (errorType === 'year_conflict') {
      return row.year_conflict;
    }
    if (errorType === 'journal_conflict') {
      return row.journal_conflict;
    }
    if (errorType === 'author_conflict') {
      return row.author_conflict;
    }
    if (errorType === 'publisher_conflict') {
      return row.publisher_conflict;
    }
    if (errorType === 'high_risk') {
      return row.hallucination_risk_bucket === 'high';
    }
    return false;
  }).length;
  return ratio(count, rows.length);
}

function riskBucketScore(bucket: string | null): number {
  if (bucket === 'high') {
    return 3;
  }
  if (bucket === 'medium') {
    return 2;
  }
  if (bucket === 'low') {
    return 1;
  }
  return 0;
}

function metadataCompleteness(row: ReportMergedRow): number | null {
  const values = CORE_METADATA_FIELDS.map((field) => row[field]);
  return ratio(values.filter((value) => hasValue(value)).length, values.length);
}

function hasAnyConflict(row: ReportMergedRow): boolean {
  return hasConflict(row, 'doi') || hasConflict(row, 'publicationYear') || hasConflict(row, 'venue') || hasConflict(row, 'title');
}

function hasConflict(row: ReportMergedRow, field: 'doi' | 'publicationYear' | 'venue' | 'title'): boolean {
  if (field === 'doi') {
    return Boolean(row.doi && row.rawDoi && row.doi !== row.rawDoi);
  }
  if (field === 'publicationYear') {
    return row.publicationYear !== null && row.rawYear !== null && row.publicationYear !== row.rawYear;
  }
  if (field === 'venue') {
    return Boolean(row.venue && row.rawVenue && row.venue.toLowerCase() !== row.rawVenue.toLowerCase());
  }
  return Boolean(row.title && row.rawTitle && row.title.toLowerCase() !== row.rawTitle.toLowerCase());
}

function oaLabel(row: ReportMergedRow): string {
  if (row.openAccessStatus) {
    return row.openAccessStatus.toLowerCase();
  }
  if (row.isOpenAccess === true) {
    return 'open';
  }
  if (row.isOpenAccess === false) {
    return 'closed';
  }
  return 'unknown';
}

function isValidDoi(value: string | null): boolean {
  if (!value) {
    return false;
  }
  return /^10\.\d{4,9}\/[-._;()/:A-Z0-9]+$/i.test(value);
}

function hhi(values: string[]): number | null {
  if (!values.length) {
    return null;
  }
  const counts = countLabels(values);
  const total = values.length;
  return Array.from(counts.values()).reduce((sum, count) => sum + (count / total) ** 2, 0);
}

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === 'string') {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return true;
}

function difference(left: number | null, right: number | null): number | null {
  return left === null || right === null ? null : left - right;
}

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

function mean(values: Array<number | null>): number | null {
  const numbers = values.filter((value): value is number => value !== null && !Number.isNaN(value));
  if (!numbers.length) {
    return null;
  }
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
}

function maxValue(values: Array<number | null>): number | null {
  const numbers = values.filter((value): value is number => value !== null && !Number.isNaN(value));
  if (!numbers.length) {
    return null;
  }
  return Math.max(...numbers);
}

function integerLabel(value: number | null): string {
  return value === null ? '—' : value.toFixed(0);
}

function numberLabel(value: number | null): string {
  return value === null ? '—' : value.toFixed(Math.abs(value) >= 100 ? 1 : 2);
}

function signedNumberLabel(value: number | null): string {
  if (value === null) {
    return '—';
  }
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${numberLabel(value)}`;
}

function percentageLabel(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function signedPercentageLabel(value: number | null): string {
  if (value === null) {
    return '—';
  }
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${percentageLabel(value)}`;
}

function fieldLabel(value: string): string {
  return value.replace(/_/g, ' ');
}

function numberOrNull(value: number | null | undefined): number | null {
  return value ?? null;
}

function card(key: string, label: string, value: string, note?: string): ReportMetricCard {
  return { key, label, value, note };
}

function column(key: string, label: string, align: 'start' | 'end' = 'start'): ReportTableColumn {
  return { key, label, align };
}

function buildTable(key: string, title: string, columns: ReportTableColumn[], rows: ReportTableRow[]): ReportTable {
  return { key, title, columns, rows };
}

function unavailableSection(
  key: string,
  eyebrow: string,
  title: string,
  description: string,
  reason: string
): ReportSection {
  return {
    key,
    eyebrow,
    title,
    description,
    status: 'unavailable',
    reason
  };
}

function insufficientSection(
  key: string,
  eyebrow: string,
  title: string,
  description: string,
  reason: string
): ReportSection {
  return {
    key,
    eyebrow,
    title,
    description,
    status: 'insufficient_coverage',
    reason
  };
}
