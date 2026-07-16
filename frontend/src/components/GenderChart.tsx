import ReactECharts from "echarts-for-react";

interface Props {
  male: number;
  female: number;
  unknown: number;
}

export default function GenderChart({ male, female, unknown }: Props) {
  const option = {
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0 },
    series: [
      {
        name: "性别分布",
        type: "pie",
        radius: "70%",
        center: ["50%", "45%"],
        data: [
          { value: male, name: "男", itemStyle: { color: "#3b82f6" } },
          { value: female, name: "女", itemStyle: { color: "#ec4899" } },
          { value: unknown, name: "保密", itemStyle: { color: "#9ca3af" } },
        ],
        label: { show: true, formatter: "{b}: {d}%" },
      },
    ],
  };

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">性别分布</h3>
      <ReactECharts option={option} style={{ height: 280 }} />
    </div>
  );
}
