import { useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { chartTooltip, chartTextColor } from '../utils';
import useDistributionChartTransition, { type DistributionChartType } from '../hooks/useDistributionChartTransition';
import DownloadChartButton from './DownloadChartButton';

interface Props { male: number; female: number; unknown: number; }

export default function GenderChart({ male, female, unknown }: Props) {
  const { type, selectType, animationDurationUpdate } = useDistributionChartTransition();
  const chartRef = useRef<ReactECharts | null>(null);
  const tt = chartTooltip(); const tc = chartTextColor();
  const radiusMap: Record<DistributionChartType, [string,string]> = { donut:['50%','75%'], pie:['0%','72%'], rose:['20%','80%'] };
  const roseType = type === 'rose';
  const data = [
    { value:male, name:'男', itemStyle:{ color:'#38BDF8' } },
    { value:female, name:'女', itemStyle:{ color:'#FB7299' } },
    { value:unknown, name:'保密', itemStyle:{ color:'#64748B' } },
  ];
  const nonZeroData = data.filter(item => item.value > 0);
  const chartData = roseType
    ? nonZeroData.sort((a, b) => b.value - a.value)
    : nonZeroData;

  const option = {
    animationDurationUpdate,
    animationEasingUpdate: 'cubicInOut',
    tooltip: { trigger:'item', formatter:'{b}: {c} ({d}%)', backgroundColor:tt.backgroundColor, borderColor:tt.borderColor, textStyle:tt.textStyle },
    legend: { bottom:0, textStyle:{ color:tc, fontSize:11 } },
    series: [{
      type:'pie', radius:radiusMap[type], center:['50%','45%'], roseType:roseType?'radius':undefined,
      itemStyle: { borderRadius:8 },
      label: { color:tc, fontSize:11, formatter:'{b}: {d}%' },
      data: chartData,
    }],
  };

  const toggle = (t: DistributionChartType) => () => selectType(t, chartRef.current?.getEchartsInstance());

  return <div className="card distribution-chart-card">
    <div className="flex items-center justify-between mb-2 distribution-chart-header">
      <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>性别分布</h3>
      <div className="flex items-center gap-2">
        <DownloadChartButton echartRefs={chartRef} />
        <div className="segmented">
          <button className={type==='donut'?'active':''} onClick={toggle('donut')}>环形</button>
          <button className={type==='pie'?'active':''} onClick={toggle('pie')}>饼图</button>
          <button className={type==='rose'?'active':''} onClick={toggle('rose')}>玫瑰</button>
        </div>
      </div>
    </div>
    <ReactECharts ref={chartRef} option={option} style={{height:260,width:'100%'}}/>
  </div>;
}
