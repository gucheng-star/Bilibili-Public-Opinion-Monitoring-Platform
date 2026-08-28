import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import SearchBar, { type SearchDraft } from './components/SearchBar';
import VideoInfo from './components/VideoInfo';
import SentimentChart from './components/SentimentChart';
import GenderChart from './components/GenderChart';
import RegionMap from './components/RegionMap';
import WordCloudCard from './components/WordCloudCard';
import HeatTimeline from './components/HeatTimeline';
import CommentTable from './components/CommentTable';
import HistoryPanel from './components/HistoryPanel';
import ThemeToggle from './components/ThemeToggle';
import LoginPage from './components/LoginPage';
import FilterBar from './components/FilterBar';
import AISummaryCard from './components/AISummaryCard';
import SettingsEntry from './components/SettingsEntry';
import AnalysisProgress from './components/AnalysisProgress';
import EventWorkspace from './components/EventWorkspace';
import AppErrorBoundary from './components/AppErrorBoundary';
import SettingsPage from './pages/SettingsPage';
import { getAuthStatus, getFilteredKeywords, getResults, getRuntimeActivity, getSettings, getStatus, logout, prepareRuntimeExit, reanalyze, startAnalysis } from './services/api';
import { checkForUpdates, downloadUpdate, installDownloadedUpdate, isDesktopRuntime, onCloseRequested, respondToCloseRequest } from './services/desktop';
import { activeFilterFields, recordBreadcrumb, setDiagnosticState, type DiagnosticState } from './services/devDiagnostics';
import { LatestRequestGuard, runConfirmedWorkflowTransition } from './services/latestRequestGuard';
import type { AnalysisResult, FilterState, AnalysisMode, KeywordItem, SentimentLLM } from './types';
import './AppShell.css';

const PROVINCES = new Set(['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','海南','四川','贵州','云南','陕西','甘肃','青海','台湾','内蒙古','广西','西藏','宁夏','新疆','香港','澳门']);
const LLM_EMOTIONS: (keyof SentimentLLM)[] = ['neutral', 'joy', 'support', 'anticipation', 'surprise', 'anger', 'sadness', 'concern', 'disgust', 'sarcasm'];
const EMPTY_SEARCH_DRAFT: SearchDraft = { rawInput: '', bv: '', videoInfo: null };
const EMPTY_FILTERS: FilterState = { gender: 'all', dateFrom: '', dateTo: '', region: '', sentiment: 'all', duplicateMode: 'include', sourceAnalysisId: 'all' };

function getLlmProgressText(processed: number, total: number): string {
  return `正在分析评论 ${Math.min(processed, total)} / ${total}`;
}

function normalizeProvince(raw: string): string {
  const s = (raw || '').replace(/^IP属地[：:]/, '');
  if (!s || s === '未知' || s === '其它' || s === '中国') return '';
  if (PROVINCES.has(s)) return s;
  for (const p of PROVINCES) { if (s.startsWith(p)) return p; }
  if (s.startsWith('中国') && s.length > 2) { const sf = s.slice(2); if (PROVINCES.has(sf)) return sf; }
  return s;
}

function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const isWorkspacePage = location.pathname === '/';
  const [analysisId, setAnalysisId] = useState<number | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [groupFilters, setGroupFilters] = useState<Record<number, FilterState>>({});
  const [groupRevision, setGroupRevision] = useState(0);
  const [results, setResults] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusText, setStatusText] = useState('');
  const [showHistory, setShowHistory] = useState(true);
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressMax, setProgressMax] = useState(100);
  const [toast, setToast] = useState<string | null>(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [searchDraft, setSearchDraft] = useState<SearchDraft>(() => ({ ...EMPTY_SEARCH_DRAFT }));
  const cancelRef = useRef(false);
  const workflowGuardRef = useRef(new LatestRequestGuard());

  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>('nlp');
  const [maxComments, setMaxComments] = useState(100);
  const [delay, setDelay] = useState(3.0);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [filteredKeywords, setFilteredKeywords] = useState<KeywordItem[]>([]);
  const [keywordStatus, setKeywordStatus] = useState<'ready' | 'loading' | 'error'>('ready');
  const keywordRequestRef = useRef(0);
  const pollStatusRef = useRef<string | null>(null);
  const [hasApiKey, setHasApiKey] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reanalyzeModal, setReanalyzeModal] = useState(false);
  const [updateInfo, setUpdateInfo] = useState<{ version?: string; notes?: string; notesUrl?: string } | null>(null);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [closeRequest, setCloseRequest] = useState<{ requestId?: string } | null>(null);
  const currentDiagnosticFilters = selectedGroupId === null ? filters : groupFilters[selectedGroupId] || EMPTY_FILTERS;
  const boundaryDiagnosticState: DiagnosticState = location.pathname === '/settings'
    ? { route: location.pathname, view_type: 'settings' }
    : selectedGroupId !== null
      ? {
          route: location.pathname,
          view_type: 'group',
          group_id: selectedGroupId,
          active_filter_fields: activeFilterFields(currentDiagnosticFilters),
        }
      : {
          route: location.pathname,
          view_type: 'single',
          analysis_id: analysisId,
          analysis_mode: analysisMode,
          loading,
          reanalyzing,
          keyword_status: keywordStatus,
          active_filter_fields: activeFilterFields(currentDiagnosticFilters),
        };

  useEffect(() => {
    recordBreadcrumb('route.changed', { path: location.pathname });
  }, [location.pathname]);
  useEffect(() => {
    if (analysisId !== null) recordBreadcrumb('analysis.selected', { analysis_id: analysisId });
  }, [analysisId]);
  useEffect(() => {
    if (selectedGroupId !== null) recordBreadcrumb('group.selected', { group_id: selectedGroupId });
  }, [selectedGroupId]);
  useEffect(() => {
    if (location.pathname === '/' && selectedGroupId === null) {
      recordBreadcrumb('analysis.mode_changed', { analysis_mode: analysisMode });
    }
  }, [analysisMode, location.pathname, selectedGroupId]);
  useEffect(() => {
    recordBreadcrumb('filter.changed', { active_filter_fields: activeFilterFields(currentDiagnosticFilters) });
  }, [currentDiagnosticFilters]);
  useEffect(() => {
    if (location.pathname !== '/settings' && selectedGroupId !== null) return;
    setDiagnosticState({
      route: location.pathname,
      view_type: location.pathname === '/settings' ? 'settings' : 'single',
      analysis_id: location.pathname === '/settings' ? null : analysisId,
      group_id: null,
      analysis_mode: location.pathname === '/settings' ? undefined : analysisMode,
      loading,
      reanalyzing,
      keyword_status: keywordStatus,
      active_filter_fields: activeFilterFields(currentDiagnosticFilters),
    });
  }, [analysisId, analysisMode, currentDiagnosticFilters, keywordStatus, loading, location.pathname, reanalyzing, selectedGroupId]);

  const recordPollStatus = useCallback((status: string) => {
    if (pollStatusRef.current === status) return;
    pollStatusRef.current = status;
    recordBreadcrumb('task.poll_status_changed', { poll_status: status });
  }, []);

  useEffect(() => { getAuthStatus().then(d=>setLoggedIn(d.logged_in)).catch(()=>setLoggedIn(false)); }, []);
  useEffect(() => { getSettings().then(s => { setHasApiKey(s.llm.sentiment.has_api_key); }).catch(() => {}); }, []);
  useEffect(() => {
    setFilters(current => current.sentiment === 'all' ? current : { ...current, sentiment: 'all' });
  }, [results?.mode]);

  const showToast = (msg: string) => { setToast(msg); setTimeout(()=>setToast(null), 4000); };

  const checkUpdate = useCallback(async (manual = false) => {
    if (!isDesktopRuntime()) return;
    try {
      const update = await checkForUpdates();
      if (update.enabled === false && update.message) throw new Error(update.message);
      if (update.available) setUpdateInfo(update);
      else if (manual) showToast('当前已是最新版本');
    } catch (e) {
      if (manual) showToast(e instanceof Error ? e.message : '检查更新失败');
    }
  }, []);

  const installUpdate = async () => {
    setUpdateBusy(true);
    try {
      await downloadUpdate();
      await installDownloadedUpdate();
    } catch (e) {
      setUpdateBusy(false);
      showToast(e instanceof Error ? e.message : '下载更新失败');
    }
  };

  useEffect(() => {
    if (!isDesktopRuntime()) return;
    const timer = window.setTimeout(() => { void checkUpdate(); }, 5000);
    return () => window.clearTimeout(timer);
  }, [checkUpdate]);

  useEffect(() => {
    if (!isDesktopRuntime()) return;
    return onCloseRequested(requestId => {
      void (async () => {
        try {
          const activity = await getRuntimeActivity();
          if (!loading && !activity.active) {
            await prepareRuntimeExit();
            await respondToCloseRequest('exit', requestId);
            return;
          }
        } catch {
          if (!loading) {
            await respondToCloseRequest('exit', requestId).catch(() => {});
            return;
          }
        }
        setCloseRequest({ requestId });
      })();
    });
  }, [loading]);

  const handleModeChange = (mode: AnalysisMode) => {
    if (mode === 'llm' && !hasApiKey) { showToast('请先在设置页面配置情绪分析模型的 API Key'); return; }
    // NLP → LLM：弹出确认弹窗
    if (mode === 'llm' && results && results.mode !== 'llm') { setReanalyzeModal(true); return; }
    setAnalysisMode(mode);
  };

  const handleReanalyzeConfirm = async () => {
    if (!analysisId) return;
    const request = workflowGuardRef.current.begin();
    const isCurrent = () => workflowGuardRef.current.isCurrent(request);
    const activeAnalysisId = analysisId;
    const totalComments = results?.total_comments || 100;
    pollStatusRef.current = null;
    setReanalyzeModal(false);
    setReanalyzing(true);
    setLoading(true); setError(null); cancelRef.current = false;
    setProgress(0); setProgressMax(totalComments);
    setStatusText(getLlmProgressText(0, totalComments));
    try {
      await reanalyze(activeAnalysisId);
      if (!isCurrent()) return;
      const poll = async () => {
        for (let i = 0; i < 300; i++) {
          if (!isCurrent()) return;
          if (cancelRef.current) { setReanalyzing(false); setLoading(false); setStatusText('已取消'); return; }
          await new Promise(r => setTimeout(r, 1500));
          if (!isCurrent()) return;
          try {
            const status = await getStatus(activeAnalysisId);
            if (!isCurrent()) return;
            recordPollStatus(status.status);
            const processed = status.processed_comments ?? 0;
            setProgress(processed);
            if (status.status === 'done') {
              if (status.error_msg) {
                setError(status.error_msg);
                setAnalysisMode(results?.mode || 'nlp');
                setReanalyzing(false);
                setLoading(false);
                showToast('大模型分析失败，已保留 NLP 结果');
                return;
              }
              setStatusText(''); const data = await getResults(activeAnalysisId);
              if (!isCurrent()) return;
              setResults(data); setAnalysisMode(data.mode); setReanalyzing(false); setLoading(false); setHistoryRefreshKey(k=>k+1); showToast('大模型分析完成');
              return;
            }
            if (status.status === 'error') { setError(status.error_msg || '分析失败'); setReanalyzing(false); setLoading(false); showToast('分析失败'); return; }
            if (status.status === 'analyzing') setStatusText(getLlmProgressText(processed, status.total_comments || totalComments));
          } catch {
            if (!isCurrent()) return;
            if (cancelRef.current) { setReanalyzing(false); setLoading(false); return; }
          }
        }
        if (!isCurrent()) return;
        setError('超时'); setReanalyzing(false); setLoading(false);
      };
      void poll();
    } catch (e: any) {
      if (!isCurrent()) return;
      setError(e.message || '重新分析失败'); setReanalyzing(false); setLoading(false);
    }
  };

  const handleAnalyze = useCallback(async (bv: string, _maxComments: number, _delay: number) => {
    const request = workflowGuardRef.current.begin();
    const isCurrent = () => workflowGuardRef.current.isCurrent(request);
    pollStatusRef.current = null;
    setReanalyzing(false);
    setLoading(true); setError(null); setResults(null); setSelectedGroupId(null); cancelRef.current = false;
    setAnalysisMode('nlp');
    setProgress(0); setProgressMax(_maxComments); setStatusText('正在获取视频信息...');
    try {
      const { analysis_id } = await startAnalysis(bv, _maxComments, _delay);
      if (!isCurrent()) return;
      setAnalysisId(analysis_id); setStatusText('正在抓取评论...');
      const poll = async () => {
        for (let i = 0; i < 300; i++) {
          if (!isCurrent()) return;
          if (cancelRef.current) { setLoading(false); setStatusText('已取消'); return; }
          await new Promise(r => setTimeout(r, 1500));
          if (!isCurrent()) return;
          try {
            const status = await getStatus(analysis_id);
            if (!isCurrent()) return;
            recordPollStatus(status.status);
            setProgress(status.total_comments);
            if (status.status === 'done') {
              setStatusText(''); const data = await getResults(analysis_id);
              if (!isCurrent()) return;
              setResults(data); setAnalysisMode(data.mode); setLoading(false); setHistoryRefreshKey(k=>k+1); showToast('分析完成');
              return;
            }
            if (status.status === 'error') { setError(status.error_msg || '分析失败'); setLoading(false); showToast('分析失败'); return; }
            if (status.status === 'fetching') setStatusText('抓取中 ('+status.total_comments+'/'+_maxComments+')');
            else if (status.status === 'analyzing') {
              setStatusText('分析中...');
            }
          } catch {
            if (!isCurrent()) return;
            if (cancelRef.current) { setLoading(false); return; }
          }
        }
        if (!isCurrent()) return;
        setError('超时'); setLoading(false);
      };
      void poll();
    } catch (e: any) {
      if (!isCurrent()) return;
      setError(e.message || '失败'); setLoading(false);
    }
  }, [recordPollStatus]);

  const handleViewHistory = useCallback(async (id: number) => {
    const request = workflowGuardRef.current.begin();
    const isCurrent = () => workflowGuardRef.current.isCurrent(request);
    cancelRef.current = false;
    if (id < 0) {
      setSelectedGroupId(null);
      setReanalyzing(false);
      setLoading(false);
      setStatusText('');
      return;
    }
    setReanalyzing(false);
    setSelectedGroupId(null);
    setLoading(true); setError(null); setStatusText('加载中...');
    try {
      const data = await getResults(id);
      if (!isCurrent()) return;
      setResults(data); setAnalysisId(id); setAnalysisMode(data.mode); setFilters({ gender:'all',dateFrom:'',dateTo:'',region:'',sentiment:'all',duplicateMode:'include',sourceAnalysisId:'all' });
    } catch (e:any) {
      if (!isCurrent()) return;
      setError(e.message);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, []);

  const handleLogout = async () => {
    try {
      const confirmation = logout().then(result => {
        if (result.ok === false) throw new Error('退出登录失败，请稍后重试。');
        return result;
      });
      await runConfirmedWorkflowTransition(workflowGuardRef.current, confirmation, () => {
        cancelRef.current = true;
        setLoggedIn(false);
        setReanalyzing(false);
        setLoading(false);
        setStatusText('');
        setError(null);
        setResults(null);
        setAnalysisId(null);
        setSelectedGroupId(null);
        setSearchDraft({ ...EMPTY_SEARCH_DRAFT });
        navigate('/', { replace: true });
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '退出登录失败，请检查本地服务后重试。';
      throw error instanceof Error ? error : new Error(message);
    }
  };
  const handleStop = () => {
    cancelRef.current = true;
    workflowGuardRef.current.invalidate();
    setReanalyzing(false);
    setLoading(false);
    setStatusText('已取消');
  };
  const handleSelectGroup = useCallback((id: number) => {
    workflowGuardRef.current.begin();
    cancelRef.current = false;
    setSelectedGroupId(id);
    setError(null);
    setReanalyzing(false);
    setLoading(false);
    setStatusText('');
  }, []);
  const handleApplyFilters = (f: FilterState) => { setFilters(f); };
  const resolveClose = async (action: 'exit' | 'tray' | 'cancel') => {
    if (action === 'exit') await prepareRuntimeExit().catch(() => {});
    await respondToCloseRequest(action, closeRequest?.requestId).catch(() => {});
    setCloseRequest(null);
  };

  const duplicateFilteredComments = useMemo(() => {
    if (!results) return [];
    if (filters.duplicateMode === 'deduplicate') {
      return results.comments.filter(comment => !comment.is_exact_duplicate || comment.is_duplicate_canonical);
    }
    if (filters.duplicateMode === 'exclude_groups') {
      return results.comments.filter(comment => !comment.is_exact_duplicate);
    }
    return results.comments;
  }, [results, filters.duplicateMode]);

  const filteredComments = useMemo(() => {
    let comments = [...duplicateFilteredComments];
    if (filters.gender === 'male') comments = comments.filter(c => c.gender === '男');
    if (filters.gender === 'female') comments = comments.filter(c => c.gender === '女');
    if (filters.dateFrom) comments = comments.filter(c => c.post_time && c.post_time.slice(0, 10) >= filters.dateFrom);
    if (filters.dateTo) comments = comments.filter(c => c.post_time && c.post_time.slice(0, 10) <= filters.dateTo);
    if (filters.region) { comments = comments.filter(c => normalizeProvince(c.ip_location) === filters.region); }
    if (filters.sentiment !== 'all') {
      comments = results?.mode === 'llm'
        ? comments.filter(c => c.sentiment_llm_label === filters.sentiment)
        : comments.filter(c => c.sentiment_label === filters.sentiment);
    }
    return comments;
  }, [results, filters, duplicateFilteredComments]);

  const duplicateGroups = useMemo(() => {
    if (!results) return [];
    const groups = new Map<string, typeof results.comments>();
    for (const comment of results.comments) {
      if (!comment.duplicate_group_key) continue;
      const members = groups.get(comment.duplicate_group_key) || [];
      members.push(comment);
      groups.set(comment.duplicate_group_key, members);
    }
    return Array.from(groups.entries()).map(([key, members]) => {
      let firstPostTime: string | null = null;
      let lastPostTime: string | null = null;
      for (const member of members) {
        const postTime = member.post_time;
        if (!postTime) continue;
        if (!firstPostTime || postTime < firstPostTime) firstPostTime = postTime;
        if (!lastPostTime || postTime > lastPostTime) lastPostTime = postTime;
      }
      return {
        key,
        content: members[0]?.content || '',
        count: members.length,
        firstPostTime,
        lastPostTime,
      };
    }).sort((left, right) => right.count - left.count || left.key.localeCompare(right.key));
  }, [results]);

  const allCommentRpids = useMemo(
    () => new Set((results?.comments || []).map(comment => String(comment.rpid))),
    [results],
  );

  const filteredSentiment = useMemo(() => ({
    positive: filteredComments.filter(c => c.sentiment_label === 'positive').length,
    negative: filteredComments.filter(c => c.sentiment_label === 'negative').length,
    neutral: filteredComments.filter(c => c.sentiment_label === 'neutral').length,
  }), [filteredComments]);

  const filteredLlmSentiment = useMemo<SentimentLLM>(() => {
    const counts: SentimentLLM = { neutral:0, joy:0, support:0, anticipation:0, surprise:0, anger:0, sadness:0, concern:0, disgust:0, sarcasm:0 };
    filteredComments.forEach(comment => {
      const label = comment.sentiment_llm_label as keyof SentimentLLM;
      if (LLM_EMOTIONS.includes(label)) counts[label]++;
    });
    return counts;
  }, [filteredComments]);

  const filteredGender = useMemo(() => ({
    male: filteredComments.filter(c => c.gender === '男').length,
    female: filteredComments.filter(c => c.gender === '女').length,
    unknown: filteredComments.filter(c => c.gender !== '男' && c.gender !== '女').length,
  }), [filteredComments]);

  const filteredRegion = useMemo(() => {
    const map = new Map<string, number>();
    filteredComments.forEach(c => { const p = normalizeProvince(c.ip_location); if (p) map.set(p, (map.get(p)||0)+1); });
    const total = filteredComments.length;
    return Array.from(map.entries()).map(([region,count]) => ({ region, count, percentage: total ? count/total*100 : 0 }));
  }, [filteredComments]);

  const filteredHeat = useMemo(() => {
    const counts = new Map<string, number>();
    filteredComments.forEach(c => { if (c.post_time) { const h = c.post_time.slice(0,13)+':00:00'; counts.set(h,(counts.get(h)||0)+1); } });
    const timeline = Array.from(counts.entries()).map(([t,c])=>({time:t,count:c})).sort((a,b)=>a.time.localeCompare(b.time));
    const hd = new Array(24).fill(0);
    filteredComments.forEach(c => { if (c.post_time) hd[new Date(c.post_time).getHours()]++; });
    const pk = filteredComments.length ? Math.max(...hd) : 0;
    const pi = pk > 0 ? hd.indexOf(pk) : -1;
    return { timeline, peak_hour: pi>=0?String(pi).padStart(2,'0')+':00':null, peak_count: pk, hourly_distribution: hd.map((c,h)=>({hour:h,count:c})) };
  }, [filteredComments]);

  useEffect(() => {
    const requestId = ++keywordRequestRef.current;
    if (!results || !analysisId) {
      setFilteredKeywords([]);
      setKeywordStatus('ready');
      return;
    }
    const isFullCollection = filters.gender === 'all'
      && !filters.dateFrom
      && !filters.dateTo
      && !filters.region
      && filters.sentiment === 'all'
      && filters.duplicateMode === 'include';
    if (isFullCollection) {
      setFilteredKeywords(results.keywords);
      setKeywordStatus('ready');
      return;
    }
    setFilteredKeywords([]);
    setKeywordStatus('loading');
    const expectedMatchedCount = filteredComments.length;
    getFilteredKeywords(analysisId, filters)
      .then(response => {
        if (keywordRequestRef.current !== requestId) return;
        if (response.matched_count !== expectedMatchedCount) {
          throw new Error('筛选集合计数不一致');
        }
        setFilteredKeywords(response.keywords);
        setKeywordStatus('ready');
      })
      .catch(() => {
        if (keywordRequestRef.current !== requestId) return;
        setFilteredKeywords([]);
        setKeywordStatus('error');
      });
  }, [analysisId, filteredComments.length, filters, results]);

  const availableRegions = useMemo(() => {
    if (!results) return [];
    const s = new Set<string>();
    results.comments.forEach(c => { const p = normalizeProvince(c.ip_location); if (p) s.add(p); });
    return Array.from(s).sort();
  }, [results]);

  if (loggedIn === null) return <div className="app-shell app-shell--booting" aria-label="正在加载应用"><div className="pulse-dot"></div></div>;
  if (!loggedIn) return <LoginPage onLogin={()=>setLoggedIn(true)}/>;

  return (
    <div className="app-shell min-h-screen">
      <header className="app-header sticky top-0 z-10">
        <div className="app-header__inner max-w-7xl mx-auto px-4 py-4" key={`header-${location.pathname}`}>
          <div className="app-header__bar route-reveal-element flex items-center justify-between mb-3">
            <div className="app-brand flex items-center gap-2">
              <img className="app-brand__icon" src="/signal-observatory-icon.png" alt="" aria-hidden="true" />
              <span className="app-brand__mark">B站</span>
              <span className="app-brand__name">舆论监测平台</span>
            </div>
            <div className="app-header__actions flex items-center gap-3">
              {isWorkspacePage && <SettingsEntry />}
              <ThemeToggle/>
            </div>
          </div>
          {isWorkspacePage && <section className="command-deck route-reveal-element" aria-label="视频分析指令舱">
            <div className="command-deck__label"><span aria-hidden="true"></span>VIDEO SIGNAL COMMAND</div>
            <SearchBar
              onAnalyze={handleAnalyze}
              loading={loading}
              maxComments={maxComments}
              delay={delay}
              draft={searchDraft}
              onDraftChange={setSearchDraft}
            />
          </section>}
        </div>
      </header>
      <div className="header-accent-line" />
      {toast && <div className="app-toast" role="status">{toast}</div>}
      <div className="app-route-stage" key={location.pathname}>
      <AppErrorBoundary diagnosticState={boundaryDiagnosticState}>
      <Routes location={location}>
        <Route path="/settings" element={(
          <SettingsPage
            maxComments={maxComments}
            onMaxCommentsChange={setMaxComments}
            delay={delay}
            onDelayChange={setDelay}
            onSettingsChanged={settings => setHasApiKey(settings.llm.sentiment.has_api_key)}
            desktopMode={isDesktopRuntime()}
            onCheckUpdate={() => { void checkUpdate(true); }}
            onLogout={handleLogout}
          />
        )} />
        <Route path="/" element={(
      <main className="app-main app-route-page max-w-7xl mx-auto px-4 py-6">
        {error && <div className="app-alert app-alert--error" role="alert">{error}</div>}
        <section className="history-rail mb-4" aria-label="历史记录">
          <button onClick={()=>setShowHistory(!showHistory)} className="history-rail__toggle flex items-center gap-1 text-xs text-muted mb-2" aria-expanded={showHistory}>
            <span>{showHistory?'收起':'展开'}历史记录</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{transform:showHistory?'rotate(180deg)':'rotate(0deg)',transition:'transform .2s'}}><path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6"/></svg>
          </button>
          {showHistory && <HistoryPanel onSelect={handleViewHistory} onSelectGroup={handleSelectGroup} selectedId={analysisId} selectedGroupId={selectedGroupId} refreshKey={historyRefreshKey} onGroupChanged={() => setGroupRevision(current => current + 1)}/>}
        </section>
        {selectedGroupId ? <EventWorkspace key={`${selectedGroupId}-${groupRevision}`} groupId={selectedGroupId} initialFilters={groupFilters[selectedGroupId] || EMPTY_FILTERS} onFiltersChange={next => setGroupFilters(current => ({ ...current, [selectedGroupId]: next }))} /> : <>
        {!loading && results && (<div className="app-alert app-alert--status">模式: {results.mode === 'llm' ? '大模型十分类' : 'NLP三分类'} · 共 {results.total_comments} 条评论</div>)}

        {loading && !results && (
          <div className="app-state flex items-center justify-center py-20">
            <AnalysisProgress
              current={progress}
              total={progressMax}
              statusText={statusText}
              ariaLabel="评论抓取进度"
              title="评论抓取进度"
              detail="正在从本机连接的 B 站账号抓取公开评论"
              variant="workspace"
              action={<button onClick={handleStop} className="btn btn-ghost">取消分析</button>}
            />
          </div>
        )}

        {loading && results && !reanalyzing && (
          <div className="app-state flex flex-col items-center justify-center py-20">
            <div className="pulse-dot app-state__pulse"></div>
            <p className="text-sm text-secondary mb-3">{statusText}</p>
            <button onClick={handleStop} className="btn btn-ghost app-state__action">取消分析</button>
          </div>
        )}

        {!loading && !results && (
          <div className="app-state flex flex-col items-center justify-center py-20 text-muted">
            <svg className="app-state__empty-icon w-12 h-12 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
            <p className="text-sm">输入 BV 号开始分析</p>
          </div>
        )}
        {results && <>
          <VideoInfo title={results.video_title} play={results.video_play} totalComments={results.total_comments}/>
          <FilterBar
            filters={filters}
            onApply={handleApplyFilters}
            availableRegions={availableRegions}
            mode={results.mode}
            duplicateStatistics={results.duplicate_statistics}
            duplicateGroups={duplicateGroups}
            originalCount={results.comments.length}
            duplicateRetainedCount={duplicateFilteredComments.length}
          />
          {analysisId && <div className="card-enter mt-4">
            <AISummaryCard scope={{ kind: 'analysis', id: analysisId }} filters={filters} matchedCount={filteredComments.length} mode={results.mode}/>
          </div>}
          <div className="mt-4 distribution-chart-stack">
            <div className="card-enter">
              <SentimentChart
                positive={filteredSentiment.positive}
                negative={filteredSentiment.negative}
                neutral={filteredSentiment.neutral}
                mode={analysisMode}
                llm={results.mode === 'llm' ? filteredLlmSentiment : null}
                onModeChange={handleModeChange}
                reanalysis={reanalyzing ? { state: 'running', current: progress, total: progressMax, statusText } : undefined}
              />
            </div>
            <div className="card-enter"><GenderChart male={filteredGender.male} female={filteredGender.female} unknown={filteredGender.unknown}/></div>
          </div>
          <div className="card-enter mt-4"><RegionMap data={filteredRegion}/></div>
          <div className="card-enter mt-4">
            <WordCloudCard keywords={filteredKeywords} status={keywordStatus} scopeKey={`analysis:${analysisId ?? ''}`}/>
          </div>
          <div className="card-enter mt-4">
            <HeatTimeline timeline={filteredHeat.timeline} hourlyDistribution={filteredHeat.hourly_distribution} peakHour={filteredHeat.peak_hour} peakCount={filteredHeat.peak_count}/>
          </div>
          <div className="card-enter mt-4"><CommentTable comments={filteredComments} mode={analysisMode} allCommentRpids={allCommentRpids}/></div>
        </>}
        </>}

        {/* Reanalyze confirmation modal */}
        {reanalyzeModal && (
          <div className="reanalyze-dialog" onClick={()=>setReanalyzeModal(false)}>
            <div className="reanalyze-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="reanalyze-title" onClick={e=>e.stopPropagation()}>
              <h3 id="reanalyze-title">切换到大模型情感分析</h3>
              <p className="reanalyze-dialog__copy">
                当前分析结果使用 NLP 三分类模式生成。是否使用已保存的 {results?.total_comments} 条评论数据，重新进行大模型十分类分析？
              </p>
              <p className="reanalyze-dialog__notice">
                ⚠ 大模型分析将调用设置中选择的情绪分析供应商，可能产生少量费用。
              </p>
              <div className="reanalyze-dialog__actions">
                <button onClick={()=>setReanalyzeModal(false)} className="btn btn-ghost">取消</button>
                <button onClick={handleReanalyzeConfirm} className="btn btn-primary">确认重新分析</button>
              </div>
            </div>
          </div>
        )}
      </main>
        )} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </AppErrorBoundary>
      </div>
      {updateInfo && (
          <div className="reanalyze-dialog" role="presentation">
            <div className="reanalyze-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="update-title">
              <h3 id="update-title">发现新版本 {updateInfo.version || ''}</h3>
              <p className="reanalyze-dialog__copy">新版本已准备好下载。更新只会替换程序文件，保留当前目录中的数据、登录信息和模型设置。</p>
              {updateInfo.notes && <p className="reanalyze-dialog__notice">{updateInfo.notes}</p>}
              <div className="reanalyze-dialog__actions">
                <button onClick={() => setUpdateInfo(null)} className="btn btn-ghost" disabled={updateBusy}>暂不更新</button>
                <button onClick={() => { void installUpdate(); }} className="btn btn-primary" disabled={updateBusy}>{updateBusy ? '下载更新中…' : '下载并重启'}</button>
              </div>
            </div>
          </div>
        )}
      {closeRequest && (
          <div className="reanalyze-dialog" role="presentation">
            <div className="reanalyze-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="desktop-close-title">
              <h3 id="desktop-close-title">后台任务仍在进行</h3>
              <p className="reanalyze-dialog__copy">关闭窗口会中断正在执行的抓取或分析。你可以停止任务后退出，或让应用继续在系统托盘中运行。</p>
              <div className="reanalyze-dialog__actions reanalyze-dialog__actions--three">
                <button onClick={() => { void resolveClose('cancel'); }} className="btn btn-ghost">取消</button>
                <button onClick={() => { void resolveClose('tray'); }} className="btn btn-ghost">继续在托盘运行</button>
                <button onClick={() => { void resolveClose('exit'); }} className="btn btn-primary">停止并退出</button>
              </div>
            </div>
          </div>
      )}
    </div>
  );
}

export default App;
