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
import { getDesktopRuntimeConfig } from './desktop';

function apiBase(): string {
  return getDesktopRuntimeConfig()?.apiBase || '/api';
}

function apiHeaders(headers?: HeadersInit): Headers {
  const merged = new Headers(headers);
  const localToken = getDesktopRuntimeConfig()?.localToken;
  if (localToken) merged.set('X-Bili-Local-Token', localToken);
  return merged;
}

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(apiBase() + url, { ...options, headers: apiHeaders(options?.headers) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export function startAnalysis(bv: string, maxComments = 100, requestDelay = 3.0) {
  return req<{ analysis_id: number; status: string }>('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bv, max_comments: maxComments, request_delay: requestDelay }),
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
  return req<{ ok: boolean }>('/history/' + analysisId, { method: 'DELETE' });
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

export function getAuthStatus() {
  return req<{ logged_in: boolean }>('/auth/status');
}

export function logout() {
  return req<{ ok?: boolean }>('/auth/logout', { method: 'POST' });
}

export function getAuthAccounts() {
  return req<{ accounts: { index: number; name: string }[] }>('/auth/accounts');
}

export function getQRCode() {
  return req<{ image_data_url?: string; qrcode_key?: string; error?: string }>('/auth/qrcode');
}

export function getQRCodeStatus(key: string) {
  return req<{ status: string; message?: string }>('/auth/qrcode/status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ qrcode_key: key }),
  });
}

export function switchAuthAccount(index: number) {
  return req<{ ok: boolean }>('/auth/accounts/' + index + '/switch', { method: 'POST' });
}

export function getRuntimeActivity() {
  return req<{ active: boolean; active_tasks?: number; can_exit?: boolean }>('/runtime/activity');
}

export function prepareRuntimeExit() {
  return req<{ ok: boolean }>('/runtime/prepare-exit', { method: 'POST' });
}
