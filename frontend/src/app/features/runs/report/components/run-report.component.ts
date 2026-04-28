import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { RunAnalysis, RunDetail, UnifiedRecordRow } from '../../models/run.models';
import { EnrichmentRow, RunReportView } from '../run-report.models';
import { buildRunReportView } from '../run-report.builders';
import { ReportSectionComponent } from './report-section.component';

@Component({
  selector: 'app-run-report',
  standalone: true,
  imports: [CommonModule, ReportSectionComponent],
  template: `
    <ng-container *ngIf="reportView as report">
      <app-report-section *ngFor="let section of report.sharedSections" [section]="section"></app-report-section>

      <section class="panel panel--muted" *ngIf="report.llmSections.length">
        <div class="panel__header">
          <div>
            <p class="eyebrow">LLM Audit</p>
            <h2>LLM-Only Panels</h2>
            <p>Sections that only render for llm_audit runs, while preserving the shared report structure above.</p>
          </div>
        </div>

        <div class="section-stack">
          <app-report-section *ngFor="let section of report.llmSections" [section]="section"></app-report-section>
        </div>
      </section>

      <section class="panel panel--muted" *ngIf="report.omittedSections.length">
        <div class="panel__header">
          <div>
            <p class="eyebrow">Intentionally Omitted</p>
            <h2>Removed From Migration</h2>
            <p>Legacy panels that are explicitly not carried into the new UI.</p>
          </div>
        </div>

        <ul class="omitted-list">
          <li *ngFor="let item of report.omittedSections">{{ item }}</li>
        </ul>
      </section>
    </ng-container>
  `,
  styles: [`
    :host {
      display: grid;
      gap: 24px;
      min-width: 0;
    }

    .panel {
      border: 1px solid #d7e1ea;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.95);
      padding: 20px;
      box-shadow: 0 12px 30px rgba(15, 35, 55, 0.05);
      display: grid;
      gap: 16px;
      min-width: 0;
    }

    .panel__header,
    .panel__header > div,
    .section-stack {
      min-width: 0;
    }

    .panel--muted {
      background: linear-gradient(180deg, rgba(251, 253, 255, 0.98), rgba(246, 249, 252, 0.96));
    }

    .panel__header h2,
    .panel__header p {
      margin: 0;
    }

    .eyebrow {
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.74rem;
      color: #56748d;
      font-weight: 700;
    }

    .section-stack {
      display: grid;
      gap: 20px;
    }

    .omitted-list {
      margin: 0;
      padding-left: 18px;
      color: #556270;
    }
  `]
})
export class RunReportComponent {
  @Input({ required: true }) detail!: RunDetail;
  @Input({ required: true }) analysis!: RunAnalysis;
  @Input({ required: true }) enrichmentRows: EnrichmentRow[] = [];
  @Input() recordsRows: UnifiedRecordRow[] = [];
  @Input() selectedQueryId = '';
  @Input() selectedEntity = '';
  @Input() selectedTopK = 10;

  protected get reportView(): RunReportView {
    return buildRunReportView({
      detail: this.detail,
      analysis: this.analysis,
      enrichmentRows: this.enrichmentRows,
      recordsRows: this.recordsRows,
      selectedQueryId: this.selectedQueryId,
      selectedEntity: this.selectedEntity,
      selectedTopK: this.selectedTopK
    });
  }
}
