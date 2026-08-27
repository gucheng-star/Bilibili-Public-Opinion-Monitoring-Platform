import assert from 'node:assert/strict';
import test from 'node:test';
import { LatestRequestGuard, runConfirmedWorkflowTransition } from '../src/services/latestRequestGuard.ts';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

test('反向完成时只允许最新请求应用结果', async () => {
  const guard = new LatestRequestGuard();
  const first = deferred();
  const second = deferred();
  const applied = [];

  const run = async (ticket, work) => {
    const value = await work;
    if (guard.isCurrent(ticket)) applied.push(value);
  };

  const firstRun = run(guard.begin(), first.promise);
  const secondRun = run(guard.begin(), second.promise);
  second.resolve('newest');
  first.resolve('stale');
  await Promise.all([firstRun, secondRun]);

  assert.deepEqual(applied, ['newest']);
});

test('取消会使当前请求失效', async () => {
  const guard = new LatestRequestGuard();
  const pending = deferred();
  const applied = [];
  const ticket = guard.begin();
  const run = pending.promise.then(value => {
    if (guard.isCurrent(ticket)) applied.push(value);
  });

  guard.invalidate();
  pending.resolve('cancelled-work');
  await run;

  assert.deepEqual(applied, []);
});

test('旧请求晚到的异常不会覆盖新请求状态', async () => {
  const guard = new LatestRequestGuard();
  const stale = deferred();
  const errors = [];
  const staleTicket = guard.begin();
  const staleRun = stale.promise.catch(error => {
    if (guard.isCurrent(staleTicket)) errors.push(error.message);
  });

  const currentTicket = guard.begin();
  stale.reject(new Error('stale failure'));
  await staleRun;

  assert.equal(guard.isCurrent(currentTicket), true);
  assert.deepEqual(errors, []);
});

test('已确认的退出转换不会被后续业务 workflow 静默忽略', async () => {
  const guard = new LatestRequestGuard();
  const logout = deferred();
  const committed = [];

  const transition = runConfirmedWorkflowTransition(guard, logout.promise, value => {
    committed.push(value);
  });
  const laterWorkflow = guard.begin();
  logout.resolve('logged-out');

  await transition;
  assert.deepEqual(committed, ['logged-out']);
  assert.equal(guard.isCurrent(laterWorkflow), false);
});

test('退出未确认时不会使现有 workflow 失效', async () => {
  const guard = new LatestRequestGuard();
  const activeWorkflow = guard.begin();
  const logout = deferred();
  const transition = runConfirmedWorkflowTransition(guard, logout.promise, () => {
    assert.fail('失败的退出不应执行确认回调');
  });

  assert.equal(guard.isCurrent(activeWorkflow), true);
  logout.reject(new Error('logout failed'));
  await assert.rejects(transition, /logout failed/);
  assert.equal(guard.isCurrent(activeWorkflow), true);
});
