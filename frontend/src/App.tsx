import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import SearchBar from './components/SearchBar';
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
import SettingsPanel from './components/SettingsPanel';
import AISummaryCard from './components/AISummaryCard';
import { startAnalysis, getStatus, getResults, getSettings, reanalyze } from './services/api';
import type { AnalysisResult, FilterState, AnalysisMode, SentimentLLM } from './types';
import './AppShell.css';

const PROVINCES = new Set(['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','海南','四川','贵州','云南','陕西','甘肃','青海','台湾','内蒙古','广西','西藏','宁夏','新疆','香港','澳门']);
const LLM_EMOTIONS: (keyof SentimentLLM)[] = ['neutral', 'joy', 'support', 'anticipation', 'surprise', 'anger', 'sadness', 'concern', 'disgust'];
const LLM_CONCURRENCY = 3;
const LLM_SECONDS_PER_COMMENT = 1.29;

function getLlmEstimateText(commentCount: number): string {
  const totalSeconds = Math.ceil(Math.max(commentCount, 1) * LLM_SECONDS_PER_COMMENT);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const duration = minutes > 0 ? `${minutes}分${seconds}秒` : `${seconds}秒`;
  return `大模型分析中，预计约 ${duration}（每轮最多并发 ${LLM_CONCURRENCY} 个单评论请求）`;
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
  const [analysisId, setAnalysisId] = useState<number | null>(null);
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
  const cancelRef = useRef(false);

  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>('nlp');
  const [maxComments, setMaxComments] = useState(100);
  const [delay, setDelay] = useState(3.0);
  const [filters, setFilters] = useState<FilterState>({ gender: 'all', dateFrom: '', dateTo: '', region: '', sentiment: 'all' });
  const [hasApiKey, setHasApiKey] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [reanalyzeModal, setReanalyzeModal] = useState(false);

  useEffect(() => { fetch('/api/auth/status').then(r=>r.json()).then(d=>setLoggedIn(d.logged_in)).catch(()=>setLoggedIn(false)); }, []);
  useEffect(() => { getSettings().then(s => { setHasApiKey(s.llm.sentiment.has_api_key); }).catch(() => {}); }, []);
  useEffect(() => {
    setFilters(current => current.sentiment === 'all' ? current : { ...current, sentiment: 'all' });
  }, [results?.mode]);

  const showToast = (msg: string) => { setToast(msg); setTimeout(()=>setToast(null), 4000); };

  const handleModeChange = (mode: AnalysisMode) => {
    if (mode === 'llm' && !hasApiKey) { showToast('请先在设置面板配置情绪分析模型的 API Key'); return; }
    // NLP → LLM：弹出确认弹窗
    if (mode === 'llm' && results && results.mode !== 'llm') { setReanalyzeModal(true); return; }
    setAnalysisMode(mode);
  };

  const handleReanalyzeConfirm = async () => {
    if (!analysisId) return;
    setReanalyzeModal(false);
    setLoading(true); setError(null); cancelRef.current = false;
    setProgress(0); setProgressMax(results?.total_comments || 100);
    setStatusText(getLlmEstimateText(results?.total_comments || 100));
    setAnalysisMode('llm');
    try {
      await reanalyze(analysisId);
      const poll = async () => {
        for (let i = 0; i < 300; i++) {
          if (cancelRef.current) { setLoading(false); setStatusText('已取消'); return; }
          await new Promise(r => setTimeout(r, 1500));
          try {
            const status = await getStatus(analysisId);
            setProgress(status.total_comments);
            if (status.status === 'done') {
              if (status.error_msg) {
                setError(status.error_msg);
                setAnalysisMode(results?.mode || 'nlp');
                setLoading(false);
                showToast('大模型分析失败，已保留 NLP 结果');
                return;
              }
              setStatusText(''); const data = await getResults(analysisId);
              setResults(data); setAnalysisMode(data.mode); setLoading(false); setHistoryRefreshKey(k=>k+1); showToast('大模型分析完成');
              return;
            }
            if (status.status === 'error') { setError(status.error_msg || '分析失败'); setLoading(false); showToast('分析失败'); return; }
            if (status.status === 'analyzing') setStatusText(getLlmEstimateText(status.total_comments || results?.total_comments || 100));
          } catch { if (cancelRef.current) { setLoading(false); return; } }
        }
        setError('超时'); setLoading(false);
      };
      poll();
    } catch (e: any) { setError(e.message || '重新分析失败'); setLoading(false); }
  };

  const handleAnalyze = useCallback(async (bv: string, _maxComments: number, _delay: number) => {
    setLoading(true); setError(null); setResults(null); cancelRef.current = false;
    setAnalysisMode('nlp');
    setProgress(0); setProgressMax(_maxComments); setStatusText('正在获取视频信息...');
    try {
      const { analysis_id } = await startAnalysis(bv, _maxComments, _delay);
      setAnalysisId(analysis_id); setStatusText('正在抓取评论...');
      const poll = async () => {
        for (let i = 0; i < 300; i++) {
          if (cancelRef.current) { setLoading(false); setStatusText('已取消'); return; }
          await new Promise(r => setTimeout(r, 1500));
          try {
            const status = await getStatus(analysis_id);
            setProgress(status.total_comments);
            if (status.status === 'done') {
              setStatusText(''); const data = await getResults(analysis_id);
              setResults(data); setAnalysisMode(data.mode); setLoading(false); setHistoryRefreshKey(k=>k+1); showToast('分析完成');
              return;
            }
            if (status.status === 'error') { setError(status.error_msg || '分析失败'); setLoading(false); showToast('分析失败'); return; }
            if (status.status === 'fetching') setStatusText('抓取中 ('+status.total_comments+'/'+_maxComments+')');
            else if (status.status === 'analyzing') {
              setStatusText('分析中...');
            }
          } catch { if (cancelRef.current) { setLoading(false); return; } }
        }
        setError('超时'); setLoading(false);
      };
      poll();
    } catch (e: any) { setError(e.message || '失败'); setLoading(false); }
  }, []);

  const handleViewHistory = useCallback(async (id: number) => {
    setLoading(true); setError(null); setStatusText('加载中...');
    try { const data = await getResults(id); setResults(data); setAnalysisId(id); setAnalysisMode(data.mode); setFilters({ gender:'all',dateFrom:'',dateTo:'',region:'',sentiment:'all' }); } catch (e:any) { setError(e.message); }
    setLoading(false);
  }, []);

  const handleLogout = async () => { await fetch('/api/auth/logout',{method:'POST'}); setLoggedIn(false); setResults(null); };
  const handleStop = () => { cancelRef.current = true; };
  const handleApplyFilters = (f: FilterState) => { setFilters(f); };

  const filteredComments = useMemo(() => {
    if (!results) return [];
    let comments = [...results.comments];
    if (filters.gender === 'male') comments = comments.filter(c => c.gender === '男');
    if (filters.gender === 'female') comments = comments.filter(c => c.gender === '女');
    if (filters.dateFrom) comments = comments.filter(c => c.post_time && c.post_time.slice(0, 10) >= filters.dateFrom);
    if (filters.dateTo) comments = comments.filter(c => c.post_time && c.post_time.slice(0, 10) <= filters.dateTo);
    if (filters.region) { comments = comments.filter(c => normalizeProvince(c.ip_location) === filters.region); }
    if (filters.sentiment !== 'all') {
      comments = results.mode === 'llm'
        ? comments.filter(c => c.sentiment_llm_label === filters.sentiment)
        : comments.filter(c => c.sentiment_label === filters.sentiment);
    }
    return comments;
  }, [results, filters]);

  const filteredSentiment = useMemo(() => ({
    positive: filteredComments.filter(c => c.sentiment_label === 'positive').length,
    negative: filteredComments.filter(c => c.sentiment_label === 'negative').length,
    neutral: filteredComments.filter(c => c.sentiment_label === 'neutral').length,
  }), [filteredComments]);

  const filteredLlmSentiment = useMemo<SentimentLLM>(() => {
    const counts: SentimentLLM = { neutral:0, joy:0, support:0, anticipation:0, surprise:0, anger:0, sadness:0, concern:0, disgust:0 };
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
    const total = filteredComments.length || 1;
    return Array.from(map.entries()).map(([region,count]) => ({ region, count, percentage: Math.round(count/total*100) }));
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

  const filteredKeywords = useMemo(() => {
    if (!results) return [];
    return results.keywords
      .map(keyword => ({
        ...keyword,
        count: filteredComments.reduce(
          (total, comment) => total + Math.max(0, comment.content.split(keyword.word).length - 1),
          0,
        ),
      }))
      .filter(keyword => keyword.count > 0)
      .sort((left, right) => right.count - left.count);
  }, [results, filteredComments]);

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
        <div className="app-header__inner max-w-7xl mx-auto px-4 py-4">
          <div className="app-header__bar flex items-center justify-between mb-3">
            <div className="app-brand flex items-center gap-2">
              <img className="app-brand__icon" src="/signal-observatory-icon.png" alt="" aria-hidden="true" />
              <span className="app-brand__mark">B站</span>
              <span className="app-brand__name">舆论监测平台</span>
            </div>
            <div className="app-header__actions flex items-center gap-3">
              <button onClick={handleLogout} className="app-header__logout">退出</button>
              <button onClick={() => setShowSettings(!showSettings)} className="theme-toggle" title="设置" style={{borderColor:showSettings?'var(--accent)':'var(--border)'}}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l-.06-.06a2 2 0 012.83 2.83l.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
              </button>
              <ThemeToggle/>
            </div>
          </div>
          <section className="command-deck" aria-label="视频分析指令舱">
            <div className="command-deck__label"><span aria-hidden="true"></span>VIDEO SIGNAL COMMAND</div>
            <SearchBar onAnalyze={handleAnalyze} loading={loading} maxComments={maxComments} delay={delay}/>
          </section>
        </div>
      </header>
      <div className="header-accent-line" />
      {showSettings && (
        <div className="settings-drawer max-w-7xl mx-auto px-4">
          <SettingsPanel maxComments={maxComments} onMaxCommentsChange={setMaxComments} delay={delay} onDelayChange={setDelay}
            onSettingsChanged={settings => setHasApiKey(settings.llm.sentiment.has_api_key)}/>
        </div>
      )}
      <main className="app-main max-w-7xl mx-auto px-4 py-6">
        {toast && <div className="app-toast" role="status">{toast}</div>}
        {error && <div className="app-alert app-alert--error" role="alert">{error}</div>}
        <section className="history-rail mb-4" aria-label="历史记录">
          <button onClick={()=>setShowHistory(!showHistory)} className="history-rail__toggle flex items-center gap-1 text-xs text-muted mb-2" aria-expanded={showHistory}>
            <span>{showHistory?'收起':'展开'}历史记录</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{transform:showHistory?'rotate(180deg)':'rotate(0deg)',transition:'transform .2s'}}><path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6"/></svg>
          </button>
          {showHistory && <HistoryPanel onSelect={handleViewHistory} selectedId={analysisId} refreshKey={historyRefreshKey}/>}
        </section>
        {!loading && results && (<div className="app-alert app-alert--status">模式: {results.mode === 'llm' ? '大模型九类主情感' : 'NLP三分类'} · 共 {results.total_comments} 条评论</div>)}

        {loading && !results && (
          <div className="app-state flex flex-col items-center justify-center py-20">
            <div className="pulse-dot app-state__pulse"></div>
            <p className="text-sm text-secondary mb-3">{statusText}</p>
            {progressMax > 0 && (
              <div className="progress-bar-track app-state__progress" role="progressbar" aria-label="评论抓取进度"
                aria-valuemin={0} aria-valuemax={progressMax} aria-valuenow={Math.min(progress, progressMax)}>
                <div className="progress-bar-fill" style={{width:Math.min(progress/progressMax*100,100)+'%'}}/>
              </div>
            )}
            <button onClick={handleStop} className="btn btn-ghost app-state__action">取消分析</button>
          </div>
        )}

        {/* Loading overlay for reanalysis (result already rendered, just updating) */}
        {loading && results && (
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
          <FilterBar filters={filters} onApply={handleApplyFilters} availableRegions={availableRegions} mode={results.mode}/>
          {analysisId && <div className="card-enter mt-4">
            <AISummaryCard analysisId={analysisId} filters={filters} matchedCount={filteredComments.length} mode={results.mode}/>
          </div>}
          <div className="grid grid-cols-1 md:grid-cols-2 md:grid-auto-rows-fr gap-4 mt-4 paired-chart-grid">
            <div className="card-enter">
              <SentimentChart positive={filteredSentiment.positive} negative={filteredSentiment.negative} neutral={filteredSentiment.neutral} mode={analysisMode} llm={results.mode === 'llm' ? filteredLlmSentiment : null} onModeChange={handleModeChange}/>
            </div>
            <div className="card-enter"><GenderChart male={filteredGender.male} female={filteredGender.female} unknown={filteredGender.unknown}/></div>
          </div>
          <div className="card-enter mt-4"><RegionMap data={filteredRegion}/></div>
          <div className="card-enter mt-4"><WordCloudCard keywords={filteredKeywords}/></div>
          <div className="card-enter mt-4">
            <HeatTimeline timeline={filteredHeat.timeline} hourlyDistribution={filteredHeat.hourly_distribution} peakHour={filteredHeat.peak_hour} peakCount={filteredHeat.peak_count}/>
          </div>
          <div className="card-enter mt-4"><CommentTable comments={filteredComments} mode={analysisMode}/></div>
        </>}

        {/* Reanalyze confirmation modal */}
        {reanalyzeModal && (
          <div className="reanalyze-dialog" onClick={()=>setReanalyzeModal(false)}>
            <div className="reanalyze-dialog__panel" role="dialog" aria-modal="true" aria-labelledby="reanalyze-title" onClick={e=>e.stopPropagation()}>
              <h3 id="reanalyze-title">切换到大模型情感分析</h3>
              <p className="reanalyze-dialog__copy">
                当前分析结果使用 NLP 三分类模式生成。是否使用已保存的 {results?.total_comments} 条评论数据，重新进行大模型九类主情感分析？
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
    </div>
  );
}

export default App;
