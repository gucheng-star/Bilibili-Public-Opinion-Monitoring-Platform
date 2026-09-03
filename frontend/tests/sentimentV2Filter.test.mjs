import assert from 'node:assert/strict';
import test from 'node:test';
import { applyCommentFilters } from '../src/utils/commentFilters.ts';

const baseFilters = {
  gender: 'all', dateFrom: '', dateTo: '', region: '',
  sentiment: 'neutral', duplicateMode: 'include', sourceAnalysisId: 'all',
};

function comment(id, schemaVersion) {
  return {
    id, rpid: id, root_rpid: null, parent_rpid: null, username: '', gender: '',
    ip_location: '', content: '', likes: 0, sentiment_label: 'neutral',
    sentiment_score: 0, sentiment_llm_label: 'neutral', sentiment_llm_style: 'plain',
    sentiment_llm_schema_version: schemaVersion, post_time: null,
    is_exact_duplicate: false, duplicate_group_size: 0, duplicate_group_key: null,
    is_duplicate_canonical: false,
  };
}

test('V2 情绪筛选不混入旧版本同名标签', () => {
  const result = applyCommentFilters([comment(1, 1), comment(2, 2)], baseFilters, 'llm', 2);
  assert.deepEqual(result.map(item => item.id), [2]);
});

test('旧版 LLM 视图仍按原有标签筛选', () => {
  const result = applyCommentFilters([comment(1, 1), comment(2, 2)], baseFilters, 'llm', 1);
  assert.deepEqual(result.map(item => item.id), [1, 2]);
});
