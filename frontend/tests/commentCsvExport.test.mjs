import assert from 'node:assert/strict';
import test from 'node:test';
import { buildCommentCsv, escapeCsvCell } from '../src/utils/commentCsvExport.ts';

const exportedAt = new Date(2026, 8, 4, 12, 34, 56);

function comment(id, overrides = {}) {
  return {
    id, rpid: id, root_rpid: id, parent_rpid: null,
    username: '用户', gender: '未知', ip_location: '上海', content: '普通评论', likes: 0,
    sentiment_label: 'neutral', sentiment_score: 0,
    sentiment_llm_label: 'joy', sentiment_llm_style: 'plain', sentiment_llm_schema_version: 2,
    post_time: '2026-09-04 12:00:00', is_exact_duplicate: false,
    duplicate_group_size: 0, duplicate_group_key: null, is_duplicate_canonical: false,
    ...overrides,
  };
}

test('默认列按稳定顺序包含固定列和三项模型列，并生成可读样本 ID', () => {
  const result = buildCommentCsv({
    comments: [comment(1)], allComments: [comment(1)],
    defaultSource: { bv: 'BV1abc', videoTitle: '中文标题' }, exportedAt,
  });
  assert.deepEqual(result.headers, ['样本ID', '视频BV号', '视频标题', '评论内容', '大模型主情感', '大模型表达风格', '本地 NLP 情感']);
  assert.deepEqual(result.rows[0], ['EXP20260904-123456-0001', 'BV1abc', '中文标题', '普通评论', '喜悦', '平实', '中性']);
  assert.ok(result.csv.startsWith('\uFEFF样本ID,视频BV号'));
  assert.ok(result.csv.endsWith('\r\n'));
});

test('机器标签统一导出为中文展示值', () => {
  const result = buildCommentCsv({
    comments: [comment(1, { sentiment_llm_label: 'disgust', sentiment_llm_style: 'rhetorical', sentiment_label: 'negative' })],
    allComments: [comment(1)], exportedAt,
  });
  assert.deepEqual(result.rows[0].slice(-3), ['厌恶', '反问', '负面']);
});

test('可选列按规定顺序追加，缺失模型字段保留空单元格', () => {
  const item = comment(1, { sentiment_llm_label: '', sentiment_llm_style: '' });
  const result = buildCommentCsv({
    comments: [item], allComments: [item], exportedAt,
    options: { llmSentiment: true, llmStyle: true, nlpSentiment: false, username: true, likes: true },
  });
  assert.deepEqual(result.headers, ['样本ID', '视频BV号', '视频标题', '用户名', '评论内容', '大模型主情感', '大模型表达风格', '点赞数']);
  assert.deepEqual(result.rows[0].slice(3), ['用户', '普通评论', '', '', '0']);
});

test('CSV 使用 BOM、Windows 换行、RFC 4180 转义和公式前缀防护', () => {
  const item = comment(1, { content: '=中文,\n"引号"', username: '+危险', ip_location: '@位置' });
  const result = buildCommentCsv({
    comments: [item], allComments: [item], exportedAt,
    options: { username: true, ipLocation: true },
  });
  assert.equal(escapeCsvCell(item.content), '"\'=中文,\n""引号"""');
  assert.match(result.csv, /^\uFEFF.*\r\n.*\r\n$/s);
  assert.match(result.csv, /"'=中文,\n""引号"""/);
  assert.match(result.csv, /,'\+危险,'@位置,"'=中文,\n""引号"""/);
});

test('上下文从完整评论池按同一来源查找，根评论和缺失评论保持空值', () => {
  const root = comment(10, { content: '根评论', source_analysis_id: 101 });
  const parent = comment(11, { root_rpid: 10, parent_rpid: 10, content: '父评论', source_analysis_id: 101 });
  const target = comment(12, { root_rpid: 10, parent_rpid: 11, content: '目标评论', source_analysis_id: 101 });
  const missing = comment(13, { root_rpid: 999, parent_rpid: 998, content: '上下文缺失', source_analysis_id: 101 });
  const result = buildCommentCsv({
    comments: [root, target, missing], allComments: [root, parent, target, missing], exportedAt,
    options: { llmSentiment: false, llmStyle: false, nlpSentiment: false, context: true },
    sources: [{ analysisId: 101, bv: 'BV1event', videoTitle: '事件视频' }],
  });
  assert.deepEqual(result.rows.map(row => row.slice(3, 5)), [['', ''], ['根评论', '父评论'], ['', '']]);
});

test('勾选的人工复核信息在评论内容前按固定阅读顺序插入', () => {
  const item = comment(1, { post_time: '2026-09-04 12:00:00', username: '标注者', gender: '女', ip_location: '北京' });
  const result = buildCommentCsv({
    comments: [item], allComments: [item], exportedAt,
    options: { llmSentiment: false, llmStyle: false, nlpSentiment: false, postTime: true, username: true, gender: true, ipLocation: true, context: true },
  });
  assert.deepEqual(result.headers, ['样本ID', '视频BV号', '视频标题', '发布时间', '用户名', '性别', 'IP 属地', '根评论内容', '父评论内容', '评论内容']);
});

test('事件中每条评论优先保留自身来源，单视频使用默认来源', () => {
  const eventOne = comment(1, { source_analysis_id: 1, source_bv: 'BV1one', source_video_title: '视频一' });
  const eventTwo = comment(2, { source_analysis_id: 2, source_video_title: '来源标题优先' });
  const result = buildCommentCsv({
    comments: [eventOne, eventTwo], allComments: [eventOne, eventTwo], exportedAt,
    sources: [
      { analysisId: 1, bv: 'BV1错误来源', videoTitle: '不应使用' },
      { analysisId: 2, bv: 'BV1two', videoTitle: '视频二' },
    ],
  });
  assert.deepEqual(result.rows.map(row => row.slice(1, 3)), [['BV1one', '视频一'], ['BV1two', '来源标题优先']]);
});
