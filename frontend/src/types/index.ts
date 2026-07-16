/** 分析状态 */
export type AnalysisStatus = "pending" | "fetching" | "analyzing" | "done" | "error";

/** 情感标签 */
export type SentimentLabel = "positive" | "negative" | "neutral";

/** 评论数据 */
export interface CommentData {
  id: number;
  rpid: number;
  username: string;
  gender: string;
  ip_location: string;
  content: string;
  likes: number;
  sentiment_label: SentimentLabel;
  sentiment_score: number;
  post_time: string | null;
}

/** 地域分布项 */
export interface RegionItem {
  region: string;
  count: number;
  percentage: number;
}

/** 热度时间点 */
export interface HeatPoint {
  time: string;
  count: number;
}

/** 关键词项 */
export interface KeywordItem {
  word: string;
  count: number;
}

/** 完整分析结果 */
export interface AnalysisResult {
  analysis_id: number;
  bv: string;
  video_title: string;
  video_cover: string;
  video_play: number;
  total_comments: number;
  created_at: string | null;
  sentiment: { positive: number; negative: number; neutral: number };
  gender: { male: number; female: number; unknown: number };
  region: RegionItem[];
  heat: {
    timeline: HeatPoint[];
    peak_hour: string | null;
    peak_count: number;
    hourly_distribution: { hour: number; count: number }[];
  };
  keywords: KeywordItem[];
  comments: CommentData[];
}

/** 历史分析项 */
export interface HistoryItem {
  id: number;
  bv: string;
  video_title: string;
  video_cover: string;
  total_comments: number;
  status: AnalysisStatus;
  created_at: string | null;
}

/** 分析进度 */
export interface StatusResponse {
  analysis_id: number;
  status: AnalysisStatus;
  total_comments: number;
  error_msg: string | null;
}
