import { useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';

interface Props { male: number; female: number; unknown: number; }

type ChartType = 'donut' | 'pie' | 'rose';

export default function GenderChart({ male, female, unknown }: Props) {
  const [type, setType] = useState<ChartType>('donut');
  const tt = chartTooltip(); const tc = chartTextColor();
  const radiusMap: Record<ChartType, [string,string]> = { donut:['50%','75%'], pie:['0%','72%'], rose:['20%','80%'] };

  const option = {
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:0, textStyle:{ color:tc, fontSize:11 } },
    series: [{
      type:'pie', radius:radiusMap[type], center:['50%','45%'], roseType:type==='rose'?'radius':undefined,
      itemStyle: { borderRadius:8, borderColor:'var(--bg)', borderWidth:2 },
      label: { color:tc, fontSize:11, formatter:'{b}: {d}%' },
      data: [
        { value:male, name:'男', itemStyle:{ color:'#38BDF8' } },
        { value:female, name:'女', itemStyle:{ color:'#FB7299' } },
        { value:unknown, name:'保密', itemStyle:{ color:'#64748B' } },
      ],
    }],
  };

  const toggle = (t: ChartType) => () => setType(t);
  const btnStyle = (t: ChartType) => ({ fontSize:'.625rem', padding:'.125rem .375rem', borderRadius:'.25rem', cursor:'pointer', border:'1px solid var(--border)', background: type===t?'var(--accent-soft)':'transparent', color: type===t?'var(--accent)':'var(--text-muted)', transition:'all .15s ease' });

  return <div className="card">
    <div className="flex items-center justify-between mb-2">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>性别分布</h3>
      <div className="flex gap-1">
        <button style={btnStyle('donut')} onClick={toggle('donut')}>环形</button>
        <button style={btnStyle('pie')} onClick={toggle('pie')}>饼图</button>
        <button style={btnStyle('rose')} onClick={toggle('rose')}>玫瑰</button>
      </div>
    </div>
    <ReactECharts option={option} style={{height:260}}/>
  </div>;
}