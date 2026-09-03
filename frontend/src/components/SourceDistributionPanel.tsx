import { useMemo, useState } from 'react';
import type { AnalysisMode, CommentData, SentimentLLMV2, SourceDistributionItem } from '../types';
import './DataPanels.css';

interface Props { sources: SourceDistributionItem[]; filteredComments: CommentData[]; mode: AnalysisMode; }

const EMOTION_LABELS: Record<string, string> = { positive: '正面', negative: '负面', neutral: '中性', joy: '喜悦', trust: '信任', anticipation: '期待', surprise: '惊讶', anger: '愤怒', sadness: '悲伤', fear: '恐惧', disgust: '厌恶' };

export default function SourceDistributionPanel({ sources, filteredComments, mode }: Props) {
  const [view, setView] = useState<'overall' | 'compare'>('overall');
  const rows = useMemo(() => {
    const bySource = new Map<number, CommentData[]>();
    filteredComments.forEach(comment => {
      if (comment.source_analysis_id === undefined) return;
      const comments = bySource.get(comment.source_analysis_id) || [];
      comments.push(comment);
      bySource.set(comment.source_analysis_id, comments);
    });
    return sources.map(source => {
      const comments = bySource.get(source.analysis_id) || [];
      const sentiment = { positive: 0, negative: 0, neutral: 0 };
      const sentimentLlm: SentimentLLMV2 = { neutral:0, joy:0, trust:0, anticipation:0, surprise:0, anger:0, sadness:0, fear:0, disgust:0 };
      comments.forEach(comment => {
        if (comment.sentiment_label in sentiment) sentiment[comment.sentiment_label] += 1;
        const label = comment.sentiment_llm_label as keyof SentimentLLMV2;
        if (comment.sentiment_llm_schema_version === 2 && label in sentimentLlm) sentimentLlm[label] += 1;
      });
      return { ...source, filtered: comments.length, filteredSentiment: sentiment, filteredSentimentLlm: sentimentLlm };
    }).sort((a, b) => b.filtered - a.filtered);
  }, [sources, filteredComments]);
  const total = filteredComments.length;
  return <section className="card source-distribution" aria-labelledby="source-distribution-title">
    <div className="flex items-center justify-between mb-3 source-distribution__header"><div><h3 id="source-distribution-title" className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>来源视频</h3><p>筛选后 {total.toLocaleString()} 条评论；各来源占比用于识别评论量主导。</p></div><div className="segmented"><button type="button" className={view === 'overall' ? 'active' : ''} onClick={() => setView('overall')}>来源占比</button><button type="button" className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}>逐视频对比</button></div></div>
    <div className="source-distribution__table-wrap"><table className="source-distribution__table"><thead><tr><th>视频</th><th>BV</th><th>原始评论</th><th>筛选后</th><th>占评论池</th>{view === 'compare' && <th>{mode === 'llm' ? '主情绪' : '主要情感'}</th>}<th>大模型覆盖</th></tr></thead><tbody>{rows.map(row => { const sentiments = mode === 'llm' ? row.filteredSentimentLlm : row.filteredSentiment; const main = row.filtered ? Object.entries(sentiments).sort((left, right) => Number(right[1]) - Number(left[1]))[0] : undefined; const completed = row.v2_completed_comments; const pending = row.v2_pending_comments; return <tr key={row.analysis_id}><td title={row.video_title}>{row.video_title || '-'}</td><td>{row.bv}</td><td>{row.total_comments.toLocaleString()}</td><td>{row.filtered.toLocaleString()}</td><td>{total ? `${(row.filtered / total * 100).toFixed(1)}%` : '0%'}</td>{view === 'compare' && <td>{main ? `${EMOTION_LABELS[main[0]] || main[0]} ${main[1]} 条` : '-'}</td>}<td>{completed === undefined ? (row.llm_ready ? '已完成' : '待补齐') : pending ? `${completed}/${row.v2_total_comments}，待补齐 ${pending}` : '已完成'}</td></tr>; })}</tbody></table></div>
  </section>;
}
