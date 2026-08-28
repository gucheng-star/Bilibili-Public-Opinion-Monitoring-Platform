import { useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';
import type { SentimentLLM, AnalysisMode } from '../types';
import useDistributionChartTransition, { type DistributionChartType } from '../hooks/useDistributionChartTransition';
import DownloadChartButton from './DownloadChartButton';
import AnalysisProgress from './AnalysisProgress';

interface Props {
  positive: number; negative: number; neutral: number;
  mode: AnalysisMode;
  llm?: SentimentLLM | null;
  onModeChange: (mode: AnalysisMode) => void;
  reanalysis?: {
    state: 'running' | 'error';
    current: number;
    total: number;
    statusText: string;
    errorText?: string;
    onRetry?: () => void;
    onShowNlp?: () => void;
  };
  backgroundReanalysis?: {
    state: 'running' | 'error';
    current: number;
    total: number;
    onShowDetails: () => void;
  };
}

const LLM_COLORS: Record<string, string> = {
  neutral: '#94A3B8', joy: '#FBBF24', support: '#22C55E', anticipation: '#06B6D4',
  surprise: '#F97316', anger: '#EF4444', sadness: '#6366F1', concern: '#8B5CF6', disgust: '#84CC16', sarcasm: '#EC4899',
};

const LLM_LABELS: Record<string, string> = {
  neutral: '中性', joy: '喜悦', support: '支持', anticipation: '期待', surprise: '惊讶',
  anger: '愤怒', sadness: '悲伤', concern: '担忧', disgust: '厌恶', sarcasm: '反讽',
};

export default function SentimentChart({
  positive,
  negative,
  neutral,
  mode,
  llm,
  onModeChange,
  reanalysis,
  backgroundReanalysis,
}: Props) {
  const { type, selectType, animationDurationUpdate } = useDistributionChartTransition();
  const chartRef = useRef<ReactECharts | null>(null);
  const tt = chartTooltip(); const tc = chartTextColor();
  const isLLM = mode === 'llm' && llm;
  const isReanalyzing = reanalysis?.state === 'running';
  const hasReanalysisError = reanalysis?.state === 'error';

  const radiusMap: Record<DistributionChartType, [string, string]> = { donut:['45%','70%'], pie:['0%','68%'], rose:['20%','74%'] };
  const roseType = type === 'rose';

  const data = isLLM
    ? Object.entries(LLM_LABELS).map(([key, label]) => ({
        value: (llm as SentimentLLM)[key as keyof SentimentLLM] || 0,
        name: label,
        itemStyle: { color: LLM_COLORS[key] },
      }))
    : [
        { value: positive, name: '正面', itemStyle: { color: '#34D399' } },
        { value: negative, name: '负面', itemStyle: { color: '#F87171' } },
        { value: neutral, name: '中性', itemStyle: { color: '#94A3B8' } },
      ];
  const nonZeroData = data.filter(item => item.value > 0);
  const chartData = roseType
    ? nonZeroData.sort((a, b) => b.value - a.value)
    : nonZeroData;

  const option = {
    animationDurationUpdate,
    animationEasingUpdate: 'cubicInOut',
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:2, itemWidth:13, itemHeight:8, itemGap:7, textStyle:{ color:tc, fontSize:9 } },
    series: [{
      type:'pie', radius:radiusMap[type], center:['50%','41%'], roseType:roseType?'radius':undefined,
      itemStyle: { borderRadius:8 },
      label: { color:tc, fontSize:11, formatter: '{b}\n{d}%' },
      data:chartData,
    }],
  };

  const toggle = (t: DistributionChartType) => () => selectType(t, chartRef.current?.getEchartsInstance());

  return (
    <div className="card distribution-chart-card">
      <div className="distribution-chart-header">
        <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>
          {isReanalyzing ? '情感分布（大模型分析中）' : hasReanalysisError ? '情感分布（大模型分析未完成）' : `情感分布${isLLM ? '（大模型十分类）' : '（NLP 三分类）'}`}
        </h3>
        {!isReanalyzing && !hasReanalysisError && (
          <div className="distribution-chart-header__controls">
            {backgroundReanalysis && (
              <button
                type="button"
                className="analysis-progress__background-status"
                onClick={backgroundReanalysis.onShowDetails}
              >
                {backgroundReanalysis.state === 'running' ? '大模型后台处理中' : '大模型分析未完成'}
                {' '}{backgroundReanalysis.current}/{backgroundReanalysis.total}
              </button>
            )}
            <div className="segmented">
              <button className={type==='donut'?'active':''} onClick={toggle('donut')}>环形</button>
              <button className={type==='pie'?'active':''} onClick={toggle('pie')}>饼图</button>
              <button className={type==='rose'?'active':''} onClick={toggle('rose')}>玫瑰</button>
            </div>
            <select value={mode} onChange={e => onModeChange(e.target.value as AnalysisMode)}
              style={{
                padding: '.25rem .375rem', fontSize: '.6875rem',
                background: 'var(--bg)', color: 'var(--text-primary)',
                border: '1px solid var(--border)', borderRadius: '.375rem',
                cursor: 'pointer', outline: 'none',
              }}>
              <option value="nlp">NLP 三分类</option>
              <option value="llm">大模型 十分类</option>
            </select>
          </div>
        )}
        {!isReanalyzing && !hasReanalysisError && <DownloadChartButton echartRefs={chartRef} />}
      </div>
      {isReanalyzing || hasReanalysisError ? (
        <AnalysisProgress
          current={reanalysis?.current ?? 0}
          total={reanalysis?.total ?? 0}
          statusText={reanalysis?.statusText || '正在分析评论情感…'}
          ariaLabel={hasReanalysisError ? '大模型重分析未完成' : '大模型重分析进度'}
          title={hasReanalysisError ? '大模型分析未完成' : '大模型分析进度'}
          detail={hasReanalysisError ? reanalysis?.errorText : '每批最多5条，最多3批并发'}
          action={(
            <div className="analysis-progress__actions">
              {hasReanalysisError && reanalysis?.onRetry && (
                <button type="button" className="btn btn-primary" onClick={reanalysis.onRetry}>重新补齐剩余评论</button>
              )}
              {reanalysis?.onShowNlp && (
                <button type="button" className="btn btn-ghost" onClick={reanalysis.onShowNlp}>后台运行，查看 NLP</button>
              )}
            </div>
          )}
        />
      ) : <ReactECharts ref={chartRef} option={option} style={{height:260,width:'100%'}}/>}
    </div>
  );
}
