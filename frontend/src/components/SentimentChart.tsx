import { useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';
import type { SentimentLLM, SentimentLLMV2, StyleDistributionV2, AnalysisMode } from '../types';
import useDistributionChartTransition, { type DistributionChartType } from '../hooks/useDistributionChartTransition';
import DownloadChartButton from './DownloadChartButton';
import AnalysisProgress from './AnalysisProgress';
import FilterSelect, { type FilterSelectOption } from './FilterSelect';

interface Props {
  positive: number; negative: number; neutral: number;
  mode: AnalysisMode;
  llm?: SentimentLLM | null;
  llmV2?: { emotion: SentimentLLMV2; style: StyleDistributionV2 } | null;
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

const MODE_OPTIONS: readonly FilterSelectOption<AnalysisMode>[] = [
  { value: 'nlp', label: 'NLP 三分类' },
  { value: 'llm', label: '大模型 情绪与表达风格' },
];

export default function SentimentChart({
  positive,
  negative,
  neutral,
  mode,
  llm,
  llmV2,
  onModeChange,
  reanalysis,
  backgroundReanalysis,
}: Props) {
  const emotionTransition = useDistributionChartTransition();
  const styleTransition = useDistributionChartTransition();
  const chartRef = useRef<ReactECharts | null>(null);
  const styleRef = useRef<ReactECharts | null>(null);
  const tt = chartTooltip(); const tc = chartTextColor();
  const isLLM = mode === 'llm' && llm;
  const isReanalyzing = reanalysis?.state === 'running';
  const hasReanalysisError = reanalysis?.state === 'error';

  if (mode === 'llm' && llmV2) {
    const emotions: Array<[keyof SentimentLLMV2, string, string]> = [['neutral','中性','#94A3B8'],['joy','喜悦','#FBBF24'],['trust','信任','#22C55E'],['anticipation','期待','#06B6D4'],['surprise','惊讶','#F97316'],['anger','愤怒','#EF4444'],['sadness','悲伤','#6366F1'],['fear','恐惧','#8B5CF6'],['disgust','厌恶','#84CC16']];
    const styles: Array<[keyof StyleDistributionV2, string, string]> = [['plain','平实','#94A3B8'],['sarcasm','反讽','#EC4899'],['meme','玩梗','#8B5CF6'],['rhetorical','反问','#06B6D4'],['hyperbole','夸张','#F97316']];
    const emotionData = emotions.map(([key, name, color]) => ({ value: llmV2.emotion[key], name, itemStyle:{ color } })).filter(item => item.value > 0);
    const styleData = styles.map(([key, name, color]) => ({ value: llmV2.style[key], name, itemStyle:{ color } })).filter(item => item.value > 0);
    const emotionRose = emotionTransition.type === 'rose';
    const styleRose = styleTransition.type === 'rose';
    const radiusMap: Record<DistributionChartType, [string, string]> = { donut:['48%','72%'], pie:['0%','72%'], rose:['20%','78%'] };
    const emotionOption = { animationDurationUpdate:emotionTransition.animationDurationUpdate, animationEasingUpdate:'cubicInOut', tooltip:{ trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle }, legend:{ bottom:2, textStyle:{ color:tc, fontSize:9 } }, series:[{ type:'pie', radius:radiusMap[emotionTransition.type], center:['50%','41%'], roseType:emotionRose?'radius':undefined, itemStyle:{ borderRadius:8 }, label:{ color:tc, fontSize:11, formatter:'{b}\n{d}%' }, data:emotionRose ? emotionData.sort((a,b)=>b.value-a.value) : emotionData }] };
    const styleOption = { animationDurationUpdate:styleTransition.animationDurationUpdate, animationEasingUpdate:'cubicInOut', tooltip:{ trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle }, legend:{ bottom:2, textStyle:{ color:tc, fontSize:9 } }, series:[{ type:'pie', radius:radiusMap[styleTransition.type], center:['50%','41%'], roseType:styleRose?'radius':undefined, itemStyle:{ borderRadius:8 }, label:{ color:tc, fontSize:11, formatter:'{b}\n{d}%' }, data:styleRose ? styleData.sort((a,b)=>b.value-a.value) : styleData }] };
    const toggleEmotion = (next: DistributionChartType) => () => emotionTransition.selectType(next, chartRef.current?.getEchartsInstance());
    const toggleStyle = (next: DistributionChartType) => () => styleTransition.selectType(next, styleRef.current?.getEchartsInstance());
    const controls = (type: DistributionChartType, toggle: (next: DistributionChartType) => () => void) => <div className="segmented"><button className={type==='donut'?'active':''} onClick={toggle('donut')}>环形</button><button className={type==='pie'?'active':''} onClick={toggle('pie')}>饼图</button><button className={type==='rose'?'active':''} onClick={toggle('rose')}>玫瑰</button></div>;
    return <div className="card distribution-chart-card"><div className="distribution-chart-header"><h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>情绪与表达风格（大模型）</h3><div className="distribution-chart-header__controls"><FilterSelect ariaLabel="情感分析模式" value={mode} options={MODE_OPTIONS} onChange={onModeChange} /></div><DownloadChartButton echartRefs={[chartRef, styleRef]} label="下载双图" /></div>{hasReanalysisError && <div className="sentiment-v2-retry" role="status"><span>{reanalysis?.errorText || '部分评论尚未完成'}</span>{reanalysis?.onRetry && <button type="button" className="btn btn-primary" onClick={reanalysis.onRetry}>继续补齐剩余评论</button>}</div>}<div className="sentiment-v2-layout"><div><div className="sentiment-v2-subheader"><h4>主情绪</h4>{controls(emotionTransition.type, toggleEmotion)}</div><ReactECharts ref={chartRef} option={emotionOption} style={{height:260,width:'100%'}}/></div><div><div className="sentiment-v2-subheader"><h4>表达风格</h4>{controls(styleTransition.type, toggleStyle)}</div><ReactECharts ref={styleRef} option={styleOption} style={{height:260,width:'100%'}}/></div></div></div>;
  }

  const radiusMap: Record<DistributionChartType, [string, string]> = { donut:['45%','70%'], pie:['0%','68%'], rose:['20%','74%'] };
  const roseType = emotionTransition.type === 'rose';

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
    animationDurationUpdate: emotionTransition.animationDurationUpdate,
    animationEasingUpdate: 'cubicInOut',
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:2, itemWidth:13, itemHeight:8, itemGap:7, textStyle:{ color:tc, fontSize:9 } },
    series: [{
      type:'pie', radius:radiusMap[emotionTransition.type], center:['50%','41%'], roseType:roseType?'radius':undefined,
      itemStyle: { borderRadius:8 },
      label: { color:tc, fontSize:11, formatter: '{b}\n{d}%' },
      data:chartData,
    }],
  };

  const toggle = (t: DistributionChartType) => () => emotionTransition.selectType(t, chartRef.current?.getEchartsInstance());

  return (
    <div className="card distribution-chart-card">
      <div className="distribution-chart-header">
        <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>
          {isReanalyzing ? '情绪与表达风格（大模型分析中）' : hasReanalysisError ? '情绪与表达风格（部分未完成）' : `情感分布${isLLM ? '（大模型十分类）' : '（NLP 三分类）'}`}
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
              <button className={emotionTransition.type==='donut'?'active':''} onClick={toggle('donut')}>环形</button>
              <button className={emotionTransition.type==='pie'?'active':''} onClick={toggle('pie')}>饼图</button>
              <button className={emotionTransition.type==='rose'?'active':''} onClick={toggle('rose')}>玫瑰</button>
            </div>
            <FilterSelect ariaLabel="情感分析模式" value={mode} options={MODE_OPTIONS} onChange={onModeChange} />
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
          detail={hasReanalysisError ? reanalysis?.errorText : '仅统计已完成的 V2 标签'}
          action={(
            <div className="analysis-progress__actions">
              {hasReanalysisError && reanalysis?.onRetry && (
                <button type="button" className="btn btn-primary" onClick={reanalysis.onRetry}>继续补齐剩余评论</button>
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
