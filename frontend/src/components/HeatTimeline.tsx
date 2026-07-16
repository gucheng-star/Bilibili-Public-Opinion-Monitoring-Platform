import ReactECharts from 'echarts-for-react';
import type { HeatPoint } from '../types';
import { chartTooltip, chartTextColor } from '../utils';

interface Props { timeline: HeatPoint[]; hourlyDistribution: {hour:number;count:number}[]; peakHour: string | null; peakCount: number; }

export default function HeatTimeline({ timeline, hourlyDistribution, peakHour, peakCount }: Props) {
  const tt = chartTooltip(); const tc = chartTextColor();
  const timeOption = {
    tooltip: { trigger: 'axis', backgroundColor: tt.backgroundColor, borderColor: tt.borderColor, textStyle: tt.textStyle },
    xAxis: { type: 'category', data: timeline.map(p => p.time.slice(5, 16)), axisLabel: { rotate: 30, fontSize: 10, color: tc } },
    yAxis: { type: 'value', name: '评论数', nameTextStyle: { color: tc }, axisLabel: { color: tc } },
    series: [{ type: 'line', data: timeline.map(p => p.count), smooth: true, areaStyle: { color: 'rgba(251,114,153,.10)' }, lineStyle: { color: '#FB7299', width: 2 }, itemStyle: { color: '#FB7299' } }],
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
  };
  const hourOption = {
    tooltip: { trigger: 'axis', backgroundColor: tt.backgroundColor, borderColor: tt.borderColor, textStyle: tt.textStyle },
    xAxis: { type: 'category', data: hourlyDistribution.map(h => h.hour + '时'), axisLabel: { color: tc, fontSize: 10 } },
    yAxis: { type: 'value', name: '评论数', nameTextStyle: { color: tc }, axisLabel: { color: tc } },
    series: [{ type: 'bar', data: hourlyDistribution.map(h => h.count), itemStyle: { color: '#FB7299', borderRadius: [4, 4, 0, 0], opacity: .7 } }],
    grid: { left: 50, right: 20, top: 10, bottom: 30 },
  };
  return <div className="card">
    <h3 className="text-xs font-semibold text-secondary mb-2" style={{letterSpacing:'.05em'}}>
      热度趋势 {peakHour && <span className="ml-2 text-xs text-muted" style={{fontWeight:400}}>峰值: {peakHour} ({peakCount} 条)</span>}
    </h3>
    <ReactECharts option={timeOption} style={{ height: 200 }} />
    <h4 className="text-xs text-muted mt-3 mb-1">24小时分布</h4>
    <ReactECharts option={hourOption} style={{ height: 160 }} />
  </div>;
}