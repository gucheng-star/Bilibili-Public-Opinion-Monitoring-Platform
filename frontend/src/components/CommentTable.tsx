import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import type { AnalysisMode, CommentData, SentimentLabel, SentimentLLM } from '../types';

interface Props { comments: CommentData[]; mode: AnalysisMode; }

type LlmSentimentLabel = keyof SentimentLLM;
type CommentNode = { comment: CommentData; children: CommentNode[] };

const COMMENT_PREVIEW_LENGTH = 72;

function getCommentPreview(content: string): string {
  const characters = Array.from(content);
  return characters.length > COMMENT_PREVIEW_LENGTH
    ? `${characters.slice(0, COMMENT_PREVIEW_LENGTH).join('')}…`
    : content;
}

const TAG: Record<SentimentLabel, { label: string; bg: string; color: string }> = {
  positive: { label: '正面', bg: 'var(--green-soft)', color: 'var(--green)' },
  negative: { label: '负面', bg: 'var(--red-soft)', color: 'var(--red)' },
  neutral: { label: '中性', bg: 'rgba(148,163,184,.06)', color: 'var(--text-muted)' },
};

const LLM_TAG: Record<LlmSentimentLabel, { label: string; bg: string; color: string }> = {
  neutral: { label: '中性', bg: 'rgba(148,163,184,.10)', color: 'var(--text-muted)' },
  joy: { label: '喜悦', bg: 'rgba(251,191,36,.14)', color: '#B45309' },
  support: { label: '支持', bg: 'var(--green-soft)', color: 'var(--green)' },
  anticipation: { label: '期待', bg: 'rgba(6,182,212,.12)', color: '#0E7490' },
  surprise: { label: '惊讶', bg: 'rgba(249,115,22,.12)', color: '#C2410C' },
  anger: { label: '愤怒', bg: 'var(--red-soft)', color: 'var(--red)' },
  sadness: { label: '悲伤', bg: 'rgba(99,102,241,.12)', color: '#4F46E5' },
  concern: { label: '担忧', bg: 'rgba(139,92,246,.12)', color: '#7C3AED' },
  disgust: { label: '厌恶', bg: 'rgba(132,204,22,.14)', color: '#4D7C0F' },
};

const UNCLASSIFIED_TAG = { label: '未分类', bg: 'rgba(148,163,184,.06)', color: 'var(--text-muted)' };
const STYLE_TAG: Record<string, { label: string; bg: string; color: string }> = {
  meme: { label: '玩梗', bg: 'rgba(6,182,212,.10)', color: '#0E7490' },
  sarcasm: { label: '反讽', bg: 'rgba(236,72,153,.10)', color: '#BE185D' },
};

export default function CommentTable({ comments, mode }: Props) {
  const [sortBy, setSortBy] = useState<'time'|'likes'>('time');
  const [page, setPage] = useState(1);
  const pageSize = 30;

  const tipEl = useRef<HTMLDivElement|null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const rafId = useRef(0);
  const hideTimer = useRef(0);

  useEffect(() => { setPage(1); }, [mode, comments, sortBy]);

  // Create persistent tooltip DOM element (portal style, command-style updates)
  useEffect(() => {
    const el = document.createElement('div');
    el.style.cssText = 'position:fixed;z-index:200;max-width:30rem;padding:.625rem .875rem;background:var(--bg-elevated);border:1px solid var(--border-strong);border-radius:.5rem;box-shadow:0 8px 24px rgba(0,0,0,.18);font-size:.8125rem;line-height:1.6;pointer-events:none;white-space:pre-wrap;word-break:break-word;opacity:0;transform:translate(-50%,-100%);will-change:transform,opacity;transition:opacity .15s ease;display:none;';
    tipEl.current = el;
    document.body.appendChild(el);
    return () => { document.body.removeChild(el); cancelAnimationFrame(rafId.current); };
  }, []);

  // Command-style position update (no React state, no re-render)
  const moveTip = useCallback((x: number, y: number) => {
    if (!tipEl.current) return;
    cancelAnimationFrame(rafId.current);
    rafId.current = requestAnimationFrame(() => {
      const el = tipEl.current!;
      // Confine: clamp to viewport
      const vw = window.innerWidth, vh = window.innerHeight;
      const rect = el.getBoundingClientRect();
      const finalX = Math.min(Math.max(x, rect.width/2), vw - rect.width/2);
      const finalY = Math.min(Math.max(y - 8, rect.height), vh - 4);
      el.style.left = finalX + 'px';
      el.style.top = finalY + 'px';
    });
  }, []);

  // Show tip (command-style: set content, show, start transition)
  const showTip = useCallback((text: string, x: number, y: number) => {
    clearTimeout(hideTimer.current);
    const el = tipEl.current; if (!el) return;
    el.textContent = text;
    if (el.style.display === 'none') { el.style.display = ''; /* trigger reflow */ void el.offsetHeight; }
    el.style.opacity = '1';
    moveTip(x, y);
  }, [moveTip]);

  // Hide tip with delay (matches ECharts hideLater pattern)
  const hideTip = useCallback(() => {
    clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      const el = tipEl.current; if (!el) return;
      el.style.opacity = '0';
      // Delay display:none until transition completes
      setTimeout(() => { if (el.style.opacity === '0') el.style.display = 'none'; }, 160);
    }, 80);
  }, []);

  const onCardMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (tipEl.current?.style.display !== 'none') {
      moveTip(e.clientX, e.clientY);
    }
  }, [moveTip]);

  const sorted = useMemo(() => {
    let list = [...comments];
    list.sort((a,b) => sortBy==='likes' ? b.likes-a.likes : new Date(b.post_time||0).getTime()-new Date(a.post_time||0).getTime());
    return list;
  }, [comments, sortBy]);

  const treeRoots = useMemo(() => {
    const nodesByRpid = new Map<string, CommentNode>();
    sorted.forEach(comment => nodesByRpid.set(String(comment.rpid), { comment, children: [] }));
    const roots: CommentNode[] = [];
    nodesByRpid.forEach(node => {
      const parent = node.comment.parent_rpid ? nodesByRpid.get(String(node.comment.parent_rpid)) : undefined;
      if (parent && parent !== node) parent.children.push(node);
      else roots.push(node);
    });
    return roots;
  }, [sorted]);

  const pages = Math.max(1, Math.ceil(treeRoots.length/pageSize));
  const pagedRoots = treeRoots.slice((page-1)*pageSize, page*pageSize);
  const replyCount = sorted.length - treeRoots.length;

  const renderNode = (node: CommentNode, depth = 0): React.ReactNode[] => {
    const c = node.comment;
    const t = mode === 'llm'
      ? LLM_TAG[c.sentiment_llm_label as LlmSentimentLabel] || UNCLASSIFIED_TAG
      : TAG[c.sentiment_label] || TAG.neutral;
    const style = mode === 'llm' ? STYLE_TAG[c.sentiment_llm_style] : undefined;
    return [
      <tr key={c.id} className={depth ? 'comment-tree-row comment-tree-row--reply' : 'comment-tree-row'}>
        <td style={{padding:'.6rem .5rem',color:'var(--text-primary)'}} className="truncate" title={c.username}>{c.username}</td>
        <td style={{padding:'.6rem .5rem',color:'var(--text-muted)',fontSize:'.6875rem'}}>{c.ip_location||'-'}</td>
        <td style={{padding:'.6rem .5rem',color:'var(--text-secondary)',cursor:'pointer'}}>
          <div className="comment-tree__content" style={{paddingLeft: `${depth * 1.25}rem`}}
            onMouseEnter={e=>{showTip(c.content,e.clientX,e.clientY);}}
            onMouseLeave={hideTip}>
            {depth > 0 && <span className="comment-tree__branch" aria-hidden="true">↳</span>}
            <span className="comment-tree__text">{getCommentPreview(c.content)}</span>
          </div>
        </td>
        <td style={{padding:'.6rem .5rem',textAlign:'center',color:'var(--text-secondary)',fontSize:'.8125rem'}}>{c.likes}</td>
        <td style={{padding:'.6rem .5rem',textAlign:'center'}}>
          <div style={{display:'inline-flex',gap:'.25rem',flexWrap:'wrap',justifyContent:'center'}}>
            <span style={{fontSize:'.6875rem',padding:'.125rem .375rem',borderRadius:'.25rem',background:t.bg,color:t.color}}>{t.label}</span>
            {style && <span style={{fontSize:'.6875rem',padding:'.125rem .375rem',borderRadius:'.25rem',background:style.bg,color:style.color}}>{style.label}</span>}
          </div>
        </td>
        <td style={{padding:'.6rem .5rem',color:'var(--text-muted)',fontSize:'.6875rem'}}>{c.post_time?new Date(c.post_time).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'-'}</td>
      </tr>,
      ...node.children.flatMap(child => renderNode(child, depth + 1)),
    ];
  };

  return <div className="card" ref={cardRef} onMouseMove={onCardMove}>
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>评论列表 ({sorted.length})</h3>
      <div className="flex items-center gap-2">
        <span className="comment-tree__legend">{treeRoots.length} 个根评论 · {replyCount} 条回复</span>
        <select value={sortBy} onChange={e=>setSortBy(e.target.value as any)} className="select-sm">
          <option value="time">按时间</option><option value="likes">按点赞</option>
        </select>
      </div>
    </div>
    <div className="overflow-x-auto">
      <table className="comment-table" style={{fontSize:'.8125rem',width:'100%'}}>
        <thead>
          <tr style={{borderBottom:'1px solid var(--border)'}}>
            <th style={{padding:'.5rem',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em',width:'12%',minWidth:'72px'}}>用户</th>
            <th style={{padding:'.5rem',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em',width:'10%',minWidth:'60px'}}>IP属地</th>
            <th className="comment-table__content-column" style={{padding:'.5rem',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em'}}>内容</th>
            <th style={{padding:'.5rem',textAlign:'center',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em',width:'7%',minWidth:'50px'}}>点赞</th>
            <th style={{padding:'.5rem',textAlign:'center',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em',width:'9%',minWidth:'56px'}}>情感</th>
            <th style={{padding:'.5rem',textAlign:'left',fontWeight:500,color:'var(--text-muted)',fontSize:'.6875rem',letterSpacing:'.05em',width:'12%',minWidth:'90px'}}>时间</th>
          </tr>
        </thead>
        <tbody>
          {pagedRoots.flatMap(root => renderNode(root))}
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
