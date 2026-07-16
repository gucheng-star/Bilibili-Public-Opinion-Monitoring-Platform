import { useEffect, useState } from 'react';
import { getHistory } from '../services/api';
import type { HistoryItem } from '../types';

interface Props { onSelect: (id: number) => void; selectedId: number | null; }

export default function HistoryPanel({ onSelect, selectedId }: Props) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); getHistory().then(setItems).catch(()=>{}).finally(()=>setLoading(false)); };
  useEffect(()=>{load();},[]);

  if (loading) return <div className="text-xs text-muted py-2">加载中...</div>;
  if (!items.length) return null;

  return (
    <div className="flex gap-2 overflow-x-auto" style={{scrollbarWidth:'thin'}}>
      {items.map(item => (
        <button key={item.id} onClick={()=>onSelect(item.id)}
          style={{
            flexShrink:0, padding:'.375rem .625rem', fontSize:'.75rem', borderRadius:'.375rem', cursor:'pointer',
            background: selectedId===item.id ? 'var(--accent-soft)' : 'transparent',
            border: selectedId===item.id ? '1px solid var(--border-accent)' : '1px solid var(--border)',
            color: selectedId===item.id ? 'var(--accent)' : 'var(--text-secondary)',
            transition:'all .15s ease', textAlign:'left', maxWidth:'16rem',
          }}>
          <div className="truncate" style={{fontWeight:500,color:selectedId===item.id?'var(--accent)':'var(--text-primary)'}}>{item.video_title || item.bv}</div>
          <div className="flex items-center gap-2 mt-1" style={{fontSize:'.625rem',color:'var(--text-muted)'}}>
            <span>{item.total_comments} 条评论</span>
            <span style={{padding:'0 .25rem',borderRadius:'.125rem',background:item.status==='done'?'var(--green-soft)':'var(--yellow-soft)',color:item.status==='done'?'var(--green)':'var(--yellow)'}}>
              {item.status==='done'?'完成':item.status}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}