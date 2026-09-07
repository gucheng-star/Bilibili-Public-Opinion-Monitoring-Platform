import assert from 'node:assert/strict';
import test from 'node:test';
import { isActiveDanmakuTask, isCurrentDanmakuRequest } from '../src/utils/danmakuTaskRequest.ts';

test('only pending danmaku work is recovered after a submit failure', () => {
  assert.equal(isActiveDanmakuTask('pending'), true);
  assert.equal(isActiveDanmakuTask('fetching'), true);
  assert.equal(isActiveDanmakuTask('analyzing'), true);
  assert.equal(isActiveDanmakuTask('done'), false);
  assert.equal(isActiveDanmakuTask('partial'), false);
  assert.equal(isActiveDanmakuTask('error'), false);
});

test('an obsolete request cannot update a newly selected analysis', () => {
  assert.equal(isCurrentDanmakuRequest(7, 7, 2, 2), true);
  assert.equal(isCurrentDanmakuRequest(7, 8, 2, 2), false);
  assert.equal(isCurrentDanmakuRequest(7, 7, 2, 3), false);
});
