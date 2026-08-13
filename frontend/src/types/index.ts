/** Analysis status */
export type AnalysisStatus = "pending" | "fetching" | "analyzing" | "done" | "error";

/** Analysis mode */
export type AnalysisMode = "nlp" | "llm";
export type LLMProvider = "bailian" | "deepseek" | "custom";
export type LLMTask = "sentiment" | "summary";

/** Sentiment label (traditional 3-class) */
export type SentimentLabel = "positive" | "negative" | "neutral";
export type DuplicateMode = "include" | "deduplicate" | "exclude_groups";

/** Comment data */
export interface CommentData {
  id: number;
  rpid: number;
  root_rpid: number | null;
  parent_rpid: number | null;
  username: string;
  gender: string;
  ip_location: string;
  content: string;
  likes: number;
  sentiment_label: SentimentLabel;
  sentiment_score: number;
  sentiment_llm_label: string;
  sentiment_llm_style: string;
  post_time: string | null;
  is_exact_duplicate: boolean;
  duplicate_group_size: number;
  duplicate_group_key: string | null;
  is_duplicate_canonical: boolean;
}

export interface DuplicateStatistics {
  group_count: number;
  involved_comments: number;
  duplicate_excess: number;
  involved_ratio: number;
}

/** LLM main-emotion distribution; expression style is stored per comment. */
export interface SentimentLLM {
  neutral: number; joy: number; support: number; anticipation: number; surprise: number;
  anger: number; sadness: number; concern: number; disgust: number;
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
  duplicate_statistics: DuplicateStatistics;
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
  processed_comments: number;
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
  duplicateMode: DuplicateMode;
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
