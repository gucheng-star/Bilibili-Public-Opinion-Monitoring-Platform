import { useState } from 'react';
import { getVideoInfo } from '../services/api';
import type { VideoInfoResponse, AnalysisMode } from '../types';

interface Props {
  onAnalyze: (bv: string, maxComments: number, delay: number, mode: AnalysisMode) => void;
  loading: boolean;
  maxComments: number;
  delay: number;
  currentMode: AnalysisMode;
}

function parseBv(input: string): string {
  const m = input.match(/BV[A-Za-z0-9]{10}/);
  return m ? m[0] : '';
}

export default function SearchBar({ onAnalyze, loading, maxComments, delay, currentMode }: Props) {
  const [rawInput, setRawInput] = useState('');
  const [bv, setBv] = useState('');
  const [videoInfo, setVideoInfo] = useState<VideoInfoResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');

  const handlePreview = async () => {
    const parsed = parseBv(rawInput);
    if (!parsed) { setPreviewError('请输入有效的 BV 号'); return; }
    setBv(parsed);
    setPreviewLoading(true); setPreviewError('');
    try { const info = await getVideoInfo(parsed); setVideoInfo(info); }
    catch { setPreviewError('获取视频信息失败'); setVideoInfo(null); }
    setPreviewLoading(false);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (bv) onAnalyze(bv, maxComments, delay, currentMode);
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
            style={{height:'3rem',padding:'0 1.25rem',fontSize:'.875rem',fontWeight:600,background:'rgba(0,161,214,.12)',color:'#00A1D6',border:'1px solid rgba(0,161,214,.25)',borderRadius:'.625rem',cursor:'pointer',whiteSpace:'nowrap',transition:'all .2s ease'}}>
            {previewLoading ? '获取中...' : '获取视频信息'}
          </button>
        )}
        {videoInfo && (
          <div className="flex items-center gap-3">
            <button type="submit" disabled={loading}
              style={{height:'3rem',padding:'0 1.25rem',fontSize:'.875rem',fontWeight:600,background:'rgba(0,161,214,.12)',color:'#00A1D6',border:'1px solid rgba(0,161,214,.25)',borderRadius:'.625rem',cursor:loading?'default':'pointer',whiteSpace:'nowrap',transition:'all .2s ease',opacity:loading?.6:1}}>
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
          <p className="text-xs text-secondary mt-1">播放 {videoInfo.play.toLocaleString()} &middot; 评论 {(videoInfo?.comment_count ?? 0).toLocaleString()}</p>
        </div>
      )}
    </form>
  );
}
