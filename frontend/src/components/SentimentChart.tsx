import { useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';

interface Props { positive: number; negative: number; neutral: number; }

type ChartType = 'donut' | 'pie' | 'rose';

export default function SentimentChart({ positive, negative, neutral }: Props) {
  const [type, setType] = useState<ChartType>('donut');
  const tt = chartTooltip(); const tc = chartTextColor();

  const radiusMap: Record<ChartType, [string,string]> = { donut:['50%','75%'], pie:['0%','72%'], rose:['20%','80%'] };
  const roseType = type === 'rose';

  const option = {
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:0, textStyle:{ color:tc, fontSize:11 } },
    series: [{
      type:'pie', radius:radiusMap[type], center:['50%','45%'], roseType:roseType?'radius':undefined,
      itemStyle: { borderRadius:8 },
      label: { color:tc, fontSize:11, formatter:'{b}\n{d}%' },
      data: [
        { value:positive, name:'正面', itemStyle:{ color:'#34D399' } },
        { value:negative, name:'负面', itemStyle:{ color:'#F87171' } },
        { value:neutral, name:'中性', itemStyle:{ color:'#94A3B8' } },
      ],
    }],
  };

  const toggle = (t: ChartType) => () => setType(t);

  return <div className="card">
    <div className="flex items-center justify-between mb-2">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>情感分布</h3>
      <div className="segmented">
        <button className={type==='donut'?'active':''} onClick={toggle('donut')}>环形</button>
        <button className={type==='pie'?'active':''} onClick={toggle('pie')}>饼图</button>
        <button className={type==='rose'?'active':''} onClick={toggle('rose')}>玫瑰</button>
      </div>
    </div>
    <ReactECharts option={option} style={{height:260}}/>
  </div>;
}
