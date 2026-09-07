interface Props { title: string; play: number; totalComments: number; }

import './DataPanels.css';

type CommentCollectionStatus = 'pending' | 'fetching' | 'completed' | 'partial' | 'failed';
type DanmakuCollectionStatus = 'not_started' | 'pending' | 'fetching' | 'analyzing' | 'done' | 'partial' | 'error';

interface CommentCollection {
  kind: 'comments';
  status: CommentCollectionStatus;
  fetchedCount: number;
  targetCount: number;
  retrying: boolean;
  onRetry: () => void;
}

interface DanmakuCollection {
  kind: 'danmaku';
  status: DanmakuCollectionStatus;
  keptCount: number;
  sampleLimit: number;
  partIndex?: number;
  partTitle?: string;
  segmentCount?: number;
  retrying: boolean;
  starting: boolean;
  onRetry: () => void;
}

function commentStatusText(status: CommentCollectionStatus): string {
  if (status === 'partial') return '评论部分完成';
  if (status === 'completed') return '评论已采集';
  if (status === 'failed') return '评论采集失败';
  return '评论采集中';
}

function danmakuStatusText(status: DanmakuCollectionStatus): string {
  if (status === 'not_started') return '弹幕尚未抽样';
  if (status === 'partial') return '弹幕部分完成';
  if (status === 'error') return '弹幕采集失败';
  if (status === 'done') return '弹幕已抽样';
  return '弹幕采集中';
}

function statusClass(status: CommentCollectionStatus | DanmakuCollectionStatus): string {
  if (status === 'failed' || status === 'error') return 'failed';
  if (status === 'partial') return 'partial';
  return 'completed';
}

export default function VideoInfo({ title, play, totalComments, collection }: Props & { collection: CommentCollection | DanmakuCollection }) {
  const isDanmaku = collection.kind === 'danmaku';
  const count = isDanmaku ? `${collection.keptCount.toLocaleString()} / ${collection.sampleLimit.toLocaleString()}` : `${collection.fetchedCount.toLocaleString()} / ${collection.targetCount.toLocaleString()}`;
  const danmakuRunning = isDanmaku && ['pending', 'fetching', 'analyzing'].includes(collection.status);
  const actionLabel = isDanmaku && collection.starting
    ? '正在创建抽样任务...'
    : danmakuRunning
      ? '正在采集弹幕...'
      : collection.retrying
    ? '正在重新获取...'
    : isDanmaku
      ? collection.status === 'not_started' ? '开始分时段抽样' : '重新采集弹幕'
      : '重新采集评论';
  return <section className="video-observation-panel" aria-labelledby="video-observation-title">
    <div className="video-observation-panel__header"><span className="panel-status">{isDanmaku ? 'PLAYBACK SAMPLE' : 'LIVE OBSERVATION'}</span><span className="video-observation-panel__status-dot" aria-hidden="true" /></div>
    <div className="video-observation-panel__body min-w-0">
      <h2 id="video-observation-title" className="text-base font-semibold text-primary truncate" title={title}>{title}</h2>
      <div className="video-observation-panel__metrics text-xs text-secondary">
        <span>播放 {play.toLocaleString()}</span>
        {isDanmaku
          ? <><span>当前分 P {collection.partIndex ? `P${collection.partIndex}` : '未选择'}{collection.partTitle ? ` · ${collection.partTitle}` : ''}</span><span>6 分钟片段 {collection.segmentCount ?? 0} 段</span></>
          : <span>评论总数 {totalComments.toLocaleString()}</span>}
      </div>
      <div className="video-observation-panel__collection">
        <span className={`video-observation-panel__collection-status video-observation-panel__collection-status--${statusClass(collection.status)}`}><i aria-hidden="true" />{isDanmaku ? danmakuStatusText(collection.status) : commentStatusText(collection.status)} <b>{count}</b></span>
        <button type="button" className="video-observation-panel__retry" onClick={collection.onRetry} disabled={collection.retrying || danmakuRunning || (isDanmaku && collection.starting)} aria-busy={collection.retrying || danmakuRunning || (isDanmaku && collection.starting)}>{actionLabel}</button>
      </div>
    </div>
  </section>;
}
