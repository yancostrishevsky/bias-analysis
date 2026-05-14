import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { RunsApiService } from '../../../core/api/runs-api.service';
import {
  CreateRunRequest,
  OpenRouterModelSummary,
  OpenRouterModelsResponse,
  RunDetail,
  RunOptionsResponse,
  RunType,
  ScholarlySourceOption,
} from '../models/run.models';

interface ProviderCard {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
  note: string;
}

interface CollectionSourceCard {
  id: string;
  label: string;
  description: string;
  selectable: boolean;
  note: string;
}

interface ModelPaginationSummary {
  start: number;
  end: number;
  totalPages: number;
}

@Component({
  selector: 'app-run-list-page',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  template: `
    <div class="layout">
      <section class="panel panel--form">
        <div class="panel__header">
          <div>
            <p class="eyebrow">Experiment Creation</p>
            <h2>Create Experiment</h2>
            <p>Create a persisted scholarly collection or multi-model LLM audit, then inspect the experiment detail page for live status and analysis.</p>
          </div>
        </div>

        <form [formGroup]="createRunForm" (ngSubmit)="createRun()" class="form">
          <div class="form__row">
            <label>
              <span>Experiment Type</span>
              <select formControlName="runType">
                <option *ngFor="let item of options?.supported_run_types ?? []" [value]="item">
                  {{ runTypeLabel(item) }}
                </option>
              </select>
            </label>

            <label>
              <span>Top K</span>
              <input formControlName="topK" type="number" min="1" max="100">
            </label>
          </div>

          <section class="subpanel subpanel--accent" *ngIf="isScholarlyMode()">
            <div class="subpanel__header">
              <h3>Collection Source</h3>
              <p>Select one or more real collection sources. Each selected source runs its own scholarly query collection and writes separate source-level artifacts.</p>
            </div>

            <div class="source-grid">
              <label
                class="source-card"
                [class.source-card--selected]="selectedSources.has(source.id)"
                [class.source-card--disabled]="!source.selectable"
                *ngFor="let source of collectionSources()">
                <input
                  type="checkbox"
                  [checked]="selectedSources.has(source.id)"
                  [disabled]="!source.selectable"
                  (change)="toggleSource(source.id, $event)">
                <span class="source-card__body">
                  <span class="source-card__title">{{ source.label }}</span>
                  <span class="source-card__description">{{ source.description }}</span>
                  <span class="source-card__note">{{ source.note }}</span>
                </span>
              </label>
            </div>
          </section>

          <section class="subpanel" *ngIf="isScholarlyMode()">
            <div class="subpanel__header">
              <h3>Metadata Enrichment Providers</h3>
              <p>The backend can enrich collected records with OpenAlex, Semantic Scholar, Scopus, and CORE. Availability here follows current backend configuration.</p>
            </div>

            <div class="provider-grid">
              <article
                class="provider-card"
                [class.provider-card--disabled]="!provider.enabled"
                *ngFor="let provider of enrichmentProviders()">
                <div class="provider-card__header">
                  <h4>{{ provider.label }}</h4>
                  <span class="badge" [class.badge--muted]="!provider.enabled">
                    {{ provider.enabled ? 'Enabled' : 'Unavailable' }}
                  </span>
                </div>
                <p>{{ provider.description }}</p>
                <p class="provider-card__note">{{ provider.note }}</p>
              </article>
            </div>
          </section>

          <section class="subpanel" *ngIf="isLlmAuditMode()">
            <div class="subpanel__header">
              <h3>LLM Models</h3>
              <p>Fetch live OpenRouter models from the backend, then search and filter before selecting up to 10 for this experiment.</p>
            </div>

            <div class="model-toolbar">
              <label>
                <span>Search</span>
                <input
                  type="search"
                  [value]="modelSearchText"
                  (input)="updateModelSearch($event)"
                  placeholder="Search by name, id, or description">
              </label>

              <label>
                <span>Modality</span>
                <select [value]="modelModalityFilter" (change)="updateModelModalityFilter($event)">
                  <option value="all">All modalities</option>
                  <option value="text">Text only</option>
                  <option value="vision">Vision-capable</option>
                  <option value="multimodal">Multimodal</option>
                  <option value="image">Image</option>
                  <option value="audio">Audio</option>
                </select>
              </label>

              <label>
                <span>Min Context</span>
                <input
                  type="number"
                  min="0"
                  [value]="modelMinContextLength ?? ''"
                  (input)="updateModelMinContext($event)"
                  placeholder="e.g. 128000">
              </label>

              <label>
                <span>Sort</span>
                <select [value]="modelSort" (change)="updateModelSort($event)">
                  <option value="name">Name</option>
                  <option value="prompt_price">Cheapest prompt</option>
                  <option value="completion_price">Cheapest completion</option>
                  <option value="context_length">Largest context</option>
                </select>
              </label>
            </div>

            <div class="selection-summary">
              <div class="selection-summary__stats">
                <strong>{{ selectedModels.size }}/{{ maxSelectedModels }} selected</strong>
                <span class="hint">{{ totalModelCount() }} models total</span>
                <span class="hint">{{ filteredModelCount() }} matching filters</span>
              </div>
              <button type="button" class="secondary button--small" (click)="clearSelectedModels()" [disabled]="!selectedModels.size">
                Clear selection
              </button>
            </div>

            <p class="hint" *ngIf="openRouterModelsResponse?.cached">
              Showing cached OpenRouter model metadata from the backend cache.
            </p>
            <div class="notice notice--warning" *ngIf="staleSelectedModelIds.length">
              <div class="notice__content">
                <strong>Removed stale model selections from the form.</strong>
                <span>
                  {{ staleSelectedModelIds.length }} previously selected
                  {{ staleSelectedModelIds.length === 1 ? 'model is' : 'models are' }}
                  no longer present in the current catalog:
                  {{ staleSelectedModelIds.join(', ') }}
                </span>
              </div>
              <button type="button" class="secondary button--small" (click)="dismissStaleModelNotice()">
                Dismiss
              </button>
            </div>
            <p class="error" *ngIf="modelsError">{{ modelsError }}</p>
            <p class="error" *ngIf="modelSelectionError()">{{ modelSelectionError() }}</p>

            <div class="empty" *ngIf="loadingModels">
              Loading OpenRouter models…
            </div>

            <div class="empty" *ngIf="!loadingModels && !modelsError && !visibleModels().length">
              No models match the current filters.
            </div>

            <section class="model-results" *ngIf="!loadingModels && visibleModels().length">
              <div class="model-results__header">
                <div class="model-results__meta">
                  <strong>
                    Showing {{ paginationSummary().start }}-{{ paginationSummary().end }}
                    of {{ filteredModelCount() }}
                  </strong>
                  <span class="hint">
                    Page {{ modelCurrentPage }} of {{ paginationSummary().totalPages }}
                  </span>
                </div>

                <label class="page-size">
                  <span>Page size</span>
                  <select [value]="modelPageSize" (change)="updateModelPageSize($event)">
                    <option *ngFor="let size of modelPageSizeOptions" [value]="size">{{ size }}</option>
                  </select>
                </label>
              </div>

              <div class="model-table">
                <div class="model-table__head">
                  <span></span>
                  <span>Model</span>
                  <span>Context</span>
                  <span>Pricing</span>
                  <span>Modalities</span>
                </div>

                <label
                  class="model-row"
                  [class.model-row--selected]="selectedModels.has(model.id)"
                  [class.model-row--disabled]="selectionLimitReached() && !selectedModels.has(model.id)"
                  *ngFor="let model of paginatedModels()">
                  <input
                    type="checkbox"
                    [checked]="selectedModels.has(model.id)"
                    [disabled]="selectionLimitReached() && !selectedModels.has(model.id)"
                    (change)="toggleModel(model.id, $event)">
                  <span class="model-row__main">
                    <span class="model-row__title">
                      <span class="model-card__title">{{ model.name }}</span>
                      <span class="badge">{{ model.provider || 'OpenRouter' }}</span>
                    </span>
                    <span class="model-card__id">{{ model.id }}</span>
              
                  </span>
                  <span class="model-row__metric model-row__metric--number">
                    {{ formatContextLength(model.context_length) }}
                  </span>
                  <span class="model-row__metric">
                    <span>Prompt {{ formatPrice(model.prompt_price) }}</span>
                    <span>Completion {{ formatPrice(model.completion_price) }}</span>
                  </span>
                  <span class="model-row__metric">
                    {{ formatModalities(model) }}
                  </span>
                </label>
              </div>

              <div class="model-pagination" *ngIf="paginationSummary().totalPages > 1">
                <button
                  type="button"
                  class="secondary"
                  (click)="goToPreviousModelPage()"
                  [disabled]="modelCurrentPage === 1">
                  Previous
                </button>
                <span class="hint">
                  Page {{ modelCurrentPage }} / {{ paginationSummary().totalPages }}
                </span>
                <button
                  type="button"
                  class="secondary"
                  (click)="goToNextModelPage()"
                  [disabled]="modelCurrentPage >= paginationSummary().totalPages">
                  Next
                </button>
              </div>
            </section>
          </section>

          <section class="subpanel subpanel--queries">
            <div class="subpanel__header">
              <h3>Queries</h3>
              <p>Enter one or many queries. Each row becomes a persisted query in the experiment, and the order is preserved.</p>
            </div>

            <div class="query-editor">
              <div class="query-editor__list">
                <article class="query-row" *ngFor="let query of queryRows; let index = index">
                  <div class="query-row__header">
                    <strong>Q{{ index + 1 }}</strong>
                    <button
                      type="button"
                      class="secondary button--small"
                      (click)="removeQueryRow(index)"
                      [disabled]="queryRows.length === 1">
                      Remove
                    </button>
                  </div>
                  <textarea
                    rows="3"
                    [value]="query"
                    (input)="updateQueryRow(index, $event)"
                    placeholder="Example: systematic review of machine learning in radiology"></textarea>
                </article>
              </div>

              <div class="query-editor__actions">
                <button type="button" class="secondary" (click)="addQueryRow()">Add query row</button>
                <span class="hint">Use concise search-like phrasing. One line equals one stored query.</span>
              </div>

              <div class="bulk-paste">
                <label>
                  <span>Paste Multiple Queries</span>
                  <textarea
                    rows="4"
                    [value]="bulkQueryText"
                    (input)="bulkQueryText = textAreaValue($event)"
                    placeholder="Paste one query per line to replace the current list"></textarea>
                </label>
                <div class="bulk-paste__actions">
                  <button
                    type="button"
                    class="secondary"
                    (click)="applyBulkQueries()"
                    [disabled]="!bulkQueryText.trim()">
                    Split Into Query Rows
                  </button>
                  <span class="hint">Blank lines are ignored.</span>
                </div>
              </div>
            </div>
          </section>

          <div class="form__actions">
            <button type="submit" [disabled]="submitting || loadingOptions">Create experiment</button>
            <span class="hint" *ngIf="isScholarlyMode()">
              Enabled enrichment order: {{ enabledEnrichmentProviderLabels().join(' → ') || 'none' }}
            </span>
          </div>

          <p class="error" *ngIf="submitError">{{ submitError }}</p>
          <p class="error" *ngIf="optionsError">{{ optionsError }}</p>
        </form>
      </section>

      <section class="panel panel--list">
        <div class="panel__header">
          <div>
            <p class="eyebrow">Persisted Experiments</p>
            <h2>Experiments</h2>
            <p>Each experiment keeps its status, artifacts, and downstream analysis. Delete is available for any experiment status, including stuck experiments.</p>
          </div>
          <button type="button" class="secondary" (click)="loadRuns()" [disabled]="loadingRuns">
            Refresh
          </button>
        </div>

        <p class="error" *ngIf="loadError">{{ loadError }}</p>

        <div class="empty" *ngIf="!loadingRuns && !runs.length">
          No runs yet. Create the first one from the form.
        </div>

        <ul class="run-list" *ngIf="runs.length">
          <li class="run-card" *ngFor="let item of runs">
            <div class="run-card__header">
              <div class="run-card__meta">
                <span class="status status--{{ item.run.status }}">{{ item.run.status }}</span>
                <span class="badge">{{ runTypeLabel(item.run.run_type) }}</span>
                <span>{{ item.queries.length }} queries</span>
                <span *ngIf="item.run.run_type === 'scholarly'">{{ item.run.sources.length }} collection sources</span>
                <span *ngIf="item.run.run_type === 'llm_audit'">{{ item.run.selected_models.length }} models</span>
                <span>top_k {{ item.run.top_k }}</span>
              </div>

              <div class="run-card__actions">
                <a [routerLink]="['/runs', item.run.id]">Open experiment</a>
                <button
                  type="button"
                  class="secondary danger"
                  (click)="deleteRun(item)"
                  [disabled]="isDeleting(item.run.id)">
                  {{ isDeleting(item.run.id) ? 'Deleting…' : 'Delete' }}
                </button>
              </div>
            </div>

            <h3>{{ item.run.id }}</h3>

            <div class="run-card__group">
              <span class="run-card__label">Queries</span>
              <p class="run-card__queries">{{ previewQueries(item) }}</p>
            </div>

            <div class="run-card__group" *ngIf="item.run.run_type === 'scholarly'">
              <span class="run-card__label">Collection</span>
              <p class="run-card__entities">{{ sourceLabels(item.run.sources).join(', ') }}</p>
            </div>

            <div class="run-card__group" *ngIf="item.run.run_type === 'scholarly'">
              <span class="run-card__label">Configured enrichment</span>
              <p class="run-card__entities">{{ enabledEnrichmentProviderLabels().join(', ') || 'No providers enabled' }}</p>
            </div>

            <div class="run-card__group" *ngIf="item.run.run_type === 'llm_audit'">
              <span class="run-card__label">Models</span>
              <p class="run-card__entities">{{ item.run.selected_models.join(', ') }}</p>
            </div>
          </li>
        </ul>
      </section>
    </div>
  `,
  styles: [`
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.82fr);
      gap: 24px;
      align-items: start;
    }

    .panel {
      border: 1px solid #d7e1ea;
      border-radius: 22px;
      background: rgba(255, 255, 255, 0.96);
      padding: 24px;
      box-shadow: 0 18px 40px rgba(15, 35, 55, 0.06);
    }

    .panel--form {
      background:
        radial-gradient(circle at top right, rgba(194, 231, 255, 0.42), transparent 30%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(245, 250, 255, 0.98));
    }

    .panel__header {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: start;
      margin-bottom: 22px;
    }

    .eyebrow {
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.74rem;
      color: #56748d;
      font-weight: 700;
    }

    .panel h2,
    .subpanel h3,
    .provider-card h4 {
      margin: 0 0 8px;
    }

    .panel p,
    .subpanel p,
    .provider-card p {
      margin: 0;
      color: #556270;
    }

    .form {
      display: grid;
      gap: 18px;
    }

    .form__row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .subpanel {
      display: grid;
      gap: 14px;
      padding: 18px;
      border: 1px solid #dde8f1;
      border-radius: 18px;
      background: #fbfdff;
    }

    .subpanel--accent {
      background: linear-gradient(180deg, rgba(250, 252, 255, 0.98), rgba(240, 247, 253, 0.98));
    }

    .subpanel__header {
      display: grid;
      gap: 6px;
    }

    label {
      display: grid;
      gap: 8px;
      font-weight: 600;
    }

    input,
    textarea,
    select {
      width: 100%;
      border: 1px solid #c7d4df;
      border-radius: 14px;
      padding: 12px 14px;
      background: #f9fbfd;
      font: inherit;
    }

    textarea {
      resize: vertical;
      min-height: 88px;
    }

    .source-grid,
    .provider-grid,
    .model-grid,
    .model-toolbar,
    .query-editor__list,
    .run-list {
      display: grid;
      gap: 12px;
    }

    .source-card,
    .provider-card,
    .model-card,
    .query-row,
    .run-card {
      border: 1px solid #dce5ed;
      border-radius: 18px;
      background: #ffffff;
    }

    .source-card {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      padding: 14px 16px;
      cursor: pointer;
    }

    .source-card input {
      width: auto;
      margin-top: 4px;
    }

    .source-card--selected,
    .model-card--selected {
      border-color: #12324a;
      box-shadow: 0 10px 24px rgba(18, 50, 74, 0.08);
    }

    .source-card--disabled {
      background: #f7f8fa;
      color: #6f7b87;
      cursor: default;
    }

    .source-card--disabled .source-card__title {
      color: #556270;
    }

    .source-card__body,
    .model-card__body {
      display: grid;
      gap: 4px;
    }

    .source-card__title,
    .model-card__title {
      font-weight: 700;
      color: #12324a;
    }

    .source-card__description,
    .model-card__meta,
    .model-card__description,
    .model-card__id {
      font-size: 0.9rem;
      color: #5f7284;
    }

    .source-card__note {
      font-size: 0.8rem;
      color: #2f5e82;
      font-weight: 600;
    }

    .model-toolbar {
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }

    .selection-summary {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }

    .selection-summary__stats {
      display: flex;
      gap: 10px 16px;
      align-items: center;
      flex-wrap: wrap;
    }

    .model-results {
      display: grid;
      gap: 14px;
    }

    .model-results__header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: end;
      flex-wrap: wrap;
    }

    .model-results__meta {
      display: flex;
      gap: 8px 14px;
      align-items: center;
      flex-wrap: wrap;
    }

    .page-size {
      display: flex;
      gap: 8px;
      align-items: center;
      font-weight: 600;
    }

    .page-size select {
      width: auto;
      min-width: 92px;
      padding-right: 36px;
    }

    .model-table {
      border: 1px solid #dce5ed;
      border-radius: 18px;
      overflow: hidden;
      background: linear-gradient(180deg, #ffffff, #fbfdff);
    }

    .model-table__head,
    .model-row {
      display: grid;
      grid-template-columns: auto minmax(0, 2.2fr) minmax(100px, 0.75fr) minmax(170px, 1fr) minmax(140px, 0.9fr);
      gap: 14px;
      align-items: start;
      padding: 14px 16px;
    }

    .model-table__head {
      background: #f4f8fc;
      color: #607283;
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .model-row {
      border-top: 1px solid #e2eaf1;
      cursor: pointer;
    }

    .model-row:first-of-type {
      border-top: 0;
    }

    .model-row--selected {
      background: linear-gradient(180deg, #f5f9fc, #eef5fb);
    }

    .model-row--disabled {
      background: #f7f8fa;
      color: #6f7b87;
      cursor: default;
    }

    .model-row--disabled .model-card__title {
      color: #556270;
    }

    .model-row input {
      width: auto;
      margin-top: 4px;
    }

    .model-row__main {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .model-row__title {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }

    .model-card__id {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
      overflow-wrap: anywhere;
    }

    .model-row__metric {
      display: grid;
      gap: 4px;
      color: #405464;
      font-size: 0.92rem;
      line-height: 1.4;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .model-row__metric--number {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }

    .model-pagination {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }

    .provider-grid {
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    }

    .model-grid {
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    }

    .provider-card {
      padding: 16px;
      display: grid;
      gap: 8px;
      background: linear-gradient(180deg, #ffffff, #f8fbfe);
    }

    .provider-card--disabled {
      background: #f7f8fa;
    }

    .provider-card__header,
    .run-card__header,
    .run-card__actions,
    .query-row__header,
    .form__actions,
    .query-editor__actions,
    .bulk-paste__actions {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }

    .provider-card__note {
      font-size: 0.86rem;
      color: #617182;
    }

    .query-editor {
      display: grid;
      gap: 14px;
    }

    .query-row {
      padding: 14px;
      background: linear-gradient(180deg, #ffffff, #f8fbfd);
    }

    .query-row__header strong {
      color: #12324a;
    }

    .bulk-paste {
      display: grid;
      gap: 10px;
      padding-top: 6px;
      border-top: 1px solid #e4ebf2;
    }

    .form__actions {
      padding-top: 4px;
    }

    button,
    .run-card__actions a {
      border: 0;
      border-radius: 12px;
      padding: 10px 14px;
      background: #12324a;
      color: #ffffff;
      cursor: pointer;
      text-decoration: none;
      width: fit-content;
      font-weight: 600;
      font: inherit;
    }

    button.secondary {
      background: #e8eff6;
      color: #12324a;
    }

    .button--small {
      padding: 8px 12px;
    }

    button.danger {
      background: #fde8e7;
      color: #8c2222;
    }

    button:disabled {
      opacity: 0.65;
      cursor: default;
    }

    .hint {
      color: #617182;
      font-size: 0.95rem;
    }

    .error {
      color: #b42318;
      margin-top: 4px;
    }

    .notice {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid #e6d4a8;
      background: #fff7e8;
      color: #7f5600;
      flex-wrap: wrap;
    }

    .notice--warning {
      border-color: #e6d4a8;
      background: #fff7e8;
    }

    .notice__content {
      display: grid;
      gap: 4px;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .empty {
      border: 1px dashed #ccd7e2;
      border-radius: 16px;
      padding: 20px;
      color: #617182;
      background: #f8fbfd;
    }

    .run-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }

    .run-card {
      padding: 18px;
      background: linear-gradient(180deg, #ffffff, #fbfdff);
      display: grid;
      gap: 14px;
    }

    .run-card h3 {
      margin: 0;
      font-size: 1rem;
      word-break: break-word;
      color: #12324a;
    }

    .run-card__meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: #617182;
      font-size: 0.9rem;
      align-items: center;
    }

    .run-card__group {
      display: grid;
      gap: 4px;
    }

    .run-card__label {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #6d7f90;
      font-weight: 700;
    }

    .run-card__queries,
    .run-card__entities {
      margin: 0;
      color: #344554;
      line-height: 1.45;
    }

    .badge {
      padding: 4px 9px;
      border-radius: 999px;
      background: #edf4fa;
      color: #12324a;
      font-weight: 700;
      font-size: 0.82rem;
    }

    .badge--muted {
      background: #edf0f4;
      color: #617182;
    }

    .status {
      display: inline-flex;
      align-items: center;
      padding: 3px 8px;
      border-radius: 999px;
      font-weight: 700;
      text-transform: capitalize;
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

    .status--partial {
      background: #fdecc8;
      color: #8a5b00;
    }

    .status--failed {
      background: #fde2e1;
      color: #9f1c1c;
    }

    @media (max-width: 1220px) {
      .layout {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 900px) {
      .model-table__head {
        display: none;
      }

      .model-row {
        grid-template-columns: auto 1fr;
      }

      .model-row__metric {
        grid-column: 2;
      }
    }

    @media (max-width: 720px) {
      .form__row {
        grid-template-columns: 1fr;
      }

      .model-toolbar {
        grid-template-columns: 1fr;
      }

      .model-results__header,
      .selection-summary,
      .selection-summary__stats,
      .model-pagination {
        align-items: start;
      }
    }
  `]
})
export class RunListPageComponent implements OnInit {
  private readonly runsApi = inject(RunsApiService);
  private readonly router = inject(Router);
  private readonly enrichmentProviderCatalog = [
    {
      id: 'openalex',
      label: 'OpenAlex',
      description: 'Open citation graph metadata and identifier enrichment.',
    },
    {
      id: 'semantic_scholar',
      label: 'Semantic Scholar',
      description: 'Paper metadata, authorship, and citation enrichment.',
    },
    {
      id: 'scopus',
      label: 'Scopus',
      description: 'Commercial bibliographic metadata and citation coverage.',
    },
    {
      id: 'core',
      label: 'CORE',
      description: 'Aggregator coverage for open-access repository metadata.',
    },
  ] as const;

  protected readonly createRunForm = new FormGroup({
    runType: new FormControl<RunType>('scholarly', { nonNullable: true }),
    topK: new FormControl(10, {
      nonNullable: true,
      validators: [Validators.min(1), Validators.max(100)]
    })
  });

  protected readonly maxSelectedModels = 10;
  protected readonly modelPageSizeOptions = [10, 25, 50, 100];
  protected options: RunOptionsResponse | null = null;
  protected openRouterModelsResponse: OpenRouterModelsResponse | null = null;
  protected runs: RunDetail[] = [];
  protected queryRows = [
    'liquid biopsy cancer detection review',
    'systematic review of machine learning in radiology',
  ];
  protected bulkQueryText = '';
  protected modelSearchText = '';
  protected modelModalityFilter = 'all';
  protected modelMinContextLength: number | null = null;
  protected modelSort = 'name';
  protected modelCurrentPage = 1;
  protected modelPageSize = 10;
  protected selectedSources = new Set<string>();
  protected selectedModels = new Set<string>();
  protected staleSelectedModelIds: string[] = [];
  protected deletingRunIds = new Set<string>();
  protected loadingOptions = false;
  protected loadingModels = false;
  protected loadingRuns = false;
  protected submitting = false;
  protected optionsError = '';
  protected modelsError = '';
  protected loadError = '';
  protected submitError = '';

  ngOnInit(): void {
    this.loadOptions();
    this.loadOpenRouterModels();
    this.loadRuns();
  }

  protected loadOptions(): void {
    this.loadingOptions = true;
    this.optionsError = '';

    this.runsApi.getOptions().subscribe({
      next: (options) => {
        this.options = options;
        this.createRunForm.controls.runType.setValue(options.default_run_type);
        this.selectedSources = this.defaultSourceSelection(options);
        this.loadingOptions = false;
      },
      error: (error: unknown) => {
        this.optionsError = this.formatError(error, 'Failed to load experiment options.');
        this.loadingOptions = false;
      }
    });
  }

  protected loadOpenRouterModels(): void {
    this.loadingModels = true;
    this.modelsError = '';

    this.runsApi.getOpenRouterModels().subscribe({
      next: (response) => {
        this.openRouterModelsResponse = response;
        const currentSelections = Array.from(this.selectedModels);
        const allowedIds = new Set(response.models.map((model) => model.id));
        this.staleSelectedModelIds = currentSelections.filter((modelId) => !allowedIds.has(modelId));
        this.selectedModels = new Set(
          currentSelections.filter((modelId) => allowedIds.has(modelId)),
        );
        this.modelCurrentPage = 1;
        this.loadingModels = false;
      },
      error: (error: unknown) => {
        this.modelsError = this.formatError(error, 'Failed to load OpenRouter models.');
        this.loadingModels = false;
      }
    });
  }

  protected loadRuns(): void {
    this.loadingRuns = true;
    this.loadError = '';

    this.runsApi.listRuns().subscribe({
      next: (runs) => {
        this.runs = runs;
        this.loadingRuns = false;
      },
      error: (error: unknown) => {
        this.loadError = this.formatError(error, 'Failed to load runs.');
        this.loadingRuns = false;
      }
    });
  }

  protected createRun(): void {
    const queries = this.normalizedQueries();
    if (!queries.length) {
      this.submitError = 'Enter at least one query.';
      return;
    }

    const runType = this.createRunForm.controls.runType.value;
    if (runType === 'scholarly' && this.selectedSources.size === 0) {
      this.submitError = 'Select at least one collection source.';
      return;
    }
    if (runType === 'llm_audit') {
      if (this.selectedModels.size === 0) {
        this.submitError = 'Select at least one OpenRouter model.';
        return;
      }
      if (this.selectedModels.size > this.maxSelectedModels) {
        this.submitError = `Select at most ${this.maxSelectedModels} OpenRouter models.`;
        return;
      }
    }
    const payload: CreateRunRequest = {
      run_type: runType,
      sources: runType === 'scholarly' ? Array.from(this.selectedSources) : [],
      selected_models: runType === 'llm_audit' ? Array.from(this.selectedModels) : [],
      top_k: this.createRunForm.controls.topK.value,
      queries,
    };

    this.submitting = true;
    this.submitError = '';

    this.runsApi.createRun(payload).subscribe({
      next: (detail) => {
        this.submitting = false;
        void this.router.navigate(['/runs', detail.run.id, 'report']);
      },
      error: (error: unknown) => {
        this.submitError = this.formatError(error, 'Failed to create experiment.');
        this.submitting = false;
      }
    });
  }

  protected deleteRun(item: RunDetail): void {
    const confirmed = window.confirm(
      `Delete experiment ${item.run.id}? This removes the experiment record, results, and saved artifacts.`,
    );
    if (!confirmed) {
      return;
    }

    this.deletingRunIds.add(item.run.id);
    this.loadError = '';

    this.runsApi.deleteRun(item.run.id).subscribe({
      next: () => {
        this.deletingRunIds.delete(item.run.id);
        this.runs = this.runs.filter((candidate) => candidate.run.id !== item.run.id);
      },
      error: (error: unknown) => {
        this.deletingRunIds.delete(item.run.id);
        this.loadError = this.formatError(error, 'Failed to delete experiment.');
      }
    });
  }

  protected isDeleting(runId: string): boolean {
    return this.deletingRunIds.has(runId);
  }

  protected addQueryRow(): void {
    this.queryRows = [...this.queryRows, ''];
  }

  protected removeQueryRow(index: number): void {
    if (this.queryRows.length === 1) {
      this.queryRows = [''];
      return;
    }
    this.queryRows = this.queryRows.filter((_, candidateIndex) => candidateIndex !== index);
  }

  protected updateQueryRow(index: number, event: Event): void {
    const nextValue = this.textAreaValue(event);
    this.queryRows = this.queryRows.map((query, candidateIndex) =>
      candidateIndex === index ? nextValue : query,
    );
  }

  protected applyBulkQueries(): void {
    const queries = this.parseLines(this.bulkQueryText);
    if (!queries.length) {
      return;
    }
    this.queryRows = queries;
    this.bulkQueryText = '';
  }

  protected toggleSource(source: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    if (checked) {
      this.selectedSources.add(source);
      return;
    }
    this.selectedSources.delete(source);
  }

  protected toggleModel(model: string, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    if (checked) {
      if (this.selectionLimitReached() && !this.selectedModels.has(model)) {
        return;
      }
      this.selectedModels.add(model);
      return;
    }
    this.selectedModels.delete(model);
  }

  protected collectionSources(): CollectionSourceCard[] {
    return (this.options?.source_catalog ?? []).map((source: ScholarlySourceOption) => ({
      id: source.id,
      label: source.display_name,
      description: source.description || 'Scholarly source',
      selectable: source.selectable,
      note: source.selectable
        ? 'Runs as a real collection source in the scholarly pipeline.'
        : (source.validation_reason || 'Not currently selectable'),
    }));
  }

  protected enrichmentProviders(): ProviderCard[] {
    const enabled = new Set(this.options?.enabled_enrichment_providers ?? []);
    const order = this.options?.enrichment_provider_order ?? [];

    return this.enrichmentProviderCatalog.map((provider) => {
      const orderIndex = order.indexOf(provider.id);
      return {
        ...provider,
        enabled: enabled.has(provider.id),
        note: enabled.has(provider.id)
          ? `Enabled${orderIndex >= 0 ? ` · provider order ${orderIndex + 1}` : ''}`
          : 'Disabled in the current backend configuration',
      };
    });
  }

  protected enabledEnrichmentProviderLabels(): string[] {
    const enabled = new Set(this.options?.enabled_enrichment_providers ?? []);
    return (this.options?.enrichment_provider_order ?? [])
      .filter((provider) => enabled.has(provider))
      .map((provider) => this.providerLabel(provider));
  }

  protected sourceLabels(values: string[]): string[] {
    return values.map((value) => this.sourceLabel(value));
  }

  protected visibleModels(): OpenRouterModelSummary[] {
    const models = [...(this.openRouterModelsResponse?.models ?? [])];
    const search = this.modelSearchText.trim().toLowerCase();
    const minimumContext = this.modelMinContextLength;

    const filtered = models.filter((model) => {
      const matchesSearch = !search || [model.name, model.id, model.description || '']
        .some((value) => value.toLowerCase().includes(search));
      const matchesModality = this.matchesModelModality(model, this.modelModalityFilter);
      const matchesContext = minimumContext === null
        || (model.context_length !== null && model.context_length >= minimumContext);
      return matchesSearch && matchesModality && matchesContext;
    });

    filtered.sort((left, right) => this.compareModels(left, right));
    return filtered;
  }

  protected paginatedModels(): OpenRouterModelSummary[] {
    const filtered = this.visibleModels();
    const summary = this.paginationSummary();
    if (!filtered.length) {
      return [];
    }
    const startIndex = summary.start - 1;
    return filtered.slice(startIndex, summary.end);
  }

  protected totalModelCount(): number {
    return this.openRouterModelsResponse?.models.length ?? 0;
  }

  protected filteredModelCount(): number {
    return this.visibleModels().length;
  }

  protected paginationSummary(): ModelPaginationSummary {
    const total = this.filteredModelCount();
    const totalPages = Math.max(1, Math.ceil(total / this.modelPageSize));
    const currentPage = Math.min(this.modelCurrentPage, totalPages);
    const start = total === 0 ? 0 : ((currentPage - 1) * this.modelPageSize) + 1;
    const end = total === 0 ? 0 : Math.min(start + this.modelPageSize - 1, total);
    return { start, end, totalPages };
  }

  protected selectionLimitReached(): boolean {
    return this.selectedModels.size >= this.maxSelectedModels;
  }

  protected clearSelectedModels(): void {
    this.selectedModels = new Set<string>();
  }

  protected dismissStaleModelNotice(): void {
    this.staleSelectedModelIds = [];
  }

  protected modelSelectionError(): string {
    if (!this.isLlmAuditMode() || this.loadingModels || this.modelsError) {
      return '';
    }
    if (this.selectedModels.size === 0) {
      return 'Select at least one OpenRouter model for llm_audit runs.';
    }
    if (this.selectedModels.size > this.maxSelectedModels) {
      return `Select at most ${this.maxSelectedModels} OpenRouter models.`;
    }
    return '';
  }

  protected textAreaValue(event: Event): string {
    return (event.target as HTMLTextAreaElement).value;
  }

  protected inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  protected selectValue(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  protected updateModelSearch(event: Event): void {
    this.modelSearchText = this.inputValue(event);
    this.resetModelPagination();
  }

  protected updateModelModalityFilter(event: Event): void {
    this.modelModalityFilter = this.selectValue(event);
    this.resetModelPagination();
  }

  protected updateModelSort(event: Event): void {
    this.modelSort = this.selectValue(event);
    this.resetModelPagination();
  }

  protected updateModelMinContext(event: Event): void {
    const rawValue = this.inputValue(event).trim();
    const parsed = rawValue ? Number(rawValue) : null;
    this.modelMinContextLength = parsed !== null && !Number.isNaN(parsed) ? parsed : null;
    this.resetModelPagination();
  }

  protected updateModelPageSize(event: Event): void {
    this.modelPageSize = Number(this.selectValue(event)) || 25;
    this.resetModelPagination();
  }

  protected goToPreviousModelPage(): void {
    this.modelCurrentPage = Math.max(1, this.modelCurrentPage - 1);
  }

  protected goToNextModelPage(): void {
    this.modelCurrentPage = Math.min(this.paginationSummary().totalPages, this.modelCurrentPage + 1);
  }

  protected isScholarlyMode(): boolean {
    return this.createRunForm.controls.runType.value === 'scholarly';
  }

  protected isLlmAuditMode(): boolean {
    return this.createRunForm.controls.runType.value === 'llm_audit';
  }

  protected previewQueries(item: RunDetail): string {
    return item.queries.map((query) => query.text).join(' | ');
  }

  protected formatContextLength(value: number | null): string {
    if (value === null || Number.isNaN(value)) {
      return 'unknown';
    }
    return value.toLocaleString();
  }

  protected formatPrice(value: number | null): string {
    if (value === null || Number.isNaN(value)) {
      return 'n/a';
    }
    return value.toFixed(value > 0 && value < 0.001 ? 6 : 4);
  }

  protected formatModalities(model: OpenRouterModelSummary): string {
    const values = Array.from(new Set([
      ...model.input_modalities,
      ...model.output_modalities,
    ]));
    return values.length ? values.join(', ') : (model.modality || 'unknown');
  }

  protected runTypeLabel(value: RunType): string {
    return value === 'llm_audit' ? 'LLM Audit' : 'Scholarly';
  }

  private resetModelPagination(): void {
    this.modelCurrentPage = 1;
  }

  private normalizedQueries(): string[] {
    return this.queryRows
      .map((item) => item.trim())
      .filter(Boolean);
  }

  private parseLines(value: string): string[] {
    return value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  private sourceLabel(source: string): string {
    const match = this.options?.source_catalog.find((item) => item.id === source);
    return match?.display_name ?? this.providerLabel(source);
  }

  private matchesModelModality(model: OpenRouterModelSummary, filterValue: string): boolean {
    if (!filterValue || filterValue === 'all') {
      return true;
    }

    const modalities = new Set([...model.input_modalities, ...model.output_modalities]);
    const textOnly = modalities.size > 0 && Array.from(modalities).every((value) => value === 'text');

    if (filterValue === 'text') {
      return textOnly;
    }
    if (filterValue === 'vision' || filterValue === 'image') {
      return modalities.has('image');
    }
    if (filterValue === 'audio') {
      return modalities.has('audio');
    }
    if (filterValue === 'multimodal') {
      return modalities.size > 1;
    }
    return model.modality === filterValue;
  }

  private compareModels(left: OpenRouterModelSummary, right: OpenRouterModelSummary): number {
    if (this.modelSort === 'context_length') {
      return (right.context_length ?? -1) - (left.context_length ?? -1)
        || left.name.localeCompare(right.name);
    }
    if (this.modelSort === 'prompt_price') {
      return (left.prompt_price ?? Number.POSITIVE_INFINITY) - (right.prompt_price ?? Number.POSITIVE_INFINITY)
        || left.name.localeCompare(right.name);
    }
    if (this.modelSort === 'completion_price') {
      return (left.completion_price ?? Number.POSITIVE_INFINITY) - (right.completion_price ?? Number.POSITIVE_INFINITY)
        || left.name.localeCompare(right.name);
    }
    return left.name.localeCompare(right.name) || left.id.localeCompare(right.id);
  }

  private defaultSourceSelection(options: RunOptionsResponse): Set<string> {
    const openalex = options.source_catalog.find((source) => source.id === 'openalex' && source.selectable);
    if (openalex) {
      return new Set([openalex.id]);
    }
    const firstSelectable = options.source_catalog.find((source) => source.selectable);
    return new Set(firstSelectable ? [firstSelectable.id] : []);
  }

  private providerLabel(provider: string): string {
    const match = this.enrichmentProviderCatalog.find((item) => item.id === provider);
    return match?.label ?? provider.replace(/_/g, ' ');
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
