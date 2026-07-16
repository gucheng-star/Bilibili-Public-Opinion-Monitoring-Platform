import ReactECharts from "echarts-for-react";

interface Props {
  positive: number;
  negative: number;
  neutral: number;
}

export default function SentimentChart({ positive, negative, neutral }: Props) {
  const total = positive + negative + neutral || 1;
  const option = {
    tooltip: {
      trigger: "item",
      formatter: "{b}: {c} ({d}%)",
    },
    legend: { bottom: 0 },
    series: [
      {
        name: "情感分布",
        type: "pie",
        radius: ["50%", "75%"],
        center: ["50%", "45%"],
        label: { show: true, formatter: "{b}\n{d}%" },
        emphasis: { label: { fontSize: 16, fontWeight: "bold" } },
        data: [
          { value: positive, name: "正面", itemStyle: { color: "#22c55e" } },
          { value: negative, name: "负面", itemStyle: { color: "#ef4444" } },
          { value: neutral, name: "中性", itemStyle: { color: "#6b7280" } },
        ],
      },
    ],
  };

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">情感分布</h3>
      <ReactECharts option={option} style={{ height: 280 }} />
      <div className="flex justify-around text-xs text-gray-500 mt-1">
        <span>正面: {(positive / total * 100).toFixed(1)}%</span>
        <span>中性: {(neutral / total * 100).toFixed(1)}%</span>
        <span>负面: {(negative / total * 100).toFixed(1)}%</span>
      </div>
    </div>
  );
}
