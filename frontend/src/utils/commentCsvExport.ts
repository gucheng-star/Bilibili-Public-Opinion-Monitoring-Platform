import type { CommentData } from '../types';

export type CommentCsvOptionalColumn =
  | 'llmSentiment'
  | 'llmStyle'
  | 'nlpSentiment'
  | 'context'
  | 'username'
  | 'ipLocation'
  | 'gender'
  | 'postTime'
  | 'likes';

export type CommentCsvOptions = Record<CommentCsvOptionalColumn, boolean>;

export const DEFAULT_COMMENT_CSV_OPTIONS: Readonly<CommentCsvOptions> = {
  llmSentiment: true,
  llmStyle: true,
  nlpSentiment: true,
  context: false,
  username: false,
  ipLocation: false,
  gender: false,
  postTime: false,
  likes: false,
};

export interface CommentCsvSource {
  analysisId?: number;
  bv: string;
  videoTitle: string;
}

export interface CommentCsvExportInput {
  /** Comments in the current filtered and searched export range. */
  comments: readonly CommentData[];
  /** Complete loaded pool, used only to find root and direct-parent context. */
  allComments: readonly CommentData[];
  /** Source video for a single-video analysis, when comments do not carry source fields. */
  defaultSource?: CommentCsvSource;
  /** Source videos for an event; comments resolve their own source by analysis id. */
  sources?: readonly CommentCsvSource[];
  options?: Partial<CommentCsvOptions>;
  exportedAt?: Date;
}

export interface CommentCsvData {
  headers: string[];
  rows: string[][];
  csv: string;
}

export interface PreparedCommentCsv {
  rows: readonly PreparedCommentCsvRow[];
}

interface PreparedCommentCsvRow {
  sampleId: string;
  bv: string;
  videoTitle: string;
  postTime: string;
  username: string;
  gender: string;
  ipLocation: string;
  rootContent: string;
  parentContent: string;
  content: string;
  llmSentiment: string;
  llmStyle: string;
  nlpSentiment: string;
  likes: string;
}

interface CsvColumn {
  header: string;
  value: (row: PreparedCommentCsvRow) => string;
}

interface CommentContext {
  rootContent: string;
  parentContent: string;
  source: CommentCsvSource;
}

const FORMULA_PREFIX = /^[=+\-@]/;

const LLM_EMOTION_LABELS: Readonly<Record<string, string>> = {
  neutral: '中性', joy: '喜悦', trust: '信任', support: '支持',
  anticipation: '期待', surprise: '惊讶', anger: '愤怒', sadness: '悲伤',
  fear: '恐惧', concern: '担忧', disgust: '厌恶', sarcasm: '反讽',
};

const LLM_STYLE_LABELS: Readonly<Record<string, string>> = {
  plain: '平实', sarcasm: '反讽', meme: '玩梗', rhetorical: '反问', hyperbole: '夸张',
};

const NLP_SENTIMENT_LABELS: Readonly<Record<string, string>> = {
  positive: '正面', negative: '负面', neutral: '中性',
};

function commentKey(comment: CommentData, rpid: number | null): string {
  return `${comment.source_analysis_id ?? 'single'}:${rpid ?? ''}`;
}

function displayText(value: string | number | null | undefined): string {
  const text = value == null ? '' : String(value);
  return FORMULA_PREFIX.test(text) ? `'${text}` : text;
}

function displayLabel(value: string, labels: Readonly<Record<string, string>>): string {
  return value ? (labels[value] ?? value) : '';
}

function resolveSource(comment: CommentData, input: CommentCsvExportInput): CommentCsvSource {
  const fromEvent = input.sources?.find(source => source.analysisId === comment.source_analysis_id);
  const fallback = fromEvent ?? input.defaultSource ?? { bv: '', videoTitle: '' };
  return {
    bv: comment.source_bv ?? fallback.bv,
    videoTitle: comment.source_video_title ?? fallback.videoTitle,
  };
}

function formatTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

export function createCommentCsvSampleId(exportedAt: Date, sequence: number): string {
  return `EXP${formatTimestamp(exportedAt)}-${String(sequence).padStart(4, '0')}`;
}

export function escapeCsvCell(value: string | number | null | undefined): string {
  const text = displayText(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function serializeCsv(headers: readonly string[], rows: readonly (readonly string[])[]): string {
  return `\uFEFF${[headers, ...rows].map(row => row.map(escapeCsvCell).join(',')).join('\r\n')}\r\n`;
}

function resolveContext(comment: CommentData, input: CommentCsvExportInput, commentsByKey: ReadonlyMap<string, CommentData>): CommentContext {
  const ownKey = commentKey(comment, comment.rpid);
  const root = comment.root_rpid == null ? undefined : commentsByKey.get(commentKey(comment, comment.root_rpid));
  const parent = comment.parent_rpid == null ? undefined : commentsByKey.get(commentKey(comment, comment.parent_rpid));
  return {
    rootContent: root && commentKey(root, root.rpid) !== ownKey ? root.content : '',
    parentContent: parent && commentKey(parent, parent.rpid) !== ownKey ? parent.content : '',
    source: resolveSource(comment, input),
  };
}

function columnsFor(options: CommentCsvOptions): CsvColumn[] {
  const columns: CsvColumn[] = [
    { header: '样本ID', value: row => row.sampleId },
    { header: '视频BV号', value: row => row.bv },
    { header: '视频标题', value: row => row.videoTitle },
  ];

  if (options.postTime) columns.push({ header: '发布时间', value: row => row.postTime });
  if (options.username) columns.push({ header: '用户名', value: row => row.username });
  if (options.gender) columns.push({ header: '性别', value: row => row.gender });
  if (options.ipLocation) columns.push({ header: 'IP 属地', value: row => row.ipLocation });
  if (options.context) {
    columns.push({ header: '根评论内容', value: row => row.rootContent });
    columns.push({ header: '父评论内容', value: row => row.parentContent });
  }
  columns.push({ header: '评论内容', value: row => row.content });

  if (options.llmSentiment) columns.push({ header: '大模型主情感', value: row => row.llmSentiment });
  if (options.llmStyle) columns.push({ header: '大模型表达风格', value: row => row.llmStyle });
  if (options.nlpSentiment) columns.push({ header: '本地 NLP 情感', value: row => row.nlpSentiment });
  if (options.likes) columns.push({ header: '点赞数', value: row => row.likes });
  return columns;
}

/** Prepares fields independent of the user's column selection for reuse in the export dialog. */
export function prepareCommentCsv(input: Omit<CommentCsvExportInput, 'options'>): PreparedCommentCsv {
  const exportedAt = input.exportedAt ?? new Date();
  const commentsByKey = new Map(input.allComments.map(comment => [commentKey(comment, comment.rpid), comment]));
  return {
    rows: input.comments.map((comment, index) => {
      const context = resolveContext(comment, input, commentsByKey);
      return {
        sampleId: createCommentCsvSampleId(exportedAt, index + 1),
        bv: context.source.bv,
        videoTitle: context.source.videoTitle,
        postTime: comment.post_time ?? '',
        username: comment.username,
        gender: comment.gender,
        ipLocation: comment.ip_location,
        rootContent: context.rootContent,
        parentContent: context.parentContent,
        content: comment.content,
        llmSentiment: displayLabel(comment.sentiment_llm_label, LLM_EMOTION_LABELS),
        llmStyle: displayLabel(comment.sentiment_llm_style, LLM_STYLE_LABELS),
        nlpSentiment: displayLabel(comment.sentiment_label, NLP_SENTIMENT_LABELS),
        likes: String(comment.likes),
      };
    }),
  };
}

/** Builds a local-only RFC 4180-compatible CSV payload from cached comment fields. */
export function buildCommentCsvFromPrepared(prepared: PreparedCommentCsv, options?: Partial<CommentCsvOptions>): CommentCsvData {
  const resolvedOptions: CommentCsvOptions = { ...DEFAULT_COMMENT_CSV_OPTIONS, ...options };
  const columns = columnsFor(resolvedOptions);
  const rows = prepared.rows.map(row => columns.map(column => column.value(row)));
  const headers = columns.map(column => column.header);
  return { headers, rows, csv: serializeCsv(headers, rows) };
}

/** Builds a local-only RFC 4180-compatible CSV payload. It performs no I/O or download. */
export function buildCommentCsv(input: CommentCsvExportInput): CommentCsvData {
  const { options, ...preparationInput } = input;
  return buildCommentCsvFromPrepared(prepareCommentCsv(preparationInput), options);
}
