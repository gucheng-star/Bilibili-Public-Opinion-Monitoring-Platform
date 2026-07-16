import { useEffect, useState } from "react";
import { getHistory } from "../services/api";
import type { HistoryItem } from "../types";

interface Props {
  onSelect: (id: number) => void;
  selectedId: number | null;
}

export default function HistoryPanel({ onSelect, selectedId }: Props) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    getHistory()
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">历史记录</h3>
        <div className="text-xs text-gray-400">加载中...</div>
      </div>
    );
  }

  if (!items.length) return null;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-700">历史记录</h3>
        <button onClick={load} className="text-xs text-blue-500 hover:text-blue-700">
          刷新
        </button>
      </div>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => onSelect(item.id)}
            className={`w-full text-left p-2 rounded-md text-xs transition-colors ${
              selectedId === item.id
                ? "bg-blue-50 border border-blue-200"
                : "hover:bg-gray-50 border border-transparent"
            }`}
          >
            <div className="truncate font-medium text-gray-700">{item.video_title || item.bv}</div>
            <div className="flex items-center gap-2 mt-1 text-gray-400">
              <span>{item.bv}</span>
              <span>{item.total_comments} 条评论</span>
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] ${
                  item.status === "done" ? "bg-green-100 text-green-600" : "bg-yellow-100 text-yellow-600"
                }`}
              >
                {item.status === "done" ? "完成" : item.status}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
