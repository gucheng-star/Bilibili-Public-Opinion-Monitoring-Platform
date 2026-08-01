import type {
  AISummary,
  AnalysisMode,
  AnalysisResult,
  FilterState,
  HistoryItem,
  LLMTask,
  LLMTaskUpdate,
  SettingsResponse,
  StatusResponse,
  VideoInfoResponse,
} from '../types';

const BASE = '/api';

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export function startAnalysis(bv: string, maxComments = 100, requestDelay = 3.0, mode: AnalysisMode = 'nlp') {
  return req<{ analysis_id: number; status: string }>('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bv, max_comments: maxComments, request_delay: requestDelay, mode }),
  });
}

export function getStatus(analysisId: number) {
  return req<StatusResponse>('/status/' + analysisId);
}

export function getResults(analysisId: number) {
  return req<AnalysisResult>('/results/' + analysisId);
}

export function getWordCloud(analysisId: number) {
  return req<{ base64: string }>('/wordcloud/' + analysisId);
}

export function getHistory(limit = 20) {
  return req<HistoryItem[]>('/history?limit=' + limit);
}

export function deleteHistory(analysisId: number) {
  return fetch(BASE + '/history/' + analysisId, { method: 'DELETE' }).then(r => {
    if (!r.ok) throw new Error('Delete failed');
    return r.json();
  });
}

export function getVideoInfo(bv: string) {
  return req<VideoInfoResponse>('/video/' + bv);
}

export function getSettings() {
  return req<SettingsResponse>('/settings');
}

export function updateSettings(data: {
  api_key?: string;
  analysis_mode?: AnalysisMode;
  llm?: Partial<Record<LLMTask, Partial<LLMTaskUpdate>>>;
}) {
  return req<SettingsResponse>('/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export function testLLM(task: LLMTask, config?: Partial<LLMTaskUpdate>) {
  return req<{ ok: boolean; provider: string; model: string; latency_ms: number; message: string }>('/settings/test-llm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, config }),
  });
}

export function getLLMModels(task: LLMTask, config?: Partial<LLMTaskUpdate>) {
  return req<{ ok: boolean; provider: string; models: string[] }>('/settings/models', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, config }),
  });
}

export function getSummaries(analysisId: number) {
  return req<AISummary[]>('/summaries/' + analysisId);
}

export function generateSummary(analysisId: number, filters: FilterState, regenerate = false) {
  return req<AISummary>('/summaries/' + analysisId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filters, regenerate }),
  });
}

export function reanalyze(analysisId: number) {
  return req<{ analysis_id: number; status: string }>('/reanalyze/' + analysisId, { method: 'POST' });
}
