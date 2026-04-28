import { Routes } from '@angular/router';

import { DocsPageComponent } from './features/docs/pages/docs-page.component';
import { RunDetailPageComponent } from './features/runs/pages/run-detail-page.component';
import { RunListPageComponent } from './features/runs/pages/run-list-page.component';
import { RunRecordsPageComponent } from './features/runs/pages/run-records-page.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'runs' },
  { path: 'docs', component: DocsPageComponent },
  { path: 'runs', component: RunListPageComponent },
  { path: 'runs/:id', pathMatch: 'full', redirectTo: 'runs/:id/report' },
  { path: 'runs/:id/report', component: RunDetailPageComponent },
  { path: 'runs/:id/records', component: RunRecordsPageComponent }
];
