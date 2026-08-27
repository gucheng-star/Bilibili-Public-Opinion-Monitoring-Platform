import assert from 'node:assert/strict';
import test from 'node:test';
import {
  __diagnosticsSnapshotForTests,
  __resetDevDiagnosticsForTests,
  __safeSessionStorageForTests,
  initializeDevDiagnostics,
  installGlobalErrorHandlers,
  normalizePath,
  recordApiRequestFailed,
  recordBreadcrumb,
  reportDiagnosticError,
  setDiagnosticState,
} from '../src/services/devDiagnostics.ts';

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
    values,
  };
}

test('breadcrumb 保留 50 条，错误只附带最近 20 条', () => {
  __resetDevDiagnosticsForTests();
  for (let index = 0; index < 55; index += 1) recordBreadcrumb('analysis.selected', { analysis_id: index });
  reportDiagnosticError('window.error', new Error('不应写入的评论正文'));
  const snapshot = __diagnosticsSnapshotForTests();
  assert.equal(snapshot.breadcrumbs.length, 50);
  assert.equal(snapshot.breadcrumbs[0].analysis_id, 5);
  assert.equal(snapshot.queuedEvents[0].breadcrumbs.length, 20);
  assert.equal(snapshot.queuedEvents[0].breadcrumbs[0].analysis_id, 35);
});

test('错误边界可用渲染当下状态覆盖尚未提交的全局状态', () => {
  __resetDevDiagnosticsForTests();
  setDiagnosticState({ route: '/', view_type: 'single', analysis_id: 7, loading: false });
  reportDiagnosticError(
    'react.error_boundary',
    new Error('render failed'),
    undefined,
    { route: '/', view_type: 'group', group_id: 42, analysis_mode: 'llm', loading: true },
  );
  const state = __diagnosticsSnapshotForTests().queuedEvents[0].state;
  assert.deepEqual(state, {
    route: '/',
    view_type: 'group',
    group_id: 42,
    analysis_mode: 'llm',
    loading: true,
  });
});

test('离线队列最多 100 条，溢出丢弃最旧项并计数', () => {
  __resetDevDiagnosticsForTests();
  for (let index = 0; index < 101; index += 1) reportDiagnosticError('window.error', new Error(String(index)));
  const snapshot = __diagnosticsSnapshotForTests();
  assert.equal(snapshot.queuedEvents.length, 100);
  assert.equal(snapshot.droppedCount, 1);
});

test('同一会话恢复后按最多 20 条补写，并在成功后移除', async () => {
  const storage = memoryStorage();
  const savedEvents = Array.from({ length: 21 }, () => ({ event: 'window.error', breadcrumbs: [], state: {} }));
  storage.setItem('bili.dev-diagnostics.last-session', 'session-a');
  storage.setItem('bili.dev-diagnostics.session-a', JSON.stringify({ events: savedEvents, dropped_count: 3 }));
  const batches = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-a' });
    batches.push(JSON.parse(options.body));
    return response({ accepted: batches.at(-1).events.length });
  };
  __resetDevDiagnosticsForTests({ fetch, storage });
  await initializeDevDiagnostics();
  const snapshot = __diagnosticsSnapshotForTests();
  assert.deepEqual(batches.map(batch => batch.events.length), [20, 1]);
  assert.deepEqual(batches.map(batch => batch.dropped_count), [3, 0]);
  assert.equal(snapshot.queuedEvents.length, 0);
  assert.equal(JSON.parse(storage.values.get('bili.dev-diagnostics.session-a')).dropped_count, 0);
});

test('后端离线时先写 pending，刷新并恢复后仍能补写', async () => {
  const storage = memoryStorage();
  __resetDevDiagnosticsForTests({ storage });
  reportDiagnosticError('window.error', new Error('不应持久化的评论正文'));
  assert.equal(JSON.parse(storage.values.get('bili.dev-diagnostics.pending')).events.length, 1);

  const posted = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-b' });
    posted.push(JSON.parse(options.body));
    return response({ accepted: posted.at(-1).events.length });
  };
  __resetDevDiagnosticsForTests({ fetch, storage });
  await initializeDevDiagnostics();
  assert.equal(posted.length, 1);
  assert.equal(posted[0].events[0].event, 'window.error');
  assert.equal(storage.values.has('bili.dev-diagnostics.pending'), false);
});

test('初始化前记录的事件不会与 pending 自身重复合并', async () => {
  const storage = memoryStorage();
  const posted = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-c' });
    posted.push(JSON.parse(options.body));
    return response({ accepted: posted.at(-1).events.length });
  };
  __resetDevDiagnosticsForTests({ fetch, storage });
  reportDiagnosticError('startup.failed', new Error('private startup text'));
  await initializeDevDiagnostics();
  assert.equal(posted.length, 1);
  assert.equal(posted[0].events.length, 1);
  assert.equal(posted[0].events[0].event, 'startup.failed');
});

test('已绑定会话的失败队列在刷新离线后自动发现并恢复', async () => {
  const storage = memoryStorage();
  let firstPost = true;
  const firstFetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-d' });
    if (firstPost) {
      firstPost = false;
      return response({}, 503);
    }
    return response({ accepted: JSON.parse(options.body).events.length });
  };
  __resetDevDiagnosticsForTests({ fetch: firstFetch, storage });
  await initializeDevDiagnostics();
  reportDiagnosticError('window.error', new Error('private offline text'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(storage.values.get('bili.dev-diagnostics.last-session'), 'session-d');
  assert.equal(JSON.parse(storage.values.get('bili.dev-diagnostics.session-d')).events.length, 1);

  let retry;
  let getAttempts = 0;
  let resolvePosted;
  const posted = new Promise(resolve => { resolvePosted = resolve; });
  const recoveredFetch = async (_url, options = {}) => {
    if (options.method === 'GET') {
      getAttempts += 1;
      if (getAttempts === 1) throw new Error('backend offline');
      return response({ enabled: true, session_id: 'session-d' });
    }
    resolvePosted(JSON.parse(options.body));
    return response({ accepted: JSON.parse(options.body).events.length });
  };
  __resetDevDiagnosticsForTests({
    fetch: recoveredFetch,
    storage,
    timer: callback => { retry = callback; return 1; },
  });
  await initializeDevDiagnostics();
  assert.equal(typeof retry, 'function');
  retry();
  const recoveredBatch = await posted;
  assert.equal(recoveredBatch.events.length, 1);
  assert.equal(recoveredBatch.events[0].event, 'window.error');
});

test('合法大事件按 8KiB 裁剪且批次不超过 64KiB', async () => {
  const storage = memoryStorage();
  const longPath = '/' + 'a'.repeat(150);
  const breadcrumbs = Array.from({ length: 20 }, () => ({
    event: 'api.request_failed', method: 'GET', path: longPath, status: 500,
    duration_ms: 120000, request_id: 'request-123',
  }));
  const stack = Array.from({ length: 30 }, (_, index) => `    at Component${index}${'A'.repeat(60)} (http://localhost:5173/src/App.tsx:1:1)`).join('\n');
  const savedEvents = Array.from({ length: 20 }, () => ({
    event: 'window.error', error_type: 'TypeError', stack, breadcrumbs,
    state: { route: '/', view_type: 'single', analysis_mode: 'nlp', loading: true },
  }));
  storage.setItem('bili.dev-diagnostics.last-session', 'session-e');
  storage.setItem('bili.dev-diagnostics.session-e', JSON.stringify({ events: savedEvents, dropped_count: 0 }));
  const bodies = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-e' });
    bodies.push(options.body);
    return response({ accepted: JSON.parse(options.body).events.length });
  };
  __resetDevDiagnosticsForTests({ fetch, storage });
  await initializeDevDiagnostics();
  const batches = bodies.map(body => JSON.parse(body));
  assert.equal(batches.flatMap(batch => batch.events).length, 20);
  assert.ok(bodies.every(body => new TextEncoder().encode(body).length <= 64 * 1024));
  assert.ok(batches.flatMap(batch => batch.events).every(event => new TextEncoder().encode(JSON.stringify(event)).length <= 8 * 1024));
});

test('StrictMode 重放不会重复写入相同上下文 breadcrumb', () => {
  __resetDevDiagnosticsForTests();
  for (let pass = 0; pass < 2; pass += 1) {
    recordBreadcrumb('route.changed', { path: '/' });
    recordBreadcrumb('analysis.mode_changed', { analysis_mode: 'nlp' });
    recordBreadcrumb('filter.changed', { active_filter_fields: [] });
  }
  assert.deepEqual(__diagnosticsSnapshotForTests().breadcrumbs.map(item => item.event), [
    'route.changed', 'analysis.mode_changed', 'filter.changed',
  ]);
});

test('sessionStorage 属性读取抛错时诊断模块安全降级', () => {
  const target = {};
  Object.defineProperty(target, 'sessionStorage', { get: () => { throw new Error('blocked'); } });
  assert.equal(__safeSessionStorageForTests(target), null);
});

test('全局 error 与 rejection 监听只安装一次', () => {
  const handlers = [];
  __resetDevDiagnosticsForTests({ eventTarget: { addEventListener: (type, handler) => handlers.push([type, handler]) } });
  installGlobalErrorHandlers();
  installGlobalErrorHandlers();
  assert.deepEqual(handlers.map(([type]) => type), ['error', 'unhandledrejection']);
});

test('路径、状态投影和 API 失败事件不包含秘密或请求内容', () => {
  __resetDevDiagnosticsForTests();
  setDiagnosticState({
    route: '/settings?api_key=must-not-appear',
    view_type: 'settings',
    loading: true,
    searchDraft: '评论正文不得出现',
    localToken: 'local-token-must-not-appear',
  });
  recordApiRequestFailed('post', '/api/analysis-groups/3/results?api_key=must-not-appear', 401, 7.3, 'request-123', new Error('Cookie=must-not-appear'));
  const snapshot = __diagnosticsSnapshotForTests();
  const serialized = JSON.stringify(snapshot);
  assert.equal(normalizePath('/api/analysis-groups/3/results?api_key=x'), '/api/analysis-groups/:id/results');
  assert.equal(snapshot.queuedEvents[0].state.view_type, 'settings');
  assert.equal(snapshot.queuedEvents[0].state.loading, true);
  assert.equal('searchDraft' in snapshot.queuedEvents[0].state, false);
  assert.equal('localToken' in snapshot.queuedEvents[0].state, false);
  assert.doesNotMatch(serialized, /must-not-appear|评论正文|local-token/i);
});

test('字符串 rejection 永不被解释为 stack', () => {
  const storage = memoryStorage();
  __resetDevDiagnosticsForTests({ storage });
  reportDiagnosticError(
    'window.unhandledrejection',
    '评论正文不得入队\n    at safeRender (http://localhost:5173/App.tsx?api_key=must-not-appear:1:2)\n    at sk-secret-value\n    at 评论正文不得出现',
  );
  const snapshot = __diagnosticsSnapshotForTests();
  const persisted = storage.values.get('bili.dev-diagnostics.pending');
  assert.equal(snapshot.queuedEvents[0].stack, undefined);
  assert.doesNotMatch(persisted, /must-not-appear|评论正文|localhost|App\.tsx|sk-secret-value/i);
});

test('恢复的旧版事件按当前服务端契约投影，不会因 422 头阻塞', async () => {
  const storage = memoryStorage();
  storage.setItem('bili.dev-diagnostics.last-session', 'session-old');
  storage.setItem('bili.dev-diagnostics.session-old', JSON.stringify({
    events: [{
      event: 'window.error',
      error_type: 'UnexpectedPrivateType',
      breadcrumbs: [
        { event: 'route.changed', path: '/评论正文' },
        { event: 'api.request_failed', method: 'OPTIONS', path: '/safe?api_key=secret', status: 500 },
        { event: 'filter.changed', active_filter_fields: ['gender', '评论正文'] },
      ],
      state: { route: '/settings?api_key=secret', active_filter_fields: ['region', '评论正文'] },
    }],
    dropped_count: 999_999,
  }));
  const posted = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-old' });
    const body = JSON.parse(options.body);
    posted.push(body);
    const serialized = JSON.stringify(body);
    const backendSafe = !serialized.includes('评论正文')
      && !serialized.includes('OPTIONS')
      && !serialized.includes('secret')
      && body.dropped_count <= 100_000;
    return response({ accepted: body.events.length }, backendSafe ? 200 : 422);
  };

  __resetDevDiagnosticsForTests({ fetch, storage });
  await initializeDevDiagnostics();

  assert.equal(posted.length, 1);
  assert.equal(__diagnosticsSnapshotForTests().queuedEvents.length, 0);
  assert.equal(posted[0].dropped_count, 100_000);
  assert.deepEqual(posted[0].events[0].breadcrumbs, [
    { event: 'route.changed' },
    { event: 'api.request_failed', path: '/safe', status: 500 },
    { event: 'filter.changed', active_filter_fields: ['gender'] },
  ]);
  assert.deepEqual(posted[0].events[0].state, {
    route: '/settings',
    active_filter_fields: ['region'],
  });
});

test('新会话不承接被丢弃旧会话的 overflow 计数', async () => {
  const storage = memoryStorage();
  const oldEvents = Array.from({ length: 100 }, () => ({
    event: 'window.error', breadcrumbs: [], state: {},
  }));
  storage.setItem('bili.dev-diagnostics.last-session', 'session-old');
  storage.setItem('bili.dev-diagnostics.session-old', JSON.stringify({ events: oldEvents, dropped_count: 7 }));
  storage.setItem('bili.dev-diagnostics.pending', JSON.stringify({
    events: [{ event: 'startup.failed', breadcrumbs: [], state: {} }],
    dropped_count: 0,
  }));
  const posted = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') return response({ enabled: true, session_id: 'session-new' });
    posted.push(JSON.parse(options.body));
    return response({ accepted: JSON.parse(options.body).events.length });
  };

  __resetDevDiagnosticsForTests({ fetch, storage });
  await initializeDevDiagnostics();

  assert.equal(posted.length, 1);
  assert.equal(posted[0].events.length, 1);
  assert.equal(posted[0].events[0].event, 'startup.failed');
  assert.equal(posted[0].dropped_count, 0);
});

test('403 后新事件挤掉旧会话事件时，overflow 仍归属旧会话', async () => {
  const storage = memoryStorage();
  const oldEvents = Array.from({ length: 100 }, () => ({
    event: 'window.error', breadcrumbs: [], state: {},
  }));
  storage.setItem('bili.dev-diagnostics.last-session', 'session-old');
  storage.setItem('bili.dev-diagnostics.session-old', JSON.stringify({ events: oldEvents, dropped_count: 0 }));
  let sessionAttempt = 0;
  let postAttempt = 0;
  const posted = [];
  const fetch = async (_url, options = {}) => {
    if (options.method === 'GET') {
      sessionAttempt += 1;
      return response({ enabled: true, session_id: sessionAttempt === 1 ? 'session-old' : 'session-new' });
    }
    postAttempt += 1;
    const body = JSON.parse(options.body);
    if (postAttempt === 1) return response({}, 403);
    posted.push(body);
    return response({ accepted: body.events.length });
  };

  __resetDevDiagnosticsForTests({ fetch, storage });
  await initializeDevDiagnostics();
  reportDiagnosticError('startup.failed', new Error('new session error'));
  await initializeDevDiagnostics();

  assert.equal(posted.length, 1);
  assert.equal(posted[0].events.length, 1);
  assert.equal(posted[0].events[0].event, 'startup.failed');
  assert.equal(posted[0].dropped_count, 0);
});
