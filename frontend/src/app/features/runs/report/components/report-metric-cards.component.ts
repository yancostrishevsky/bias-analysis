import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { ReportMetricCard } from '../run-report.models';

@Component({
  selector: 'app-report-metric-cards',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="metric-grid" *ngIf="cards.length">
      <article class="metric-card" *ngFor="let card of cards">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small *ngIf="card.note">{{ card.note }}</small>
      </article>
    </div>
  `,
  styles: [`
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
      gap: 12px;
    }

    .metric-card {
      border: 1px solid #dce5ed;
      border-radius: 14px;
      padding: 14px;
      background: #fbfdff;
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .metric-card span,
    .metric-card small {
      color: #617182;
    }

    .metric-card strong {
      color: #12324a;
      font-size: 1.1rem;
    }
  `]
})
export class ReportMetricCardsComponent {
  @Input({ required: true }) cards: ReportMetricCard[] = [];
}
