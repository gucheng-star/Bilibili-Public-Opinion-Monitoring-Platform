import type { AnalysisResult, HistoryItem, StatusResponse } from "../types";

const BASE = "/api";

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "请求失败");
  }
  return res.json();
}

/** 提交 BV 号开始分析 */
export function startAnalysis(bv: string): Promise<{ analysis_id: number; status: string }> {
  return req("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bv }),
  });
}

/** 查询分析状态 */
export function getStatus(analysisId: number): Promise<StatusResponse> {
  return req(`/status/${analysisId}`);
}

/** 获取完整分析结果 */
export function getResults(analysisId: number): Promise<AnalysisResult> {
  return req(`/results/${analysisId}`);
}

/** 获取词云 base64 */
export function getWordCloud(analysisId: number): Promise<{ base64: string }> {
  return req(`/wordcloud/${analysisId}`);
}

/** 获取历史分析列表 */
export function getHistory(limit = 20): Promise<HistoryItem[]> {
  return req(`/history?limit=${limit}`);
}
