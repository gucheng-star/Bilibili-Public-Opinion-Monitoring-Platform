type BreadcrumbEvent =
  | 'route.changed'
  | 'analysis.selected'
  | 'group.selected'
  | 'analysis.mode_changed'
  | 'filter.changed'
  | 'api.request_started'
  | 'api.request_completed'
  | 'api.request_failed'
  | 'task.poll_status_changed'
  | 'component.action_started'
  | 'component.action_completed';

type DiagnosticErrorEvent = 'window.error' | 'window.unhandledrejection' | 'react.error_boundary' | 'api.request_failed' | 'startup.failed';

type Breadcrumb = {
  event: BreadcrumbEvent;
  path?: string;
  method?: string;
  status?: number;
  duration_ms?: number;
  request_id?: string;
  analysis_id?: number;
  group_id?: number;
  analysis_mode?: 'nlp' | 'llm';
  active_filter_fields?: string[];
  poll_status?: string;
  action?: string;
};
export type DiagnosticState = {
  route?: string;
  view_type?: 'single' | 'group' | 'settings' | 'comments';
  analysis_id?: number | null;
  group_id?: number | null;
  analysis_mode?: 'nlp' | 'llm';
  loading?: boolean;
  reanalyzing?: boolean;
  keyword_status?: 'ready' | 'loading' | 'error';
  active_filter_fields?: string[];
};
type DiagnosticEvent = {
  event: DiagnosticErrorEvent;
  error_type?: string;
  stack?: string;
  breadcrumbs: Breadcrumb[];
  state: DiagnosticState;
};

type StorageLike = Pick<Storage, 'getItem' | 'setItem'> & Partial<Pick<Storage, 'removeItem'>>;
type EventTargetLike = Pick<Window, 'addEventListener'>;
type TimerLike = (callback: () => void, delay: number) => number;

const BREADCRUMB_LIMIT = 50;
const ERROR_BREADCRUMB_LIMIT = 20;
const QUEUE_LIMIT = 100;
const BATCH_LIMIT = 20;
const MAX_EVENT_BYTES = 8 * 1024;
const MAX_BATCH_BYTES = 64 * 1024;
const MAX_REPORTED_DROPPED_COUNT = 100_000;
const RETRY_DELAY_MS = 5_000;
const DIAGNOSTICS_PATH = '/api/runtime/dev-diagnostics';
const LAST_SESSION_KEY = 'bili.dev-diagnostics.last-session';
const ERROR_EVENTS = new Set<DiagnosticErrorEvent>(['window.error', 'window.unhandledrejection', 'react.error_boundary', 'api.request_failed', 'startup.failed']);
const SAFE_ERROR_TYPES = new Set(['Error', 'TypeError', 'RangeError', 'SyntaxError', 'ReferenceError', 'URIError', 'EvalError', 'DOMException']);
const SAFE_HTTP_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);
const SAFE_FILTER_FIELDS = new Set(['gender', 'date_range', 'region', 'sentiment', 'duplicate_mode', 'source_analysis_id']);
const SAFE_PATH_PATTERN = /^\/[A-Za-z0-9/:_.-]{0,159}$/;

let breadcrumbs: Breadcrumb[] = [];
let queuedEvents: DiagnosticEvent[] = [];
let droppedCount = 0;
let sessionId: string | null = null;
let stateProvider: () => DiagnosticState = () => ({});
let flushInFlight = false;
let retryTimer: number | null = null;
let globalListenersInstalled = false;
let pendingStorageLoaded = false;
let restoredSessionId: string | null = null;
let restoredBoundEvents = new Set<DiagnosticEvent>();
let restoredBoundDroppedCount = 0;
let recentContextBreadcrumbs = new Map<BreadcrumbEvent, { signature: string; recordedAt: number }>();
let eventTarget: EventTargetLike | null = typeof window === 'undefined' ? null : window;
let storage: StorageLike | null = safeSessionStorage(typeof window === 'undefined' ? null : window);
let fetchImplementation: typeof fetch | null = typeof fetch === 'function' ? fetch : null;
let timerImplementation: TimerLike | null = typeof window === 'undefined' ? null : window.setTimeout.bind(window);
let devOverride: boolean | null = null;

function isDevEnabled(): boolean {
  return devOverride ?? Boolean(import.meta.env?.DEV);
}

function queueKey(id: string): string {
  return `bili.dev-diagnostics.${id}`;
}

function safeSessionStorage(target: { readonly sessionStorage: Storage } | null): StorageLike | null {
  try {
    return target?.sessionStorage ?? null;
  } catch {
    return null;
  }
}

function safeStorageRead(id: string): { events: DiagnosticEvent[]; droppedCount: number } {
  try {
    const raw = storage?.getItem(queueKey(id));
    if (!raw) return { events: [], droppedCount: 0 };
    const saved = JSON.parse(raw) as { events?: unknown; dropped_count?: unknown };
    const events = Array.isArray(saved.events)
      ? saved.events
        .map(normalizeQueuedEvent)
        .filter((event): event is DiagnosticEvent => event !== null)
        .slice(-QUEUE_LIMIT)
      : [];
    const savedDropped = typeof saved.dropped_count === 'number' && Number.isFinite(saved.dropped_count) && saved.dropped_count >= 0
      ? Math.floor(saved.dropped_count)
      : 0;
    return { events, droppedCount: savedDropped };
  } catch {
    // sessionStorage is optional; diagnostics must never affect the application.
    return { events: [], droppedCount: 0 };
  }
}

function safeStorageWrite(): void {
  try {
    if (sessionId) {
      storage?.setItem(LAST_SESSION_KEY, sessionId);
      storage?.setItem(queueKey(sessionId), JSON.stringify({ events: queuedEvents, dropped_count: droppedCount }));
      return;
    }
    const pendingEvents = queuedEvents.filter(event => !restoredBoundEvents.has(event));
    const pendingDroppedCount = Math.max(0, droppedCount - restoredBoundDroppedCount);
    storage?.setItem(queueKey('pending'), JSON.stringify({ events: pendingEvents, dropped_count: pendingDroppedCount }));
  } catch {
    // Private browsing and quota failures are intentionally ignored.
  }
}

function safeLastSessionRead(): string | null {
  try {
    const value = storage?.getItem(LAST_SESSION_KEY);
    return value && /^[A-Za-z0-9_.-]{1,128}$/.test(value) ? value : null;
  } catch {
    return null;
  }
}

function safeStorageRemove(id: string): void {
  try {
    storage?.removeItem?.(queueKey(id));
  } catch {
    // Storage cleanup is best-effort only.
  }
}

function mergeStoredQueue(stored: { events: DiagnosticEvent[]; droppedCount: number }): {
  survivingStoredEvents: Set<DiagnosticEvent>;
  attributedDroppedCount: number;
} {
  const merged = [...stored.events, ...queuedEvents];
  const overflow = Math.max(0, merged.length - QUEUE_LIMIT);
  queuedEvents = merged.slice(-QUEUE_LIMIT);
  droppedCount += stored.droppedCount + overflow;
  return {
    survivingStoredEvents: new Set(stored.events.filter(event => queuedEvents.includes(event))),
    attributedDroppedCount: stored.droppedCount + Math.min(overflow, stored.events.length),
  };
}

function ensureStoredQueueLoaded(): void {
  if (pendingStorageLoaded) return;
  pendingStorageLoaded = true;
  mergeStoredQueue(safeStorageRead('pending'));
  const previousSessionId = safeLastSessionRead();
  if (!previousSessionId) return;
  const stored = safeStorageRead(previousSessionId);
  const restored = mergeStoredQueue(stored);
  restoredSessionId = previousSessionId;
  restoredBoundEvents = restored.survivingStoredEvents;
  restoredBoundDroppedCount = restored.attributedDroppedCount;
}

function normalizeQueuedEvent(value: unknown): DiagnosticEvent | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<DiagnosticEvent>;
  if (!candidate.event || !ERROR_EVENTS.has(candidate.event)) return null;
  return fitDiagnosticEvent({
    event: candidate.event,
    ...(typeof candidate.error_type === 'string' ? { error_type: safeErrorType(candidate.error_type) } : {}),
    ...(typeof candidate.stack === 'string' && safeStack(candidate.stack) ? { stack: safeStack(candidate.stack) } : {}),
    breadcrumbs: Array.isArray(candidate.breadcrumbs) ? candidate.breadcrumbs.slice(-ERROR_BREADCRUMB_LIMIT).map(normalizeBreadcrumb).filter((item): item is Breadcrumb => item !== null) : [],
    state: projectState(candidate.state),
  });
}

function normalizeBreadcrumb(value: unknown): Breadcrumb | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<Breadcrumb>;
  if (typeof candidate.event !== 'string' || !isBreadcrumbEvent(candidate.event)) return null;
  return { event: candidate.event, ...projectBreadcrumbDetails(candidate.event, candidate as Record<string, unknown>) };
}

function isBreadcrumbEvent(value: string): value is BreadcrumbEvent {
  return [
    'route.changed', 'analysis.selected', 'group.selected', 'analysis.mode_changed', 'filter.changed',
    'api.request_started', 'api.request_completed', 'api.request_failed', 'task.poll_status_changed',
    'component.action_started', 'component.action_completed',
  ].includes(value);
}

function projectBreadcrumbDetails(event: BreadcrumbEvent, details: Record<string, unknown>): Record<string, unknown> {
  const selected: Record<string, unknown> = {};
  const copy = (key: string, valid: (value: unknown) => boolean) => {
    if (valid(details[key])) selected[key] = details[key];
  };
  if (event === 'route.changed') {
    const path = safeProjectedPath(details.path);
    if (path) selected.path = path;
  }
  if (event === 'analysis.selected') copy('analysis_id', value => Number.isInteger(value) && (value as number) >= 1);
  if (event === 'group.selected') copy('group_id', value => Number.isInteger(value) && (value as number) >= 1);
  if (event === 'analysis.mode_changed') copy('analysis_mode', value => value === 'nlp' || value === 'llm');
  if (event === 'filter.changed' && Array.isArray(details.active_filter_fields)) {
    selected.active_filter_fields = details.active_filter_fields
      .filter((item): item is string => typeof item === 'string' && SAFE_FILTER_FIELDS.has(item))
      .slice(0, 8);
  }
  if (event.startsWith('api.request_')) {
    const method = typeof details.method === 'string' ? normalizeMethod(details.method) : '';
    const path = safeProjectedPath(details.path);
    if (SAFE_HTTP_METHODS.has(method)) selected.method = method;
    if (path) selected.path = path;
    copy('status', value => typeof value === 'number' && Number.isInteger(value) && value >= 100 && value <= 599);
    copy('duration_ms', value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 120_000);
    copy('request_id', value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value));
  }
  if (event === 'task.poll_status_changed') copy('poll_status', value => typeof value === 'string' && /^[a-z_]+$/.test(value) && value.length <= 40);
  if (event.startsWith('component.action_')) copy('action', value => typeof value === 'string' && /^[a-z_.-]+$/.test(value) && value.length <= 80);
  return selected;
}

function projectState(value: unknown): DiagnosticState {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const state: DiagnosticState = {};
  const route = safeProjectedPath(source.route);
  if (route) state.route = route;
  if (source.view_type === 'single' || source.view_type === 'group' || source.view_type === 'settings') state.view_type = source.view_type;
  if ((Number.isInteger(source.analysis_id) && (source.analysis_id as number) >= 1) || source.analysis_id === null) state.analysis_id = source.analysis_id as number | null;
  if ((Number.isInteger(source.group_id) && (source.group_id as number) >= 1) || source.group_id === null) state.group_id = source.group_id as number | null;
  if (source.analysis_mode === 'nlp' || source.analysis_mode === 'llm') state.analysis_mode = source.analysis_mode;
  if (typeof source.loading === 'boolean') state.loading = source.loading;
  if (typeof source.reanalyzing === 'boolean') state.reanalyzing = source.reanalyzing;
  if (source.keyword_status === 'ready' || source.keyword_status === 'loading' || source.keyword_status === 'error') state.keyword_status = source.keyword_status;
  if (Array.isArray(source.active_filter_fields)) {
    state.active_filter_fields = source.active_filter_fields
      .filter((item): item is string => typeof item === 'string' && SAFE_FILTER_FIELDS.has(item))
      .slice(0, 8);
  }
  return state;
}

function safeErrorType(error: unknown): string {
  const name = typeof error === 'string' ? error : error instanceof Error ? error.name : '';
  return SAFE_ERROR_TYPES.has(name) ? name : 'Error';
}

function safeStack(error: unknown, componentStack?: string): string | undefined {
  const raw = componentStack || (error instanceof Error ? error.stack : undefined);
  if (!raw) return undefined;
  const frames = raw.split(/\r?\n/)
    .map(line => /^\s*(at|in)\s+(?:(?:async|new)\s+)?([A-Za-z_$][A-Za-z0-9_$.[\]<>-]{0,119})(?:\s|\(|$)/.exec(line))
    .filter((match): match is RegExpExecArray => match !== null)
    .slice(0, 30)
    .map(match => `${match[1]} ${match[2]}`);
  return frames.length > 0 ? frames.join('\n').slice(0, 12_000) : undefined;
}

function utf8Size(value: string): number {
  return new TextEncoder().encode(value).length;
}

function diagnosticEventSize(event: DiagnosticEvent): number {
  return utf8Size(JSON.stringify(event));
}

function fitDiagnosticEvent(event: DiagnosticEvent): DiagnosticEvent {
  const fitted: DiagnosticEvent = {
    ...event,
    breadcrumbs: [...event.breadcrumbs].slice(-ERROR_BREADCRUMB_LIMIT),
    state: projectState(event.state),
  };
  if (diagnosticEventSize(fitted) <= MAX_EVENT_BYTES) return fitted;
  if (fitted.stack) fitted.stack = fitted.stack.slice(0, 2_048);
  while (fitted.breadcrumbs.length > 0 && diagnosticEventSize(fitted) > MAX_EVENT_BYTES) {
    fitted.breadcrumbs.shift();
  }
  if (diagnosticEventSize(fitted) > MAX_EVENT_BYTES) delete fitted.stack;
  return fitted;
}

function createBatchPayload(currentSessionId: string, currentDroppedCount: number): { batch: DiagnosticEvent[]; body: string } {
  let batch: DiagnosticEvent[] = [];
  let body = '';
  for (const event of queuedEvents.slice(0, BATCH_LIMIT)) {
    const candidate = [...batch, event];
    const candidateBody = JSON.stringify({
      session_id: currentSessionId,
      events: candidate,
      dropped_count: currentDroppedCount,
    });
    if (utf8Size(candidateBody) > MAX_BATCH_BYTES) break;
    batch = candidate;
    body = candidateBody;
  }
  if (batch.length === 0) {
    const event = queuedEvents[0];
    batch = [event];
    body = JSON.stringify({ session_id: currentSessionId, events: batch, dropped_count: currentDroppedCount });
  }
  return { batch, body };
}

function scheduleRetry(): void {
  if (retryTimer !== null || !timerImplementation) return;
  retryTimer = timerImplementation(() => {
    retryTimer = null;
    if (sessionId) void flushDiagnostics();
    else void initializeDevDiagnostics();
  }, RETRY_DELAY_MS);
}

export function recordBreadcrumb(event: BreadcrumbEvent, details: Record<string, unknown> = {}): void {
  if (!isDevEnabled()) return;
  const breadcrumb = { event, ...projectBreadcrumbDetails(event, details) } as Breadcrumb;
  const signature = JSON.stringify(breadcrumb);
  if (!event.startsWith('api.request_')) {
    const previousContext = recentContextBreadcrumbs.get(event);
    const recordedAt = Date.now();
    if (previousContext?.signature === signature && recordedAt - previousContext.recordedAt < 250) return;
    recentContextBreadcrumbs.set(event, { signature, recordedAt });
  }
  const previous = breadcrumbs.at(-1);
  if (previous && JSON.stringify(previous) === signature) return;
  breadcrumbs.push(breadcrumb);
  if (breadcrumbs.length > BREADCRUMB_LIMIT) breadcrumbs = breadcrumbs.slice(-BREADCRUMB_LIMIT);
}

export function reportDiagnosticError(
  event: DiagnosticErrorEvent,
  error?: unknown,
  componentStack?: string,
  stateOverride?: DiagnosticState,
): void {
  if (!isDevEnabled()) return;
  ensureStoredQueueLoaded();
  const stack = safeStack(error, componentStack);
  const diagnostic = fitDiagnosticEvent({
    event,
    error_type: safeErrorType(error),
    ...(stack ? { stack } : {}),
    breadcrumbs: breadcrumbs.slice(-ERROR_BREADCRUMB_LIMIT),
    state: projectState(stateOverride ?? stateProvider()),
  });
  queuedEvents.push(diagnostic);
  if (queuedEvents.length > QUEUE_LIMIT) {
    const removed = queuedEvents.length - QUEUE_LIMIT;
    const removedEvents = queuedEvents.slice(0, removed);
    const removedRestoredEvents = removedEvents.filter(event => restoredBoundEvents.has(event));
    restoredBoundDroppedCount += removedRestoredEvents.length;
    for (const event of removedRestoredEvents) restoredBoundEvents.delete(event);
    queuedEvents = queuedEvents.slice(-QUEUE_LIMIT);
    droppedCount += removed;
  }
  safeStorageWrite();
  if (sessionId) void flushDiagnostics();
  else scheduleRetry();
}

export function recordApiRequestStarted(method: string, path: string): void {
  recordBreadcrumb('api.request_started', { method: normalizeMethod(method), path: normalizePath(path) });
}

export function recordApiRequestCompleted(method: string, path: string, status: number, durationMs: number, requestId?: string | null): void {
  recordBreadcrumb('api.request_completed', apiDetails(method, path, status, durationMs, requestId));
}

export function recordApiRequestFailed(method: string, path: string, status: number, durationMs: number, requestId?: string | null, error?: unknown): void {
  recordBreadcrumb('api.request_failed', apiDetails(method, path, status, durationMs, requestId));
  reportDiagnosticError('api.request_failed', error);
}

function apiDetails(method: string, path: string, status: number, durationMs: number, requestId?: string | null): Record<string, unknown> {
  return {
    method: normalizeMethod(method), path: normalizePath(path), status,
    duration_ms: Math.max(0, Math.round(durationMs)),
    ...(requestId ? { request_id: requestId } : {}),
  };
}

function normalizeMethod(method: string): string {
  return method.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 10) || 'GET';
}

function safeProjectedPath(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const path = normalizePath(value);
  return SAFE_PATH_PATTERN.test(path) ? path : undefined;
}

export function normalizePath(path: string): string {
  try {
    const pathname = new URL(path, 'http://diagnostics.local').pathname
      .replace(/\/BV[0-9A-Za-z]+(?=\/|$)/g, '/:bv')
      .replace(/\/\d+(?=\/|$)/g, '/:id');
    return pathname.slice(0, 160) || '/';
  } catch {
    return '/';
  }
}

export function setDiagnosticState(next: DiagnosticState): void {
  stateProvider = () => projectState(next);
}

export async function initializeDevDiagnostics(): Promise<void> {
  if (!isDevEnabled() || !fetchImplementation) return;
  ensureStoredQueueLoaded();
  try {
    const response = await fetchImplementation(`${DIAGNOSTICS_PATH}/session`, { method: 'GET' });
    if (!response.ok) {
      if (response.status !== 404 && queuedEvents.length > 0) scheduleRetry();
      return;
    }
    const configuration = await response.json() as { enabled?: unknown; session_id?: unknown };
    if (configuration.enabled !== true || typeof configuration.session_id !== 'string' || !configuration.session_id) return;
    if (sessionId !== configuration.session_id) {
      if (restoredSessionId && restoredSessionId !== configuration.session_id) {
        queuedEvents = queuedEvents.filter(event => !restoredBoundEvents.has(event));
        droppedCount = Math.max(0, droppedCount - restoredBoundDroppedCount);
      }
      restoredSessionId = null;
      restoredBoundEvents.clear();
      restoredBoundDroppedCount = 0;
      sessionId = configuration.session_id;
      safeStorageRemove('pending');
      safeStorageWrite();
    }
    await flushDiagnostics();
  } catch {
    if (queuedEvents.length > 0) scheduleRetry();
  }
}

export async function flushDiagnostics(): Promise<void> {
  if (!isDevEnabled() || !sessionId || !fetchImplementation || flushInFlight || queuedEvents.length === 0) return;
  flushInFlight = true;
  try {
    while (queuedEvents.length > 0) {
      const reportedDroppedCount = Math.min(droppedCount, MAX_REPORTED_DROPPED_COUNT);
      const activeSessionId = sessionId;
      if (!activeSessionId) throw new Error('diagnostics session unavailable');
      const { batch, body } = createBatchPayload(activeSessionId, reportedDroppedCount);
      const response = await fetchImplementation(`${DIAGNOSTICS_PATH}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      });
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) {
          restoredSessionId = activeSessionId;
          restoredBoundEvents = new Set(queuedEvents);
          restoredBoundDroppedCount = droppedCount;
          sessionId = null;
          safeStorageWrite();
        }
        throw new Error('diagnostics unavailable');
      }
      const delivered = new Set(batch);
      queuedEvents = queuedEvents.filter(event => !delivered.has(event));
      droppedCount = Math.max(0, droppedCount - reportedDroppedCount);
      safeStorageWrite();
    }
  } catch {
    safeStorageWrite();
    scheduleRetry();
  } finally {
    flushInFlight = false;
  }
}

export function installGlobalErrorHandlers(): void {
  if (!isDevEnabled() || globalListenersInstalled || !eventTarget) return;
  globalListenersInstalled = true;
  eventTarget.addEventListener('error', event => reportDiagnosticError('window.error', (event as globalThis.ErrorEvent).error));
  eventTarget.addEventListener('unhandledrejection', event => reportDiagnosticError('window.unhandledrejection', (event as PromiseRejectionEvent).reason));
}

export function activeFilterFields(filters: {
  gender?: unknown;
  dateFrom?: unknown;
  dateTo?: unknown;
  region?: unknown;
  sentiment?: unknown;
  duplicateMode?: unknown;
  sourceAnalysisId?: unknown;
}): string[] {
  const fields: string[] = [];
  if (filters.gender && filters.gender !== 'all') fields.push('gender');
  if (filters.dateFrom || filters.dateTo) fields.push('date_range');
  if (filters.region) fields.push('region');
  if (filters.sentiment && filters.sentiment !== 'all') fields.push('sentiment');
  if (filters.duplicateMode && filters.duplicateMode !== 'include') fields.push('duplicate_mode');
  if (filters.sourceAnalysisId && filters.sourceAnalysisId !== 'all') fields.push('source_analysis_id');
  return fields;
}

export function __resetDevDiagnosticsForTests(options: {
  fetch?: typeof fetch | null;
  storage?: StorageLike | null;
  eventTarget?: EventTargetLike | null;
  timer?: TimerLike | null;
} = {}): void {
  breadcrumbs = [];
  queuedEvents = [];
  droppedCount = 0;
  sessionId = null;
  stateProvider = () => ({});
  flushInFlight = false;
  retryTimer = null;
  globalListenersInstalled = false;
  pendingStorageLoaded = false;
  restoredSessionId = null;
  restoredBoundEvents = new Set<DiagnosticEvent>();
  restoredBoundDroppedCount = 0;
  recentContextBreadcrumbs = new Map<BreadcrumbEvent, { signature: string; recordedAt: number }>();
  devOverride = true;
  fetchImplementation = options.fetch ?? null;
  storage = options.storage ?? null;
  eventTarget = options.eventTarget ?? null;
  timerImplementation = options.timer ?? null;
}

export function __diagnosticsSnapshotForTests(): { breadcrumbs: Breadcrumb[]; queuedEvents: DiagnosticEvent[]; droppedCount: number } {
  return { breadcrumbs: [...breadcrumbs], queuedEvents: [...queuedEvents], droppedCount };
}

export function __safeSessionStorageForTests(target: unknown): StorageLike | null {
  return safeSessionStorage(target as { readonly sessionStorage: Storage } | null);
}
