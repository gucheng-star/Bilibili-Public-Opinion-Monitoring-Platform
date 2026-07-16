import { useState, useCallback, useRef, useEffect } from 'react';
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
import { startAnalysis, getStatus, getResults } from './services/api';
import type { AnalysisResult } from './types';

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
  const cancelRef = useRef(false);

  useEffect(() => { fetch('/api/auth/status').then(r=>r.json()).then(d=>setLoggedIn(d.logged_in)).catch(()=>setLoggedIn(false)); }, []);

  const showToast = (msg: string) => { setToast(msg); setTimeout(()=>setToast(null), 4000); };

  const handleAnalyze = useCallback(async (bv: string, maxComments: number, delay: number) => {
    setLoading(true); setError(null); setResults(null); cancelRef.current = false;
    setProgress(0); setProgressMax(maxComments); setStatusText('正在获取视频信息...');
    try {
      const { analysis_id } = await startAnalysis(bv, maxComments, delay);
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
              setResults(data); setLoading(false); showToast('分析完成');
              return;
            }
            if (status.status === 'error') { setError(status.error_msg || '分析失败'); setLoading(false); showToast('分析失败'); return; }
            if (status.status === 'fetching') setStatusText('抓取中 (' + status.total_comments + '/' + maxComments + ')');
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
    try { const data = await getResults(id); setResults(data); setAnalysisId(id); } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, []);

  const handleLogout = async () => { await fetch('/api/auth/logout',{method:'POST'}); setLoggedIn(false); setResults(null); };
  const handleStop = () => { cancelRef.current = true; };

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
              <ThemeToggle/>
            </div>
          </div>
          <SearchBar onAnalyze={handleAnalyze} loading={loading}/>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-6">
        {toast && <div style={{position:'fixed',top:'1rem',left:'50%',transform:'translateX(-50%)',zIndex:100,padding:'.5rem 1.25rem',background:'var(--green-soft)',border:'1px solid var(--green)',borderRadius:'.5rem',color:'var(--green)',fontSize:'.8125rem',fontWeight:500}}>{toast}</div>}
        {error && <div style={{padding:'.75rem 1rem',background:'var(--red-soft)',border:'1px solid var(--red)',borderRadius:'.5rem',color:'var(--red)',fontSize:'.8125rem',marginBottom:'1rem'}}>{error}</div>}
        {loading && !results && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="pulse-dot" style={{width:'.875rem',height:'.875rem',marginBottom:'1.5rem'}}></div>
            <p className="text-sm text-secondary mb-3">{statusText}</p>
            {progressMax > 0 && (
              <div style={{width:'20rem',maxWidth:'80%',height:'.375rem',background:'var(--border)',borderRadius:'.25rem',overflow:'hidden'}}>
                <div style={{height:'100%',width:Math.min(progress/progressMax*100,100)+'%',background:'var(--accent)',borderRadius:'.25rem',transition:'width .3s ease'}}/>
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
          <div className="mb-4">
            <button onClick={()=>setShowHistory(!showHistory)} className="flex items-center gap-1 text-xs text-muted mb-2" style={{background:'none',border:'none',cursor:'pointer'}}>
              <span>{showHistory?'收起':'展开'}历史记录</span>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{transform:showHistory?'rotate(180deg)':'rotate(0deg)',transition:'transform .2s'}}><path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6"/></svg>
            </button>
            {showHistory && <HistoryPanel onSelect={handleViewHistory} selectedId={analysisId}/>}
          </div>
          <VideoInfo title={results.video_title} play={results.video_play} totalComments={results.total_comments}/>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
            <SentimentChart {...results.sentiment}/>
            <RegionMap data={results.region}/>
            <GenderChart {...results.gender}/>
            <WordCloudCard keywords={results.keywords}/>
            <HeatTimeline timeline={results.heat.timeline} hourlyDistribution={results.heat.hourly_distribution} peakHour={results.heat.peak_hour} peakCount={results.heat.peak_count}/>
          </div>
          <div className="mt-4"><CommentTable comments={results.comments}/></div>
        </>}
      </main>
    </div>
  );
}

export default App;