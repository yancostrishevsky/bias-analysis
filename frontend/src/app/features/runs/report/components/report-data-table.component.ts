import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { ReportTable } from '../run-report.models';

@Component({
  selector: 'app-report-data-table',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="table-section" *ngIf="table">
      <div class="section-header">
        <h3>{{ table.title }}</h3>
      </div>

      <div class="table-wrap" *ngIf="table.rows.length; else emptyState">
        <table>
          <thead>
            <tr>
              <th *ngFor="let column of table.columns" [class.th-end]="column.align === 'end'">
                {{ column.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let row of table.rows">
              <td *ngFor="let column of table.columns" [class.td-end]="column.align === 'end'">
                {{ row.values[column.key] || '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <ng-template #emptyState>
        <div class="empty">{{ table.emptyMessage || 'No rows are available for this table.' }}</div>
      </ng-template>
    </section>
  `,
  styles: [`
    :host {
      display: block;
      min-width: 0;
    }

    .table-section {
      display: grid;
      gap: 12px;
      min-width: 0;
    }

    .section-header h3 {
      margin: 0;
    }

    .table-wrap {
      overflow-x: auto;
      max-width: 100%;
      min-width: 0;
      overscroll-behavior-x: contain;
      border: 1px solid #e2eaf1;
      border-radius: 16px;
      background: #ffffff;
    }

    table {
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
    }

    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid #e4ebf2;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }

    th {
      color: #617182;
      font-size: 0.92rem;
      background: #f8fbfd;
    }

    .th-end,
    .td-end {
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
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
export class ReportDataTableComponent {
  @Input({ required: true }) table!: ReportTable;
}
