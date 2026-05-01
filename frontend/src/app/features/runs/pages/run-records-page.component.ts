import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, ParamMap, RouterLink } from '@angular/router';
import { combineLatest, filter, map } from 'rxjs';

import { RunsApiService } from '../../../core/api/runs-api.service';
import { RunDetail, RunRecordsResponse, UnifiedRecordRow } from '../models/run.models';

type ViewPreset = 'raw' | 'enriched' | 'verification' | 'unified';
type SortKey =
  | 'rank'
  | 'parsed_year'
  | 'cited_by_count'
  | 'conflict_count'
  | 'parse_confidence'
  | 'model_or_platform'
  | 'query_text';

@Component({
  selector: 'app-run-records-page',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="page">
      <p class="back-link"><a routerLink="/runs">← Back to runs</a></p>

      <section class="panel" *ngIf="detail">
        <div class="hero__header">
          <div class="hero__intro">
            <p class="eyebrow">Records Explorer</p>
            <h2>{{ detail.run.id }}</h2>
            <p>Records Explorer separates row-level inspection and exports from the interpretive report page.</p>
          </div>
          <div class="actions">
            <a class="nav-button secondary" [routerLink]="['/runs', detail.run.id, 'report']">Report</a>
          </div>
        </div>

        <div class="summary-grid">
          <div class="summary-card">
            <span>Run Type</span>
            <strong>{{ detail.run.run_type }}</strong>
          </div>
          <div class="summary-card">
            <span>Queries</span>
            <strong>{{ detail.queries.length }}</strong>
          </div>
          <div class="summary-card">
            <span>Top K</span>
            <strong>{{ detail.run.top_k }}</strong>
          </div>
          <div class="summary-card" *ngIf="recordsResponse">
            <span>Rows</span>
            <strong>{{ recordsResponse.summary.filtered_rows }} / {{ recordsResponse.summary.total_rows }}</strong>
          </div>
        </div>
      </section>

      <section class="panel" *ngIf="recordsResponse">
        <div class="panel__header">
          <div>
            <p class="eyebrow">Records Filters</p>
            <h2>Explore Unified Rows</h2>
            <p>Filter raw, parsed, enriched, and verification fields without cluttering the report surface.</p>
          </div>
        </div>

        <div class="filters">
          <label>
            <span>Query</span>
            <select [value]="selectedQueryId" (change)="selectedQueryId = selectValue($event)">
              <option value="">All queries</option>
              <option *ngFor="let item of recordsResponse.filters.queries" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Model / Platform</span>
            <select [value]="selectedEntity" (change)="selectedEntity = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.entities" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Top-K Cutoff</span>
            <select [value]="selectedTopK" (change)="selectedTopK = selectValue($event)">
              <option value="">All ranks</option>
              <option value="1">Top-1</option>
              <option value="3">Top-3</option>
              <option value="5">Top-5</option>
              <option *ngIf="detail" [value]="detail.run.top_k">Configured top-k</option>
            </select>
          </label>

          <label>
            <span>Rank Bucket</span>
            <select [value]="selectedRankBucket" (change)="selectedRankBucket = selectValue($event)">
              <option value="">All</option>
              <option value="top_1">Top-1</option>
              <option value="top_3">Top-3</option>
              <option value="top_5">Top-5</option>
              <option value="top_k">Top-K</option>
              <option value="rest">Rest</option>
            </select>
          </label>

          <label>
            <span>Matched</span>
            <select [value]="matchedFilter" (change)="matchedFilter = selectValue($event)">
              <option value="">All</option>
              <option value="true">Matched only</option>
              <option value="false">Unmatched only</option>
            </select>
          </label>

          <label>
            <span>DOI Valid</span>
            <select [value]="doiValidFilter" (change)="doiValidFilter = selectValue($event)">
              <option value="">All</option>
              <option value="true">Valid DOI only</option>
              <option value="false">Invalid DOI only</option>
            </select>
          </label>

          <label>
            <span>Conflicts</span>
            <select [value]="conflictFilter" (change)="conflictFilter = selectValue($event)">
              <option value="">All</option>
              <option value="true">Conflicting only</option>
              <option value="false">No conflicts</option>
            </select>
          </label>

          <label>
            <span>Language</span>
            <select [value]="selectedLanguage" (change)="selectedLanguage = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.languages" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Publisher</span>
            <select [value]="selectedPublisher" (change)="selectedPublisher = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.publishers" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Country</span>
            <select [value]="selectedCountry" (change)="selectedCountry = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.countries" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>OA Status</span>
            <select [value]="selectedOaStatus" (change)="selectedOaStatus = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.oa_statuses" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Source Type</span>
            <select [value]="selectedSourceType" (change)="selectedSourceType = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.source_types" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Parse Status</span>
            <select [value]="selectedParseStatus" (change)="selectedParseStatus = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.parse_statuses" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label>
            <span>Risk Bucket</span>
            <select [value]="selectedRiskBucket" (change)="selectedRiskBucket = selectValue($event)">
              <option value="">All</option>
              <option *ngFor="let item of recordsResponse.filters.risk_buckets" [value]="item.value">{{ item.label }}</option>
            </select>
          </label>

          <label class="filter-wide">
            <span>Search</span>
            <input type="search" [value]="searchText" (input)="searchText = textValue($event)" placeholder="Search title, DOI, journal, authors, publisher, query">
          </label>
        </div>

        <div class="toolbar">
          <div class="toolbar__group">
            <label>
              <span>View Preset</span>
              <select [value]="viewPreset" (change)="viewPreset = viewPresetValue($event)">
                <option value="raw">Raw</option>
                <option value="enriched">Enriched</option>
                <option value="verification">Verification</option>
                <option value="unified">Export-ready</option>
              </select>
            </label>

            <label>
              <span>Sort</span>
              <select [value]="sortKey" (change)="sortKey = sortKeyValue($event)">
                <option value="rank">Rank</option>
                <option value="parsed_year">Year</option>
                <option value="cited_by_count">Citations</option>
                <option value="conflict_count">Conflict count</option>
                <option value="parse_confidence">Parse confidence</option>
                <option value="model_or_platform">Model / platform</option>
                <option value="query_text">Query</option>
              </select>
            </label>

            <label>
              <span>Direction</span>
              <select [value]="sortDirection" (change)="sortDirection = sortDirectionValue($event)">
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
            </label>
          </div>

          <div class="toolbar__group toolbar__group--actions">
            <button type="button" (click)="loadRecords()">Apply filters</button>
            <button type="button" class="secondary" (click)="resetFilters()">Reset</button>
          </div>
        </div>

        <div class="toolbar toolbar--exports">
          <div class="toolbar__group">
            <strong>Exports</strong>
            <span class="hint">Current filtered view using the selected export preset.</span>
          </div>
          <div class="toolbar__group toolbar__group--actions">
            <a class="nav-button secondary" [href]="exportUrl('csv')" target="_blank" rel="noreferrer">CSV</a>
            <a class="nav-button secondary" [href]="exportUrl('json')" target="_blank" rel="noreferrer">JSON</a>
            <a class="nav-button secondary" [href]="exportUrl('jsonl')" target="_blank" rel="noreferrer">JSONL</a>
          </div>
        </div>

        <div class="notice notice--error" *ngIf="recordsError">{{ recordsError }}</div>

        <div class="table-wrap table-wrap--records" *ngIf="visibleRows().length; else emptyState">
          <table class="records-table">
            <thead>
              <tr>
                <th *ngFor="let column of visibleColumns()">{{ column.label }}</th>
                <th class="col-compact">Inspect</th>
              </tr>
            </thead>
            <tbody>
              <ng-container *ngFor="let row of visibleRows()">
                <tr class="table-row--interactive" [class.table-row--expanded]="expandedRowId === rowKey(row)">
                  <td *ngFor="let column of visibleColumns()" [class.cell-number]="column.numeric">
                    <div class="cell-wrap" [class.cell-wrap--mono]="column.mono">{{ column.value(row) }}</div>
                  </td>
                  <td class="cell-action">
                    <button type="button" class="link-button" (click)="toggleRow(rowKey(row))">
                      {{ expandedRowId === rowKey(row) ? 'Hide' : 'Inspect' }}
                    </button>
                  </td>
                </tr>
                <tr class="detail-row" *ngIf="expandedRowId === rowKey(row)">
                  <td [attr.colspan]="visibleColumns().length + 1">
                    <div class="detail-panel">
                      <div class="detail-grid">
                        <div><span class="detail-label">Query</span><p>{{ row.query_text }}</p></div>
                        <div><span class="detail-label">Entity</span><p>{{ row.model_or_platform }}</p></div>
                        <div><span class="detail-label">Matched</span><p>{{ row.matched ? 'yes' : 'no' }}</p></div>
                        <div><span class="detail-label">Verification</span><p>{{ row.verification_status || '—' }}</p></div>
                        <div><span class="detail-label">Existence Risk</span><p>{{ row.existence_risk_bucket || '—' }}</p></div>
                        <div><span class="detail-label">Metadata Risk</span><p>{{ row.metadata_risk_bucket || '—' }}</p></div>
                        <div><span class="detail-label">Near Match</span><p>{{ row.near_match_reason ? (row.near_match_reason + (row.near_match_score !== null ? ' (' + (row.near_match_score | number:'1.2-2') + ')' : '')) : '—' }}</p></div>
                        <div><span class="detail-label">Risk Bucket</span><p>{{ row.hallucination_risk_bucket || '—' }}</p></div>
                        <div><span class="detail-label">Risk Reasons</span><p>{{ row.risk_reasons.length ? row.risk_reasons.join(', ') : '—' }}</p></div>
                        <div><span class="detail-label">Parse Strategy</span><p>{{ row.parse_strategy || '—' }}</p></div>
                        <div><span class="detail-label">Provenance</span><p>{{ row.provenance_summary || '—' }}</p></div>
                      </div>

                      <div class="inspect-grid inspect-grid--wide">
                        <div class="debug-card">
                          <div class="debug-card__header">
                            <strong>Raw Payload</strong>
                            <span>Original source or model row.</span>
                          </div>
                          <pre class="json-block">{{ row.raw_payload | json }}</pre>
                        </div>
                        <div class="debug-card">
                          <div class="debug-card__header">
                            <strong>Parsed Payload</strong>
                            <span>Structured fields used for comparison.</span>
                          </div>
                          <pre class="json-block">{{ row.parsed_payload | json }}</pre>
                        </div>
                        <div class="debug-card">
                          <div class="debug-card__header">
                            <strong>Enriched Payload</strong>
                            <span>Canonical external metadata.</span>
                          </div>
                          <pre class="json-block">{{ row.enriched_payload | json }}</pre>
                        </div>
                        <div class="debug-card">
                          <div class="debug-card__header">
                            <strong>Verification Trace</strong>
                            <span>Conflict and verifiability diagnostics for this record.</span>
                          </div>
                          <pre class="json-block">{{ row.verification_trace | json }}</pre>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </ng-container>
            </tbody>
          </table>
        </div>

        <ng-template #emptyState>
          <div class="empty">No record rows match the current filters.</div>
        </ng-template>
      </section>
    </div>
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .page { display: grid; gap: 24px; width: min(100%, 1380px); margin: 0 auto; padding: 24px clamp(16px, 3vw, 28px) 40px; box-sizing: border-box; }
    .back-link { margin: 0; }
    .back-link a { color: #12324a; font-weight: 600; text-decoration: none; }
    .panel { border: 1px solid #d7e1ea; border-radius: 18px; background: rgba(255,255,255,0.95); padding: 20px; box-shadow: 0 12px 30px rgba(15,35,55,0.05); min-width: 0; }
    .hero__header, .panel__header, .toolbar { display: flex; justify-content: space-between; gap: 16px; align-items: start; margin-bottom: 16px; }
    .hero__intro { display: grid; gap: 8px; }
    .eyebrow { margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.74rem; color: #56748d; font-weight: 700; }
    h2, h3, p { margin: 0; }
    p { color: #556270; }
    .actions, .toolbar__group { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .toolbar { flex-wrap: wrap; }
    .toolbar--exports { padding-top: 12px; border-top: 1px solid #e3ebf2; }
    .toolbar__group--actions { margin-left: auto; }
    .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); gap: 12px; }
    .summary-card { border: 1px solid #dce5ed; border-radius: 14px; padding: 14px; background: #fbfdff; display: grid; gap: 6px; }
    .filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 12px; }
    .filter-wide { grid-column: 1 / -1; }
    .filters label, .toolbar label { display: grid; gap: 8px; font-weight: 600; min-width: 0; }
    input, select, button, .nav-button { font: inherit; }
    input, select { border: 1px solid #c7d4df; border-radius: 12px; padding: 12px 14px; background: #f9fbfd; width: 100%; box-sizing: border-box; }
    button, .nav-button { border: 0; border-radius: 12px; padding: 10px 14px; background: #12324a; color: #fff; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; }
    .secondary { background: #e8eff6; color: #12324a; }
    .hint { color: #617182; }
    .notice { border-radius: 14px; padding: 12px 14px; font-weight: 600; }
    .notice--error { background: #fde8e7; color: #9f1c1c; }
    .table-wrap { overflow-x: auto; border: 1px solid #e2eaf1; border-radius: 16px; background: #fff; }
    .records-table { min-width: 1320px; width: 100%; border-collapse: collapse; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #e4ebf2; text-align: left; vertical-align: top; }
    th { color: #617182; font-size: 0.92rem; background: #f8fbfd; }
    .cell-number { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .cell-wrap { white-space: normal; line-height: 1.45; overflow-wrap: anywhere; max-width: 100%; }
    .cell-wrap--mono, .json-block { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }
    .cell-action { white-space: nowrap; text-align: right; }
    .table-row--interactive:hover > td { background: #f8fbfe; }
    .table-row--expanded > td { background: #f3f8fc; }
    .detail-row > td { padding: 0; background: #f8fbfd; }
    .detail-panel { display: grid; gap: 16px; padding: 18px; }
    .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 14px; }
    .detail-label { display: inline-block; margin-bottom: 6px; font-size: 0.76rem; letter-spacing: 0.08em; text-transform: uppercase; color: #627587; font-weight: 700; }
    .inspect-grid { display: grid; gap: 12px; }
    .inspect-grid--wide { grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); }
    .debug-card { border: 1px solid #dde6ee; border-radius: 14px; background: #fff; padding: 14px; display: grid; gap: 10px; min-width: 0; }
    .debug-card__header { display: grid; gap: 4px; }
    .debug-card__header span { color: #5f7284; font-size: 0.9rem; }
    .json-block { display: block; margin: 0; padding: 14px; border-radius: 12px; background: #0f1720; color: #dce7f3; white-space: pre-wrap; overflow-wrap: anywhere; overflow: auto; font-size: 0.84rem; line-height: 1.5; }
    .link-button { padding: 0; border: 0; background: transparent; color: #0d4b8c; font-weight: 700; cursor: pointer; }
    .empty { border: 1px dashed #ccd7e2; border-radius: 14px; padding: 18px; color: #617182; background: #f8fbfd; }
    @media (max-width: 960px) { .hero__header, .panel__header, .toolbar { flex-direction: column; } .toolbar__group--actions { margin-left: 0; } .actions { width: 100%; } }
  `]
})
export class RunRecordsPageComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly runsApi = inject(RunsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected detail: RunDetail | null = null;
  protected recordsResponse: RunRecordsResponse | null = null;
  protected recordsError = '';
  protected loading = false;
  protected expandedRowId = '';

  protected selectedQueryId = '';
  protected selectedEntity = '';
  protected selectedTopK = '';
  protected selectedRankBucket = '';
  protected matchedFilter = '';
  protected doiValidFilter = '';
  protected conflictFilter = '';
  protected selectedLanguage = '';
  protected selectedPublisher = '';
  protected selectedCountry = '';
  protected selectedOaStatus = '';
  protected selectedSourceType = '';
  protected selectedParseStatus = '';
  protected selectedRiskBucket = '';
  protected searchText = '';
  protected viewPreset: ViewPreset = 'unified';
  protected sortKey: SortKey = 'rank';
  protected sortDirection: 'asc' | 'desc' = 'asc';

  private runId = '';

  ngOnInit(): void {
    combineLatest([
      this.route.paramMap.pipe(map((params) => params.get('id'))),
      this.route.queryParamMap,
    ]).pipe(
      filter(([id]) => Boolean(id)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(([id, queryParams]) => {
      this.runId = id ?? '';
      this.hydrateFilters(queryParams);
      this.loadRun();
      this.loadRecords();
    });
  }

  protected loadRun(): void {
    this.runsApi.getRun(this.runId).subscribe({
      next: (detail) => {
        this.detail = detail;
      },
      error: (error: unknown) => {
        this.recordsError = this.formatError(error, 'Failed to load run details.');
      }
    });
  }

  protected loadRecords(): void {
    if (!this.runId) {
      return;
    }
    this.loading = true;
    this.recordsError = '';
    this.runsApi.getRecords(this.runId, this.queryParams()).subscribe({
      next: (response) => {
        this.recordsResponse = response;
        this.loading = false;
      },
      error: (error: unknown) => {
        this.recordsError = this.formatError(error, 'Failed to load record rows.');
        this.loading = false;
      }
    });
  }

  protected resetFilters(): void {
    this.selectedQueryId = '';
    this.selectedEntity = '';
    this.selectedTopK = '';
    this.selectedRankBucket = '';
    this.matchedFilter = '';
    this.doiValidFilter = '';
    this.conflictFilter = '';
    this.selectedLanguage = '';
    this.selectedPublisher = '';
    this.selectedCountry = '';
    this.selectedOaStatus = '';
    this.selectedSourceType = '';
    this.selectedParseStatus = '';
    this.selectedRiskBucket = '';
    this.searchText = '';
    this.loadRecords();
  }

  protected visibleRows(): UnifiedRecordRow[] {
    const rows = [...(this.recordsResponse?.rows ?? [])];
    rows.sort((left, right) => this.compareRows(left, right));
    return rows;
  }

  protected visibleColumns(): Array<{ label: string; value: (row: UnifiedRecordRow) => string; numeric?: boolean; mono?: boolean }> {
    if (this.viewPreset === 'raw') {
      return [
        column('Query', (row) => row.query_text),
        column('Entity', (row) => row.model_or_platform),
        column('Rank', (row) => String(row.rank), true),
        column('Raw Title', (row) => row.raw_title || '—'),
        column('Raw DOI', (row) => row.raw_doi || '—', false, true),
        column('Raw Journal', (row) => row.raw_journal || '—'),
        column('Rationale', (row) => row.raw_rationale || '—'),
      ];
    }
    if (this.viewPreset === 'enriched') {
      return [
        column('Query', (row) => row.query_text),
        column('Entity', (row) => row.model_or_platform),
        column('Rank', (row) => String(row.rank), true),
        column('Parsed Title', (row) => row.parsed_title || '—'),
        column('Enriched Title', (row) => row.enriched_title || '—'),
        column('Publisher', (row) => row.publisher || '—'),
        column('Country', (row) => row.country_primary || '—'),
        column('OA', (row) => row.oa_status || (row.is_oa === true ? 'open' : row.is_oa === false ? 'closed' : '—')),
        column('Citations', (row) => row.cited_by_count === null ? '—' : String(row.cited_by_count), true),
      ];
    }
    if (this.viewPreset === 'verification') {
      return [
        column('Query', (row) => row.query_text),
        column('Entity', (row) => row.model_or_platform),
        column('Rank', (row) => String(row.rank), true),
        column('Matched', (row) => row.matched ? 'yes' : 'no'),
        column('DOI Valid', (row) => row.doi_valid === null ? '—' : row.doi_valid ? 'yes' : 'no'),
        column('Verification', (row) => row.verification_status || '—'),
        column('Existence Risk', (row) => row.existence_risk_bucket || '—'),
        column('Metadata Risk', (row) => row.metadata_risk_bucket || '—'),
        column('Title Match', (row) => row.title_match_status || '—'),
        column('Conflicts', (row) => String(row.conflict_count), true),
        column('Risk Bucket', (row) => row.hallucination_risk_bucket || '—'),
        column('Risk Reasons', (row) => row.risk_reasons.join(', ') || '—'),
        column('Parse', (row) => row.parse_strategy || row.parse_status || '—'),
      ];
    }
    return [
      column('Query', (row) => row.query_text),
      column('Entity', (row) => row.model_or_platform),
      column('Rank', (row) => String(row.rank), true),
      column('Parsed Title', (row) => row.parsed_title || '—'),
      column('DOI', (row) => row.parsed_doi || '—', false, true),
      column('Year', (row) => row.parsed_year === null ? '—' : String(row.parsed_year), true),
      column('Publisher', (row) => row.publisher || '—'),
      column('Language', (row) => row.language || '—'),
      column('Matched', (row) => row.matched ? 'yes' : 'no'),
      column('Verification', (row) => row.verification_status || '—'),
      column('Conflicts', (row) => String(row.conflict_count), true),
    ];
  }

  protected exportUrl(format: string): string {
    return this.runsApi.buildRecordsExportUrl(this.runId, {
      ...this.queryParams(),
      format,
      view: this.viewPreset === 'unified' ? 'unified' : this.viewPreset,
    });
  }

  protected rowKey(row: UnifiedRecordRow): string {
    return `${row.query_id}:${row.model_or_platform}:${row.rank}:${row.parsed_doi || row.parsed_title || 'row'}`;
  }

  protected toggleRow(rowId: string): void {
    this.expandedRowId = this.expandedRowId === rowId ? '' : rowId;
  }

  protected selectValue(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  protected textValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  protected viewPresetValue(event: Event): ViewPreset {
    return (event.target as HTMLSelectElement).value as ViewPreset;
  }

  protected sortKeyValue(event: Event): SortKey {
    return (event.target as HTMLSelectElement).value as SortKey;
  }

  protected sortDirectionValue(event: Event): 'asc' | 'desc' {
    return (event.target as HTMLSelectElement).value as 'asc' | 'desc';
  }

  private compareRows(left: UnifiedRecordRow, right: UnifiedRecordRow): number {
    const leftValue = left[this.sortKey];
    const rightValue = right[this.sortKey];
    if (leftValue === rightValue) {
      return left.rank - right.rank;
    }
    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return this.sortDirection === 'asc' ? leftValue - rightValue : rightValue - leftValue;
    }
    const comparison = String(leftValue ?? '').localeCompare(String(rightValue ?? ''));
    return this.sortDirection === 'asc' ? comparison : -comparison;
  }

  private hydrateFilters(queryParams: ParamMap): void {
    this.selectedQueryId = queryParams.get('query_id') ?? '';
    this.selectedEntity = queryParams.get('entity') ?? '';
    this.selectedTopK = queryParams.get('top_k') ?? '';
    this.selectedRankBucket = queryParams.get('rank_bucket') ?? '';
    this.matchedFilter = queryParams.get('matched') ?? '';
    this.doiValidFilter = queryParams.get('doi_valid') ?? '';
    this.conflictFilter = queryParams.get('conflicting') ?? '';
    this.selectedLanguage = queryParams.get('language') ?? '';
    this.selectedPublisher = queryParams.get('publisher') ?? '';
    this.selectedCountry = queryParams.get('country') ?? '';
    this.selectedOaStatus = queryParams.get('oa_status') ?? '';
    this.selectedSourceType = queryParams.get('source_type') ?? '';
    this.selectedParseStatus = queryParams.get('parse_status') ?? '';
    this.selectedRiskBucket = queryParams.get('risk_bucket') ?? '';
    this.searchText = queryParams.get('search') ?? '';
  }

  private queryParams(): Record<string, string | number | boolean> {
    return {
      query_id: this.selectedQueryId,
      entity: this.selectedEntity,
      top_k: this.selectedTopK ? Number(this.selectedTopK) : '',
      rank_bucket: this.selectedRankBucket,
      matched: this.matchedFilter,
      doi_valid: this.doiValidFilter,
      conflicting: this.conflictFilter,
      language: this.selectedLanguage,
      publisher: this.selectedPublisher,
      country: this.selectedCountry,
      oa_status: this.selectedOaStatus,
      source_type: this.selectedSourceType,
      parse_status: this.selectedParseStatus,
      risk_bucket: this.selectedRiskBucket,
      search: this.searchText,
    };
  }

  private formatError(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse) {
      if (typeof error.error?.detail === 'string') {
        return error.error.detail;
      }
      return error.message || fallback;
    }
    return fallback;
  }
}

function column(
  label: string,
  value: (row: UnifiedRecordRow) => string,
  numeric = false,
  mono = false,
) {
  return { label, value, numeric, mono };
}
