import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="shell">
      <header class="shell__header">
        <div>
          <h1>Bias Analysis</h1>
          <p>Interactive scholarly retrieval and OpenRouter model audit workspace with persisted SQLite runs.</p>
        </div>
        <nav class="shell__nav">
          <a routerLink="/runs" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">
            Runs
          </a>
          <a routerLink="/docs" routerLinkActive="active">
            Docs
          </a>
        </nav>
      </header>

      <main class="shell__content">
        <router-outlet />
      </main>
    </div>
  `,
  styles: [`
    .shell {
      max-width: 1480px;
      margin: 0 auto;
      padding: clamp(16px, 2vw, 28px);
    }

    .shell__header {
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      margin-bottom: 24px;
      padding: 24px;
      border: 1px solid #d7e1ea;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(8px);
    }

    .shell__header h1 {
      margin: 0 0 8px;
      font-size: 2rem;
    }

    .shell__header p {
      margin: 0;
      color: #556270;
    }

    .shell__nav {
      display: flex;
      gap: 12px;
    }

    .shell__nav a {
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      background: #eef4fb;
      color: #12324a;
      font-weight: 600;
    }

    .shell__nav a.active {
      background: #12324a;
      color: #ffffff;
    }

    .shell__content {
      display: block;
    }

    @media (max-width: 800px) {
      .shell {
        padding: 16px;
      }

      .shell__header {
        flex-direction: column;
      }
    }
  `]
})
export class AppComponent {}
