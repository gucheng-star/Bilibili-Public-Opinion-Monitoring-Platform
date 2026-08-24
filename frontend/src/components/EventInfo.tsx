import type { GroupAnalysisResult } from '../types';
import './DataPanels.css';

function formatRange(result: GroupAnalysisResult) {
  const range = result.time_range;
  if (!range?.earliest && !range?.latest) return '时间范围暂无数据';
  const format = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '未知';
  return `${format(range?.earliest)} 至 ${format(range?.latest)}`;
}

export default function EventInfo({ result }: { result: GroupAnalysisResult }) {
  return <section className="event-observation-panel" aria-labelledby="event-observation-title">
    <div className="event-observation-panel__header"><span className="panel-status">EVENT OBSERVATION</span><span className="event-observation-panel__status-dot" aria-hidden="true" /></div>
    <div className="event-observation-panel__body min-w-0">
      <h2 id="event-observation-title" className="text-base font-semibold text-primary truncate" title={result.group_name}>{result.group_name}</h2>
      {result.description && <p className="event-observation-panel__description">{result.description}</p>}
      <div className="event-observation-panel__metrics text-xs text-secondary"><span>{result.member_count} 个来源视频</span><span>评论池 {result.total_comments.toLocaleString()} 条</span><span>{formatRange(result)}</span></div>
      <p className="event-observation-panel__notice">当前采用评论池汇总口径：每条已采集评论等权，请结合来源视频占比解读。</p>
    </div>
  </section>;
}
