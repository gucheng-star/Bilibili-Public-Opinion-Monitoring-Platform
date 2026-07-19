import { useEffect, useState } from 'react';
import { getHistory, deleteHistory } from '../services/api';
import type { HistoryItem } from '../types';

interface Props {
  onSelect: (id: number) => void;
  selectedId: number | null;
  refreshKey?: number;
  onDelete?: () => void;
}

export default function HistoryPanel({ onSelect, selectedId, refreshKey = 0, onDelete }: Props) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmItem, setConfirmItem] = useState<HistoryItem | null>(null);
  const load = () => { setLoading(true); getHistory().then(setItems).catch(()=>{}).finally(()=>setLoading(false)); };
  useEffect(()=>{load();},[refreshKey]);

  const handleDelete = async () => {
    if (!confirmItem) return;
    try { await deleteHistory(confirmItem.id); load(); onDelete?.(); }
    catch { alert('删除失败'); }
    setConfirmItem(null);
  };

  if (loading) return <div className="text-xs text-muted py-2">加载中...</div>;
  if (!items.length) return <div className="text-xs text-muted py-2">暂无历史记录</div>;

  return (
    <>
      <div className="history-scroll" style={{display:'flex',gap:'.5rem',overflowX:'auto',paddingBottom:'.25rem'}}>
        {items.map(item => (
          <div key={item.id} style={{position:'relative',flexShrink:0}}>
            <button onClick={()=>onSelect(item.id)}
              style={{
                padding:'.375rem 1.5rem .375rem .625rem', fontSize:'.75rem', borderRadius:'.375rem', cursor:'pointer',
                background: selectedId===item.id ? 'var(--accent-soft)' : 'transparent',
                border: selectedId===item.id ? '1px solid var(--border-accent)' : '1px solid var(--border)',
                color: selectedId===item.id ? 'var(--accent)' : 'var(--text-secondary)',
                transition:'all .15s ease', textAlign:'left', maxWidth:'16rem',
              }}>
              <div className="truncate" style={{fontWeight:500,color:selectedId===item.id?'var(--accent)':'var(--text-primary)'}}>{item.video_title || item.bv}</div>
              <div className="truncate"><span style={{fontSize:'.625rem',color:'var(--text-muted)'}}>{item.total_comments} 条评论</span></div>
            </button>
            <span
              onClick={(e)=>{e.stopPropagation();setConfirmItem(item);}}
              style={{position:'absolute',top:'.25rem',right:'.25rem',zIndex:5,fontSize:'.75rem',lineHeight:1,cursor:'pointer',color:'var(--text-muted)',padding:'0 .25rem',borderRadius:'.25rem',background:'transparent'}}
              title="删除记录"
            >&times;</span>
          </div>
        ))}
      </div>

      {confirmItem && (
        <div className="modal-overlay">
          <div className="modal-backdrop" onClick={()=>setConfirmItem(null)} />
          <div className="modal-content">
            <p style={{fontSize:'.875rem',fontWeight:600,color:'var(--text-primary)',marginBottom:'.25rem'}}>删除历史记录</p>
            <p style={{fontSize:'.75rem',color:'var(--text-secondary)',marginBottom:'1rem',lineHeight:1.5}}>
              确定要删除 <span style={{color:'var(--text-primary)',fontWeight:500}}>{confirmItem.video_title || confirmItem.bv}</span> 的分析记录吗？此操作不可撤销。
            </p>
            <div className="flex gap-2 justify-end">
              <button onClick={()=>setConfirmItem(null)} className="btn btn-ghost" style={{fontSize:'.75rem'}}>取消</button>
              <button onClick={handleDelete} className="btn btn-primary" style={{fontSize:'.75rem',background:'var(--red)',borderColor:'var(--red)'}}>确认删除</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
