import type {
  AISummary,
  AnalysisMode,
  AnalysisResult,
  AnalysisGroup,
  GroupAISummary,
  GroupAnalysisResult,
  GroupReanalysisStatus,
  FilterState,
  InterpretationView,
  HistoryItem,
  KeywordItem,
  LLMTask,
  SummaryReportMode,
  LLMTaskUpdate,
  SettingsResponse,
  StatusResponse,
  VideoInfoResponse,
} from '../types';
import { getDesktopRuntimeConfig } from './desktop';
import { recordApiRequestCompleted, recordApiRequestFailed, recordApiRequestStarted } from './devDiagnostics';

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
  const method = (options?.method || 'GET').toUpperCase();
  const startedAt = performance.now();
  let failureRecorded = false;
  let responseStatus = 0;
  let responseRequestId: string | null = null;
  recordApiRequestStarted(method, url);
  try {
    const res = await fetch(apiBase() + url, { ...options, headers: apiHeaders(options?.headers) });
    const durationMs = performance.now() - startedAt;
    const requestId = res.headers.get('X-Request-ID');
    responseStatus = res.status;
    responseRequestId = requestId;
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText })) as { detail?: unknown };
      const detail = err.detail;
      const message = typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message?: unknown }).message === 'string'
          ? (detail as { message: string }).message
          : res.statusText || 'Request failed';
      const error = new Error(message);
      recordApiRequestFailed(method, url, res.status, durationMs, requestId, error);
      failureRecorded = true;
      throw error;
    }
    const data = await res.json() as T;
    recordApiRequestCompleted(method, url, res.status, durationMs, requestId);
    return data;
  } catch (error) {
    if (!failureRecorded) {
      recordApiRequestFailed(method, url, responseStatus, performance.now() - startedAt, responseRequestId, error);
    }
    throw error;
  }
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

export function getFilteredKeywords(analysisId: number, filters: FilterState) {
  return req<{ matched_count: number; keywords: KeywordItem[] }>('/keywords/' + analysisId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filters }),
  });
}

export function getAnalysisGroups() {
  return req<AnalysisGroup[]>('/analysis-groups');
}

export function getAnalysisGroup(groupId: number) {
  return req<AnalysisGroup>('/analysis-groups/' + groupId);
}

export function createAnalysisGroup(data: { name: string; description?: string; analysis_ids: number[] }) {
  return req<AnalysisGroup>('/analysis-groups', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
}

export function updateAnalysisGroup(groupId: number, data: Partial<{ name: string; description: string; analysis_ids: number[] }>) {
  return req<AnalysisGroup>('/analysis-groups/' + groupId, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
}

export function deleteAnalysisGroup(groupId: number) {
  return req<{ deleted: boolean; group_id: number }>('/analysis-groups/' + groupId, { method: 'DELETE' });
}

export function getGroupResults(groupId: number, mode: AnalysisMode, filters?: FilterState) {
  const query = new URLSearchParams({ mode });
  if (filters) query.set('filters', JSON.stringify(filters));
  return req<GroupAnalysisResult>('/analysis-groups/' + groupId + '/results?' + query.toString());
}

export function getGroupFilteredKeywords(groupId: number, mode: AnalysisMode, filters: FilterState) {
  return req<{ matched_count: number; keywords: KeywordItem[] }>('/analysis-groups/' + groupId + '/keywords', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, filters }),
  });
}

export function reanalyzeGroup(groupId: number) {
  return req<GroupReanalysisStatus>('/analysis-groups/' + groupId + '/reanalyze', { method: 'POST' });
}

export function getGroupReanalysisStatus(groupId: number) {
  return req<GroupReanalysisStatus>('/analysis-groups/' + groupId + '/reanalyze/status');
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

export function generateSummary(
  analysisId: number,
  filters: FilterState,
  regenerate = false,
  interpretationView: InterpretationView = 'public_opinion',
  reportMode: SummaryReportMode = 'quick',
) {
  return req<AISummary>('/summaries/' + analysisId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filters, regenerate, interpretationView, reportMode }),
  });
}

export function getGroupSummaries(groupId: number) {
  return req<GroupAISummary[]>('/analysis-groups/' + groupId + '/summaries');
}

export function generateGroupSummary(groupId: number, mode: AnalysisMode, filters: FilterState, regenerate = false) {
  return req<GroupAISummary>('/analysis-groups/' + groupId + '/summaries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, filters, regenerate }),
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
