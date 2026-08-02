import { useState, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';
import type { SentimentLLM, AnalysisMode } from '../types';
import DownloadChartButton from './DownloadChartButton';

interface Props {
  positive: number; negative: number; neutral: number;
  mode: AnalysisMode;
  llm?: SentimentLLM | null;
  onModeChange: (mode: AnalysisMode) => void;
}

type ChartType = 'donut' | 'pie' | 'rose';

const LLM_COLORS: Record<string, string> = {
  neutral: '#94A3B8', joy: '#FBBF24', support: '#22C55E', anticipation: '#06B6D4',
  surprise: '#F97316', anger: '#EF4444', sadness: '#6366F1', concern: '#8B5CF6', disgust: '#84CC16',
};

const LLM_LABELS: Record<string, string> = {
  neutral: '中性', joy: '喜悦', support: '支持', anticipation: '期待', surprise: '惊讶',
  anger: '愤怒', sadness: '悲伤', concern: '担忧', disgust: '厌恶',
};

export default function SentimentChart({ positive, negative, neutral, mode, llm, onModeChange }: Props) {
  const [type, setType] = useState<ChartType>('donut');
  const chartRef = useRef<ReactECharts | null>(null);
  const tt = chartTooltip(); const tc = chartTextColor();
  const isLLM = mode === 'llm' && llm;

  const radiusMap: Record<ChartType, [string, string]> = { donut:['45%','70%'], pie:['0%','68%'], rose:['20%','74%'] };
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
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:2, itemWidth:13, itemHeight:8, itemGap:7, textStyle:{ color:tc, fontSize:9 } },
    series: [{
      type:'pie', radius:radiusMap[type], center:['50%','41%'], roseType:roseType?'radius':undefined,
      itemStyle: { borderRadius:8 },
      label: { color:tc, fontSize:11, formatter: '{b}\n{d}%' },
      data:chartData,
    }],
  };

  const toggle = (t: ChartType) => () => setType(t);

  return (
    <div className="card distribution-chart-card">
      <div className="flex items-center justify-between mb-2 distribution-chart-header">
        <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>
          情感分布{isLLM ? '（大模型九类主情感）' : '（NLP 三分类）'}
        </h3>
        <div className="flex items-center gap-2">
          <DownloadChartButton echartRefs={chartRef} />
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
            <option value="llm">大模型 九类主情感</option>
          </select>
        </div>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{height:260,width:'100%'}}/>
    </div>
  );
}
