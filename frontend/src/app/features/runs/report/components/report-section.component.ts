import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { ReportSection } from '../run-report.models';
import { ReportDataTableComponent } from './report-data-table.component';
import { ReportHeatmapComponent } from './report-heatmap.component';
import { ReportMetricCardsComponent } from './report-metric-cards.component';

@Component({
  selector: 'app-report-section',
  standalone: true,
  imports: [CommonModule, ReportMetricCardsComponent, ReportHeatmapComponent, ReportDataTableComponent],
  template: `
    <section class="panel">
      <div class="panel__header">
        <div>
          <p class="eyebrow">{{ section.eyebrow }}</p>
          <h2>{{ section.title }}</h2>
          <p>{{ section.description }}</p>
        </div>
      </div>

      <div class="state state--warning" *ngIf="section.status !== 'available'">
        {{ section.reason || 'This panel is currently unavailable.' }}
      </div>

      <ng-container *ngIf="section.status === 'available'">
        <app-report-metric-cards *ngIf="section.cards?.length" [cards]="section.cards || []"></app-report-metric-cards>

        <div class="series-grid" *ngIf="section.series?.length">
          <article class="series-card" *ngFor="let series of section.series">
            <div class="series-card__header">
              <h3>{{ series.title }}</h3>
              <p *ngIf="series.description">{{ series.description }}</p>
            </div>
            <div class="bar-list" *ngIf="series.items.length; else emptySeries">
              <div class="bar-row" *ngFor="let item of series.items">
                <div class="bar-row__label">
                  <strong>{{ item.label }}</strong>
                  <span>{{ item.valueLabel }}</span>
                </div>
                <div class="bar-row__track">
                  <div class="bar-row__fill" [style.width.%]="(item.value || 0) * 100"></div>
                </div>
              </div>
            </div>
          </article>
        </div>

        <div class="content-stack" *ngIf="section.heatmaps?.length">
          <app-report-heatmap *ngFor="let heatmap of section.heatmaps" [heatmap]="heatmap"></app-report-heatmap>
        </div>

        <div class="content-stack" *ngIf="section.tables?.length">
          <app-report-data-table *ngFor="let table of section.tables" [table]="table"></app-report-data-table>
        </div>

        <ul class="notes" *ngIf="section.notes?.length">
          <li *ngFor="let note of section.notes">{{ note }}</li>
        </ul>
      </ng-container>

      <ng-template #emptySeries>
        <div class="state">No items are available for this chart.</div>
      </ng-template>
    </section>
  `,
  styles: [`
    :host {
      display: block;
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

    .panel__header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      min-width: 0;
    }

    .panel__header > div,
    .series-grid,
    .series-card,
    .series-card__header,
    .bar-list,
    .bar-row,
    .bar-row__label,
    .content-stack,
    .notes {
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

    h2,
    h3,
    p {
      margin: 0;
    }

    p {
      color: #556270;
    }

    .series-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
      gap: 14px;
    }

    .series-card {
      border: 1px solid #dce5ed;
      border-radius: 16px;
      background: #fbfdff;
      padding: 14px;
      display: grid;
      gap: 12px;
      overflow: hidden;
    }

    .series-card__header {
      display: grid;
      gap: 4px;
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

    .content-stack,
    .notes {
      display: grid;
      gap: 16px;
    }

    .notes {
      margin: 0;
      padding-left: 18px;
      color: #556270;
    }

    .state {
      border: 1px dashed #ccd7e2;
      border-radius: 14px;
      padding: 16px;
      background: #f8fbfd;
      color: #617182;
    }

    .state--warning {
      background: #fff3db;
      border-style: solid;
      border-color: #ecd7aa;
      color: #8a5b00;
    }
  `]
})
export class ReportSectionComponent {
  @Input({ required: true }) section!: ReportSection;
}
