import { useEffect, useMemo, useState } from 'react';
import type { VideoInfoResponse } from '../types';
import './DanmakuSamplingDialog.css';

interface Props {
  videoInfo: VideoInfoResponse;
  initialPartIndex?: number;
  initialSampleLimit?: number;
  initialDelay?: number;
  onCancel: () => void;
  onStart: (partIndex: number, sampleLimit: number, requestDelay: number) => void;
}

const SEGMENT_SECONDS = 6 * 60;
const SAMPLES_PER_SEGMENT = 500;
const DEFAULT_SAMPLES_PER_SEGMENT = 100;
const HIGH_VOLUME_THRESHOLD = 5_000;

const segmentCount = (duration: number) => Math.max(1, Math.ceil(Math.max(0, duration) / SEGMENT_SECONDS));
const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));
const durationText = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
};

export default function DanmakuSamplingDialog({ videoInfo, initialPartIndex, initialSampleLimit, initialDelay = 3, onCancel, onStart }: Props) {
  const pages = videoInfo.pages;
  const [partIndex, setPartIndex] = useState(() => initialPartIndex ?? pages[0]?.page ?? 1);
  const selectedPart = pages.find(page => page.page === partIndex) ?? pages[0];
  const segments = segmentCount(selectedPart?.duration ?? 0);
  const maxSampleLimit = segments * SAMPLES_PER_SEGMENT;
  const defaultSampleLimit = segments * DEFAULT_SAMPLES_PER_SEGMENT;
  const [sampleLimit, setSampleLimit] = useState(() => clamp(initialSampleLimit ?? defaultSampleLimit, 1, maxSampleLimit));
  const [requestDelay, setRequestDelay] = useState(() => clamp(initialDelay, 1, 60));
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    const nextPart = pages.some(page => page.page === initialPartIndex) ? initialPartIndex! : pages[0]?.page ?? 1;
    setPartIndex(nextPart);
    setRequestDelay(clamp(initialDelay, 1, 60));
    setConfirmed(false);
  }, [initialDelay, initialPartIndex, pages]);

  useEffect(() => {
    setSampleLimit(clamp(initialSampleLimit ?? defaultSampleLimit, 1, maxSampleLimit));
    setConfirmed(false);
  }, [defaultSampleLimit, initialSampleLimit, maxSampleLimit, partIndex]);

  const estimatedRequests = useMemo(() => segments, [segments]);
  const estimatedSeconds = useMemo(() => Math.round(estimatedRequests * requestDelay), [estimatedRequests, requestDelay]);
  const requiresConfirmation = sampleLimit > HIGH_VOLUME_THRESHOLD;
  const disabled = !selectedPart || (requiresConfirmation && !confirmed);

  return <div className="danmaku-sampling-dialog" role="presentation">
    <div className="danmaku-sampling-dialog__backdrop" onClick={onCancel}/>
    <section className="danmaku-sampling-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="danmaku-sampling-title">
      <header><span>弹幕抽样参数</span><h3 id="danmaku-sampling-title">开始分时段抽样</h3><p>{videoInfo.title}</p></header>
      <label>分 P
        {pages.length <= 1
          ? <div className="danmaku-sampling-dialog__readonly">P{selectedPart?.page ?? 1} · {selectedPart?.part || 'P1'} · {durationText(selectedPart?.duration ?? 0)}</div>
          : <select value={partIndex} onChange={event => setPartIndex(Number(event.target.value))}>{pages.map(page => <option key={page.page} value={page.page}>P{page.page} · {page.part || `P${page.page}`} · {durationText(page.duration)}</option>)}</select>}
      </label>
      <div className="danmaku-sampling-dialog__summary"><span>本分 P 时长</span><strong>{durationText(selectedPart?.duration ?? 0)} · {segments} 个 6 分钟片段</strong></div>
      <label>本次最多抽样弹幕数
        <div className="danmaku-sampling-dialog__control"><input type="range" min="1" max={maxSampleLimit} value={sampleLimit} onChange={event => { setSampleLimit(Number(event.target.value)); setConfirmed(false); }}/><input type="number" min="1" max={maxSampleLimit} value={sampleLimit} onChange={event => { setSampleLimit(clamp(Number(event.target.value) || 1, 1, maxSampleLimit)); setConfirmed(false); }}/></div>
      </label>
      <label>请求间隔
        <div className="danmaku-sampling-dialog__control"><input type="range" min="1" max="60" step="0.5" value={requestDelay} onChange={event => setRequestDelay(Number(event.target.value))}/><input type="number" min="1" max="60" step="0.5" value={requestDelay} onChange={event => setRequestDelay(clamp(Number(event.target.value) || 1, 1, 60))}/><span>秒</span></div>
      </label>
      <p className="danmaku-sampling-dialog__estimate">预计 {estimatedRequests} 次片段请求，约 {estimatedSeconds} 秒。分时段抽样仅反映已采样弹幕；单个片段最多保留 500 条。</p>
      {requestDelay < 2 && <p className="danmaku-sampling-dialog__warning">较短间隔可能触发账号或网络访问限制，建议设置为 3 秒以上。</p>}
      {requiresConfirmation && <label className="danmaku-sampling-dialog__confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>本次预计抽样 {sampleLimit.toLocaleString()} 条弹幕，约需 {estimatedRequests} 次请求、约 {Math.max(1, Math.round(estimatedSeconds / 60))} 分钟。长时间连续请求可能触发访问限制，我确认继续。</label>}
      <footer><button type="button" className="btn btn-ghost" onClick={onCancel}>取消</button><button type="button" className="btn btn-primary" disabled={disabled} onClick={() => onStart(partIndex, sampleLimit, requestDelay)}>开始分时段抽样</button></footer>
    </section>
  </div>;
}
