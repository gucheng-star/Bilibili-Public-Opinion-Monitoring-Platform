import { useEffect, useState } from 'react';
import { getHistory, deleteHistory } from '../services/api';
import type { HistoryItem } from '../types';
import './DataPanels.css';

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
      <div className="history-panel">
        <div className="history-panel__header"><span className="panel-status">ANALYSIS ARCHIVE</span><span className="history-panel__count">{items.length}</span></div>
      <div className="history-scroll history-panel__list">
        {items.map(item => (
          <div key={item.id} className="history-panel__item">
            <button onClick={()=>onSelect(item.id)} className={`history-panel__record${selectedId===item.id ? ' is-selected' : ''}`} aria-pressed={selectedId===item.id}>
              <div className="history-panel__record-title truncate">{item.video_title || item.bv}</div>
              <div className="history-panel__record-meta truncate">{item.total_comments} 条评论</div>
            </button>
            <button type="button" className="history-panel__delete"
              onClick={(e)=>{e.stopPropagation();setConfirmItem(item);}}
              title="删除记录"
              aria-label={`删除记录：${item.video_title || item.bv}`}
            >&times;</button>
          </div>
        ))}
      </div>
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
