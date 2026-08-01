import { useEffect, useMemo, useState } from 'react';
import { generateSummary, getSummaries } from '../services/api';
import type { AISummary, AnalysisMode, FilterState, LLMProvider } from '../types';

interface Props {
  analysisId: number;
  filters: FilterState;
  matchedCount: number;
  mode: AnalysisMode;
}

const PROVIDER_NAMES: Record<LLMProvider, string> = {
  bailian: '阿里百炼',
  deepseek: 'DeepSeek',
  custom: '自定义接口',
};

function sameFilters(left: FilterState, right: FilterState): boolean {
  return left.gender === right.gender
    && left.dateFrom === right.dateFrom
    && left.dateTo === right.dateTo
    && left.region === right.region
    && left.sentiment === right.sentiment;
}

export default function AISummaryCard({ analysisId, filters, matchedCount, mode }: Props) {
  const [summaries, setSummaries] = useState<AISummary[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    setError(null);
    getSummaries(analysisId)
      .then(items => { if (active) setSummaries(items); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '读取总结失败'); })
      .finally(() => { if (active) setLoadingList(false); });
    return () => { active = false; };
  }, [analysisId, mode]);

  const exact = useMemo(
    () => summaries.find(item => sameFilters(item.filters, filters)),
    [summaries, filters],
  );
  const current = exact && !exact.stale ? exact : null;

  const run = async () => {
    setGenerating(true); setError(null);
    try {
      const result = await generateSummary(analysisId, filters, Boolean(exact));
      setSummaries(items => {
        const others = items.filter(item => item.filter_hash !== result.filter_hash);
        return [...others, result];
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成总结失败');
    } finally {
      setGenerating(false);
    }
  };

  const updatedAt = current?.updated_at || current?.created_at;

  return (
    <section className="card ai-summary-card" aria-labelledby="ai-summary-title">
      <div className="ai-summary-header">
        <div className="ai-summary-title-group">
          <div className="summary-signal" aria-hidden="true"><i /><i /><i /><i /></div>
          <div>
            <span className="ai-summary-eyebrow">CURRENT SIGNAL</span>
            <h3 id="ai-summary-title">AI 舆情简报</h3>
          </div>
        </div>
        <button type="button" className={current ? 'btn btn-ghost' : 'btn btn-primary'}
          onClick={run} disabled={generating || loadingList || matchedCount === 0}>
          {generating ? '归纳中…' : current ? '重新生成' : exact?.stale ? '更新总结' : '生成总结'}
        </button>
      </div>

      {loadingList ? (
        <div className="ai-summary-loading"><span className="pulse-dot" />正在读取已保存的简报…</div>
      ) : current ? (
        <>
          <p className="ai-summary-text">{current.summary_text}</p>
          <div className="ai-summary-meta">
            <span>基于 {current.matched_count} 条筛选数据</span>
            <span>抽取 {current.sampled_count} 条代表评论</span>
            <span>{PROVIDER_NAMES[current.provider]} · {current.model}</span>
            {updatedAt && <span>{new Date(updatedAt).toLocaleString('zh-CN')}</span>}
          </div>
        </>
      ) : (
        <div className="ai-summary-empty">
          <p>{matchedCount > 0 ? `当前筛选命中 ${matchedCount} 条评论。生成后会保存到这条分析记录。` : '当前筛选没有可总结的评论。'}</p>
          <span>{exact?.stale ? '评论数据或情绪标签已经变化，请更新总结。' : '只在点击按钮时调用模型，不会随筛选自动产生费用。'}</span>
        </div>
      )}

      {error && <div className="ai-summary-error" role="alert">{error}</div>}
      <p className="ai-summary-disclaimer">统计基于全部筛选结果，观点归纳使用代表性样本，AI 内容仅供参考。</p>
    </section>
  );
}
