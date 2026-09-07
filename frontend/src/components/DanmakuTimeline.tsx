import { useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import type { DanmakuTask, DanmakuTimeline as DanmakuTimelineData, DanmakuTimelineBucket } from '../types';
import { chartTextColor, chartTooltip } from '../utils';
import './DanmakuTimeline.css';

interface Props {
  task: DanmakuTask | null;
  timeline: DanmakuTimelineData | null;
  loadingTask: boolean;
  startingTask: boolean;
  error: string | null;
  openingDialog: boolean;
  onOpenStart: () => void;
}

function formatPlaybackTime(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function durationText(seconds: number): string {
  return formatPlaybackTime(seconds * 1000);
}

function coverageText(coverage: DanmakuTimelineBucket['coverage']): string {
  switch (coverage) {
    case 'sampled': return '已抽样';
    case 'failed': return '请求失败';
    case 'partial': return '部分覆盖';
    default: return '未采样';
  }
}

export default function DanmakuTimeline({ task, timeline, loadingTask, startingTask, error, openingDialog, onOpenStart }: Props) {
  const chartRef = useRef<ReactECharts | null>(null);
  const tooltipTheme = chartTooltip();
  const textColor = chartTextColor();
  const buckets = useMemo(() => timeline?.buckets ?? [], [timeline]);
  const quality = useMemo(() => {
    if (!task) return null;
    const lowSample = task.sample_limit < task.segment_count * 3;
    const broadCoverage = task.sample_limit >= task.segment_count * 5;
    const failedBuckets = buckets.filter(bucket => bucket.coverage === 'failed').length;
    const notSampledBuckets = buckets.filter(bucket => bucket.coverage === 'not_sampled').length;
    return { lowSample, broadCoverage, failedBuckets, notSampledBuckets };
  }, [buckets, task]);

  const chartOption = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      backgroundColor: tooltipTheme.backgroundColor,
      borderColor: tooltipTheme.borderColor,
      textStyle: tooltipTheme.textStyle,
      formatter: (params: Array<{ dataIndex: number; seriesName: string; value: number; marker: string }>) => {
        const index = params[0]?.dataIndex;
        const bucket = buckets[index];
        if (!bucket) return '';
        const lines = params.map(point => `${point.marker}${point.seriesName}：${point.value}`);
        return [
          `${formatPlaybackTime(bucket.start_ms)} – ${formatPlaybackTime(bucket.end_ms)}`,
          `状态：${coverageText(bucket.coverage)}`,
          `抽样弹幕：${bucket.total} 条`,
          ...lines,
        ].join('<br/>');
      },
    },
    legend: { top: 0, right: 0, textStyle: { color: textColor, fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
    grid: { left: 46, right: 18, top: 34, bottom: 40, containLabel: false },
    xAxis: {
      type: 'category',
      data: buckets.map(bucket => formatPlaybackTime(bucket.start_ms)),
      axisLabel: { color: textColor, fontSize: 10, interval: Math.max(0, Math.ceil(buckets.length / 8) - 1) },
      axisLine: { lineStyle: { color: 'rgba(135,145,164,.32)' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      name: '抽样条数',
      nameTextStyle: { color: textColor, fontSize: 10 },
      axisLabel: { color: textColor, fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(135,145,164,.14)' } },
    },
    series: [
      { name: '正面', type: 'line', stack: 'sample', showSymbol: false, smooth: 0.28, smoothMonotone: 'x', data: buckets.map(bucket => bucket.coverage === 'sampled' || bucket.coverage === 'partial' ? bucket.positive : null), itemStyle: { color: '#059669' }, lineStyle: { color: '#059669', width: 2 }, areaStyle: { color: 'rgba(5,150,105,.15)' }, emphasis: { focus: 'series' } },
      { name: '中性', type: 'line', stack: 'sample', showSymbol: false, smooth: 0.28, smoothMonotone: 'x', data: buckets.map(bucket => bucket.coverage === 'sampled' || bucket.coverage === 'partial' ? bucket.neutral : null), itemStyle: { color: '#159BB3' }, lineStyle: { color: '#159BB3', width: 2 }, areaStyle: { color: 'rgba(21,155,179,.15)' }, emphasis: { focus: 'series' } },
      { name: '负面', type: 'line', stack: 'sample', showSymbol: false, smooth: 0.28, smoothMonotone: 'x', data: buckets.map(bucket => bucket.coverage === 'sampled' || bucket.coverage === 'partial' ? bucket.negative : null), itemStyle: { color: '#FB7299' }, lineStyle: { color: '#FB7299', width: 2 }, areaStyle: { color: 'rgba(251,114,153,.16)' }, emphasis: { focus: 'series' } },
    ],
  }), [buckets, textColor, tooltipTheme]);

  const isRunning = task?.status === 'pending' || task?.status === 'fetching' || task?.status === 'analyzing';
  const canRenderTimeline = (task?.status === 'done' || task?.status === 'partial') && timeline && buckets.length > 0;

  return (
    <section className="danmaku-timeline card" aria-label="弹幕时间轴">
      <header className="danmaku-timeline__header">
        <div>
          <div className="danmaku-timeline__eyebrow"><span aria-hidden="true"></span>PLAYBACK SIGNAL SAMPLE</div>
          <h2>弹幕时间轴</h2>
          <p>仅统计主动发起的分时段抽样弹幕；每个时间段按弹幕在视频内的精确出现时间聚合。</p>
        </div>
        {task && <div className={`danmaku-timeline__state danmaku-timeline__state--${task.status}`}>
          {task.status === 'done' ? '已完成' : task.status === 'partial' ? '部分完成' : task.status === 'error' ? '需要重试' : '正在处理'}
        </div>}
      </header>

      {!task && !loadingTask && !startingTask && (
        <div className="danmaku-timeline__empty">
          <div className="danmaku-timeline__empty-copy">
            <strong>尚未开始分时段抽样</strong>
          <p>系统会顺序请求本分 P 的 6 分钟片段，只保留普通弹幕并在本机进行 NLP 三分类。不会调用大模型。</p>
          </div>
          <button type="button" className="btn btn-primary" onClick={onOpenStart} disabled={openingDialog}>{openingDialog ? '正在重新获取...' : '开始分时段抽样'}</button>
        </div>
      )}

      {startingTask && <div className="danmaku-timeline__loading" role="status">弹幕抽样任务正在创建，稍后将在此显示实时进度…</div>}
      {loadingTask && !task && !startingTask && <div className="danmaku-timeline__loading">正在读取已保存的弹幕抽样记录…</div>}

      {error && !task && <div className="danmaku-timeline__failure" role="alert"><div><strong>{error}</strong><p>请检查本机网络和登录状态后再次开始。</p></div></div>}

      {task && (
        <>
          <div className="danmaku-timeline__metrics" aria-label="抽样任务概况">
            <Metric label="分 P" value={`P${task.part_index}${task.part_title ? ` · ${task.part_title}` : ''}`} />
            <Metric label="视频时长" value={durationText(task.video_duration_seconds)} />
            <Metric label="6 分钟片段" value={`${task.segment_count} 段`} />
            <Metric label="保留样本" value={`${task.kept_count} / ${task.sample_limit} 条`} />
            <Metric label="请求间隔" value={`${task.request_delay} 秒`} />
            <Metric label="已忽略" value={`${task.ignored_count} 项`} />
          </div>

          {isRunning && (
            <div className="danmaku-timeline__progress" role="status">
              <div className="danmaku-timeline__progress-line"><span style={{ width: `${task.segment_count ? Math.min(100, task.requested_segments / task.segment_count * 100) : 0}%` }}></span></div>
              <p>已真实请求 {task.requested_segments} 段，成功 {task.successful_segments} 段，保留 {task.kept_count} 条；完成后将显示时间轴。</p>
            </div>
          )}

          {(task.status === 'error' || task.status === 'partial') && (
            <div className="danmaku-timeline__failure" role="alert">
              <div><strong>{task.status === 'partial' ? '部分片段获取失败，可重试' : task.error_msg || '弹幕获取失败，可重试'}</strong><p>此前的抽样尝试会保留在本机；再次开始会创建新的尝试，不会覆盖已有记录。</p></div>
              <button type="button" className="btn btn-primary" onClick={onOpenStart} disabled={openingDialog}>{openingDialog ? '正在重新获取...' : '重新采集弹幕'}</button>
            </div>
          )}

          {canRenderTimeline && quality && (
            <>
              <div className="danmaku-timeline__quality">
                <div><b>{task.kept_count}</b><span>条本地 NLP 抽样弹幕</span></div>
                <p>
                  {quality.failedBuckets > 0 ? '部分分段请求失败，失败区间不参与统计。' : quality.lowSample ? '样本较少，走势可能失真。' : quality.broadCoverage ? '覆盖较充分，仍应按抽样结果解读。' : '请按分时段抽样结果观察情绪线索。'}
                  {' '}未采样 {quality.notSampledBuckets} 个时间桶，失败 {quality.failedBuckets} 个时间桶。
                </p>
              </div>
              <div className="danmaku-timeline__chart-wrap">
                <ReactECharts ref={chartRef} option={chartOption} style={{ height: 320, width: '100%' }} notMerge lazyUpdate />
              </div>
              <div className="danmaku-timeline__coverage-ribbon" role="img" aria-label="播放时间抽样覆盖：绿色为已抽样，斜线为未采样，红色为请求失败，紫色为部分覆盖">
                {buckets.map(bucket => <span key={bucket.start_ms} className={`danmaku-timeline__ribbon-segment danmaku-timeline__ribbon-segment--${bucket.coverage}`} title={`${formatPlaybackTime(bucket.start_ms)} – ${formatPlaybackTime(bucket.end_ms)}：${coverageText(bucket.coverage)}`} />)}
              </div>
              <div className="danmaku-timeline__legend-note">
                <span className="danmaku-timeline__coverage danmaku-timeline__coverage--sampled"></span>已抽样
                <span className="danmaku-timeline__coverage danmaku-timeline__coverage--not-sampled"></span>未采样
                <span className="danmaku-timeline__coverage danmaku-timeline__coverage--failed"></span>请求失败
                <span className="danmaku-timeline__coverage danmaku-timeline__coverage--partial"></span>部分覆盖
              </div>
            </>
          )}

          {task.status === 'done' && !canRenderTimeline && (
            <div className="danmaku-timeline__loading">已完成请求，但没有可用于时间轴的普通弹幕样本。</div>
          )}
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="danmaku-timeline__metric"><span>{label}</span><b title={value}>{value}</b></div>;
}
