import { useState, useEffect } from 'react';
import type { AnalysisMode, FilterState } from '../types';
import DateRangePicker from './DateRangePicker';
import FilterSelect, { type FilterSelectOption } from './FilterSelect';

interface Props {
  filters: FilterState;
  onApply: (f: FilterState) => void;
  availableRegions: string[];
  mode: AnalysisMode;
}

const NLP_SENTIMENTS = [
  ['positive', '正面'], ['neutral', '中性'], ['negative', '负面'],
] as const;
const LLM_SENTIMENTS = [
  ['neutral', '中性'], ['joy', '喜悦'], ['support', '支持'], ['anticipation', '期待'],
  ['surprise', '惊讶'], ['anger', '愤怒'], ['sadness', '悲伤'], ['concern', '担忧'], ['disgust', '厌恶'],
] as const;

export default function FilterBar({ filters, onApply, availableRegions, mode }: Props) {
  const [draft, setDraft] = useState<FilterState>(filters);
  useEffect(() => { setDraft(filters); }, [filters]);

  const update = (patch: Partial<FilterState>) => setDraft(prev => ({ ...prev, ...patch }));
  const changed = draft.gender !== filters.gender || draft.dateFrom !== filters.dateFrom
    || draft.dateTo !== filters.dateTo || draft.region !== filters.region
    || draft.sentiment !== filters.sentiment;
  const hasActiveFilter = filters.gender !== 'all' || Boolean(filters.dateFrom || filters.dateTo || filters.region)
    || filters.sentiment !== 'all';
  const sentimentOptions = mode === 'llm' ? LLM_SENTIMENTS : NLP_SENTIMENTS;
  const regionOptions: FilterSelectOption<string>[] = [
    { value: '', label: '全部地域' },
    ...availableRegions.map(region => ({ value: region, label: region })),
  ];
  const sentimentFilterOptions: FilterSelectOption<FilterState['sentiment']>[] = [
    { value: 'all', label: '全部情绪' },
    ...sentimentOptions.map(([value, label]) => ({ value, label })),
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

      <FilterSelect
        ariaLabel="情绪筛选"
        value={draft.sentiment}
        options={sentimentFilterOptions}
        onChange={sentiment => update({ sentiment })}
      />

      <button onClick={() => onApply(draft)}
        disabled={!changed}
        style={{
          padding: '.25rem .75rem', fontSize: '.6875rem', fontWeight: 600,
          background: changed ? 'var(--accent)' : 'var(--border)',
          color: changed ? '#fff' : 'var(--text-muted)',
          border: 'none', borderRadius: '.375rem', cursor: changed ? 'pointer' : 'default',
          transition: 'all .15s ease',
        }}>
        应用筛选
      </button>

      {(changed || hasActiveFilter) && (
        <button onClick={() => onApply({ gender: 'all', dateFrom: '', dateTo: '', region: '', sentiment: 'all' })}
          style={{
            padding: '.25rem .5rem', fontSize: '.6875rem', color: 'var(--text-muted)',
            background: 'transparent', border: '1px solid var(--border)', borderRadius: '.375rem', cursor: 'pointer',
          }}>
          重置
        </button>
      )}
    </div>
  );
}
