import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { ReportHeatmap } from '../run-report.models';

@Component({
  selector: 'app-report-heatmap',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="heatmap" *ngIf="heatmap">
      <div class="section-header">
        <h3>{{ heatmap.title }}</h3>
        <p *ngIf="heatmap.description">{{ heatmap.description }}</p>
      </div>

      <div class="heatmap-grid-wrap" *ngIf="rowLabels.length && columnLabels.length; else emptyState">
        <div class="heatmap-grid"
          [style.gridTemplateColumns]="'minmax(130px, 1.2fr) repeat(' + columnLabels.length + ', minmax(92px, 1fr))'">
          <div class="axis-cell axis-cell--corner"></div>
          <div class="axis-cell axis-cell--column" *ngFor="let column of columnLabels">{{ column }}</div>

          <ng-container *ngFor="let row of rowLabels">
            <div class="axis-cell axis-cell--row">{{ row }}</div>
            <div class="value-cell"
              *ngFor="let column of columnLabels"
              [style.background]="backgroundFor(cellValue(row, column))">
              <span>{{ cellLabel(row, column) }}</span>
            </div>
          </ng-container>
        </div>
      </div>

      <ng-template #emptyState>
        <div class="empty">No heatmap cells are available for this panel.</div>
      </ng-template>
    </section>
  `,
  styles: [`
    :host {
      display: block;
      min-width: 0;
    }

    .heatmap {
      display: grid;
      gap: 12px;
      min-width: 0;
    }

    .section-header {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .section-header h3,
    .section-header p {
      margin: 0;
    }

    .section-header p {
      color: #617182;
    }

    .heatmap-grid-wrap {
      overflow-x: auto;
      max-width: 100%;
      min-width: 0;
      overscroll-behavior-x: contain;
    }

    .heatmap-grid {
      display: grid;
      gap: 6px;
      align-items: stretch;
      min-width: max-content;
    }

    .axis-cell,
    .value-cell {
      border-radius: 12px;
      padding: 10px;
      min-height: 54px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      font-size: 0.88rem;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .axis-cell {
      background: #f3f7fb;
      color: #344554;
      font-weight: 700;
    }

    .axis-cell--row {
      justify-content: flex-start;
      text-align: left;
    }

    .value-cell {
      color: #12324a;
      border: 1px solid rgba(18, 50, 74, 0.05);
    }

    .empty {
      border: 1px dashed #ccd7e2;
      border-radius: 14px;
      padding: 16px;
      background: #f8fbfd;
      color: #617182;
    }
  `]
})
export class ReportHeatmapComponent {
  @Input({ required: true }) heatmap!: ReportHeatmap;

  protected get rowLabels(): string[] {
    return Array.from(new Set(this.heatmap.cells.map((cell) => cell.rowLabel)));
  }

  protected get columnLabels(): string[] {
    return Array.from(new Set(this.heatmap.cells.map((cell) => cell.columnLabel)));
  }

  protected cellValue(rowLabel: string, columnLabel: string): number | null {
    return this.heatmap.cells.find((cell) => cell.rowLabel === rowLabel && cell.columnLabel === columnLabel)?.value ?? null;
  }

  protected cellLabel(rowLabel: string, columnLabel: string): string {
    return this.heatmap.cells.find((cell) => cell.rowLabel === rowLabel && cell.columnLabel === columnLabel)?.valueLabel ?? '—';
  }

  protected backgroundFor(value: number | null): string {
    if (value === null) {
      return '#f8fbfd';
    }
    const clamped = Math.max(0, Math.min(1, Math.abs(value)));
    const alpha = 0.12 + clamped * 0.48;
    return value < 0
      ? `rgba(160, 69, 33, ${alpha})`
      : `rgba(43, 110, 138, ${alpha})`;
  }
}
