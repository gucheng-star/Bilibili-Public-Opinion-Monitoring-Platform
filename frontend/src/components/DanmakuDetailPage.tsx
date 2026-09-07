import { useEffect, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { getDanmakuSamples, getDanmakuTimeline } from '../services/api';
import type { DanmakuSamplePage, DanmakuTask } from '../types';
import './CommentDetail.css';

const PAGE_SIZE = 30;

const SENTIMENT_TAG = {
  positive: { label: '正面', background: 'var(--green-soft)', color: 'var(--green)' },
  neutral: { label: '中性', background: 'rgba(148,163,184,.10)', color: 'var(--text-muted)' },
  negative: { label: '负面', background: 'var(--red-soft)', color: 'var(--red)' },
} as const;

function formatPlaybackTime(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

function DanmakuDetailError({ message }: { message: string }) {
  return <main className="app-main comment-detail max-w-7xl mx-auto px-4 py-6">
    <div className="app-alert app-alert--error" role="alert">{message}</div>
    <Link className="btn btn-ghost" to="/?source=danmaku">返回弹幕时间轴</Link>
  </main>;
}

export default function DanmakuDetailPage() {
  const rawTaskId = useParams().danmakuAnalysisId;
  const taskId = Number(rawTaskId);
  const validTaskId = Number.isInteger(taskId) && taskId > 0;
  const [task, setTask] = useState<DanmakuTask | null>(null);
  const [samples, setSamples] = useState<DanmakuSamplePage | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!validTaskId) return;
    let cancelled = false;
    setError(null);
    Promise.all([
      getDanmakuTimeline(taskId),
      getDanmakuSamples(taskId, (page - 1) * PAGE_SIZE, PAGE_SIZE),
    ]).then(([nextTask, nextSamples]) => {
      if (cancelled) return;
      setTask(nextTask);
      setSamples(nextSamples);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : '读取弹幕明细失败');
    });
    return () => { cancelled = true; };
  }, [page, taskId, validTaskId]);

  if (!validTaskId) return <Navigate to="/" replace />;
  if (error) return <DanmakuDetailError message={error} />;
  if (!task || !samples) return <main className="app-main comment-detail max-w-7xl mx-auto px-4 py-6">
    <div className="app-state flex flex-col items-center justify-center py-20">
      <div className="pulse-dot app-state__pulse"></div>
      <p className="text-sm text-secondary mt-3">正在加载弹幕明细…</p>
    </div>
  </main>;

  const pages = Math.max(1, Math.ceil(samples.total / PAGE_SIZE));
  const safePage = Math.min(page, pages);

  return <main className="app-main comment-detail max-w-7xl mx-auto px-4 py-6">
    <div className="comment-detail__topbar"><Link className="ui-secondary-action comment-detail__back" to="/?source=danmaku">← 返回弹幕时间轴</Link></div>
    <header className="comment-detail__header">
      <h1 className="comment-detail__title">弹幕明细</h1>
      <p className="comment-detail__meta">P{task.part_index}{task.part_title ? ` · ${task.part_title}` : ''} · 本地 NLP 三分类 · 共 {samples.total.toLocaleString()} 条抽样弹幕</p>
    </header>
    {samples.items.length === 0 ? <div className="app-state comment-detail__empty flex flex-col items-center justify-center py-16 text-muted"><p className="text-sm">当前抽样任务没有保留可展示的普通弹幕</p></div> : <>
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-semibold text-secondary" style={{ letterSpacing: '.05em' }}>弹幕列表 ({samples.total})</h2>
          <span className="comment-tree__legend">按播放时间排序</span>
        </div>
        <div className="overflow-x-auto"><table className="comment-table" style={{ fontSize: '.8125rem', width: '100%' }}>
          <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ padding: '.5rem', textAlign: 'left', fontWeight: 500, color: 'var(--text-muted)', fontSize: '.6875rem', letterSpacing: '.05em', width: '16%', minWidth: '90px' }}>播放时间</th>
            <th className="comment-table__content-column" style={{ padding: '.5rem', textAlign: 'left', fontWeight: 500, color: 'var(--text-muted)', fontSize: '.6875rem', letterSpacing: '.05em' }}>内容</th>
            <th style={{ padding: '.5rem', textAlign: 'center', fontWeight: 500, color: 'var(--text-muted)', fontSize: '.6875rem', letterSpacing: '.05em', width: '14%', minWidth: '80px' }}>情感</th>
            <th style={{ padding: '.5rem', textAlign: 'center', fontWeight: 500, color: 'var(--text-muted)', fontSize: '.6875rem', letterSpacing: '.05em', width: '14%', minWidth: '80px' }}>请求片段</th>
          </tr></thead>
          <tbody>{samples.items.map(sample => {
            const sentiment = sample.sentiment_label && SENTIMENT_TAG[sample.sentiment_label];
            return <tr key={sample.id} className="comment-tree-row">
              <td style={{ padding: '.6rem .5rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-data)' }}>{formatPlaybackTime(sample.progress_ms)}</td>
              <td style={{ padding: '.6rem .5rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{sample.content}</td>
              <td style={{ padding: '.6rem .5rem', textAlign: 'center' }}><span style={{ display: 'inline-block', padding: '.125rem .375rem', borderRadius: '.25rem', fontSize: '.6875rem', background: sentiment?.background ?? 'rgba(148,163,184,.10)', color: sentiment?.color ?? 'var(--text-muted)' }}>{sentiment?.label ?? '未分类'}</span></td>
              <td style={{ padding: '.6rem .5rem', textAlign: 'center', color: 'var(--text-muted)' }}>第 {sample.segment_index + 1} 段</td>
            </tr>;
          })}</tbody>
        </table></div>
        {pages > 1 && <div className="flex items-center justify-center gap-2 mt-3">
          <button type="button" onClick={() => setPage(current => Math.max(1, current - 1))} disabled={safePage === 1} className="btn btn-ghost">上一页</button>
          <span className="text-xs text-muted">{safePage} / {pages}</span>
          <button type="button" onClick={() => setPage(current => Math.min(pages, current + 1))} disabled={safePage === pages} className="btn btn-ghost">下一页</button>
        </div>}
      </div>
    </>}
  </main>;
}
