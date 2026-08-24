import { useEffect, useMemo, useState } from 'react';
import { generateGroupSummary, generateSummary, getGroupSummaries, getSummaries } from '../services/api';
import type { AISummary, AnalysisMode, FilterState, GroupAISummary, LLMProvider } from '../types';
import './DataPanels.css';

interface Props {
  scope: { kind: 'analysis'; id: number } | { kind: 'group'; id: number };
  filters: FilterState;
  matchedCount: number;
  mode: AnalysisMode;
}

const PROVIDER_NAMES: Record<LLMProvider, string> = {
  bailian: '阿里百炼',
  deepseek: 'DeepSeek',
  custom: '自定义接口',
};

const THINKING_MESSAGES = ['AI 正在思考', '正在仔细分析', '正在遣词造句'];

function sameFilters(left: FilterState, right: FilterState): boolean {
  return left.gender === right.gender
    && left.dateFrom === right.dateFrom
    && left.dateTo === right.dateTo
    && left.region === right.region
    && left.sentiment === right.sentiment
    && (left.duplicateMode || 'include') === (right.duplicateMode || 'include')
    && (left.sourceAnalysisId || 'all') === (right.sourceAnalysisId || 'all');
}

export default function AISummaryCard({ scope, filters, matchedCount, mode }: Props) {
  const [summaries, setSummaries] = useState<Array<AISummary | GroupAISummary>>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [thinkingText, setThinkingText] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    setError(null);
    const load = scope.kind === 'group' ? getGroupSummaries(scope.id) : getSummaries(scope.id);
    load
      .then(items => { if (active) setSummaries(items); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '读取总结失败'); })
      .finally(() => { if (active) setLoadingList(false); });
    return () => { active = false; };
  }, [scope.id, scope.kind, mode]);

  useEffect(() => {
    if (!generating) {
      setThinkingText('');
      return;
    }

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setThinkingText(THINKING_MESSAGES[0]);
      return;
    }

    let cancelled = false;
    let messageIndex = 0;
    let characterIndex = 0;
    let timer = 0;

    const typeNextCharacter = () => {
      if (cancelled) return;
      const message = THINKING_MESSAGES[messageIndex];
      if (characterIndex <= message.length) {
        setThinkingText(message.slice(0, characterIndex));
        characterIndex += 1;
        timer = window.setTimeout(typeNextCharacter, 85);
        return;
      }
      timer = window.setTimeout(() => {
        messageIndex = (messageIndex + 1) % THINKING_MESSAGES.length;
        characterIndex = 0;
        typeNextCharacter();
      }, 900);
    };

    typeNextCharacter();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [generating]);

  const exact = useMemo(
    () => summaries.find(item => sameFilters(item.filters, filters)),
    [summaries, filters],
  );
  const current = exact && !exact.stale ? exact : null;

  const run = async () => {
    setGenerating(true); setError(null);
    try {
      const result = scope.kind === 'group'
        ? await generateGroupSummary(scope.id, mode, filters, Boolean(exact))
        : await generateSummary(scope.id, filters, Boolean(exact));
      setSummaries(items => {
        // Regenerating a legacy `include` summary can retain its database id while
        // moving it to the new filter hash. Remove by both identities so the
        // obsolete object cannot win the next exact-match lookup.
        const others = items.filter(
          item => item.id !== result.id && item.filter_hash !== result.filter_hash,
        );
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
      <div className="ai-summary-header panel-heading">
        <div className="ai-summary-title-group">
          <div className="summary-signal" aria-hidden="true"><i /><i /><i /><i /></div>
          <div>
            <span className="ai-summary-eyebrow panel-status">CURRENT SIGNAL</span>
            <h3 id="ai-summary-title">AI 舆情简报</h3>
          </div>
        </div>
        <button type="button" className={`${current ? 'btn btn-ghost' : 'btn btn-primary'} ai-summary-card__action`}
          onClick={run} disabled={generating || loadingList || matchedCount === 0}>
          {generating ? '归纳中…' : current ? '重新生成' : exact?.stale ? '更新总结' : '生成总结'}
        </button>
      </div>

      {loadingList ? (
        <div className="ai-summary-loading"><span className="pulse-dot" />正在读取已保存的简报…</div>
      ) : generating ? (
        <div className="ai-summary-thinking" role="status" aria-live="polite">
          <div className="ai-summary-thinking__line">
            <span className="ai-summary-thinking__prompt" aria-hidden="true">AI</span>
            <strong>{thinkingText}<span className="ai-summary-thinking__cursor" aria-hidden="true" /></strong>
          </div>
          <p>正在归纳 {matchedCount} 条筛选评论，请保持当前页面开启。</p>
        </div>
      ) : current ? (
        <>
          <p className="ai-summary-text">{current.summary_text}</p>
          <div className="ai-summary-meta" aria-label="简报元数据">
            <span>基于 {current.matched_count} 条筛选数据</span>
            <span>抽取 {current.sampled_count} 条代表评论</span>
            <span>{PROVIDER_NAMES[current.provider]} · {current.model}</span>
            {updatedAt && <span>{new Date(updatedAt).toLocaleString('zh-CN')}</span>}
          </div>
        </>
      ) : (
        <div className="ai-summary-empty">
          <p>{matchedCount > 0
            ? `当前筛选命中 ${matchedCount} 条评论。生成后会保存到${scope.kind === 'group' ? '该舆情事件' : '这条分析记录'}。`
            : '当前筛选没有可总结的评论。'}</p>
          <span>{exact?.stale ? '评论数据或情绪标签已经变化，请更新总结。' : '只在点击按钮时调用模型，不会随筛选自动产生费用。'}</span>
        </div>
      )}

      {error && <div className="ai-summary-error" role="alert">{error}</div>}
      <p className="ai-summary-disclaimer">统计基于全部筛选结果，观点归纳使用代表性样本，AI 内容仅供参考。</p>
    </section>
  );
}
