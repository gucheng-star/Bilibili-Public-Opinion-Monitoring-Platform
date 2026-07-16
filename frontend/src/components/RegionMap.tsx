import ReactECharts from "echarts-for-react";
import type { RegionItem } from "../types";

interface Props {
  data: RegionItem[];
}

// 省份名称到 ECharts 地图名的映射
const NAME_MAP: Record<string, string> = {
  "北京": "北京", "天津": "天津", "上海": "上海", "重庆": "重庆",
  "河北": "河北", "山西": "山西", "辽宁": "辽宁", "吉林": "吉林",
  "黑龙江": "黑龙江", "江苏": "江苏", "浙江": "浙江", "安徽": "安徽",
  "福建": "福建", "江西": "江西", "山东": "山东", "河南": "河南",
  "湖北": "湖北", "湖南": "湖南", "广东": "广东", "海南": "海南",
  "四川": "四川", "贵州": "贵州", "云南": "云南", "陕西": "陕西",
  "甘肃": "甘肃", "青海": "青海", "台湾": "台湾",
  "内蒙古": "内蒙古", "广西": "广西", "西藏": "西藏", "宁夏": "宁夏",
  "新疆": "新疆", "香港": "香港", "澳门": "澳门",
};

export default function RegionMap({ data }: Props) {
  const mapData = data
    .filter((d) => NAME_MAP[d.region])
    .map((d) => ({ name: NAME_MAP[d.region], value: d.count }));

  const option = {
    tooltip: {
      trigger: "item",
      formatter: "{b}: {c} 条评论",
    },
    visualMap: {
      min: 0,
      max: Math.max(...data.map((d) => d.count), 1),
      left: -10,
      bottom: 0,
      text: ["高", "低"],
      inRange: { color: ["#e0f2fe", "#0ea5e9", "#0369a1"] },
      calculable: false,
    },
    geo: {
      map: "china",
      roam: false,
      layoutCenter: ["50%", "50%"],
      layoutSize: "100%",
      itemStyle: {
        areaColor: "#f3f4f6",
        borderColor: "#d1d5db",
      },
      emphasis: {
        itemStyle: { areaColor: "#93c5fd" },
      },
    },
    series: [
      {
        name: "评论地域分布",
        type: "map",
        map: "china",
        geoIndex: 0,
        data: mapData,
      },
    ],
  };

  if (!data.length) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">地域分布</h3>
        <div className="flex items-center justify-center h-72 text-gray-400 text-sm">
          暂无地域数据（用户未显示 IP 属地）
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">地域分布</h3>
      <ReactECharts option={option} style={{ height: 360 }} />
    </div>
  );
}
