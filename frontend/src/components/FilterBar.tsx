import { useState, useEffect } from 'react';
import type { FilterState } from '../types';

interface Props {
  filters: FilterState;
  onApply: (f: FilterState) => void;
  availableRegions: string[];
}

export default function FilterBar({ filters, onApply, availableRegions }: Props) {
  const [draft, setDraft] = useState<FilterState>(filters);
  useEffect(() => { setDraft(filters); }, [filters]);

  const update = (patch: Partial<FilterState>) => setDraft(prev => ({ ...prev, ...patch }));
  const changed = draft.gender !== filters.gender || draft.dateFrom !== filters.dateFrom || draft.dateTo !== filters.dateTo || draft.region !== filters.region;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '.75rem', padding: '.5rem 0',
      flexWrap: 'wrap', borderBottom: '1px solid var(--border)', marginBottom: '.75rem',
    }}>
      <span style={{ fontSize: '.75rem', color: 'var(--text-muted)', fontWeight: 500 }}>筛选</span>

      <div className="segmented" style={{ fontSize: '.6875rem' }}>
        <button className={draft.gender === 'all' ? 'active' : ''} onClick={() => update({ gender: 'all' })}>全部</button>
        <button className={draft.gender === 'male' ? 'active' : ''} onClick={() => update({ gender: 'male' })}>仅男</button>
        <button className={draft.gender === 'female' ? 'active' : ''} onClick={() => update({ gender: 'female' })}>仅女</button>
      </div>

      <input type="date" value={draft.dateFrom}
        onChange={e => update({ dateFrom: e.target.value })}
        style={{
          padding: '.25rem .5rem', fontSize: '.6875rem', background: 'var(--bg)',
          color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '.375rem',
        }} />

      <span style={{ fontSize: '.6875rem', color: 'var(--text-muted)' }}>至</span>

      <input type="date" value={draft.dateTo}
        onChange={e => update({ dateTo: e.target.value })}
        style={{
          padding: '.25rem .5rem', fontSize: '.6875rem', background: 'var(--bg)',
          color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '.375rem',
        }} />

      <select value={draft.region}
        onChange={e => update({ region: e.target.value })}
        style={{
          padding: '.25rem .5rem', fontSize: '.6875rem', background: 'var(--bg)',
          color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: '.375rem',
        }}>
        <option value="">全部地域</option>
        {availableRegions.map(r => <option key={r} value={r}>{r}</option>)}
      </select>

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

      {changed && (
        <button onClick={() => onApply({ gender: 'all', dateFrom: '', dateTo: '', region: '' })}
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
