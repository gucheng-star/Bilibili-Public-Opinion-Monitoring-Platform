import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { generateGroupSummary, generateSummary, getGroupSummaries, getSummaries } from '../services/api';
import FilterSelect, { type FilterSelectOption } from './FilterSelect';
import type { AISummary, AnalysisMode, FilterState, GroupAISummary, InterpretationView, LLMProvider, SummaryReportMode } from '../types';
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
  zhipu: '智谱 GLM',
  custom: '自定义接口',
};

const THINKING_MESSAGES = ['AI 正在思考', '正在仔细分析', '正在遣词造句'];

const VIEW_OPTIONS: readonly FilterSelectOption<InterpretationView>[] = [
  { value: 'public_opinion', label: '舆情观察' },
  { value: 'pr_risk', label: '公关与风险处置' },
  { value: 'creator', label: '视频创作者' },
  { value: 'news_editor', label: '新闻编辑' },
];

const REPORT_MODE_OPTIONS: readonly FilterSelectOption<SummaryReportMode>[] = [
  { value: 'quick', label: '快速' },
  { value: 'standard', label: '标准' },
];

const VIEW_BOUNDARIES: Record<InterpretationView, string> = {
  public_opinion: '关注整体情绪、讨论焦点、主要分歧与变化线索。',
  pr_risk: '关注可能引发误解的表达、潜在舆情风险与待关注事项。',
  creator: '关注观众关注点、理解障碍与内容改进线索。',
  news_editor: '关注待核实说法、观点分歧、叙事倾向与采访线索。',
};

const STANDARD_HEADINGS = ['观察', '依据与边界', '建议线索'] as const;

function standardSections(summary: string): Array<{ heading: string; content: string }> | null {
  const matches = Array.from(summary.matchAll(/(?:^|\n)\s*(?:#{1,6}\s*|\*\*)?(观察|依据与边界|建议线索)(?:\*\*)?\s*(?:[：:]|\n)/g));
  if (matches.length !== STANDARD_HEADINGS.length) return null;

  const sections = matches.map((match, index) => ({
    heading: match[1],
    content: summary.slice((match.index ?? 0) + match[0].length, matches[index + 1]?.index).trim(),
  }));
  return sections.every(section => section.content) ? sections : null;
}

function renderInlineMarkdown(value: string): ReactNode {
  return value.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    const bold = /^\*\*([^*]+)\*\*$/.exec(part);
    return bold ? <strong key={index}>{bold[1]}</strong> : part;
  });
}

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
  const [interpretationView, setInterpretationView] = useState<InterpretationView>('public_opinion');
  const [reportMode, setReportMode] = useState<SummaryReportMode>('quick');

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

  const exact = useMemo(() => summaries.find(item => {
    if (!sameFilters(item.filters, filters)) return false;
    if (scope.kind === 'group') return true;
    return 'analysis_id' in item
      && item.interpretation_view === interpretationView
      && item.report_mode === reportMode;
  }), [summaries, filters, interpretationView, reportMode, scope.kind]);
  const current = exact && !exact.stale ? exact : null;
  const analysisSummary = scope.kind === 'analysis' && current && 'analysis_id' in current ? current : null;
  const standardReportSections = analysisSummary?.report_mode === 'standard'
    ? standardSections(analysisSummary.summary_text)
    : null;

  const run = async () => {
    setGenerating(true); setError(null);
    try {
      const result = scope.kind === 'group'
        ? await generateGroupSummary(scope.id, mode, filters, Boolean(exact))
        : await generateSummary(scope.id, filters, Boolean(exact), interpretationView, reportMode);
      setSummaries(items => {
        // Regenerating a legacy `include` summary can retain its database id while
        // moving it to the new filter hash. Remove by both identities so the
        // obsolete object cannot win the next exact-match lookup.
        const others = items.filter(item => scope.kind === 'group'
          ? item.id !== result.id && item.filter_hash !== result.filter_hash
          : item.id !== result.id,
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
        <button type="button" className="btn btn-ghost ai-summary-card__action"
          onClick={run} disabled={generating || loadingList || matchedCount === 0}>
          {generating ? '归纳中…' : current ? '重新生成' : exact?.stale ? '更新总结' : '生成总结'}
        </button>
      </div>

      {scope.kind === 'analysis' && (
        <div className="ai-summary-controls" aria-label="简评生成选项">
          <label className="ai-summary-control">
            <span>解读视角</span>
            <FilterSelect ariaLabel="解读视角" value={interpretationView} options={VIEW_OPTIONS} onChange={setInterpretationView} />
          </label>
          <label className="ai-summary-control">
            <span>报告模式</span>
            <FilterSelect ariaLabel="报告模式" value={reportMode} options={REPORT_MODE_OPTIONS} onChange={setReportMode} />
          </label>
          <p className="ai-summary-boundary">{VIEW_BOUNDARIES[interpretationView]}</p>
        </div>
      )}

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
          {standardReportSections ? (
            <div className="ai-summary-standard-report" aria-label="标准报告内容">
              {standardReportSections.map(section => <section key={section.heading}>
                <h4>{section.heading}</h4>
                <p>{renderInlineMarkdown(section.content)}</p>
              </section>)}
            </div>
          ) : <p className="ai-summary-text">{renderInlineMarkdown(current.summary_text)}</p>}
          <div className="ai-summary-meta" aria-label="简报元数据">
            <span>基于 {current.matched_count} 条筛选数据</span>
            <span>抽取 {current.sampled_count} 条代表评论</span>
            <span>{PROVIDER_NAMES[current.provider]} · {current.model}</span>
            {analysisSummary && <span>{VIEW_OPTIONS.find(option => option.value === analysisSummary.interpretation_view)?.label} · {analysisSummary.report_mode === 'quick' ? '快速报告' : '标准报告'}</span>}
            {analysisSummary?.report_mode === 'standard' && analysisSummary.thinking_status === 'enabled' && <span>已启用模型思考</span>}
            {analysisSummary?.report_mode === 'standard' && analysisSummary.thinking_status === 'unsupported' && <span className="ai-summary-meta__notice">当前模型未启用思考，已按普通生成完成</span>}
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
      <p className="ai-summary-disclaimer">统计基于全部筛选结果，观点归纳使用代表性样本；点击生成或重新生成会按当前模型配置产生费用，AI 内容仅供参考。</p>
    </section>
  );
}
