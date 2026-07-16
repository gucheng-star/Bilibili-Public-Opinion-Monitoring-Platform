import { useState } from 'react';
import { getVideoInfo } from '../services/api';
import type { VideoInfoResponse } from '../types';

interface Props {
  onAnalyze: (bv: string, maxComments: number, delay: number) => void;
  loading: boolean;
}

function parseBv(input: string): string {
  const m = input.match(/BV[A-Za-z0-9]{10}/);
  return m ? m[0] : '';
}

export default function SearchBar({ onAnalyze, loading }: Props) {
  const [rawInput, setRawInput] = useState('');
  const [bv, setBv] = useState('');
  const [videoInfo, setVideoInfo] = useState<VideoInfoResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [maxComments, setMaxComments] = useState(100);
  const [delay, setDelay] = useState(3.0);

  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);
  const perPage = 20;
  const totalRequests = Math.ceil(maxComments / perPage);
  const estimatedTime = Math.round(totalRequests * delay);

  const handlePreview = async () => {
    const parsed = parseBv(rawInput);
    if (!parsed) { setPreviewError('OtherBV'); return; }
    setBv(parsed);
    setPreviewLoading(true); setPreviewError('');
    try { const info = await getVideoInfo(parsed); setVideoInfo(info); setShowSettings(true); }
    catch { setPreviewError('获取视频信息失败'); setVideoInfo(null); }
    setPreviewLoading(false);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (bv) onAnalyze(bv, maxComments, delay);
  };

  return (
    <form onSubmit={handleSubmit}>
      <div className="flex items-center gap-3">
        <div className="flex-1 relative">
          <input type="text" value={rawInput} onChange={e => { setRawInput(e.target.value); setVideoInfo(null); setPreviewError(''); }}
            placeholder="B站视频链接或 BV 号" className="search-input" disabled={loading}/>
        </div>
        {!videoInfo && (
          <button type="button" onClick={handlePreview} disabled={loading || previewLoading || !rawInput.trim()}
            className="btn-analyze" style={{background:'var(--blue)',whiteSpace:'nowrap'}}>
            {previewLoading ? '获取中...' : '获取视频信息'}
          </button>
        )}
        {videoInfo && (
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => setShowSettings(!showSettings)}
              className="theme-toggle" title="设置" style={{borderColor:showSettings?'var(--accent)':'var(--border)'}}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
            </button>
            <button type="submit" disabled={loading} className="btn-analyze">
              {loading ? '分析中...' : '开始分析'}
            </button>
          </div>
        )}
      </div>

      {previewError && (
        <div style={{marginTop:'.5rem',padding:'.5rem .75rem',background:'var(--red-soft)',border:'1px solid var(--red)',borderRadius:'.375rem'}}>
          <p className="text-xs" style={{color:'var(--red)'}}>{previewError}</p>
        </div>
      )}

      {videoInfo && (
        <div className="card mt-3" style={{padding:'.75rem 1rem'}}>
          <p className="text-sm font-medium text-primary truncate">{videoInfo.title}</p>
          <p className="text-xs text-secondary mt-1">播放 {videoInfo.play.toLocaleString()} &middot; 评论 {videoInfo.comment_count.toLocaleString()}</p>
        </div>
      )}

      {showSettings && videoInfo && (
        <div className="card mt-3" style={{padding:'1rem 1.25rem'}}>
          <div className="flex items-center gap-6 flex-wrap">
            <div style={{flex:'1 1 14rem'}}>
              <label className="text-xs text-secondary mb-1" style={{display:'block'}}>
                抓取评论总数（此视频共 {videoInfo.comment_count.toLocaleString()} 条，每页{perPage}条，预计 {totalRequests} 次请求约 {estimatedTime} 秒）
              </label>
              <div className="flex items-center gap-2">
                <input type="range" min="1" max="2000" value={Math.min(maxComments, 2000)}
                  onChange={e => setMaxComments(Number(e.target.value))}
                  style={{flex:1,accentColor:'var(--accent)'}}/>
                <input type="number" min="1" value={maxComments}
                  onChange={e => setMaxComments(clamp(Number(e.target.value), 1, 99999))}
                  style={{width:'5rem',padding:'.25rem .375rem',fontSize:'.8125rem',textAlign:'center',background:'var(--input-bg)',color:'var(--text-primary)',border:'1px solid var(--input-border)',borderRadius:'.375rem',outline:'none'}}/>
              </div>
            </div>
            <div style={{flex:'1 1 12rem'}}>
              <label className="text-xs text-secondary mb-1" style={{display:'block'}}>请求间隔</label>
              <div className="flex items-center gap-2">
                <input type="range" min="1" max="10" step="0.5" value={delay}
                  onChange={e => setDelay(Number(e.target.value))}
                  style={{flex:1,accentColor:'var(--accent)'}}/>
                <input type="number" min="1" max="60" step="0.5" value={delay}
                  onChange={e => setDelay(clamp(Number(e.target.value), 1, 60))}
                  style={{width:'4.5rem',padding:'.25rem .375rem',fontSize:'.8125rem',textAlign:'center',background:'var(--input-bg)',color:'var(--text-primary)',border:'1px solid var(--input-border)',borderRadius:'.375rem',outline:'none'}}/>
                <span className="text-xs text-muted">秒</span>
              </div>
            </div>
          </div>
          {delay < 2 && (
            <div style={{marginTop:'.75rem',padding:'.5rem .75rem',background:'var(--red-soft)',border:'1px solid var(--red)',borderRadius:'.375rem'}}>
              <p className="text-xs" style={{color:'var(--red)',lineHeight:1.5}}>间隔过短可能触发风控，建议 3 秒以上。</p>
            </div>
          )}
          {totalRequests > 10 && (
            <div style={{marginTop:'.75rem',padding:'.5rem .75rem',background:'var(--yellow-soft)',border:'1px solid var(--yellow)',borderRadius:'.375rem'}}>
              <p className="text-xs" style={{color:'var(--yellow)',lineHeight:1.5}}>将抓取 {maxComments} 条评论，共 {totalRequests} 次请求，可能触发风控。</p>
            </div>
          )}
        </div>
      )}
    </form>
  );
}