import { useState, useEffect } from 'react';
import type { AnalysisMode, DuplicateStatistics, FilterState } from '../types';
import DateRangePicker from './DateRangePicker';
import FilterSelect, { type FilterSelectOption } from './FilterSelect';

interface Props {
  filters: FilterState;
  onApply: (f: FilterState) => void;
  availableRegions: string[];
  mode: AnalysisMode;
  duplicateStatistics: DuplicateStatistics;
  duplicateGroups: Array<{
    key: string;
    content: string;
    count: number;
    firstPostTime: string | null;
    lastPostTime: string | null;
  }>;
  originalCount: number;
  duplicateRetainedCount: number;
  sources?: Array<{ analysis_id: number; video_title: string; bv: string }>;
}

const NLP_SENTIMENTS = [
  ['positive', '正面'], ['neutral', '中性'], ['negative', '负面'],
] as const;
const LLM_SENTIMENTS = [
  ['neutral', '中性'], ['joy', '喜悦'], ['support', '支持'], ['anticipation', '期待'],
  ['surprise', '惊讶'], ['anger', '愤怒'], ['sadness', '悲伤'], ['concern', '担忧'], ['disgust', '厌恶'], ['sarcasm', '反讽'],
] as const;

const DUPLICATE_OPTIONS: FilterSelectOption<FilterState['duplicateMode']>[] = [
  { value: 'include', label: '包含全部' },
  { value: 'deduplicate', label: '每组保留一条' },
  { value: 'exclude_groups', label: '排除整组' },
];

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN') : '未知';
}

export default function FilterBar({
  filters, onApply, availableRegions, mode, duplicateStatistics, duplicateGroups,
  originalCount, duplicateRetainedCount, sources,
}: Props) {
  const [draft, setDraft] = useState<FilterState>(filters);
  useEffect(() => { setDraft(filters); }, [filters]);

  const update = (patch: Partial<FilterState>) => setDraft(prev => ({ ...prev, ...patch }));
  const changed = draft.gender !== filters.gender || draft.dateFrom !== filters.dateFrom
    || draft.dateTo !== filters.dateTo || draft.region !== filters.region
    || draft.sentiment !== filters.sentiment || draft.duplicateMode !== filters.duplicateMode;
  const sourceChanged = draft.sourceAnalysisId !== filters.sourceAnalysisId;
  const hasActiveFilter = filters.gender !== 'all' || Boolean(filters.dateFrom || filters.dateTo || filters.region)
    || filters.sentiment !== 'all' || filters.duplicateMode !== 'include' || filters.sourceAnalysisId !== 'all';
  const sentimentOptions = mode === 'llm' ? LLM_SENTIMENTS : NLP_SENTIMENTS;
  const regionOptions: FilterSelectOption<string>[] = [
    { value: '', label: '全部地域' },
    ...availableRegions.map(region => ({ value: region, label: region })),
  ];
  const sentimentFilterOptions: FilterSelectOption<FilterState['sentiment']>[] = [
    { value: 'all', label: '全部情绪' },
    ...sentimentOptions.map(([value, label]) => ({ value, label })),
  ];
  const sourceOptions: FilterSelectOption<string>[] = [
    { value: 'all', label: '全部来源视频' },
    ...(sources || []).map(source => ({ value: String(source.analysis_id), label: source.video_title || source.bv })),
  ];

  return (
    <div className="filter-bar">
      <span style={{ fontSize: '.75rem', color: 'var(--text-muted)', fontWeight: 500 }}>筛选</span>

      <div className="segmented" style={{ fontSize: '.6875rem' }}>
        <button className={draft.gender === 'all' ? 'active' : ''} onClick={() => update({ gender: 'all' })}>全部</button>
        <button className={draft.gender === 'male' ? 'active' : ''} onClick={() => update({ gender: 'male' })}>仅男</button>
        <button className={draft.gender === 'female' ? 'active' : ''} onClick={() => update({ gender: 'female' })}>仅女</button>
      </div>

      <DateRangePicker
        dateFrom={draft.dateFrom}
        dateTo={draft.dateTo}
        onChange={range => update(range)}
      />

      <FilterSelect
        ariaLabel="地域筛选"
        value={draft.region}
        options={regionOptions}
        onChange={region => update({ region })}
      />

      {sources && sources.length > 0 && (
        <FilterSelect
          ariaLabel="来源视频筛选"
          value={draft.sourceAnalysisId}
          options={sourceOptions}
          onChange={sourceAnalysisId => update({ sourceAnalysisId })}
        />
      )}

      <FilterSelect
        ariaLabel="重复内容筛选"
        value={draft.duplicateMode}
        options={DUPLICATE_OPTIONS}
        onChange={duplicateMode => update({ duplicateMode })}
      />

      <FilterSelect
        ariaLabel="情绪筛选"
        value={draft.sentiment}
        options={sentimentFilterOptions}
        onChange={sentiment => update({ sentiment })}
      />

      <button onClick={() => onApply(draft)}
        disabled={!changed && !sourceChanged}
        style={{
          padding: '.25rem .75rem', fontSize: '.6875rem', fontWeight: 600,
          background: (changed || sourceChanged) ? 'var(--accent)' : 'var(--border)',
          color: (changed || sourceChanged) ? '#fff' : 'var(--text-muted)',
          border: 'none', borderRadius: '.375rem', cursor: (changed || sourceChanged) ? 'pointer' : 'default',
          transition: 'all .15s ease',
        }}>
        应用筛选
      </button>

      {(changed || hasActiveFilter) && (
        <button onClick={() => onApply({ gender: 'all', dateFrom: '', dateTo: '', region: '', sentiment: 'all', duplicateMode: 'include', sourceAnalysisId: 'all' })}
          style={{
            padding: '.25rem .5rem', fontSize: '.6875rem', color: 'var(--text-muted)',
            background: 'transparent', border: '1px solid var(--border)', borderRadius: '.375rem', cursor: 'pointer',
          }}>
          重置
        </button>
      )}
      <details className="duplicate-quality" open={false}>
        <summary>
          {duplicateStatistics.group_count > 0
            ? `发现 ${duplicateStatistics.group_count} 组完全相同内容，共涉及 ${duplicateStatistics.involved_comments} 条评论`
            : '未发现完全相同的评论内容'}
        </summary>
        <div className="duplicate-quality__panel">
          <p>当前重复内容模式保留 {duplicateRetainedCount} / {originalCount} 条，排除 {originalCount - duplicateRetainedCount} 条。</p>
          <p className="duplicate-quality__notice">重复内容不一定是异常账号或水军，仅供数据清洗参考。</p>
          {duplicateGroups.length > 0 && (
            <ol className="duplicate-quality__groups">
              {duplicateGroups.map(group => (
                <li key={group.key}>
                  <strong>相同内容 × {group.count}</strong>
                  <span>{group.content}</span>
                  <small>{formatTime(group.firstPostTime)} — {formatTime(group.lastPostTime)}</small>
                </li>
              ))}
            </ol>
          )}
        </div>
      </details>
    </div>
  );
}
