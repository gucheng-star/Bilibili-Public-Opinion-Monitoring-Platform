import { useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';

interface Props { positive: number; negative: number; neutral: number; }

type ChartType = 'donut' | 'pie' | 'rose';

export default function SentimentChart({ positive, negative, neutral }: Props) {
  const [type, setType] = useState<ChartType>('donut');
  const total = positive + negative + neutral || 1;
  const tt = chartTooltip(); const tc = chartTextColor();

  const radiusMap: Record<ChartType, [string,string]> = { donut:['50%','75%'], pie:['0%','72%'], rose:['20%','80%'] };
  const roseType = type === 'rose';

  const option = {
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:0, textStyle:{ color:tc, fontSize:11 } },
    series: [{
      type:'pie', radius:radiusMap[type], center:['50%','45%'], roseType:roseType?'radius':undefined,
      itemStyle: { borderRadius:8, borderColor:'var(--bg)', borderWidth:2 },
      label: { color:tc, fontSize:11, formatter:'{b}\n{d}%' },
      data: [
        { value:positive, name:'正面', itemStyle:{ color:'#34D399' } },
        { value:negative, name:'负面', itemStyle:{ color:'#F87171' } },
        { value:neutral, name:'中性', itemStyle:{ color:'#94A3B8' } },
      ],
    }],
  };

  const toggle = (t: ChartType) => () => setType(t);
  const btnStyle = (t: ChartType) => ({ fontSize:'.625rem', padding:'.125rem .375rem', borderRadius:'.25rem', cursor:'pointer', border:'1px solid var(--border)', background: type===t?'var(--accent-soft)':'transparent', color: type===t?'var(--accent)':'var(--text-muted)', transition:'all .15s ease' });

  return <div className="card">
    <div className="flex items-center justify-between mb-2">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>情感分布</h3>
      <div className="flex gap-1">
        <button style={btnStyle('donut')} onClick={toggle('donut')}>环形</button>
        <button style={btnStyle('pie')} onClick={toggle('pie')}>饼图</button>
        <button style={btnStyle('rose')} onClick={toggle('rose')}>玫瑰</button>
      </div>
    </div>
    <ReactECharts option={option} style={{height:260}}/>
    <div className="flex justify-around text-xs text-secondary mt-1">
      <span>正面 {(positive/total*100).toFixed(1)}%</span>
      <span>中性 {(neutral/total*100).toFixed(1)}%</span>
      <span>负面 {(negative/total*100).toFixed(1)}%</span>
    </div>
  </div>;
}