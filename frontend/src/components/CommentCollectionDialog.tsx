import { useEffect, useMemo, useState } from 'react';
import type { VideoInfoResponse } from '../types';
import './CommentCollectionDialog.css';

interface Props {
  videoInfo: VideoInfoResponse;
  initialTarget: number;
  initialDelay: number;
  busy?: boolean;
  onCancel: () => void;
  onStart: (target: number, delay: number) => void;
}

const HIGH_VOLUME_THRESHOLD = 5_000;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export default function CommentCollectionDialog({ videoInfo, initialTarget, initialDelay, busy = false, onCancel, onStart }: Props) {
  const publicCount = Math.max(0, videoInfo.comment_count || 0);
  const [target, setTarget] = useState(() => clamp(initialTarget, 0, publicCount));
  const [delay, setDelay] = useState(() => clamp(initialDelay, 1, 60));
  const [highVolumeConfirmed, setHighVolumeConfirmed] = useState(false);

  useEffect(() => {
    setTarget(clamp(initialTarget, 0, publicCount));
    setDelay(clamp(initialDelay, 1, 60));
    setHighVolumeConfirmed(false);
  }, [initialTarget, initialDelay, publicCount]);

  const requestPages = useMemo(() => Math.ceil(target / 20), [target]);
  const estimatedSeconds = useMemo(() => Math.round(requestPages * delay), [requestPages, delay]);
  const requiresConfirmation = target > HIGH_VOLUME_THRESHOLD;
  const disabled = publicCount === 0 || target < 1 || busy || (requiresConfirmation && !highVolumeConfirmed);

  return <div className="comment-collection-dialog" role="presentation">
    <div className="comment-collection-dialog__backdrop" onClick={busy ? undefined : onCancel}/>
    <section className="comment-collection-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="comment-collection-title">
      <header>
        <span>评论采集参数</span>
        <h3 id="comment-collection-title">开始评论分析</h3>
        <p>{videoInfo.title}</p>
      </header>
      <div className="comment-collection-dialog__summary">
        <span>公开评论数</span><strong>{publicCount.toLocaleString()} 条</strong>
      </div>
      <label>
        本次最多尝试获取评论数
        <div className="comment-collection-dialog__control">
          <input type="range" min="0" max={publicCount} value={target} disabled={publicCount === 0 || busy} onChange={event => { setTarget(Number(event.target.value)); setHighVolumeConfirmed(false); }}/>
          <input type="number" min="0" max={publicCount} value={target} disabled={publicCount === 0 || busy} onChange={event => { setTarget(clamp(Number(event.target.value) || 0, 0, publicCount)); setHighVolumeConfirmed(false); }}/>
        </div>
      </label>
      <label>
        请求间隔
        <div className="comment-collection-dialog__control">
          <input type="range" min="1" max="60" step="0.5" value={delay} disabled={busy} onChange={event => setDelay(Number(event.target.value))}/>
          <input type="number" min="1" max="60" step="0.5" value={delay} disabled={busy} onChange={event => setDelay(clamp(Number(event.target.value) || 1, 1, 60))}/>
          <span>秒</span>
        </div>
      </label>
      <p className="comment-collection-dialog__estimate">预计 {requestPages} 次请求，约 {estimatedSeconds} 秒。实际结果可能受删除、折叠或访问限制影响。</p>
      {publicCount === 0 && <p className="comment-collection-dialog__error" role="alert">该视频暂无可采集的公开评论。</p>}
      {delay < 2 && <p className="comment-collection-dialog__warning">较短间隔可能触发账号或网络访问限制，建议设置为 3 秒以上。</p>}
      {requiresConfirmation && <label className="comment-collection-dialog__confirm"><input type="checkbox" checked={highVolumeConfirmed} disabled={busy} onChange={event => setHighVolumeConfirmed(event.target.checked)}/>本次预计尝试获取 {target.toLocaleString()} 条评论，约需 {requestPages} 次请求、约 {Math.max(1, Math.round(estimatedSeconds / 60))} 分钟。长时间连续请求可能触发访问限制，我确认继续。</label>}
      <footer>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>取消</button>
        <button type="button" className="btn btn-primary" onClick={() => onStart(target, delay)} disabled={disabled}>{busy ? '创建中…' : '开始评论分析'}</button>
      </footer>
    </section>
  </div>;
}
