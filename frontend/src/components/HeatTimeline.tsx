import ReactECharts from "echarts-for-react";
import type { HeatPoint } from "../types";

interface Props {
  timeline: HeatPoint[];
  hourlyDistribution: { hour: number; count: number }[];
  peakHour: string | null;
  peakCount: number;
}

export default function HeatTimeline({ timeline, hourlyDistribution, peakHour, peakCount }: Props) {
  const timeOption = {
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: timeline.map((p) => p.time.slice(5, 16)),
      axisLabel: { rotate: 30, fontSize: 10 },
    },
    yAxis: { type: "value", name: "评论数" },
    series: [
      {
        type: "line",
        data: timeline.map((p) => p.count),
        smooth: true,
        areaStyle: { color: "rgba(59,130,246,0.15)" },
        lineStyle: { color: "#3b82f6", width: 2 },
        itemStyle: { color: "#3b82f6" },
      },
    ],
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
  };

  const hourOption = {
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: hourlyDistribution.map((h) => `${h.hour}时`),
    },
    yAxis: { type: "value", name: "评论数" },
    series: [
      {
        type: "bar",
        data: hourlyDistribution.map((h) => h.count),
        itemStyle: { color: "#f59e0b", borderRadius: [4, 4, 0, 0] },
      },
    ],
    grid: { left: 50, right: 20, top: 10, bottom: 30 },
  };

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        热度趋势
        {peakHour && (
          <span className="ml-2 text-xs text-gray-400 font-normal">
            峰值: {peakHour} ({peakCount} 条)
          </span>
        )}
      </h3>
      <ReactECharts option={timeOption} style={{ height: 220 }} />
      <h4 className="text-xs text-gray-500 mt-3 mb-1">24小时分布</h4>
      <ReactECharts option={hourOption} style={{ height: 180 }} />
    </div>
  );
}
