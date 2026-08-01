/** Analysis status */
export type AnalysisStatus = "pending" | "fetching" | "analyzing" | "done" | "error";

/** Analysis mode */
export type AnalysisMode = "nlp" | "llm";
export type LLMProvider = "bailian" | "deepseek" | "custom";
export type LLMTask = "sentiment" | "summary";

/** Sentiment label (traditional 3-class) */
export type SentimentLabel = "positive" | "negative" | "neutral";

/** Comment data */
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
  sentiment_llm_label: string;
  post_time: string | null;
}

/** LLM 8-category sentiment counts */
export interface SentimentLLM {
  joy: number; anger: number; sadness: number; surprise: number;
  fear: number; disgust: number; anticipation: number; trust: number;
}

/** Region distribution item */
export interface RegionItem {
  region: string;
  count: number;
  percentage: number;
}

/** Heat timeline point */
export interface HeatPoint {
  time: string;
  count: number;
}

/** Keyword item */
export interface KeywordItem {
  word: string;
  count: number;
}

/** Complete analysis result */
export interface AnalysisResult {
  analysis_id: number;
  bv: string;
  video_title: string;
  video_cover: string;
  video_play: number;
  total_comments: number;
  created_at: string | null;
  mode: AnalysisMode;
  sentiment: { positive: number; negative: number; neutral: number };
  sentiment_llm?: SentimentLLM;
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

/** History analysis item */
export interface HistoryItem {
  id: number;
  bv: string;
  video_title: string;
  video_cover: string;
  total_comments: number;
  status: AnalysisStatus;
  created_at: string | null;
}

/** Analysis progress */
export interface StatusResponse {
  analysis_id: number;
  status: AnalysisStatus;
  total_comments: number;
  error_msg: string | null;
}

/** Video info response */
export interface VideoInfoResponse {
  bv: string; avid: number; title: string; cover: string; play: number; comment_count: number;
}

/** Settings response */
export interface SettingsResponse {
  has_api_key: boolean;
  api_key_preview: string;
  analysis_mode: AnalysisMode;
  llm: {
    sentiment: LLMTaskSettings;
    summary: LLMTaskSettings;
  };
}

export interface LLMTaskSettings {
  provider: LLMProvider;
  base_url: string;
  model: string;
  fallback_model: string;
  has_api_key: boolean;
  api_key_preview: string;
}

export interface LLMTaskUpdate {
  provider: LLMProvider;
  base_url: string;
  model: string;
  fallback_model?: string;
  api_key?: string;
  clear_api_key?: boolean;
}

/** Filter state */
export interface FilterState {
  gender: "all" | "male" | "female";
  dateFrom: string;
  dateTo: string;
  region: string;
  sentiment: "all" | SentimentLabel | keyof SentimentLLM;
}

export interface AISummary {
  id: number;
  analysis_id: number;
  filters: FilterState;
  filter_hash: string;
  summary_text: string;
  provider: LLMProvider;
  model: string;
  matched_count: number;
  sampled_count: number;
  created_at: string | null;
  updated_at: string | null;
  stale: boolean;
}
