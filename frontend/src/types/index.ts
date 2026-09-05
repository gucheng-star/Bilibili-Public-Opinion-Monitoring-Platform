/** Analysis status */
export type AnalysisStatus = "pending" | "fetching" | "analyzing" | "done" | "error";

/** Analysis mode */
export type AnalysisMode = "nlp" | "llm";
export type LLMProvider = "bailian" | "deepseek" | "zhipu" | "custom";
export type LLMTask = "sentiment" | "summary";
export type InterpretationView = "public_opinion" | "pr_risk" | "creator" | "news_editor";
export type SummaryReportMode = "quick" | "standard";
export type SummaryThinkingStatus = "disabled" | "enabled" | "unsupported";

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
  sentiment_llm_schema_version: number;
  post_time: string | null;
  is_exact_duplicate: boolean;
  duplicate_group_size: number;
  duplicate_group_key: string | null;
  is_duplicate_canonical: boolean;
  /** Present only when the comment belongs to an aggregated event. */
  source_analysis_id?: number;
  source_bv?: string;
  source_video_title?: string;
}

export interface DuplicateStatistics {
  group_count: number;
  involved_comments: number;
  duplicate_excess: number;
  involved_ratio: number;
}

/** LLM ten-class sentiment distribution. */
export interface SentimentLLM {
  neutral: number; joy: number; support: number; anticipation: number; surprise: number;
  anger: number; sadness: number; concern: number; disgust: number; sarcasm: number;
}

export type V2Emotion = 'neutral' | 'joy' | 'trust' | 'anticipation' | 'surprise' | 'anger' | 'sadness' | 'fear' | 'disgust';
export type V2Style = 'plain' | 'sarcasm' | 'meme' | 'rhetorical' | 'hyperbole';
export type SentimentLLMV2 = Record<V2Emotion, number>;
export type StyleDistributionV2 = Record<V2Style, number>;

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
  sentiment_llm_schema_version?: number;
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

export interface AnalysisGroupMember {
  analysis_id: number;
  bv: string;
  video_title: string;
  video_cover?: string;
  total_comments: number;
  status?: AnalysisStatus;
  mode?: AnalysisMode;
  created_at?: string | null;
}

export interface AnalysisGroup {
  id: number;
  name: string;
  description?: string | null;
  member_count: number;
  total_comments?: number;
  created_at: string | null;
  updated_at?: string | null;
  members?: AnalysisGroupMember[];
  is_analyzable?: boolean;
}

export interface SourceDistributionItem {
  analysis_id: number;
  bv: string;
  video_title: string;
  total_comments: number;
  matched_comments?: number;
  percentage?: number;
  sentiment?: { positive: number; negative: number; neutral: number };
  sentiment_llm?: SentimentLLMV2;
  sentiment_llm_style?: StyleDistributionV2;
  llm_ready?: boolean;
  v2_total_comments?: number;
  v2_completed_comments?: number;
  v2_pending_comments?: number;
}

/** Result payload for an event. Comments remain the source of all client-side filtered views. */
export interface GroupAnalysisResult {
  scope: 'group';
  group_id: number;
  group_name: string;
  description?: string | null;
  mode: AnalysisMode;
  member_count: number;
  total_comments: number;
  time_range?: { earliest: string | null; latest: string | null };
  members: AnalysisGroupMember[];
  source_distribution: SourceDistributionItem[];
  llm_readiness?: {
    ready: boolean;
    missing_members: Array<AnalysisGroupMember & { reason?: string; v2_total_comments?: number; v2_completed_comments?: number; v2_pending_comments?: number }>;
    source_coverage?: Array<AnalysisGroupMember & { v2_total_comments: number; v2_completed_comments: number; v2_pending_comments: number; v2_coverage: number; reason?: string }>;
  };
  sentiment: { positive: number; negative: number; neutral: number };
  sentiment_llm?: SentimentLLMV2;
  emotion_distribution?: SentimentLLMV2;
  style_distribution?: StyleDistributionV2;
  gender: { male: number; female: number; unknown: number };
  region: RegionItem[];
  heat: AnalysisResult['heat'];
  keywords: KeywordItem[];
  duplicate_statistics: DuplicateStatistics;
  comments: CommentData[];
}

export interface GroupReanalysisStatus {
  group_id: number;
  status: 'pending' | 'analyzing' | 'done' | 'error';
  ready: boolean;
  total_comments: number;
  processed_comments: number;
  pending_comments: number;
  /** Present on the explicit start response; only these comments are sent to the LLM. */
  target_comments?: number;
  missing_members: Array<AnalysisGroupMember & { reason?: string }>;
  errors: Array<{ analysis_id: number; video_title: string; message: string }>;
  started_analysis_ids?: number[];
  already_ready_analysis_ids?: number[];
}

/** History analysis item */
export interface HistoryItem {
  id: number;
  bv: string;
  video_title: string;
  video_cover: string;
  total_comments: number;
  status: AnalysisStatus;
  mode?: AnalysisMode;
  affected_group_count?: number;
  created_at: string | null;
}

/** Analysis progress */
export interface StatusResponse {
  analysis_id: number;
  status: AnalysisStatus;
  total_comments: number;
  processed_comments: number;
  error_msg: string | null;
  error_summary?: string | null;
  v2_target_count?: number;
  v2_completed_count?: number;
  v2_pending_count?: number;
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
  sentiment: "all" | SentimentLabel | keyof SentimentLLM | V2Emotion;
  duplicateMode: DuplicateMode;
  /** `all` for the complete comment pool; used by event workspaces only. */
  sourceAnalysisId: string;
}

export interface AISummary {
  id: number;
  analysis_id: number;
  filters: FilterState;
  filter_hash: string;
  interpretation_view: InterpretationView;
  report_mode: SummaryReportMode;
  thinking_status: SummaryThinkingStatus;
  summary_text: string;
  provider: LLMProvider;
  model: string;
  matched_count: number;
  sampled_count: number;
  created_at: string | null;
  updated_at: string | null;
  stale: boolean;
}

/** Event brief responses intentionally retain the pre-role-report contract. */
export interface GroupAISummary extends Omit<AISummary, 'analysis_id' | 'interpretation_view' | 'report_mode' | 'thinking_status'> {
  group_id: number;
  member_signature?: string;
}
