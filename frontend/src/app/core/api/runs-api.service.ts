import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from './api.config';
import {
  CreateRunRequest,
  OpenRouterModelsResponse,
  ResultEnrichmentResponse,
  ResultRecord,
  ReplayStatusResponse,
  RunAnalysis,
  RunDetail,
  RunRecordsResponse,
  RunOptionsResponse
} from '../../features/runs/models/run.models';

@Injectable({ providedIn: 'root' })
export class RunsApiService {
  private readonly http = inject(HttpClient);
  private readonly apiBaseUrl = inject(API_BASE_URL);

  getOptions(): Observable<RunOptionsResponse> {
    return this.http.get<RunOptionsResponse>(`${this.apiBaseUrl}/runs/options`);
  }

  getOpenRouterModels(): Observable<OpenRouterModelsResponse> {
    return this.http.get<OpenRouterModelsResponse>(`${this.apiBaseUrl}/openrouter/models`);
  }

  listRuns(): Observable<RunDetail[]> {
    return this.http.get<RunDetail[]>(`${this.apiBaseUrl}/runs`);
  }

  createRun(payload: CreateRunRequest): Observable<RunDetail> {
    return this.http.post<RunDetail>(`${this.apiBaseUrl}/runs`, payload);
  }

  getRun(runId: string): Observable<RunDetail> {
    return this.http.get<RunDetail>(`${this.apiBaseUrl}/runs/${runId}`);
  }

  deleteRun(runId: string): Observable<void> {
    return this.http.delete<void>(`${this.apiBaseUrl}/runs/${runId}`);
  }

  startRun(runId: string): Observable<RunDetail> {
    return this.http.post<RunDetail>(`${this.apiBaseUrl}/runs/${runId}/start`, {});
  }

  replayLlmArtifacts(runId: string): Observable<RunDetail> {
    return this.http.post<RunDetail>(`${this.apiBaseUrl}/runs/${runId}/replay-llm-artifacts`, {});
  }

  retryRunModel(runId: string, modelId: string): Observable<RunDetail> {
    return this.http.post<RunDetail>(
      `${this.apiBaseUrl}/runs/${runId}/models/${encodeURIComponent(modelId)}/retry`,
      {},
    );
  }

  getReplayStatus(runId: string): Observable<ReplayStatusResponse> {
    return this.http.get<ReplayStatusResponse>(`${this.apiBaseUrl}/runs/${runId}/replay-status`);
  }

  getResults(runId: string): Observable<ResultRecord[]> {
    return this.http.get<ResultRecord[]>(`${this.apiBaseUrl}/runs/${runId}/results`);
  }

  getEnrichments(runId: string): Observable<ResultEnrichmentResponse[]> {
    return this.http.get<ResultEnrichmentResponse[]>(`${this.apiBaseUrl}/runs/${runId}/enrichments`);
  }

  getAnalysis(runId: string): Observable<RunAnalysis> {
    return this.http.get<RunAnalysis>(`${this.apiBaseUrl}/runs/${runId}/analysis`);
  }

  getRecords(
    runId: string,
    params: Record<string, string | number | boolean | null | undefined> = {},
  ): Observable<RunRecordsResponse> {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined || value === '') {
        continue;
      }
      search.set(key, String(value));
    }
    const query = search.toString();
    const suffix = query ? `?${query}` : '';
    return this.http.get<RunRecordsResponse>(`${this.apiBaseUrl}/runs/${runId}/records${suffix}`);
  }

  buildRecordsExportUrl(
    runId: string,
    params: Record<string, string | number | boolean | null | undefined> = {},
  ): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined || value === '') {
        continue;
      }
      search.set(key, String(value));
    }
    const query = search.toString();
    return `${this.apiBaseUrl}/runs/${runId}/records/export${query ? `?${query}` : ''}`;
  }
}
