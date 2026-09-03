import type { AnalysisMode, CommentData, FilterState } from '../types';

export const EMPTY_FILTERS: FilterState = {
  gender: 'all',
  dateFrom: '',
  dateTo: '',
  region: '',
  sentiment: 'all',
  duplicateMode: 'include',
  sourceAnalysisId: 'all',
};

const PROVINCES = new Set(['北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江', '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '海南', '四川', '贵州', '云南', '陕西', '甘肃', '青海', '台湾', '内蒙古', '广西', '西藏', '宁夏', '新疆', '香港', '澳门']);

export function normalizeProvince(raw: string): string {
  const s = (raw || '').replace(/^IP属地[：:]/, '');
  if (!s || s === '未知' || s === '其它' || s === '中国') return '';
  if (PROVINCES.has(s)) return s;
  for (const p of PROVINCES) { if (s.startsWith(p)) return p; }
  if (s.startsWith('中国') && s.length > 2) { const sf = s.slice(2); if (PROVINCES.has(sf)) return sf; }
  return s;
}

export function applyDuplicateMode(comments: CommentData[], duplicateMode: FilterState['duplicateMode']): CommentData[] {
  if (duplicateMode === 'deduplicate') {
    return comments.filter(comment => !comment.is_exact_duplicate || comment.is_duplicate_canonical);
  }
  if (duplicateMode === 'exclude_groups') {
    return comments.filter(comment => !comment.is_exact_duplicate);
  }
  return comments;
}

export function applyCommentFilters(comments: CommentData[], filters: FilterState, mode: AnalysisMode, llmSchemaVersion?: number): CommentData[] {
  let list = applyDuplicateMode(comments, filters.duplicateMode);
  if (filters.sourceAnalysisId !== 'all') list = list.filter(comment => String(comment.source_analysis_id) === filters.sourceAnalysisId);
  if (filters.gender === 'male') list = list.filter(comment => comment.gender === '男');
  if (filters.gender === 'female') list = list.filter(comment => comment.gender === '女');
  if (filters.dateFrom) list = list.filter(comment => comment.post_time && comment.post_time.slice(0, 10) >= filters.dateFrom);
  if (filters.dateTo) list = list.filter(comment => comment.post_time && comment.post_time.slice(0, 10) <= filters.dateTo);
  if (filters.region) list = list.filter(comment => normalizeProvince(comment.ip_location) === filters.region);
  if (filters.sentiment !== 'all') {
    list = mode === 'llm'
      ? list.filter(comment => comment.sentiment_llm_label === filters.sentiment
        && (llmSchemaVersion !== 2 || comment.sentiment_llm_schema_version === 2))
      : list.filter(comment => comment.sentiment_label === filters.sentiment);
  }
  return list;
}

export interface DuplicateGroup {
  key: string;
  content: string;
  count: number;
  firstPostTime: string | null;
  lastPostTime: string | null;
}

export function buildDuplicateGroups(comments: CommentData[], prefixWithSource = false): DuplicateGroup[] {
  const groups = new Map<string, CommentData[]>();
  for (const comment of comments) {
    if (!comment.duplicate_group_key) continue;
    const key = prefixWithSource
      ? `${comment.source_analysis_id ?? 'unknown'}:${comment.duplicate_group_key}`
      : comment.duplicate_group_key;
    const members = groups.get(key) || [];
    members.push(comment);
    groups.set(key, members);
  }
  return Array.from(groups.entries()).map(([key, members]) => {
    let firstPostTime: string | null = null;
    let lastPostTime: string | null = null;
    for (const member of members) {
      const postTime = member.post_time;
      if (!postTime) continue;
      if (!firstPostTime || postTime < firstPostTime) firstPostTime = postTime;
      if (!lastPostTime || postTime > lastPostTime) lastPostTime = postTime;
    }
    return {
      key,
      content: members[0]?.content || '',
      count: members.length,
      firstPostTime,
      lastPostTime,
    };
  }).sort((left, right) => right.count - left.count || left.key.localeCompare(right.key));
}

export function listRegions(comments: CommentData[]): string[] {
  const regions = new Set<string>();
  comments.forEach(comment => {
    const province = normalizeProvince(comment.ip_location);
    if (province) regions.add(province);
  });
  return Array.from(regions).sort();
}
