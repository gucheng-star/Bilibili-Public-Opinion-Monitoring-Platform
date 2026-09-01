import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { getGroupResults, getResults } from '../services/api';
import type { AnalysisMode, AnalysisResult, CommentData, DuplicateStatistics, FilterState, GroupAnalysisResult } from '../types';
import { EMPTY_FILTERS, applyCommentFilters, applyDuplicateMode, buildDuplicateGroups, listRegions } from '../utils/commentFilters';
import {
  buildDetailSearch, filtersEqual, filtersSearchString, hasActiveFilters,
  parseDetailState, searchParamsToFilters, type DetailSort,
} from '../utils/commentQuery';
import { COMMENT_PAGE_SIZE, buildCommentTree, commentKey } from '../utils/commentTree';
import CommentTable from './CommentTable';
import FilterBar from './FilterBar';
import './CommentDetail.css';

interface ShellProps {
  title: string;
  scopeLabel: string;
  mode: AnalysisMode;
  totalComments: number;
  comments: CommentData[];
  filters: FilterState;
  onFiltersChange: (filters: FilterState) => void;
  duplicateStatistics: DuplicateStatistics;
  showSource?: boolean;
  sources?: Array<{ analysis_id: number; video_title: string; bv: string }>;
}

function CommentDetailShell({
  title, scopeLabel, mode, totalComments, comments, filters, onFiltersChange,
  duplicateStatistics, showSource = false, sources,
}: ShellProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchDraft, setSearchDraft] = useState('');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<DetailSort>('time');
  const [page, setPage] = useState(1);
  const [hydrated, setHydrated] = useState(false);

  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const onFiltersChangeRef = useRef(onFiltersChange);
  onFiltersChangeRef.current = onFiltersChange;
  const locationRef = useRef(location);
  locationRef.current = location;
  const qRef = useRef(q);
  qRef.current = q;

  // Hydrate filters / search / sort / page from the URL once on mount, so
  // refreshed or shared links restore the exact detail view.
  useEffect(() => {
    const params = new URLSearchParams(locationRef.current.search);
    const parsed = searchParamsToFilters(params, filtersRef.current);
    if (!filtersEqual(parsed, filtersRef.current)) onFiltersChangeRef.current(parsed);
    const detail = parseDetailState(params);
    setSearchDraft(detail.q);
    setQ(detail.q);
    setSort(detail.sort);
    setPage(detail.page);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const search = buildDetailSearch(filtersRef.current, { q, sort, page });
    if (search !== locationRef.current.search) {
      navigate({ pathname: locationRef.current.pathname, search }, { replace: true });
    }
  }, [hydrated, filters, q, sort, page, navigate]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = searchDraft.trim();
      if (next === qRef.current) return;
      setQ(next);
      setPage(1);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [searchDraft]);

  const filtered = useMemo(() => applyCommentFilters(comments, filters, mode), [comments, filters, mode]);
  const duplicateRetainedCount = useMemo(() => applyDuplicateMode(comments, filters.duplicateMode).length, [comments, filters.duplicateMode]);
  const searched = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return filtered;
    return filtered.filter(comment => comment.content.toLowerCase().includes(needle) || comment.username.toLowerCase().includes(needle));
  }, [filtered, q]);
  const allCommentRpids = useMemo(() => new Set(comments.map(comment => commentKey(comment))), [comments]);
  const treeRoots = useMemo(() => buildCommentTree(searched, allCommentRpids), [searched, allCommentRpids]);
  const rootCount = treeRoots.length;
  const replyCount = searched.length - rootCount;
  const availableRegions = useMemo(() => listRegions(comments), [comments]);
  const duplicateGroups = useMemo(() => buildDuplicateGroups(comments, showSource), [comments, showSource]);
  const pages = Math.max(1, Math.ceil(rootCount / COMMENT_PAGE_SIZE));
  const safePage = Math.min(page, pages);

  const applyFilters = (next: FilterState) => { onFiltersChange(next); setPage(1); };
  const changeSort = (next: DetailSort) => { setSort(next); setPage(1); };
  const clearAll = () => {
    setSearchDraft('');
    setQ('');
    setPage(1);
    onFiltersChangeRef.current(EMPTY_FILTERS);
  };

  return (
    <main className="app-main comment-detail max-w-7xl mx-auto px-4 py-6">
      <div className="comment-detail__topbar">
        <Link className="comment-detail__back" to={{ pathname: '/', search: filtersSearchString(filters) }}>← 返回概览</Link>
      </div>
      <header className="comment-detail__header">
        <h1 className="comment-detail__title">评论明细</h1>
        <p className="comment-detail__meta">
          {scopeLabel} · {title} · {mode === 'llm' ? '大模型十分类' : 'NLP三分类'} · 共 {totalComments.toLocaleString()} 条评论
        </p>
      </header>
      <FilterBar
        filters={filters}
        onApply={applyFilters}
        availableRegions={availableRegions}
        mode={mode}
        duplicateStatistics={duplicateStatistics}
        duplicateGroups={duplicateGroups}
        originalCount={comments.length}
        duplicateRetainedCount={duplicateRetainedCount}
        sources={sources}
      />
      <div className="comment-detail__toolbar">
        <label className="comment-detail__search">
          <svg className="comment-detail__search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={searchDraft}
            onChange={event => setSearchDraft(event.target.value)}
            placeholder="搜索评论关键词或用户名"
            aria-label="搜索评论关键词或用户名"
          />
          {searchDraft && (
            <button type="button" className="comment-detail__clear" onClick={() => setSearchDraft('')} aria-label="清空搜索">清空</button>
          )}
        </label>
        <p className="comment-detail__stats" role="status">
          命中 {searched.length.toLocaleString()} 条 · {rootCount.toLocaleString()} 个根评论 · {replyCount.toLocaleString()} 条回复
        </p>
      </div>
      {searched.length === 0 ? (
        <div className="app-state comment-detail__empty flex flex-col items-center justify-center py-16 text-muted">
          <p className="text-sm mb-3">{q ? '没有匹配该搜索的评论' : '当前筛选没有命中评论'}</p>
          {(q || hasActiveFilters(filters)) && (
            <button type="button" className="btn btn-ghost" onClick={clearAll}>清空搜索与筛选</button>
          )}
        </div>
      ) : (
        <CommentTable
          comments={searched}
          mode={mode}
          allCommentRpids={allCommentRpids}
          showSource={showSource}
          sortBy={sort}
          onSortChange={changeSort}
          page={safePage}
          onPageChange={setPage}
        />
      )}
    </main>
  );
}

function DetailLoadingScreen() {
  return (
    <main className="app-main comment-detail max-w-7xl mx-auto px-4 py-6">
      <div className="app-state flex flex-col items-center justify-center py-20">
        <div className="pulse-dot app-state__pulse"></div>
        <p className="text-sm text-secondary mt-3">正在加载分析结果…</p>
      </div>
    </main>
  );
}

function DetailErrorScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="app-main comment-detail max-w-7xl mx-auto px-4 py-6">
      <div className="app-alert app-alert--error" role="alert">{message}</div>
      <div className="comment-detail__retry">
        <button type="button" className="btn btn-primary" onClick={onRetry}>重新加载</button>
        <Link className="btn btn-ghost" to="/">返回工作台</Link>
      </div>
    </main>
  );
}

interface AnalysisDetailProps {
  results: AnalysisResult | null;
  filters: FilterState;
  onFiltersChange: (filters: FilterState) => void;
  onLoadAnalysis: (data: AnalysisResult) => void;
}

export function AnalysisCommentDetailPage({ results, filters, onFiltersChange, onLoadAnalysis }: AnalysisDetailProps) {
  const { analysisId: rawId } = useParams();
  const analysisId = Number(rawId);
  const valid = Number.isInteger(analysisId) && analysisId > 0;
  const matches = valid && results !== null && results.analysis_id === analysisId;
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const onLoadAnalysisRef = useRef(onLoadAnalysis);
  onLoadAnalysisRef.current = onLoadAnalysis;

  useEffect(() => {
    if (!valid || matches) return;
    let cancelled = false;
    setErrorMessage(null);
    getResults(analysisId)
      .then(data => { if (!cancelled) onLoadAnalysisRef.current(data); })
      .catch((reason: unknown) => {
        if (!cancelled) setErrorMessage(reason instanceof Error ? reason.message : '读取分析结果失败');
      });
    return () => { cancelled = true; };
  }, [analysisId, valid, matches, reloadKey]);

  if (!valid) return <Navigate to="/" replace />;
  if (!matches || !results) {
    return errorMessage
      ? <DetailErrorScreen message={errorMessage} onRetry={() => setReloadKey(current => current + 1)} />
      : <DetailLoadingScreen />;
  }
  return (
    <CommentDetailShell
      title={results.video_title || results.bv}
      scopeLabel="单视频分析"
      mode={results.mode}
      totalComments={results.total_comments}
      comments={results.comments}
      filters={filters}
      onFiltersChange={onFiltersChange}
      duplicateStatistics={results.duplicate_statistics}
    />
  );
}

interface GroupDetailProps {
  groupFilters: Record<number, FilterState>;
  onGroupFiltersChange: (groupId: number, filters: FilterState) => void;
}

export function GroupCommentDetailPage({ groupFilters, onGroupFiltersChange }: GroupDetailProps) {
  const { groupId: rawId } = useParams();
  const groupId = Number(rawId);
  const valid = Number.isInteger(groupId) && groupId > 0;
  const [result, setResult] = useState<GroupAnalysisResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!valid) return;
    let cancelled = false;
    setResult(null);
    setErrorMessage(null);
    getGroupResults(groupId, 'nlp')
      .then(data => { if (!cancelled) setResult(data); })
      .catch((reason: unknown) => {
        if (!cancelled) setErrorMessage(reason instanceof Error ? reason.message : '读取舆情事件失败');
      });
    return () => { cancelled = true; };
  }, [groupId, valid, reloadKey]);

  if (!valid) return <Navigate to="/" replace />;
  if (!result) {
    return errorMessage
      ? <DetailErrorScreen message={errorMessage} onRetry={() => setReloadKey(current => current + 1)} />
      : <DetailLoadingScreen />;
  }
  const filters = groupFilters[groupId] ?? EMPTY_FILTERS;
  return (
    <CommentDetailShell
      title={result.group_name}
      scopeLabel="舆情事件"
      mode={result.mode}
      totalComments={result.total_comments}
      comments={result.comments}
      filters={filters}
      onFiltersChange={next => onGroupFiltersChange(groupId, next)}
      duplicateStatistics={result.duplicate_statistics}
      showSource
      sources={result.members}
    />
  );
}
