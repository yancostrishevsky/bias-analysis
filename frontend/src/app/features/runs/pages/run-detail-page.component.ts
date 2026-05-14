import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { catchError, distinctUntilChanged, filter, forkJoin, map, of } from 'rxjs';

import { RunsApiService } from '../../../core/api/runs-api.service';
import {
  CanonicalEnrichment,
  ConcentrationRow,
  CoverageRow,
  DistributionRow,
  EntityExecutionSummary,
  LLMCallRow,
  LLMMetricRow,
  OpenRouterModelSummary,
  OverlapRow,
  ResultEnrichmentResponse,
  ResultRecord,
  RunAnalysis,
  RunDetail,
  ReplayStatusResponse,
  UnifiedRecordRow,
  TopKComparisonRow
} from '../models/run.models';
import { RunReportComponent } from '../report/components/run-report.component';
import { EnrichmentRow } from '../report/run-report.models';

@Component({
  selector: 'app-run-detail-page',
  standalone: true,
  imports: [CommonModule, RouterLink, RunReportComponent],
  template: `
    <div class="page">
      <p class="back-link"><a routerLink="/runs">← Back to experiments</a></p>

      <section class="hero panel" *ngIf="detail; else loadingBlock">
        <div class="hero__header">
          <div class="hero__intro">
            <p class="eyebrow">Experiment Detail</p>
            <h2>{{ detail.run.id }}</h2>
            <p>
              {{ detail.run.run_type === 'llm_audit' ? 'LLM audit experiment' : 'Scholarly collection experiment' }}
              with persisted execution state, artifacts, and interactive analysis.
            </p>
          </div>

          <div class="actions">
            <button
              type="button"
              (click)="startRun()"
              [disabled]="starting || detail.run.status !== 'pending'">
              Start experiment
            </button>

            <button
              type="button"
              class="secondary"
              *ngIf="detail.run.run_type === 'llm_audit'"
              (click)="replayRun()"
              [disabled]="replaying || !canReplay()">
              {{ replaying ? 'Replaying…' : 'Replay stored LLM artifacts' }}
            </button>

            <button
              type="button"
              class="secondary"
              (click)="refreshAll()"
              [disabled]="loadingRun || loadingResults || loadingEnrichments || loadingAnalysis">
              Refresh
            </button>

            <a
              class="nav-button secondary"
              [routerLink]="['/runs', detail.run.id, 'records']"
              [queryParams]="recordsQueryParams()">
              Records Explorer
            </a>

            <button
              type="button"
              class="danger"
              (click)="deleteRun()"
              [disabled]="deleting">
              {{ deleting ? 'Deleting…' : 'Delete experiment' }}
            </button>
          </div>
        </div>

        <section class="status-panel">
          <div class="status-panel__header">
            <div class="status-panel__headline">
              <span class="status status--large status--{{ detail.run.status }}">{{ detail.run.status }}</span>
              <span class="live-indicator" *ngIf="isLiveUpdating()">Live updating</span>
            </div>
            <div class="status-panel__stage">
              <span>Stage</span>
              <strong>{{ stageLabel(detail.run.stage) }}</strong>
            </div>
          </div>

          <p class="status-panel__message">
            {{ detail.run.progress_message || defaultProgressMessage() }}
          </p>

          <div class="progress-stack" *ngIf="detail.run.progress_total > 0">
            <div class="progress-stack__meta">
              <strong>{{ detail.run.progress_current }} / {{ detail.run.progress_total }}</strong>
              <span>{{ displayPercentage(runProgressRatio()) }}</span>
            </div>
            <div class="progress-bar">
              <div class="progress-bar__fill" [style.width.%]="runProgressRatio() * 100"></div>
            </div>
          </div>

          <div
            class="entity-strip entity-strip--models"
            *ngIf="detail.run.run_type === 'llm_audit' && detail.entity_statuses.length">
            <article class="entity-card entity-card--model" *ngFor="let item of detail.entity_statuses">
              <div class="entity-card__header">
                <strong>{{ item.name }}</strong>
                <div class="entity-card__status-actions">
                  <span class="status status--{{ item.status }}">{{ item.status }}</span>
                  <button
                    type="button"
                    class="secondary entity-card__retry"
                    *ngIf="canRetryModel(item)"
                    (click)="retryModel(item)"
                    [disabled]="isRetryingModel(item.name)">
                    {{ isRetryingModel(item.name) ? 'Retrying...' : 'Retry' }}
                  </button>
                </div>
              </div>
              <p>{{ item.progress_message || entitySummary(item) }}</p>
              <div class="progress-stack progress-stack--compact" *ngIf="item.progress_total > 0">
                <div class="progress-stack__meta">
                  <strong>{{ item.progress_current }} / {{ item.progress_total }}</strong>
                  <span>{{ displayPercentage(entityProgressRatio(item)) }}</span>
                </div>
                <div class="progress-bar progress-bar--compact">
                  <div class="progress-bar__fill" [style.width.%]="entityProgressRatio(item) * 100"></div>
                </div>
              </div>
              <p class="entity-card__meta" *ngIf="item.error_message">{{ item.error_message }}</p>
            </article>
          </div>
        </section>

        <div class="notice notice--success" *ngIf="actionNotice">{{ actionNotice }}</div>
        <div class="notice notice--warning" *ngIf="detail.run.error_message">{{ detail.run.error_message }}</div>
        <div class="notice notice--warning" *ngIf="replayStatusError">{{ replayStatusError }}</div>
        <div class="notice notice--error" *ngIf="actionError">{{ actionError }}</div>
        <div class="notice notice--error" *ngIf="analysisError">{{ analysisError }}</div>
        <div class="notice notice--error" *ngIf="recordsError">{{ recordsError }}</div>

        <div class="summary-grid">
          <div class="summary-card">
            <span>Status</span>
            <strong class="status status--{{ detail.run.status }}">{{ detail.run.status }}</strong>
          </div>
          <div class="summary-card">
            <span>Experiment Type</span>
            <strong>{{ detail.run.run_type === 'llm_audit' ? 'LLM Audit' : 'Scholarly' }}</strong>
          </div>
          <div class="summary-card">
            <span>Top K</span>
            <strong>{{ detail.run.top_k }}</strong>
          </div>
          <div class="summary-card">
            <span>Results</span>
            <strong>{{ analysis?.summary?.total_results ?? results.length }}</strong>
          </div>
          <div class="summary-card">
            <span>Queries</span>
            <strong>{{ detail.queries.length }}</strong>
          </div>
          <div class="summary-card">
            <span>{{ detail.run.run_type === 'llm_audit' ? 'Models' : 'Sources' }}</span>
            <strong>{{ detail.run.run_type === 'llm_audit' ? detail.run.selected_models.length : detail.run.sources.length }}</strong>
          </div>
        </div>

        <section class="context-grid">
          <article class="context-card">
            <p class="eyebrow eyebrow--compact">Queries</p>
            <div class="chip-list">
              <span class="chip" *ngFor="let query of detail.queries">
                Q{{ query.position }} · {{ query.text }}
              </span>
            </div>
          </article>

          <article class="context-card">
            <p class="eyebrow eyebrow--compact">{{ detail.run.run_type === 'llm_audit' ? 'Selected Models' : 'Collection Sources' }}</p>
            <div class="chip-list" *ngIf="detail.run.run_type === 'llm_audit'; else scholarlyContext">
              <span class="context-card__meta">{{ detail.run.selected_models.length }} selected models</span>
              <span class="context-card__meta">Validated for execution: {{ validatedSelectedModelCount() }}</span>
              <span class="context-card__meta" *ngIf="invalidSelectedModelStatuses().length">
                Unavailable or skipped: {{ invalidSelectedModelStatuses().length }}
              </span>
              <span class="chip" *ngFor="let model of detail.run.selected_models">{{ selectedModelDisplay(model) }}</span>
            </div>
            <div class="model-validation-list" *ngIf="invalidSelectedModelStatuses().length">
              <strong class="model-validation-list__title">Model validation issues</strong>
              <article class="model-validation-item" *ngFor="let item of invalidSelectedModelStatuses()">
                <strong>{{ selectedModelDisplay(item.name) }}</strong>
                <span>{{ item.error_message || item.progress_message || 'Unavailable during execution' }}</span>
              </article>
            </div>
            <ng-template #scholarlyContext>
              <div class="chip-list">
                <span class="chip" *ngFor="let source of detail.run.sources">{{ source }}</span>
              </div>
            </ng-template>
          </article>

          <article class="context-card" *ngIf="detail.run.run_type === 'llm_audit'">
            <p class="eyebrow eyebrow--compact">Artifact Replay</p>
            <p>Replay rebuilds parsing, enrichment, and analysis from saved LLM outputs. It does not call OpenRouter again and does not spend tokens again.</p>
            <div class="meta-stack">
              <span *ngIf="loadingReplayStatus">Checking replayable artifacts…</span>
              <span>Replay readiness: {{ replayStatus?.replay_available ? 'Ready from stored artifacts' : 'Not yet available' }}</span>
              <span *ngIf="replayStatus?.current_output_source">Current outputs: {{ currentOutputSourceLabel() }}</span>
              <span *ngIf="replayStatus?.current_output_generated_at">Outputs generated: {{ replayStatus?.current_output_generated_at }}</span>
              <span *ngIf="replayFinishedAt()">Last replay finished: {{ replayFinishedAt() }}</span>
              <span *ngIf="replayResultStatus()">Last replay status: {{ replayResultStatus() }}</span>
            </div>
          </article>

          <article class="context-card">
            <p class="eyebrow eyebrow--compact">Execution Timeline</p>
            <div class="meta-stack">
              <span>Created: {{ detail.run.created_at }}</span>
              <span *ngIf="detail.run.started_at">Started: {{ detail.run.started_at }}</span>
              <span *ngIf="detail.run.finished_at || detail.run.completed_at">Finished: {{ detail.run.finished_at || detail.run.completed_at }}</span>
            </div>
          </article>
        </section>

        <div class="entity-strip" *ngIf="detail.run.run_type !== 'llm_audit' && detail.entity_statuses.length">
          <article class="entity-card" *ngFor="let item of detail.entity_statuses">
            <div class="entity-card__header">
              <strong>{{ item.name }}</strong>
              <span class="status status--{{ item.status }}">{{ item.status }}</span>
            </div>
            <p>{{ item.completed_count }} completed / {{ item.failed_count }} failed / {{ item.total_count }} total</p>
          </article>
        </div>

        <section class="filters" *ngIf="analysis">
          <label>
            <span>Query</span>
            <select [value]="selectedQueryId" (change)="selectedQueryId = selectValue($event)">
              <option value="">All queries</option>
              <option *ngFor="let query of analysis.filters.queries" [value]="query.value">
                {{ query.label }}
              </option>
            </select>
          </label>

          <label>
            <span>{{ analysis.summary.entity_label }}</span>
            <select [value]="selectedEntity" (change)="selectedEntity = selectValue($event)">
              <option value="">All {{ analysis.summary.entity_label.toLowerCase() }}s</option>
              <option *ngFor="let entity of analysis.filters.entities" [value]="entity.value">
                {{ entity.label }}
              </option>
            </select>
          </label>

          <label>
            <span>Top K Slice</span>
            <select [value]="selectedTopK" (change)="selectedTopK = numberValue($event)">
              <option *ngFor="let item of analysis.filters.top_ks" [value]="item">{{ item }}</option>
            </select>
          </label>
        </section>
      </section>

      <app-run-report
        *ngIf="detail && analysis"
        [detail]="detail"
        [analysis]="analysis"
        [enrichmentRows]="enrichmentRows"
        [recordsRows]="reportRecords"
        [selectedQueryId]="selectedQueryId"
        [selectedEntity]="selectedEntity"
        [selectedTopK]="selectedTopK">
      </app-run-report>

      <ng-template #loadingBlock>
        <section class="panel">
          <h2>Experiment Details</h2>
          <p>{{ loadingRun ? 'Loading experiment...' : 'Experiment not available.' }}</p>
          <p class="error" *ngIf="runError">{{ runError }}</p>
        </section>
      </ng-template>
    </div>
  `,
  styles: [`
    :host {
      display: block;
      min-width: 0;
    }

    .page {
      display: grid;
      gap: 24px;
      width: min(100%, 1480px);
      margin: 0 auto;
      padding: 24px clamp(16px, 3vw, 28px) 40px;
      box-sizing: border-box;
      min-width: 0;
    }

    .page > *,
    .page > app-run-report,
    .hero__header > *,
    .panel__header > *,
    .status-panel__header > *,
    .status-panel__headline > *,
    .summary-grid > *,
    .context-grid > *,
    .entity-strip > *,
    .chart-grid > *,
    .detail-grid > *,
    .inspect-grid > *,
    .filters > * {
      min-width: 0;
    }

    .back-link {
      margin: 0;
    }

    .back-link a {
      color: #12324a;
      font-weight: 600;
      text-decoration: none;
    }

    .panel {
      border: 1px solid #d7e1ea;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.95);
      padding: 20px;
      box-shadow: 0 12px 30px rgba(15, 35, 55, 0.05);
      min-width: 0;
    }

    .hero {
      background:
        radial-gradient(circle at top right, rgba(188, 226, 255, 0.42), transparent 28%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(245, 250, 255, 0.98));
    }

    .hero__header,
    .panel__header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 20px;
    }

    .hero__intro {
      display: grid;
      gap: 8px;
      min-width: 0;
    }

    .eyebrow {
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.74rem;
      color: #56748d;
      font-weight: 700;
    }

    .eyebrow--compact {
      margin-bottom: 6px;
      font-size: 0.7rem;
    }

    .panel h2,
    .panel h3,
    .inspect-grid h4 {
      margin: 0 0 8px;
    }

    .panel p {
      margin: 0;
      color: #556270;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: flex-start;
      min-width: 0;
    }

    .actions > * {
      flex: 0 1 auto;
      max-width: 100%;
    }

    .actions--compact {
      gap: 10px;
    }

    .filters {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
      gap: 12px;
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid #e3ebf2;
    }

    .filters label {
      display: grid;
      gap: 8px;
      min-width: 0;
      font-weight: 600;
    }

    button,
    select {
      font: inherit;
    }

    button {
      border: 0;
      border-radius: 12px;
      padding: 10px 14px;
      background: #12324a;
      color: #ffffff;
      cursor: pointer;
      font-weight: 600;
      max-width: 100%;
      white-space: normal;
      text-align: center;
    }

    button.secondary {
      background: #e8eff6;
      color: #12324a;
    }

    button.danger {
      background: #fde8e7;
      color: #8c2222;
    }

    button:disabled {
      opacity: 0.65;
      cursor: default;
    }

    .nav-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 12px;
      padding: 10px 14px;
      background: #12324a;
      color: #ffffff;
      font-weight: 600;
      text-decoration: none;
    }

    .nav-button.secondary {
      background: #e8eff6;
      color: #12324a;
    }

    select {
      border: 1px solid #c7d4df;
      border-radius: 12px;
      padding: 12px 14px;
      background: #f9fbfd;
      width: 100%;
      min-width: 0;
      max-width: 100%;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
      gap: 12px;
    }

    .context-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
      gap: 14px;
      margin: 18px 0;
    }

    .context-card {
      border: 1px solid #dce5ed;
      border-radius: 16px;
      padding: 16px;
      background: #fbfdff;
      display: grid;
      gap: 10px;
      min-width: 0;
      overflow: hidden;
    }

    .context-card__meta {
      font-size: 0.9rem;
      color: #617182;
      overflow-wrap: anywhere;
    }

    .meta-stack {
      display: grid;
      gap: 8px;
      color: #344554;
      min-width: 0;
    }

    .meta-stack > span {
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .chip-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      min-width: 0;
      align-items: flex-start;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: #edf4fa;
      color: #12324a;
      font-size: 0.88rem;
      line-height: 1.35;
      max-width: 100%;
      white-space: normal;
      overflow-wrap: anywhere;
    }

    .model-validation-list {
      display: grid;
      gap: 10px;
      padding-top: 4px;
    }

    .model-validation-list__title {
      color: #7f5600;
      font-size: 0.92rem;
    }

    .model-validation-item {
      display: grid;
      gap: 4px;
      padding: 10px 12px;
      border: 1px solid #ecd7aa;
      border-radius: 12px;
      background: #fff8eb;
      color: #5f4b1d;
      overflow-wrap: anywhere;
    }

    .status-panel {
      display: grid;
      gap: 14px;
      padding: 16px;
      border: 1px solid #dce5ed;
      border-radius: 16px;
      background: rgba(251, 253, 255, 0.96);
      margin-bottom: 16px;
      min-width: 0;
    }

    .status-panel__header,
    .status-panel__headline,
    .progress-stack__meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }

    .status-panel__stage {
      display: grid;
      gap: 4px;
      justify-items: end;
      color: #556270;
      min-width: 0;
      text-align: right;
    }

    .status-panel__message {
      color: #1f3447;
      font-weight: 600;
    }

    .live-indicator {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: #0d4b8c;
      font-weight: 700;
    }

    .live-indicator::before {
      content: '';
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: #1d74d1;
      box-shadow: 0 0 0 6px rgba(29, 116, 209, 0.12);
    }

    .progress-stack {
      display: grid;
      gap: 8px;
    }

    .progress-stack--compact {
      gap: 6px;
    }

    .progress-bar {
      height: 12px;
      border-radius: 999px;
      background: #e4edf5;
      overflow: hidden;
    }

    .progress-bar--compact {
      height: 8px;
    }

    .progress-bar__fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #12324a, #2b6e8a);
      transition: width 180ms ease-out;
    }

    .notice {
      border-radius: 14px;
      padding: 12px 14px;
      margin-bottom: 12px;
      font-weight: 600;
    }

    .notice--success {
      background: #e7f5ec;
      color: #16643b;
    }

    .notice--warning {
      background: #fff3db;
      color: #8a5b00;
    }

    .notice--error {
      background: #fde8e7;
      color: #9f1c1c;
    }

    .summary-card,
    .entity-card {
      border: 1px solid #dce5ed;
      border-radius: 14px;
      padding: 14px;
      background: #fbfdff;
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .entity-card--model {
      gap: 10px;
    }

    .entity-card__meta {
      color: #6b7280;
      font-size: 0.92rem;
    }

    .entity-card__status-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 8px;
      min-width: 0;
    }

    .entity-card__retry {
      padding: 7px 10px;
      border-radius: 10px;
      font-size: 0.88rem;
    }

    .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px 20px;
      margin: 16px 0;
      color: #617182;
      font-size: 0.95rem;
    }

    .entity-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
      gap: 12px;
    }

    .entity-card__header,
    .chart-card__header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
    }

    .chart-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
      gap: 14px;
    }

    .chart-card {
      border: 1px solid #dce5ed;
      border-radius: 16px;
      background: #fbfdff;
      padding: 14px;
      min-width: 0;
    }

    .bar-list {
      display: grid;
      gap: 10px;
    }

    .bar-row {
      display: grid;
      gap: 8px;
    }

    .bar-row__label {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      color: #344554;
      font-size: 0.92rem;
      min-width: 0;
    }

    .bar-row__track {
      height: 10px;
      border-radius: 999px;
      background: #e7eef5;
      overflow: hidden;
    }

    .bar-row__fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #12324a, #2b6e8a);
    }

    .status {
      display: inline-flex;
      width: fit-content;
      align-items: center;
      padding: 3px 8px;
      border-radius: 999px;
      font-weight: 700;
      text-transform: capitalize;
    }

    .status--large {
      padding: 7px 12px;
      font-size: 0.92rem;
    }

    .status--pending {
      background: #fff3cd;
      color: #7a5400;
    }

    .status--running {
      background: #ddeafb;
      color: #0d4b8c;
    }

    .status--completed {
      background: #d9f2e3;
      color: #16643b;
    }

    .status--partial,
    .status--skipped {
      background: #fdecc8;
      color: #8a5b00;
    }

    .status--failed {
      background: #fde2e1;
      color: #9f1c1c;
    }

    .error {
      color: #b42318;
      margin-top: 12px;
    }

    .empty {
      border: 1px dashed #ccd7e2;
      border-radius: 14px;
      padding: 18px;
      color: #617182;
      background: #f8fbfd;
    }

    .empty.compact {
      padding: 12px;
    }

    .table-wrap {
      overflow-x: auto;
      max-width: 100%;
      min-width: 0;
      overscroll-behavior-x: contain;
    }

    .table-wrap--records {
      border: 1px solid #e2eaf1;
      border-radius: 16px;
      background: #ffffff;
      min-width: 0;
    }

    .panel--muted {
      background: linear-gradient(180deg, rgba(251, 253, 255, 0.98), rgba(246, 249, 252, 0.96));
    }

    .data-details {
      display: grid;
      gap: 16px;
      min-width: 0;
    }

    .data-details summary {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      cursor: pointer;
      font-weight: 700;
      color: #12324a;
      list-style: none;
      min-width: 0;
    }

    .data-details summary::-webkit-details-marker {
      display: none;
    }

    .data-details__meta {
      color: #617182;
      font-size: 0.92rem;
      font-weight: 600;
    }

    table {
      width: auto;
      border-collapse: collapse;
      min-width: 100%;
      table-layout: auto;
    }

    .records-table {
      min-width: 1120px;
    }

    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid #e4ebf2;
      text-align: left;
      vertical-align: top;
      min-width: 0;
    }

    th {
      white-space: normal;
      color: #617182;
      font-size: 0.92rem;
      background: #f8fbfd;
      position: sticky;
      top: 0;
      z-index: 1;
    }

    .col-number,
    .cell-number {
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
      width: 1%;
    }

    .col-compact,
    .cell-compact {
      white-space: normal;
      min-width: 8rem;
    }

    .col-doi {
      min-width: 12rem;
    }

    .col-medium {
      min-width: 14rem;
    }

    .col-wide {
      min-width: 16rem;
    }

    .cell-wrap {
      white-space: normal;
      line-height: 1.45;
      overflow-wrap: break-word;
      word-break: normal;
      max-width: 100%;
    }

    .cell-wrap--title {
      font-weight: 600;
      color: #15344a;
    }

    .cell-wrap--mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
      font-size: 0.88rem;
      overflow-wrap: anywhere;
      word-break: break-word;
      max-width: 100%;
    }

    .cell-action {
      white-space: nowrap;
      text-align: right;
      min-width: 6rem;
    }

    .table-row--interactive:hover > td {
      background: #f8fbfe;
    }

    .table-row--expanded > td {
      background: #f3f8fc;
    }

    .detail-row > td {
      padding: 0;
      background: #f8fbfd;
    }

    .detail-panel {
      display: grid;
      gap: 16px;
      padding: 18px;
      min-width: 0;
    }

    .detail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
      gap: 14px;
    }

    .detail-grid__span {
      grid-column: 1 / -1;
    }

    .detail-label {
      display: inline-block;
      margin-bottom: 6px;
      font-size: 0.76rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #627587;
      font-weight: 700;
    }

    .detail-grid p {
      margin: 0;
      color: #1f3447;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }

    .mono-wrap {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
      font-size: 0.88rem;
      white-space: pre-wrap;
      word-break: break-word;
      max-width: 100%;
    }

    .link-button {
      padding: 0;
      border: 0;
      background: transparent;
      color: #0d4b8c;
      font-weight: 700;
      cursor: pointer;
    }

    .link-button:disabled {
      color: #8da1b3;
      background: transparent;
    }

    .debug-card {
      border: 1px solid #dde6ee;
      border-radius: 14px;
      background: #ffffff;
      padding: 14px;
      display: grid;
      gap: 10px;
      min-width: 0;
    }

    .debug-card__header {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .debug-card__header span {
      color: #5f7284;
      font-size: 0.9rem;
    }

    .inspect-grid {
      display: grid;
      gap: 12px;
      min-width: 0;
    }

    .inspect-grid--wide {
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
    }

    .json-block {
      display: block;
      margin: 0;
      padding: 14px;
      border-radius: 12px;
      background: #0f1720;
      color: #dce7f3;
      max-width: 100%;
      min-width: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
      overflow: auto;
      font-size: 0.84rem;
      line-height: 1.5;
    }

    @media (max-width: 960px) {
      .page {
        gap: 20px;
        padding-bottom: 32px;
      }

      .hero__header,
      .panel__header {
        flex-direction: column;
      }

      .hero__intro,
      .actions {
        width: 100%;
      }

      .actions > button {
        flex: 1 1 220px;
      }

      .filters {
        grid-template-columns: 1fr;
      }

      .status-panel__stage {
        justify-items: start;
        text-align: left;
      }
    }

    @media (max-width: 640px) {
      .panel {
        padding: 16px;
        border-radius: 16px;
      }

      .status-panel,
      .context-card,
      .summary-card,
      .entity-card,
      .chart-card,
      .debug-card {
        padding: 14px;
      }
    }
  `]
})
export class RunDetailPageComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly runsApi = inject(RunsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly pollingIntervalMs = 1500;

  protected detail: RunDetail | null = null;
  protected openRouterModels: OpenRouterModelSummary[] = [];
  protected results: ResultRecord[] = [];
  protected enrichments: ResultEnrichmentResponse[] = [];
  protected enrichmentRows: EnrichmentRow[] = [];
  protected analysis: RunAnalysis | null = null;
  protected reportRecords: UnifiedRecordRow[] = [];
  protected replayStatus: ReplayStatusResponse | null = null;
  protected loadingRun = true;
  protected loadingModels = false;
  protected loadingResults = false;
  protected loadingEnrichments = false;
  protected loadingAnalysis = false;
  protected loadingReplayStatus = false;
  protected starting = false;
  protected replaying = false;
  protected deleting = false;
  protected retryingModelIds = new Set<string>();
  protected runError = '';
  protected resultsError = '';
  protected enrichmentsError = '';
  protected analysisError = '';
  protected recordsError = '';
  protected replayStatusError = '';
  protected actionError = '';
  protected actionNotice = '';
  protected selectedQueryId = '';
  protected selectedEntity = '';
  protected selectedTopK = 10;
  protected expandedResultIds = new Set<string>();
  protected expandedEnrichmentIds = new Set<string>();
  protected readonly distributionMetrics = [
    'publication_year_bucket',
    'language',
    'open_access',
    'country',
    'publisher',
    'venue'
  ];

  private runId = '';
  private pollingTimerId: number | null = null;
  private pollingRequestInFlight = false;

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => this.stopPolling());
    this.route.paramMap.pipe(
      map((params) => params.get('id')),
      filter((id): id is string => Boolean(id)),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe((id) => {
      this.stopPolling();
      this.runId = id;
      this.selectedQueryId = '';
      this.selectedEntity = '';
      this.refreshAll();
    });
  }

  protected refreshAll(): void {
    this.loadRun();
    this.loadOpenRouterModels();
    this.loadResults();
    this.loadEnrichments();
    this.loadAnalysis();
    this.loadReportRecords();
    this.loadReplayStatus();
    this.syncPolling();
  }

  protected loadRun(): void {
    if (!this.runId) {
      return;
    }

    this.loadingRun = true;
    this.runError = '';

    this.runsApi.getRun(this.runId).subscribe({
      next: (detail) => {
        this.detail = detail;
        if (detail.run.status !== 'pending') {
          this.starting = false;
        }
        this.loadingRun = false;
        this.syncPolling();
      },
      error: (error: unknown) => {
        this.runError = this.formatError(error, 'Failed to load experiment details.');
        this.loadingRun = false;
        this.syncPolling();
      }
    });
  }

  protected loadOpenRouterModels(): void {
    this.loadingModels = true;

    this.runsApi.getOpenRouterModels().subscribe({
      next: (response) => {
        this.openRouterModels = response.models;
        this.loadingModels = false;
      },
      error: () => {
        this.loadingModels = false;
      }
    });
  }

  protected loadResults(): void {
    if (!this.runId) {
      return;
    }

    this.loadingResults = true;
    this.resultsError = '';

    this.runsApi.getResults(this.runId).subscribe({
      next: (results) => {
        this.results = results;
        this.rebuildEnrichmentRows();
        this.loadingResults = false;
      },
      error: (error: unknown) => {
        this.resultsError = this.formatError(error, 'Failed to load results.');
        this.loadingResults = false;
      }
    });
  }

  protected loadEnrichments(): void {
    if (!this.runId) {
      return;
    }

    this.loadingEnrichments = true;
    this.enrichmentsError = '';

    this.runsApi.getEnrichments(this.runId).subscribe({
      next: (enrichments) => {
        this.enrichments = enrichments;
        this.rebuildEnrichmentRows();
        this.loadingEnrichments = false;
      },
      error: (error: unknown) => {
        this.enrichmentsError = this.formatError(error, 'Failed to load enrichments.');
        this.loadingEnrichments = false;
      }
    });
  }

  protected loadAnalysis(): void {
    if (!this.runId) {
      return;
    }

    this.loadingAnalysis = true;
    this.analysisError = '';

    this.runsApi.getAnalysis(this.runId).subscribe({
      next: (analysis) => {
        this.analysis = analysis;
        if (!analysis.filters.top_ks.includes(this.selectedTopK)) {
          this.selectedTopK = analysis.filters.default_top_k;
        }
        this.loadingAnalysis = false;
      },
      error: (error: unknown) => {
        this.analysisError = this.formatError(error, 'Failed to load analysis.');
        this.loadingAnalysis = false;
      }
    });
  }

  protected loadReportRecords(): void {
    if (!this.runId) {
      return;
    }

    this.recordsError = '';

    this.runsApi.getRecords(this.runId).subscribe({
      next: (response) => {
        this.reportRecords = response.rows;
      },
      error: (error: unknown) => {
        this.recordsError = this.formatError(error, 'Failed to load unified record rows.');
      }
    });
  }

  protected loadReplayStatus(): void {
    if (!this.runId) {
      return;
    }

    this.loadingReplayStatus = true;
    this.replayStatusError = '';

    this.runsApi.getReplayStatus(this.runId).subscribe({
      next: (payload) => {
        this.replayStatus = payload;
        this.loadingReplayStatus = false;
      },
      error: (error: unknown) => {
        this.replayStatusError = this.formatError(error, 'Failed to load replay status.');
        this.loadingReplayStatus = false;
      }
    });
  }

  protected startRun(): void {
    if (!this.runId) {
      return;
    }

    this.starting = true;
    this.actionError = '';
    this.actionNotice = '';
    if (this.detail) {
      this.detail = {
        ...this.detail,
        run: {
          ...this.detail.run,
          status: 'running',
          stage: 'initializing',
          progress_current: 0,
          progress_total: this.detail.queries.length || this.detail.run.progress_total,
          progress_message: 'Preparing experiment execution'
        }
      };
    }
    this.syncPolling();

    this.runsApi.startRun(this.runId).subscribe({
      next: (detail) => {
        this.detail = detail;
        this.starting = false;
        this.refreshAll();
      },
      error: (error: unknown) => {
        this.actionError = this.formatError(error, 'Failed to start experiment.');
        this.starting = false;
        this.syncPolling();
      }
    });
  }

  protected replayRun(): void {
    if (!this.runId || !this.canReplay()) {
      return;
    }

    this.replaying = true;
    this.actionError = '';
    this.actionNotice = '';

    this.runsApi.replayLlmArtifacts(this.runId).subscribe({
      next: (detail) => {
        this.detail = detail;
        this.replaying = false;
        this.actionNotice = 'Replay finished from stored LLM artifacts. No new LLM API calls were made.';
        this.refreshAll();
      },
      error: (error: unknown) => {
        this.actionError = this.formatError(error, 'Failed to replay stored LLM artifacts.');
        this.replaying = false;
      }
    });
  }

  protected retryModel(item: EntityExecutionSummary): void {
    if (!this.runId || !this.detail || !this.canRetryModel(item)) {
      return;
    }

    this.retryingModelIds = new Set([...this.retryingModelIds, item.name]);
    this.actionError = '';
    this.actionNotice = '';
    this.detail = {
      ...this.detail,
      entity_statuses: this.detail.entity_statuses.map((entity) =>
        entity.name === item.name && entity.entity_type === 'model'
          ? {
              ...entity,
              status: 'running',
              progress_message: 'Retrying failed or missing queries'
            }
          : entity
      )
    };
    this.syncPolling();

    this.runsApi.retryRunModel(this.runId, item.name).subscribe({
      next: (detail) => {
        this.detail = detail;
        this.retryingModelIds.delete(item.name);
        this.retryingModelIds = new Set(this.retryingModelIds);
        this.actionNotice = `Retry finished for ${item.name}.`;
        this.refreshAll();
      },
      error: (error: unknown) => {
        this.actionError = this.formatError(error, `Failed to retry ${item.name}.`);
        this.retryingModelIds.delete(item.name);
        this.retryingModelIds = new Set(this.retryingModelIds);
        this.syncPolling();
      }
    });
  }

  protected deleteRun(): void {
    if (!this.runId || !this.detail) {
      return;
    }

    const confirmed = window.confirm(
      `Delete experiment ${this.detail.run.id}? This removes the experiment record, results, and saved artifacts.`,
    );
    if (!confirmed) {
      return;
    }

    this.deleting = true;
    this.actionError = '';
    this.actionNotice = '';

    this.runsApi.deleteRun(this.runId).subscribe({
      next: () => {
        this.deleting = false;
        void this.router.navigate(['/runs']);
      },
      error: (error: unknown) => {
        this.actionError = this.formatError(error, 'Failed to delete experiment.');
        this.deleting = false;
      }
    });
  }

  protected selectValue(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  protected numberValue(event: Event): number {
    return Number((event.target as HTMLSelectElement).value);
  }

  protected queryLabel(queryId: string): string {
    const query = this.detail?.queries.find((item) => item.id === queryId);
    return query ? `Q${query.position}` : queryId;
  }

  protected fieldLabel(field: string): string {
    return field.replace(/_/g, ' ');
  }

  protected metricLabel(metric: string): string {
    return metric.replace(/_/g, ' ');
  }

  protected distributionTitle(metric: string): string {
    if (metric === 'publication_year_bucket') {
      return 'Publication Year / Recency';
    }
    return this.metricLabel(metric);
  }

  protected stageLabel(stage: string | null | undefined): string {
    if (!stage) {
      return 'Pending';
    }
    return stage
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (character) => character.toUpperCase());
  }

  protected isLiveUpdating(): boolean {
    return this.shouldPoll();
  }

  protected defaultProgressMessage(): string {
    if (!this.detail) {
      return 'Waiting for experiment details';
    }
    if (this.detail.run.status === 'pending') {
      return 'Experiment is ready to start';
    }
    if (this.detail.run.status === 'running') {
      return 'Experiment is in progress';
    }
    if (this.detail.run.status === 'completed') {
      return 'Experiment completed successfully';
    }
    if (this.detail.run.status === 'partial') {
      return 'Experiment completed with partial failures';
    }
    return this.detail.run.error_message || 'Experiment failed';
  }

  protected canReplay(): boolean {
    return Boolean(
      this.detail?.run.run_type === 'llm_audit' &&
      this.detail.run.status !== 'running' &&
      this.replayStatus?.replay_available,
    );
  }

  protected canRetryModel(item: EntityExecutionSummary): boolean {
    return Boolean(
      this.detail?.run.run_type === 'llm_audit' &&
      this.detail.run.status !== 'running' &&
      item.entity_type === 'model' &&
      (
        item.status === 'failed' ||
        item.status === 'partial' ||
        item.status === 'skipped' ||
        item.progress_current < item.progress_total ||
        item.completed_count < item.total_count
      )
    );
  }

  protected isRetryingModel(modelName: string): boolean {
    return this.retryingModelIds.has(modelName);
  }

  protected currentOutputSourceLabel(): string {
    if (this.replayStatus?.current_output_source === 'artifact_replay') {
      return 'Artifact replay';
    }
    if (this.replayStatus?.current_output_source === 'fresh_execution') {
      return 'Fresh execution';
    }
    return 'Unknown';
  }

  protected replayFinishedAt(): string | null {
    const value = this.replayStatus?.replay_summary?.['finished_at'];
    return typeof value === 'string' && value ? value : null;
  }

  protected replayResultStatus(): string | null {
    const value = this.replayStatus?.replay_summary?.['status'];
    return typeof value === 'string' && value ? value : null;
  }

  protected queryText(queryId: string): string {
    return this.detail?.queries.find((item) => item.id === queryId)?.text || 'Unknown query';
  }

  protected selectedModelDisplay(modelId: string): string {
    const name = this.openRouterModels.find((item) => item.id === modelId)?.name;
    if (!name || name === modelId) {
      return modelId;
    }
    return `${name} · ${modelId}`;
  }

  protected invalidSelectedModelStatuses(): EntityExecutionSummary[] {
    if (this.detail?.run.run_type !== 'llm_audit') {
      return [];
    }
    return this.detail.entity_statuses.filter((item) =>
      item.entity_type === 'model' &&
      Boolean(item.error_message?.includes('Skipped without API call because model'))
    );
  }

  protected validatedSelectedModelCount(): number {
    if (this.detail?.run.run_type !== 'llm_audit') {
      return 0;
    }
    return Math.max(this.detail.run.selected_models.length - this.invalidSelectedModelStatuses().length, 0);
  }

  protected joinedValues(values: string[]): string {
    return values.length ? values.join(', ') : '—';
  }

  protected toggleResultDetails(resultId: string): void {
    if (this.expandedResultIds.has(resultId)) {
      this.expandedResultIds.delete(resultId);
    } else {
      this.expandedResultIds.add(resultId);
    }
    this.expandedResultIds = new Set(this.expandedResultIds);
  }

  protected isResultExpanded(resultId: string): boolean {
    return this.expandedResultIds.has(resultId);
  }

  protected toggleEnrichmentDetails(resultId: string): void {
    if (this.expandedEnrichmentIds.has(resultId)) {
      this.expandedEnrichmentIds.delete(resultId);
    } else {
      this.expandedEnrichmentIds.add(resultId);
    }
    this.expandedEnrichmentIds = new Set(this.expandedEnrichmentIds);
  }

  protected isEnrichmentExpanded(resultId: string): boolean {
    return this.expandedEnrichmentIds.has(resultId);
  }

  protected runProgressRatio(): number {
    if (!this.detail || this.detail.run.progress_total <= 0) {
      return 0;
    }
    return Math.min(1, this.detail.run.progress_current / this.detail.run.progress_total);
  }

  protected entityProgressRatio(item: EntityExecutionSummary): number {
    if (item.progress_total <= 0) {
      return 0;
    }
    return Math.min(1, item.progress_current / item.progress_total);
  }

  protected entitySummary(item: EntityExecutionSummary): string {
    return `${item.completed_count} completed / ${item.failed_count} failed / ${item.total_count} total`;
  }

  protected entityName(result: ResultRecord): string {
    return result.model_name || result.source_name || 'overall';
  }

  protected providerList(records: ResultEnrichmentResponse['provider_records']): string {
    return records.map((record) => `${record.provider} (${record.status})`).join(', ');
  }

  protected countryList(enrichment: CanonicalEnrichment | null): string {
    return enrichment?.countries?.join(', ') || enrichment?.country_primary || '—';
  }

  protected oaLabel(enrichment: CanonicalEnrichment | null): string {
    if (!enrichment) {
      return '—';
    }
    if (enrichment.open_access_status) {
      return enrichment.open_access_status;
    }
    if (enrichment.is_open_access === true) {
      return 'open';
    }
    if (enrichment.is_open_access === false) {
      return 'closed';
    }
    return 'unknown';
  }

  protected filteredDistributionRows(metric: string): DistributionRow[] {
    return (this.analysis?.distributions ?? []).filter((row) =>
      row.metric === metric &&
      this.matchesQuery(row.query_id) &&
      this.matchesEntity(row.entity)
    );
  }

  protected filteredCoverageRows(): CoverageRow[] {
    return (this.analysis?.coverage_rows ?? []).filter((row) =>
      this.matchesQuery(row.query_id) &&
      this.matchesEntity(row.entity)
    );
  }

  protected filteredTopKRows(): TopKComparisonRow[] {
    return (this.analysis?.top_k_rows ?? []).filter((row) =>
      row.k === this.selectedTopK &&
      this.matchesQuery(row.query_id) &&
      this.matchesEntity(row.entity)
    );
  }

  protected filteredOverlapRows(): OverlapRow[] {
    return (this.analysis?.overlap_rows ?? []).filter((row) =>
      this.matchesQuery(row.query_id) &&
      (this.selectedEntity === '' || row.left_entity === this.selectedEntity || row.right_entity === this.selectedEntity)
    );
  }

  protected filteredConcentrationRows(): ConcentrationRow[] {
    return (this.analysis?.concentration_rows ?? []).filter((row) =>
      this.selectedEntity === '' ? row.entity === 'overall' : row.entity === this.selectedEntity
    );
  }

  protected filteredResults(): ResultRecord[] {
    return this.results.filter((result) =>
      (this.selectedQueryId === '' || result.query_id === this.selectedQueryId) &&
      (this.selectedEntity === '' || this.entityName(result) === this.selectedEntity)
    );
  }

  protected filteredEnrichmentRows(): EnrichmentRow[] {
    return this.enrichmentRows.filter((row) =>
      (this.selectedQueryId === '' || row.result.query_id === this.selectedQueryId) &&
      (this.selectedEntity === '' || this.entityName(row.result) === this.selectedEntity)
    );
  }

  protected filteredLlmCalls(): LLMCallRow[] {
    return (this.analysis?.llm?.calls ?? []).filter((row) =>
      (this.selectedQueryId === '' || row.query_id === this.selectedQueryId) &&
      (this.selectedEntity === '' || row.model_name === this.selectedEntity)
    );
  }

  protected filteredLlmMetrics(): LLMMetricRow[] {
    return (this.analysis?.llm?.metrics ?? []).filter((row) =>
      (this.selectedQueryId === '' || row.query_id === this.selectedQueryId) &&
      (this.selectedEntity === '' || row.entity === this.selectedEntity || row.entity === 'overall')
    );
  }

  protected llmMetric(metric: string): number | null {
    const row = (this.analysis?.llm?.metrics ?? []).find((item) => item.metric === metric && item.entity === 'overall');
    return row?.value ?? null;
  }

  protected concentrationValue(metric: string): number | null {
    const row = (this.analysis?.concentration_rows ?? []).find((item) => item.metric === metric && item.entity === 'overall');
    return row?.value ?? null;
  }

  protected displayPercentage(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return '—';
    }
    return `${(value * 100).toFixed(1)}%`;
  }

  protected recordsQueryParams(): Record<string, string | number> {
    const params: Record<string, string | number> = {};
    if (this.selectedQueryId) {
      params['query_id'] = this.selectedQueryId;
    }
    if (this.selectedEntity) {
      params['entity'] = this.selectedEntity;
    }
    if (this.selectedTopK) {
      params['top_k'] = this.selectedTopK;
    }
    return params;
  }

  private shouldPoll(): boolean {
    if (!this.runId) {
      return false;
    }
    const status = this.detail?.run.status;
    return this.starting || this.retryingModelIds.size > 0 || status === 'pending' || status === 'running';
  }

  private syncPolling(): void {
    if (this.shouldPoll()) {
      if (this.pollingTimerId === null) {
        this.pollingTimerId = window.setTimeout(() => this.runPollingTick(), this.pollingIntervalMs);
      }
      return;
    }
    this.stopPolling();
  }

  private stopPolling(): void {
    if (this.pollingTimerId !== null) {
      window.clearTimeout(this.pollingTimerId);
      this.pollingTimerId = null;
    }
  }

  private runPollingTick(): void {
    this.pollingTimerId = null;
    if (!this.runId || !this.shouldPoll() || this.pollingRequestInFlight) {
      this.syncPolling();
      return;
    }

    this.pollingRequestInFlight = true;

    forkJoin({
      detail: this.runsApi.getRun(this.runId).pipe(catchError((error: unknown) => {
        this.runError = this.formatError(error, 'Failed to load experiment details.');
        return of<RunDetail | null>(null);
      })),
      results: this.runsApi.getResults(this.runId).pipe(catchError((error: unknown) => {
        this.resultsError = this.formatError(error, 'Failed to load results.');
        return of<ResultRecord[] | null>(null);
      })),
      enrichments: this.runsApi.getEnrichments(this.runId).pipe(catchError((error: unknown) => {
        this.enrichmentsError = this.formatError(error, 'Failed to load enrichments.');
        return of<ResultEnrichmentResponse[] | null>(null);
      })),
      analysis: this.runsApi.getAnalysis(this.runId).pipe(catchError((error: unknown) => {
        this.analysisError = this.formatError(error, 'Failed to load analysis.');
        return of<RunAnalysis | null>(null);
      })),
      replayStatus: this.runsApi.getReplayStatus(this.runId).pipe(catchError((error: unknown) => {
        this.replayStatusError = this.formatError(error, 'Failed to load replay status.');
        return of<ReplayStatusResponse | null>(null);
      })),
      recordRows: this.runsApi.getRecords(this.runId).pipe(catchError((error: unknown) => {
        this.recordsError = this.formatError(error, 'Failed to load unified record rows.');
        return of(null);
      }))
    }).subscribe({
      next: ({ detail, results, enrichments, analysis, replayStatus, recordRows }) => {
        if (detail) {
          this.detail = detail;
          if (detail.run.status !== 'pending') {
            this.starting = false;
          }
        }
        if (results) {
          this.results = results;
        }
        if (enrichments) {
          this.enrichments = enrichments;
        }
        if (results || enrichments) {
          this.rebuildEnrichmentRows();
        }
        if (analysis) {
          this.analysis = analysis;
          if (!analysis.filters.top_ks.includes(this.selectedTopK)) {
            this.selectedTopK = analysis.filters.default_top_k;
          }
        }
        if (replayStatus) {
          this.replayStatus = replayStatus;
        }
        if (recordRows) {
          this.reportRecords = recordRows.rows;
        }
      },
      complete: () => {
        this.pollingRequestInFlight = false;
        this.syncPolling();
      }
    });
  }

  protected displayNumber(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return '—';
    }
    if (Math.abs(value) >= 1000) {
      return value.toFixed(0);
    }
    return value.toFixed(2);
  }

  private matchesQuery(queryId: string | null): boolean {
    if (this.selectedQueryId === '') {
      return queryId === null;
    }
    return queryId === this.selectedQueryId;
  }

  private matchesEntity(entity: string): boolean {
    if (this.selectedEntity === '') {
      return entity === 'overall';
    }
    return entity === this.selectedEntity;
  }

  private rebuildEnrichmentRows(): void {
    const enrichmentByResultId = new Map(this.enrichments.map((item) => [item.result_record_id, item]));
    this.enrichmentRows = this.results.map((result) => {
      const enrichment = enrichmentByResultId.get(result.id);
      return {
        result,
        providerRecords: enrichment?.provider_records ?? [],
        canonicalEnrichment: enrichment?.canonical_enrichment ?? null
      };
    });
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
