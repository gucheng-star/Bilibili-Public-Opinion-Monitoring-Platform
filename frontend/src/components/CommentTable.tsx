import { useState, useMemo } from "react";
import type { CommentData, SentimentLabel } from "../types";

interface Props {
  comments: CommentData[];
}

const SENTIMENT_TAG: Record<SentimentLabel, { label: string; color: string }> = {
  positive: { label: "正面", color: "bg-green-100 text-green-700" },
  negative: { label: "负面", color: "bg-red-100 text-red-700" },
  neutral: { label: "中性", color: "bg-gray-100 text-gray-600" },
};

export default function CommentTable({ comments }: Props) {
  const [filterSentiment, setFilterSentiment] = useState<SentimentLabel | "all">("all");
  const [sortBy, setSortBy] = useState<"time" | "likes">("time");
  const [page, setPage] = useState(1);
  const pageSize = 30;

  const filtered = useMemo(() => {
    let list = [...comments];
    if (filterSentiment !== "all") {
      list = list.filter((c) => c.sentiment_label === filterSentiment);
    }
    list.sort((a, b) => {
      if (sortBy === "likes") return b.likes - a.likes;
      return new Date(b.post_time || 0).getTime() - new Date(a.post_time || 0).getTime();
    });
    return list;
  }, [comments, filterSentiment, sortBy]);

  const totalPages = Math.ceil(filtered.length / pageSize);
  const paged = filtered.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700">
          评论列表 ({filtered.length})
        </h3>
        <div className="flex items-center gap-2">
          <select
            value={filterSentiment}
            onChange={(e) => { setFilterSentiment(e.target.value as SentimentLabel | "all"); setPage(1); }}
            className="text-xs border border-gray-200 rounded px-2 py-1"
          >
            <option value="all">全部情感</option>
            <option value="positive">正面</option>
            <option value="neutral">中性</option>
            <option value="negative">负面</option>
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "time" | "likes")}
            className="text-xs border border-gray-200 rounded px-2 py-1"
          >
            <option value="time">按时间</option>
            <option value="likes">按点赞</option>
          </select>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
              <th className="pb-2 w-24">用户</th>
              <th className="pb-2 w-20">属地</th>
              <th className="pb-2">评论内容</th>
              <th className="pb-2 w-16 text-center">点赞</th>
              <th className="pb-2 w-16 text-center">情感</th>
              <th className="pb-2 w-36">时间</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((c) => {
              const tag = SENTIMENT_TAG[c.sentiment_label] || SENTIMENT_TAG.neutral;
              return (
                <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50/50">
                  <td className="py-2 pr-2 text-gray-700 truncate max-w-[100px]" title={c.username}>
                    {c.username}
                  </td>
                  <td className="py-2 pr-2 text-gray-400 text-xs">{c.ip_location || "-"}</td>
                  <td className="py-2 pr-2 text-gray-600 max-w-[300px] truncate" title={c.content}>
                    {c.content}
                  </td>
                  <td className="py-2 text-center text-gray-500">{c.likes}</td>
                  <td className="py-2 text-center">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${tag.color}`}>
                      {tag.label}
                    </span>
                  </td>
                  <td className="py-2 text-xs text-gray-400">
                    {c.post_time ? formatTime(c.post_time) : "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-3">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-2 py-1 text-xs border rounded disabled:opacity-30"
          >
            上一页
          </button>
          <span className="text-xs text-gray-500">{page} / {totalPages}</span>
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="px-2 py-1 text-xs border rounded disabled:opacity-30"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
