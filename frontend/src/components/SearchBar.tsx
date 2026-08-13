import { useState, type Dispatch, type SetStateAction } from 'react';
import { getVideoInfo } from '../services/api';
import type { VideoInfoResponse } from '../types';
import './DataPanels.css';

export interface SearchDraft {
  rawInput: string;
  bv: string;
  videoInfo: VideoInfoResponse | null;
}

interface BaseProps {
  onAnalyze: (bv: string, maxComments: number, delay: number) => void;
  loading: boolean;
  maxComments: number;
  delay: number;
}

type Props = BaseProps & (
  | { draft: SearchDraft; onDraftChange: Dispatch<SetStateAction<SearchDraft>> }
  | { draft?: never; onDraftChange?: never }
);

function parseBv(input: string): string {
  const m = input.match(/BV[A-Za-z0-9]{10}/);
  return m ? m[0] : '';
}

export default function SearchBar({ onAnalyze, loading, maxComments, delay, draft, onDraftChange }: Props) {
  const [uncontrolledDraft, setUncontrolledDraft] = useState<SearchDraft>({ rawInput: '', bv: '', videoInfo: null });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const currentDraft = draft ?? uncontrolledDraft;
  const { rawInput, bv, videoInfo } = currentDraft;
  const updateDraft = (next: SetStateAction<SearchDraft>) => {
    if (draft !== undefined && onDraftChange) {
      onDraftChange(next);
      return;
    }
    setUncontrolledDraft(next);
  };

  const handlePreview = async () => {
    const parsed = parseBv(rawInput);
    if (!parsed) { setPreviewError('请输入有效的 BV 号'); return; }
    const previewInput = rawInput;
    updateDraft(current => ({ ...current, bv: parsed, videoInfo: null }));
    setPreviewLoading(true); setPreviewError('');
    try {
      const info = await getVideoInfo(parsed);
      updateDraft(current => current.rawInput === previewInput ? { ...current, bv: parsed, videoInfo: info } : current);
    } catch {
      setPreviewError('获取视频信息失败');
      updateDraft(current => current.rawInput === previewInput ? { ...current, videoInfo: null } : current);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (bv) onAnalyze(bv, maxComments, delay);
  };

  return (
    <form className="signal-search" onSubmit={handleSubmit}>
      <div className="signal-search__controls">
        <div className="signal-search__field">
          <input type="text" value={rawInput} onChange={e => {
            updateDraft({ rawInput: e.target.value, bv: '', videoInfo: null });
            setPreviewError('');
          }}
            placeholder="B站视频链接或 BV 号" className="search-input" disabled={loading || previewLoading}/>
        </div>
        {!videoInfo && (
          <button type="button" className="signal-search__action signal-search__action--preview" onClick={handlePreview} disabled={loading || previewLoading || !rawInput.trim()}>
            {previewLoading ? '获取中...' : '获取视频信息'}
          </button>
        )}
        {videoInfo && (
          <div className="signal-search__actions">
            <button type="submit" className="signal-search__action signal-search__action--analyze" disabled={loading}>
              {loading ? '分析中...' : '开始分析'}
            </button>
          </div>
        )}
      </div>

      {previewError && (
        <div className="signal-search__alert" role="alert">
          <p className="text-xs">{previewError}</p>
        </div>
      )}

      {videoInfo && (
        <div className="signal-search__preview">
          <span className="panel-status">VIDEO READY</span>
          <div className="signal-search__preview-copy">
            <p className="text-sm font-medium text-primary truncate">{videoInfo.title}</p>
            <p className="text-xs text-secondary">播放 {videoInfo.play.toLocaleString()} &middot; 评论 {(videoInfo?.comment_count ?? 0).toLocaleString()}</p>
          </div>
        </div>
      )}
    </form>
  );
}
