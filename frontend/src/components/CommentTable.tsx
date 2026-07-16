import { useState, useMemo } from 'react';
import type { CommentData, SentimentLabel } from '../types';

interface Props { comments: CommentData[]; }

const TAG: Record<SentimentLabel, { label: string; bg: string; color: string }> = {
  positive: { label: '正面', bg: 'var(--green-soft)', color: 'var(--green)' },
  negative: { label: '负面', bg: 'var(--red-soft)', color: 'var(--red)' },
  neutral: { label: '中性', bg: 'rgba(148,163,184,.06)', color: 'var(--text-muted)' },
};

export default function CommentTable({ comments }: Props) {
  const [filter, setFilter] = useState<SentimentLabel|'all'>('all');
  const [sortBy, setSortBy] = useState<'time'|'likes'>('time');
  const [page, setPage] = useState(1);
  const pageSize = 30;

  const filtered = useMemo(() => {
    let list = [...comments];
    if (filter !== 'all') list = list.filter(c => c.sentiment_label === filter);
    list.sort((a,b) => sortBy==='likes' ? b.likes-a.likes : new Date(b.post_time||0).getTime()-new Date(a.post_time||0).getTime());
    return list;
  }, [comments, filter, sortBy]);

  const pages = Math.ceil(filtered.length/pageSize);
  const paged = filtered.slice((page-1)*pageSize, page*pageSize);

  return <div className="card">
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>评论列表 ({filtered.length})</h3>
      <div className="flex items-center gap-2">
        <select value={filter} onChange={e=>{setFilter(e.target.value as any);setPage(1)}} className="select-sm">
          <option value="all">全部</option><option value="positive">正面</option><option value="neutral">中性</option><option value="negative">负面</option>
        </select>
        <select value={sortBy} onChange={e=>setSortBy(e.target.value as any)} className="select-sm">
          <option value="time">按时间</option><option value="likes">按点赞</option>
        </select>
      </div>
    </div>
    <div className="overflow-x-auto">
      <table style={{fontSize:'.8125rem'}}>
        <thead>
          <tr style={{borderBottom:'1px solid var(--border)'}}>
            <th style={{padding:'.5rem .5rem .5rem 0',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>用户</th>
            <th style={{padding:'.5rem',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>IP属地</th>
            <th style={{padding:'.5rem',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>内容</th>
            <th style={{padding:'.5rem',textAlign:'center',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>点赞</th>
            <th style={{padding:'.5rem',textAlign:'center',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>情感</th>
            <th style={{padding:'.5rem .5rem .5rem 0',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>时间</th>
          </tr>
        </thead>
        <tbody>
          {paged.map(c => {
            const t = TAG[c.sentiment_label] || TAG.neutral;
            return <tr key={c.id} style={{borderBottom:'1px solid var(--border)'}} className="transition-colors">
              <td style={{padding:'.5rem .5rem .5rem 0',color:'var(--text-primary)',maxWidth:'96px'}} className="truncate">{c.username}</td>
              <td style={{padding:'.5rem',color:'var(--text-muted)',fontSize:'.6875rem'}}>{c.ip_location||'-'}</td>
              <td style={{padding:'.5rem',color:'var(--text-secondary)',maxWidth:'280px'}} className="truncate">{c.content}</td>
              <td style={{padding:'.5rem',textAlign:'center',color:'var(--text-secondary)',fontSize:'.8125rem'}}>{c.likes}</td>
              <td style={{padding:'.5rem',textAlign:'center'}}><span style={{fontSize:'.6875rem',padding:'.125rem .375rem',borderRadius:'.25rem',background:t.bg,color:t.color}}>{t.label}</span></td>
              <td style={{padding:'.5rem .5rem .5rem 0',color:'var(--text-muted)',fontSize:'.6875rem'}}>{c.post_time?new Date(c.post_time).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'-'}</td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
    {pages>1 && <div className="flex items-center justify-center gap-2 mt-3">
      <button onClick={()=>setPage(Math.max(1,page-1))} disabled={page===1} style={{padding:'.25rem .5rem',fontSize:'.75rem',color:'var(--text-secondary)',background:'transparent',border:'1px solid var(--border)',borderRadius:'.25rem',cursor:'pointer',opacity:page===1?.4:1}}>上一页</button>
      <span className="text-xs text-muted">{page} / {pages}</span>
      <button onClick={()=>setPage(Math.min(pages,page+1))} disabled={page===pages} style={{padding:'.25rem .5rem',fontSize:'.75rem',color:'var(--text-secondary)',background:'transparent',border:'1px solid var(--border)',borderRadius:'.25rem',cursor:'pointer',opacity:page===pages?.4:1}}>下一页</button>
    </div>}
  </div>;
}