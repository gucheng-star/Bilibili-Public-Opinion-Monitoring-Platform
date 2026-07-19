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
import { startAnalysis, getStatus, getResults, getSettings } from './services/api';
import type { AnalysisResult, FilterState, AnalysisMode, KeywordItem } from './types';

const PROVINCES = new Set(['北京','天津','上海','重庆','河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','海南','四川','贵州','云南','陕西','甘肃','青海','台湾','内蒙古','广西','西藏','宁夏','新疆','香港','澳门']);

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
  const [filters, setFilters] = useState<FilterState>({ gender: 'all', dateFrom: '', dateTo: '', region: '' });
  const [hasApiKey, setHasApiKey] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => { fetch('/api/auth/status').then(r=>r.json()).then(d=>setLoggedIn(d.logged_in)).catch(()=>setLoggedIn(false)); }, []);
  useEffect(() => { getSettings().then(s => { setHasApiKey(s.has_api_key); setAnalysisMode(s.analysis_mode || 'nlp'); }).catch(() => {}); }, []);

  const showToast = (msg: string) => { setToast(msg); setTimeout(()=>setToast(null), 4000); };

  const handleModeChange = (mode: AnalysisMode) => {
    if (mode === 'llm' && !hasApiKey) { showToast('请先在设置面板填入百炼 API Key 后再切换到大模型模式'); return; }
    setAnalysisMode(mode);
  };

  const handleAnalyze = useCallback(async (bv: string, _maxComments: number, _delay: number, mode: AnalysisMode) => {
    setLoading(true); setError(null); setResults(null); cancelRef.current = false;
    setProgress(0); setProgressMax(_maxComments); setStatusText('正在获取视频信息...');
    try {
      const { analysis_id } = await startAnalysis(bv, _maxComments, _delay, mode);
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
            else if (status.status === 'analyzing') setStatusText('分析中...');
          } catch { if (cancelRef.current) { setLoading(false); return; } }
        }
        setError('超时'); setLoading(false);
      };
      poll();
    } catch (e: any) { setError(e.message || '失败'); setLoading(false); }
  }, []);

  const handleViewHistory = useCallback(async (id: number) => {
    setLoading(true); setError(null); setStatusText('加载中...');
    try { const data = await getResults(id); setResults(data); setAnalysisId(id); setAnalysisMode(data.mode); setFilters({ gender:'all',dateFrom:'',dateTo:'',region:'' }); } catch (e:any) { setError(e.message); }
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
    if (filters.dateFrom) { const ts = new Date(filters.dateFrom).getTime(); comments = comments.filter(c => c.post_time && new Date(c.post_time).getTime() >= ts); }
    if (filters.dateTo) { const ts = new Date(filters.dateTo).getTime() + 86400000; comments = comments.filter(c => c.post_time && new Date(c.post_time).getTime() <= ts); }
    if (filters.region) { comments = comments.filter(c => c.ip_location && (c.ip_location === filters.region || c.ip_location.startsWith(filters.region+' '))); }
    return comments;
  }, [results, filters]);

  const filteredSentiment = useMemo(() => ({
    positive: filteredComments.filter(c => c.sentiment_label === 'positive').length,
    negative: filteredComments.filter(c => c.sentiment_label === 'negative').length,
    neutral: filteredComments.filter(c => c.sentiment_label === 'neutral').length,
  }), [filteredComments]);

  const filteredGender = useMemo(() => ({
    male: filteredComments.filter(c => c.gender === '男').length,
    female: filteredComments.filter(c => c.gender === '女').length,
    unknown: filteredComments.filter(c => c.gender === '保密').length,
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
    const pk = Math.max(...hd); const pi = hd.indexOf(pk);
    return { timeline, peak_hour: pi>=0?String(pi).padStart(2,'0')+':00':null, peak_count: pk, hourly_distribution: hd.map((c,h)=>({hour:h,count:c})) };
  }, [filteredComments]);

  const filteredKeywords = useMemo(() => {
    if (!results) return [];
    const txt = filteredComments.map(c=>c.content).join(' ');
    return results.keywords.filter(k => txt.includes(k.word));
  }, [results, filteredComments]);

  const availableRegions = useMemo(() => {
    if (!results) return [];
    const s = new Set<string>();
    results.comments.forEach(c => { const p = normalizeProvince(c.ip_location); if (p) s.add(p); });
    return Array.from(s).sort();
  }, [results]);

  if (loggedIn === null) return <div className="min-h-screen flex items-center justify-center" style={{background:'var(--bg)'}}><div className="pulse-dot"></div></div>;
  if (!loggedIn) return <LoginPage onLogin={()=>setLoggedIn(true)}/>;

  return (
    <div className="min-h-screen" style={{background:'var(--bg)'}}>
      <header className="sticky top-0 z-10" style={{background:'var(--bg)',borderBottom:'1px solid var(--border)'}}>
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span style={{fontSize:'1.25rem',fontWeight:700,color:'var(--accent)'}}>B站</span>
              <span className="text-primary" style={{fontSize:'1rem',fontWeight:600}}>舆论监测平台</span>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={handleLogout} style={{fontSize:'.75rem',color:'var(--text-muted)',background:'none',border:'none',cursor:'pointer'}}>退出</button>
              <button onClick={() => setShowSettings(!showSettings)} className="theme-toggle" title="设置" style={{borderColor:showSettings?'var(--accent)':'var(--border)'}}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
              </button>
              <ThemeToggle/>
            </div>
          </div>
          <SearchBar onAnalyze={handleAnalyze} loading={loading} maxComments={maxComments} delay={delay} currentMode={analysisMode}/>
        </div>
      </header>
      <div className="header-accent-line" />
      {showSettings && (
        <div className="max-w-7xl mx-auto px-4" style={{background:'var(--bg)'}}>
          <SettingsPanel maxComments={maxComments} onMaxCommentsChange={setMaxComments} delay={delay} onDelayChange={setDelay} mode={analysisMode} onModeChange={handleModeChange} hasApiKey={hasApiKey} onApiKeySaved={() => getSettings().then(s => setHasApiKey(s.has_api_key))}/>
        </div>
      )}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {toast && <div style={{position:'fixed',top:'1rem',left:'50%',transform:'translateX(-50%)',zIndex:100,padding:'.5rem 1.25rem',background:'var(--green-soft)',border:'1px solid var(--green)',borderRadius:'.5rem',color:'var(--green)',fontSize:'.8125rem',fontWeight:500}}>{toast}</div>}
        {error && <div style={{padding:'.75rem 1rem',background:'var(--red-soft)',border:'1px solid var(--red)',borderRadius:'.5rem',color:'var(--red)',fontSize:'.8125rem',marginBottom:'1rem'}}>{error}</div>}
        <div className="mb-4">
          <button onClick={()=>setShowHistory(!showHistory)} className="flex items-center gap-1 text-xs text-muted mb-2" style={{background:'none',border:'none',cursor:'pointer'}}>
            <span>{showHistory?'收起':'展开'}历史记录</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{transform:showHistory?'rotate(180deg)':'rotate(0deg)',transition:'transform .2s'}}><path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6"/></svg>
          </button>
          {showHistory && <HistoryPanel onSelect={handleViewHistory} selectedId={analysisId} refreshKey={historyRefreshKey}/>}
        </div>
        {loading && !results && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="pulse-dot" style={{width:'.875rem',height:'.875rem',marginBottom:'1.5rem'}}></div>
            <p className="text-sm text-secondary mb-3">{statusText}</p>
            {progressMax > 0 && (
              <div className="progress-bar-track" style={{width:'20rem',maxWidth:'80%'}}>
                <div className="progress-bar-fill" style={{width:Math.min(progress/progressMax*100,100)+'%'}}/>
              </div>
            )}
            <button onClick={handleStop} style={{marginTop:'1rem',padding:'.375rem 1rem',fontSize:'.75rem',color:'var(--text-muted)',background:'transparent',border:'1px solid var(--border)',borderRadius:'.375rem',cursor:'pointer'}}>取消分析</button>
          </div>
        )}
        {!loading && !results && (
          <div className="flex flex-col items-center justify-center py-20 text-muted">
            <svg className="w-12 h-12 mb-4" style={{opacity:.15}} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
            <p className="text-sm">输入 BV 号开始分析</p>
          </div>
        )}
        {results && <>
          <VideoInfo title={results.video_title} play={results.video_play} totalComments={results.total_comments}/>
          <FilterBar filters={filters} onApply={handleApplyFilters} availableRegions={availableRegions}/>
          <div className="grid grid-cols-1 md:grid-cols-2 md:grid-auto-rows-fr gap-4 mt-4">
            <div className="card-enter">
              <SentimentChart positive={filteredSentiment.positive} negative={filteredSentiment.negative} neutral={filteredSentiment.neutral} mode={analysisMode} llm={results.sentiment_llm || null} onModeChange={handleModeChange}/>
            </div>
            <div className="card-enter"><GenderChart male={filteredGender.male} female={filteredGender.female} unknown={filteredGender.unknown}/></div>
          </div>
          <div className="card-enter mt-4"><RegionMap data={filteredRegion}/></div>
          <div className="card-enter mt-4"><WordCloudCard keywords={filteredKeywords}/></div>
          <div className="card-enter mt-4">
            <HeatTimeline timeline={filteredHeat.timeline} hourlyDistribution={filteredHeat.hourly_distribution} peakHour={filteredHeat.peak_hour} peakCount={filteredHeat.peak_count}/>
          </div>
          <div className="card-enter mt-4"><CommentTable comments={filteredComments}/></div>
        </>}
      </main>
    </div>
  );
}

export default App;
