import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

interface DocNavItem {
  id: string;
  label: string;
}

interface DocCallout {
  tone: 'important' | 'tip' | 'limitation';
  title: string;
  body: string;
}

interface DocMetricSection {
  title: string;
  scope: string;
  measures: string;
  reveals: string;
  interpretation: string;
  gating: string;
}

interface DocFaqItem {
  question: string;
  answer: string;
}

@Component({
  selector: 'app-docs-page',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="docs-layout">
      <aside class="toc panel">
        <p class="eyebrow">Documentation</p>
        <h2>On This Page</h2>
        <p class="toc__intro">This guide reflects the currently implemented run, report, and records workflow in the app.</p>
        <nav class="toc__nav">
          <a *ngFor="let item of navItems" [href]="'#' + item.id">{{ item.label }}</a>
        </nav>
      </aside>

      <div class="docs-page">
        <section class="panel hero" id="overview">
          <div class="hero__header">
            <div>
              <p class="eyebrow">Research Guide</p>
              <h1>Using Bias Analysis as a Research Tool</h1>
              <p class="hero__lede">
                Bias Analysis supports structured retrieval experiments, LLM audit runs, bibliographic enrichment,
                bias analysis, row-level inspection, and export-ready datasets. The app is designed to help you compare
                scholarly retrieval systems and LLM-based retrieval with traceable evidence instead of only pooled summaries.
              </p>
            </div>
            <div class="hero__actions">
              <a class="nav-button" routerLink="/runs">Open Runs</a>
              <a class="nav-button secondary" href="#workflow">Suggested Workflow</a>
            </div>
          </div>

          <div class="quick-links">
            <article class="quick-link-card">
              <p class="eyebrow eyebrow--compact">Create</p>
              <h3>Create a Run</h3>
              <p>Choose <code>scholarly</code> or <code>llm_audit</code>, select sources or models, define queries, and start the experiment.</p>
            </article>
            <article class="quick-link-card">
              <p class="eyebrow eyebrow--compact">Interpret</p>
              <h3>Read the Report</h3>
              <p>Use grouped metrics to compare models, platforms, and queries instead of relying only on one pooled aggregate.</p>
            </article>
            <article class="quick-link-card">
              <p class="eyebrow eyebrow--compact">Inspect</p>
              <h3>Inspect Records</h3>
              <p>Move from charts to row-level evidence in the Records Explorer, then inspect raw, enriched, and verification fields.</p>
            </article>
            <article class="quick-link-card">
              <p class="eyebrow eyebrow--compact">Reuse</p>
              <h3>Export Data</h3>
              <p>Download filtered datasets in <code>CSV</code>, <code>JSON</code>, or <code>JSONL</code> for downstream analysis, annotation, or thesis figures.</p>
            </article>
          </div>

          <div class="callout-grid">
            <article class="callout" *ngFor="let callout of overviewCallouts" [class]="'callout callout--' + callout.tone">
              <strong>{{ callout.title }}</strong>
              <p>{{ callout.body }}</p>
            </article>
          </div>
        </section>

        <section class="panel" id="quick-start">
          <div class="section-heading">
            <p class="eyebrow">Quick Start</p>
            <h2>Simple Path Through the Tool</h2>
            <p>Use this sequence for a first pass through the product.</p>
          </div>
          <ol class="step-list">
            <li *ngFor="let step of quickStartSteps">{{ step }}</li>
          </ol>
        </section>

        <section class="panel" id="run-types">
          <div class="section-heading">
            <p class="eyebrow">Run Types</p>
            <h2>Scholarly vs LLM Audit</h2>
            <p>The app supports two run modes that share the same reporting structure where possible.</p>
          </div>
          <div class="two-column-grid">
            <article class="info-card">
              <h3>Scholarly</h3>
              <p>Scholarly runs query selected scholarly sources such as OpenAlex, Semantic Scholar, Scopus, and CORE, then enrich and analyze the returned records.</p>
              <ul class="plain-list">
                <li>Best for comparing retrieval platforms and source-specific bias.</li>
                <li>Shared report sections focus on coverage, overlap, language, publisher, geo, OA, recency, citation, source type, and diversity.</li>
                <li>LLM-only diagnostics do not render in this mode.</li>
              </ul>
            </article>
            <article class="info-card">
              <h3>LLM Audit</h3>
              <p>LLM audit runs ask multiple selected OpenRouter models to return literature, then parse, enrich, verify, and compare those outputs.</p>
              <ul class="plain-list">
                <li>Best for cross-model comparison, bibliographic quality assessment, and verifiability analysis.</li>
                <li>Includes all shared report sections plus LLM-only panels such as Parse Robustness, Cross-Model Divergence, Stability, and Verifiability / Hallucination Risk.</li>
                <li>Supports artifact replay without calling the LLM provider again when replayable outputs exist.</li>
              </ul>
            </article>
          </div>
        </section>

        <section class="panel" id="report-page">
          <div class="section-heading">
            <p class="eyebrow">Report</p>
            <h2>What the Report Page Is For</h2>
            <p>
              The report page is the interpretation surface. It is meant for comparison, pattern detection, and
              identifying potential bias or quality issues across runs, models, platforms, and queries.
            </p>
          </div>
          <div class="content-stack">
            <p>
              The report is not limited to one overall summary. Many sections are designed to support per-model or
              per-platform comparison, per-query diagnostics, and selected top-k interpretation. When a metric depends
              on enough coverage, enrichment, or repeated calls, the panel will show an unavailable or insufficient
              coverage state instead of rendering a misleading chart.
            </p>
            <p>
              Shared sections render for both <code>scholarly</code> and <code>llm_audit</code> runs when the underlying data exists. LLM-only
              sections render only for <code>llm_audit</code>. Use the report to identify suspicious patterns first, then move into
              the Records Explorer to inspect the underlying rows.
            </p>
          </div>
        </section>

        <section class="panel" id="records-explorer">
          <div class="section-heading">
            <p class="eyebrow">Records Explorer</p>
            <h2>Why Records Live Separately</h2>
            <p>
              Row-level inspection and export are separated from the report on purpose. The report is for interpretation;
              the Records Explorer is for inspection, filtering, and evidence tracing.
            </p>
          </div>

          <div class="two-column-grid">
            <article class="info-card">
              <h3>Current Views and Presets</h3>
              <ul class="plain-list">
                <li><strong>Raw:</strong> titles, DOI, year, journal, authors, rationale, model or platform, query, and rank as originally returned.</li>
                <li><strong>Enriched:</strong> resolved bibliographic metadata such as language, country, publisher, OA status, source type, topic, and citations.</li>
                <li><strong>Verification:</strong> matching outcomes, DOI validity, conflicts, unmatched reasons, and hallucination risk bucket.</li>
                <li><strong>Export-ready:</strong> the unified research dataset combining raw, parsed, enriched, and verification fields.</li>
                <li><strong>Parsed details:</strong> parse status, confidence, strategy, fallback, and payload are available in the unified rows and row drilldown.</li>
              </ul>
            </article>
            <article class="info-card">
              <h3>How to Work with Rows</h3>
              <ul class="plain-list">
                <li>Filter by query, model or platform, top-k cutoff, rank bucket, matched state, DOI validity, conflicts, language, publisher, country, OA status, source type, parse status, and risk bucket.</li>
                <li>Search across title, DOI, journal, authors, publisher, and query text.</li>
                <li>Sort by rank, year, citations, conflict count, parse confidence, model or platform, and query.</li>
                <li>Open row drilldown to inspect raw, parsed, enriched, and verification payloads together with provenance.</li>
              </ul>
            </article>
          </div>
        </section>

        <section class="panel" id="exports">
          <div class="section-heading">
            <p class="eyebrow">Exports</p>
            <h2>Research-Friendly Reuse</h2>
            <p>Exports are available from the Records Explorer and follow the current filtered view and selected export preset.</p>
          </div>
          <div class="two-column-grid">
            <article class="info-card">
              <h3>Supported Formats</h3>
              <ul class="plain-list">
                <li><code>CSV</code> for spreadsheet and statistical workflows.</li>
                <li><code>JSON</code> for structured archival or notebook workflows.</li>
                <li><code>JSONL</code> for row-wise pipelines and reproducible processing.</li>
              </ul>
            </article>
            <article class="info-card">
              <h3>Supported Export Types</h3>
              <ul class="plain-list">
                <li><strong>Raw export:</strong> model or platform outputs before enrichment.</li>
                <li><strong>Enriched export:</strong> resolved metadata fields suitable for bias analysis.</li>
                <li><strong>Verification export:</strong> matching, DOI validity, conflict flags, and risk fields.</li>
                <li><strong>Unified export-ready view:</strong> one research row with raw, parsed, enriched, and verification context together.</li>
              </ul>
            </article>
          </div>
          <p class="muted">
            Unified exports are the best starting point for downstream analysis because they preserve provenance while still
            being convenient to filter, merge, or summarize in external tools.
          </p>
        </section>

        <section class="panel" id="interpretation">
          <div class="section-heading">
            <p class="eyebrow">Interpretation Guide</p>
            <h2>How to Read the Main Report Sections</h2>
            <p>
              Each section below describes what the panel measures, what it may reveal, how to read higher or lower values,
              and when the metric may be unavailable or less reliable.
            </p>
          </div>
          <div class="metric-grid">
            <article class="metric-card" *ngFor="let item of metricSections">
              <h3>{{ item.title }}</h3>
              <p><strong>Scope:</strong> {{ item.scope }}</p>
              <p><strong>Measures:</strong> {{ item.measures }}</p>
              <p><strong>May reveal:</strong> {{ item.reveals }}</p>
              <p><strong>Interpretation:</strong> {{ item.interpretation }}</p>
              <p><strong>Reliability / gating:</strong> {{ item.gating }}</p>
            </article>
          </div>
        </section>

        <section class="panel" id="verifiability">
          <div class="section-heading">
            <p class="eyebrow">Verifiability</p>
            <h2>What “Hallucination” Means in This Project</h2>
            <p>
              In this application, hallucination is treated as bibliographic unverifiability or fabricated or inconsistent
              metadata risk. It is not a vague label and it is not inferred from style or tone alone.
            </p>
          </div>
          <div class="content-stack">
            <p>
              The Bibliographic Verifiability / Hallucination Risk section is grounded in measurable signals such as unmatched
              records, invalid DOI, title mismatch, year conflict, journal conflict, author conflict, publisher conflict,
              parse failure, and suspicious completeness without external confirmation.
            </p>
            <p>
              A higher hallucination risk means the returned bibliographic item is harder to verify externally or contains
              stronger signs of fabrication or internal inconsistency. It does not automatically mean the model intended to
              fabricate, only that the record is less trustworthy for research use without further inspection.
            </p>
            <article class="callout callout--important">
              <strong>Interpretation note</strong>
              <p>
                Treat high-risk rows as investigation targets. Open the Records Explorer, inspect the row drilldown, and confirm
                whether the issue comes from parsing, matching failure, DOI problems, or conflicting metadata.
              </p>
            </article>
          </div>
        </section>

        <section class="panel" id="gating">
          <div class="section-heading">
            <p class="eyebrow">Availability</p>
            <h2>Gating, Coverage, and Reliability</h2>
            <p>The app prefers explicit unavailability states over misleading charts. A panel may be hidden or gated when:</p>
          </div>
          <ul class="plain-list">
            <li>metadata coverage is too sparse for a stable comparison</li>
            <li>the run type does not support the metric</li>
            <li>only one repetition exists, so stability cannot be estimated</li>
            <li>prestige metadata such as CORE or JIF is not available</li>
            <li>institution taxonomy is not available even if affiliation text exists</li>
            <li>a selected filter leaves too few rows for a meaningful chart</li>
            <li>verification or enrichment coverage is too limited for the requested interpretation</li>
          </ul>
        </section>

        <section class="panel" id="limitations">
          <div class="section-heading">
            <p class="eyebrow">Limitations</p>
            <h2>Current Limits of the Implementation</h2>
            <p>This app is meant to support research interpretation, not replace manual judgment.</p>
          </div>
          <ul class="plain-list">
            <li>Some metrics depend on enrichment quality and external provider availability.</li>
            <li>Prestige-based sections may still be gated if CORE or journal-impact metadata is unavailable.</li>
            <li>Institution-type and similar taxonomy-heavy panels remain limited when upstream metadata is not normalized enough.</li>
            <li>Stability metrics require repeated calls per model and query pair.</li>
            <li>Counts can change after enrichment because records may be matched, normalized, or left unresolved.</li>
            <li>The report is analytical support, not absolute truth. Suspicious rows should be checked in the Records Explorer and, when necessary, against external sources.</li>
          </ul>
        </section>

        <section class="panel" id="workflow">
          <div class="section-heading">
            <p class="eyebrow">Suggested Workflow</p>
            <h2>Recommended Evaluation Path</h2>
            <p>This path works well for demos, pilot studies, and thesis evaluation sessions.</p>
          </div>
          <ol class="step-list">
            <li>Create one <code>scholarly</code> run using the same query set across multiple scholarly sources.</li>
            <li>Create one <code>llm_audit</code> run using the same query set across multiple LLM models.</li>
            <li>Open both report pages and compare shared sections such as language, publisher, geo, OA, recency, citation, and source-type patterns.</li>
            <li>Use Record Overlap and Cross-Model Divergence to see where systems agree or diverge.</li>
            <li>Inspect Bibliographic Quality and Bibliographic Verifiability / Hallucination Risk for the LLM run.</li>
            <li>Open the Records Explorer for suspicious subsets, such as one model with high conflict rate or a publisher skew.</li>
            <li>Export the filtered rows you want to analyze further in external notebooks, spreadsheets, or statistical tools.</li>
          </ol>
        </section>

        <section class="panel" id="faq">
          <div class="section-heading">
            <p class="eyebrow">FAQ</p>
            <h2>Practical Questions</h2>
          </div>
          <div class="faq-list">
            <article class="faq-card" *ngFor="let item of faqItems">
              <h3>{{ item.question }}</h3>
              <p>{{ item.answer }}</p>
            </article>
          </div>
        </section>
      </div>
    </div>
  `,
  styles: [`
    :host {
      display: block;
    }

    .docs-layout {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 24px;
      align-items: start;
    }

    .docs-page {
      display: grid;
      gap: 24px;
      min-width: 0;
    }

    .panel {
      border: 1px solid #d7e1ea;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.95);
      padding: 24px;
      box-shadow: 0 12px 30px rgba(15, 35, 55, 0.05);
      min-width: 0;
    }

    .toc {
      position: sticky;
      top: 16px;
      display: grid;
      gap: 16px;
    }

    .toc h2,
    .toc p,
    .section-heading h2,
    .section-heading p,
    .hero h1,
    .hero p,
    .quick-link-card h3,
    .quick-link-card p,
    .info-card h3,
    .info-card p,
    .metric-card h3,
    .metric-card p,
    .faq-card h3,
    .faq-card p,
    .callout p {
      margin: 0;
    }

    .toc__intro,
    .muted {
      color: #5a6c7d;
    }

    .toc__nav {
      display: grid;
      gap: 8px;
    }

    .toc__nav a {
      color: #12324a;
      text-decoration: none;
      font-weight: 600;
      padding: 8px 10px;
      border-radius: 12px;
      background: #f3f7fb;
    }

    .toc__nav a:hover {
      background: #e7f0f8;
    }

    .hero {
      display: grid;
      gap: 20px;
      scroll-margin-top: 16px;
    }

    .hero__header,
    .section-heading,
    .two-column-grid,
    .callout-grid,
    .quick-links,
    .content-stack,
    .faq-list {
      min-width: 0;
    }

    .hero__header {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: start;
    }

    .hero__lede {
      max-width: 70ch;
      color: #455768;
      line-height: 1.6;
    }

    .hero__actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }

    .nav-button {
      border: 0;
      border-radius: 12px;
      padding: 10px 14px;
      background: #12324a;
      color: #fff;
      cursor: pointer;
      font-weight: 600;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }

    .nav-button.secondary {
      background: #eef4fb;
      color: #12324a;
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
    }

    .quick-links,
    .callout-grid,
    .two-column-grid,
    .metric-grid,
    .faq-list {
      display: grid;
      gap: 16px;
    }

    .quick-links {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }

    .two-column-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .metric-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }

    .callout-grid,
    .faq-list {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .quick-link-card,
    .info-card,
    .metric-card,
    .faq-card,
    .callout {
      border: 1px solid #e1e9f0;
      border-radius: 16px;
      padding: 18px;
      background: linear-gradient(180deg, rgba(251, 253, 255, 0.98), rgba(247, 250, 253, 0.95));
      display: grid;
      gap: 10px;
      min-width: 0;
    }

    .metric-card p,
    .content-stack p,
    .info-card p,
    .faq-card p,
    .quick-link-card p,
    .callout p,
    .plain-list li,
    .step-list li {
      color: #455768;
      line-height: 1.6;
    }

    .callout--important {
      border-color: #bfd7ea;
      background: #eef6fd;
    }

    .callout--tip {
      border-color: #cfe7cf;
      background: #f4fbf2;
    }

    .callout--limitation {
      border-color: #edd8bf;
      background: #fff8ef;
    }

    .section-heading {
      display: grid;
      gap: 8px;
      margin-bottom: 18px;
      scroll-margin-top: 16px;
    }

    .section-heading p:last-child {
      color: #5a6c7d;
      max-width: 74ch;
      line-height: 1.6;
    }

    .content-stack {
      display: grid;
      gap: 14px;
    }

    .plain-list,
    .step-list {
      margin: 0;
      padding-left: 20px;
      display: grid;
      gap: 10px;
    }

    @media (max-width: 1180px) {
      .docs-layout {
        grid-template-columns: 1fr;
      }

      .toc {
        position: static;
      }
    }

    @media (max-width: 900px) {
      .quick-links,
      .two-column-grid,
      .metric-grid,
      .callout-grid,
      .faq-list {
        grid-template-columns: 1fr;
      }

      .hero__header {
        flex-direction: column;
      }
    }
  `]
})
export class DocsPageComponent {
  protected readonly navItems: DocNavItem[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'quick-start', label: 'Quick Start' },
    { id: 'run-types', label: 'Run Types' },
    { id: 'report-page', label: 'Report Page' },
    { id: 'records-explorer', label: 'Records Explorer' },
    { id: 'exports', label: 'Exports' },
    { id: 'interpretation', label: 'Interpret Main Sections' },
    { id: 'verifiability', label: 'Hallucination / Verifiability' },
    { id: 'gating', label: 'Gating and Reliability' },
    { id: 'limitations', label: 'Limitations' },
    { id: 'workflow', label: 'Suggested Workflow' },
    { id: 'faq', label: 'FAQ' }
  ];

  protected readonly overviewCallouts: DocCallout[] = [
    {
      tone: 'important',
      title: 'Research orientation',
      body: 'The product is designed as an inspectable research workflow. Important findings should be traceable to artifacts and row-level evidence.'
    },
    {
      tone: 'tip',
      title: 'Use both surfaces',
      body: 'Use the Report page to identify patterns and the Records Explorer to verify whether those patterns come from specific rows, queries, or models.'
    },
    {
      tone: 'limitation',
      title: 'Coverage matters',
      body: 'Many metrics depend on enrichment and verification coverage. Missing or gated panels usually indicate a data limitation rather than a rendering bug.'
    }
  ];

  protected readonly quickStartSteps: string[] = [
    'Open the Runs page and create a new run.',
    'Choose `scholarly` for source comparison or `llm_audit` for model comparison.',
    'Select the relevant scholarly sources or LLM models and provide your query set.',
    'Start the run and monitor live execution status on the run detail page.',
    'Open the report to compare grouped metrics across models, platforms, and queries.',
    'Open the Records Explorer to inspect suspicious rows, conflicts, and verification outcomes.',
    'Export the filtered dataset you need for notebooks, spreadsheets, or further research analysis.'
  ];

  protected readonly metricSections: DocMetricSection[] = [
    {
      title: 'Summary / Experiment Overview',
      scope: 'Run-level overview for both run modes.',
      measures: 'Run type, number of queries, number of models or platforms, total records, top-k, enrichment context, and high-level run composition.',
      reveals: 'Whether the experiment scope is broad enough and whether later comparisons are based on a meaningful number of entities and queries.',
      interpretation: 'Use this first to confirm what the run actually contains before reading any bias or quality charts.',
      gating: 'Usually available once a run has results; some counts may depend on enrichment or verification completion.'
    },
    {
      title: 'Per-Model / Per-Platform Summary',
      scope: 'Grouped by model in `llm_audit` and by source or platform in `scholarly` runs.',
      measures: 'Returned records, unique records, average results per query, DOI rate, metadata completeness, missingness, known language and country rates, OA coverage, conflict rate, and verification profile.',
      reveals: 'Which systems are richer, sparser, noisier, or riskier before deeper section-by-section analysis.',
      interpretation: 'Higher completeness or DOI validity is usually better; higher conflict or high-risk share is usually worse and worth drilling into.',
      gating: 'Requires records for the compared entities. Some fields become less informative if enrichment coverage is low.'
    },
    {
      title: 'Metadata Coverage',
      scope: 'Overall, per model or platform, and selected per-query views.',
      measures: 'How often key bibliographic fields such as DOI, year, journal, authors, language, country, publisher, and OA status are populated.',
      reveals: 'Whether some systems provide materially weaker bibliographic context than others.',
      interpretation: 'Higher coverage means more analysis-ready records. Large gaps often indicate strong dependence on enrichment.',
      gating: 'Depends on enough records and, for some fields, on enrichment availability.'
    },
    {
      title: 'Missingness Bias',
      scope: 'Per field, per entity, and selected top-k comparisons.',
      measures: 'Which metadata fields are systematically absent rather than present.',
      reveals: 'Whether a model or source tends to omit certain classes of metadata more often than others.',
      interpretation: 'Higher missingness indicates weaker metadata reliability and a greater chance that later comparisons are coverage-limited.',
      gating: 'Most useful when there are enough records to compare missingness patterns across entities or queries.'
    },
    {
      title: 'Enrichment Gain',
      scope: 'Before vs after enrichment, by field and by entity.',
      measures: 'Absolute and relative improvement in metadata coverage after external resolution.',
      reveals: 'Which systems rely heavily on enrichment to become analysis-ready.',
      interpretation: 'Large gain means enrichment adds substantial value, but it also means the raw outputs were relatively incomplete.',
      gating: 'Unavailable when baseline and enriched coverage cannot both be estimated.'
    },
    {
      title: 'Record Overlap',
      scope: 'Cross-entity comparison, with overlap@k and top-1 agreement where available.',
      measures: 'How similar the returned literature sets are across models or platforms.',
      reveals: 'Agreement, divergence, and whether different systems converge on the same references.',
      interpretation: 'Higher overlap means more similar retrieval behavior. Lower overlap suggests divergence, complementarity, or instability.',
      gating: 'Requires at least two comparable entities with enough overlapping query scope.'
    },
    {
      title: 'Ranking Bias',
      scope: 'Top-k, top-vs-rest, and rank-sensitive views when the metadata exists.',
      measures: 'Whether high-ranked positions concentrate prestige, recency, or citation characteristics differently from the rest of the retrieved set.',
      reveals: 'Position-sensitive preferences that would be hidden if you only looked at the full result pool.',
      interpretation: 'Large top-k deltas indicate that ranking is systematically favoring certain record types.',
      gating: 'Prestige-specific subpanels are gated when CORE, JIF, or similar metadata is unavailable.'
    },
    {
      title: 'Language Bias',
      scope: 'Per entity, with top-k comparisons and selected over or under-representation views.',
      measures: 'Language distribution, English share, non-English share, and unknown share.',
      reveals: 'Whether a system disproportionately surfaces certain languages and suppresses others.',
      interpretation: 'Higher English share is not automatically better; the key question is whether the language mix is narrower or skewed relative to the broader set.',
      gating: 'Depends on enough language-resolved records. Unknown language share reduces interpretability.'
    },
    {
      title: 'Publisher Bias',
      scope: 'Per model or platform, plus selected top-k and concentration views.',
      measures: 'Publisher distribution, concentration, top publishers, and over or under-representation against the broader pool.',
      reveals: 'Whether a system disproportionately favors outputs from a small set of publishers.',
      interpretation: 'Higher concentration or strong over-representation suggests narrower publisher diversity and potential selection bias.',
      gating: 'Requires sufficient publisher metadata after enrichment.'
    },
    {
      title: 'Venue Diversity',
      scope: 'Cross-entity comparison with concentration metrics and top-venue share.',
      measures: 'Unique venues, concentration, entropy-style diversity, and how much retrieval is dominated by one or a few venues.',
      reveals: 'Whether literature is spread across many venues or clustered narrowly.',
      interpretation: 'Higher diversity usually indicates broader venue spread, while higher concentration suggests a narrower literature slice.',
      gating: 'Depends on enough resolved venue metadata.'
    },
    {
      title: 'Geo Bias',
      scope: 'Per entity and selected country or region distribution views.',
      measures: 'Country coverage, dominant country, multi-country share, geographic distribution, and top-k geographic skew.',
      reveals: 'Whether certain countries or regions are systematically overrepresented.',
      interpretation: 'Higher concentration in one geography suggests a narrower geographic footprint; compare top-k against overall to see rank effects.',
      gating: 'Requires country or region metadata. Sparse geography data can trigger unavailable or insufficient coverage states.'
    },
    {
      title: 'OA Bias',
      scope: 'Per entity with OA-vs-closed and OA pathway comparisons.',
      measures: 'Known OA rate, OA status distribution, and top-k OA skew.',
      reveals: 'Whether a system prefers open access, closed, or specific OA pathway records.',
      interpretation: 'Higher open-access share may reflect accessibility preference, but should be read against the baseline pool and query context.',
      gating: 'Depends on enough OA metadata and may be less stable when OA status is frequently unknown.'
    },
    {
      title: 'Recency Bias',
      scope: 'Per entity, selected top-k views, and year-based comparisons.',
      measures: 'Publication year distribution, mean or median year, and share of recent versus older papers.',
      reveals: 'Whether a system systematically favors newer or older literature.',
      interpretation: 'Higher recent share indicates recency preference; compare it against overall or rest-of-list values to detect ranking skew.',
      gating: 'Requires enough resolved publication years.'
    },
    {
      title: 'Citation Bias',
      scope: 'Per entity and rank-aware comparison views.',
      measures: 'Citation distribution, median citations, highly cited share, and citation level by rank.',
      reveals: 'Whether a system privileges highly cited literature over lower-cited work.',
      interpretation: 'Higher citation concentration in top ranks suggests ranking preference for established literature rather than necessarily better relevance.',
      gating: 'Requires citation metadata and enough records to compare distributions.'
    },
    {
      title: 'Source-Type Bias',
      scope: 'Cross-entity compare for journals, conferences, repositories, preprints, and other source types.',
      measures: 'Source-type distribution overall and in selected top-k slices.',
      reveals: 'Whether a system favors certain publication formats.',
      interpretation: 'A high share for one source type indicates format preference and should be read relative to the broader candidate set.',
      gating: 'Requires source-type metadata from enrichment.'
    },
    {
      title: 'Topic / Subfield Drift',
      scope: 'Per entity concentration and drift from the broader topic mix.',
      measures: 'Topic or subfield distribution and whether retrieval narrows into a small thematic slice.',
      reveals: 'Whether a model or source drifts toward a narrow subfield rather than covering the broader intended topic.',
      interpretation: 'Higher concentration can mean sharper specialization, but also less thematic coverage.',
      gating: 'Requires enough topic or subfield metadata; sparse enrichment can limit this section.'
    },
    {
      title: 'Parse Robustness',
      scope: 'LLM-only, per model and query-model detail.',
      measures: 'Raw success, strict JSON success, fallback parsing, malformed outputs, and parse failure patterns.',
      reveals: 'How reliably each model produces machine-readable outputs that can be analyzed downstream.',
      interpretation: 'Higher parse success is better. High fallback or parse-failure rates indicate fragile output formatting.',
      gating: 'Only available for `llm_audit` runs with recorded LLM call rows.'
    },
    {
      title: 'Cross-Model Divergence',
      scope: 'LLM-only, pairwise comparison across models.',
      measures: 'Jaccard overlap, overlap@k, top-1 agreement, and related pairwise disagreement signals.',
      reveals: 'How much LLMs disagree on what literature is most relevant.',
      interpretation: 'Higher overlap means more agreement; lower overlap indicates stronger divergence or model-specific retrieval behavior.',
      gating: 'Requires at least two comparable models in the run.'
    },
    {
      title: 'Repeatability / Stability',
      scope: 'LLM-only, per model and repeated-query views.',
      measures: 'How similar outputs remain across repeated calls for the same query-model pair.',
      reveals: 'Whether the same model behaves consistently or drifts between repetitions.',
      interpretation: 'Higher stability suggests more reproducible outputs. Lower stability means more sensitivity to repeated execution.',
      gating: 'Unavailable when the run has only one call per query-model pair.'
    },
    {
      title: 'Bibliographic Quality',
      scope: 'LLM-only, per model and query-model summary.',
      measures: 'Valid DOI rate, matched or verified record rate, metadata completeness, and useful records per query.',
      reveals: 'How usable the returned records are for real research workflows.',
      interpretation: 'Higher verified and DOI-valid rates are better. Low completeness or low verified yield means more manual cleanup.',
      gating: 'Only available for `llm_audit`, and strongest when enrichment and verification coverage are good.'
    },
    {
      title: 'Metadata Conflicts',
      scope: 'LLM-only conflict diagnostics across models and queries.',
      measures: 'Any conflict rate plus year, journal, DOI, author, and publisher disagreement where available.',
      reveals: 'How often model-claimed metadata conflicts with external reference metadata.',
      interpretation: 'Higher conflict rates indicate lower metadata trustworthiness and should lead to row-level inspection.',
      gating: 'Depends on having matched records and comparable enriched metadata.'
    },
    {
      title: 'Bibliographic Verifiability / Hallucination Risk',
      scope: 'LLM-only risk diagnostics grounded in verification evidence.',
      measures: 'Matched versus unmatched rates, DOI validity, mismatch patterns, parse failure, suspicious completeness, and risk bucket counts.',
      reveals: 'Whether a model tends to return bibliographically unverifiable, fabricated, or internally inconsistent records.',
      interpretation: 'Higher unmatched, invalid DOI, conflict, or high-risk counts indicate lower trustworthiness of the returned bibliography.',
      gating: 'Requires LLM rows plus enough verification evidence. Risk should always be read together with row drilldown for context.'
    },
    {
      title: 'Query Details',
      scope: 'LLM-only per-query and per-model drilldown.',
      measures: 'Prompt or query text, parsed items, result counts, verification outcomes, and model-specific query behavior.',
      reveals: 'Whether the observed behavior is consistent across prompts or dominated by a few difficult queries.',
      interpretation: 'Use this when one query appears to drive a surprising aggregate pattern elsewhere in the report.',
      gating: 'Only available for `llm_audit` runs with stored call rows.'
    }
  ];

  protected readonly faqItems: DocFaqItem[] = [
    {
      question: 'Why is a section unavailable?',
      answer: 'The current filters, run type, or metadata coverage may not support that metric. The app gates sections instead of rendering potentially misleading charts.'
    },
    {
      question: 'Why do some counts change after enrichment?',
      answer: 'Enrichment can fill missing fields, normalize identifiers, match records to external sources, or leave unresolved rows unchanged. The enriched view is not always identical to the raw output surface.'
    },
    {
      question: 'Why does the Records Explorer show more detail than the report?',
      answer: 'The report is intentionally selective and comparative. The Records Explorer is the evidence surface and includes raw, parsed, enriched, and verification fields for each row.'
    },
    {
      question: 'What is the difference between raw and enriched data?',
      answer: 'Raw data is what the model or scholarly source returned. Enriched data is the externally resolved bibliographic metadata used to improve comparison, verification, and bias analysis.'
    },
    {
      question: 'What does a high hallucination risk mean?',
      answer: 'It means the row shows stronger evidence of bibliographic unverifiability, such as failed matching, invalid DOI, parse failure, or metadata conflict. It is a risk signal, not a claim about model intent.'
    },
    {
      question: 'Why can two models disagree on the same query?',
      answer: 'Models can differ in retrieval heuristics, ranking preferences, output formatting quality, and stability across repeated calls. Cross-Model Divergence and Query Details help explain that disagreement.'
    }
  ];
}
