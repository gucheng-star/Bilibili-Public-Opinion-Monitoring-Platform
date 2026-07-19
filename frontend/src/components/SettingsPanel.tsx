import { useState, useEffect } from 'react';
import { getSettings, updateSettings } from '../services/api';
import type { AnalysisMode } from '../types';

interface SettingsData {
  has_api_key: boolean;
  api_key_preview: string;
  analysis_mode: AnalysisMode;
}

interface Props {
  maxComments: number;
  onMaxCommentsChange: (v: number) => void;
  delay: number;
  onDelayChange: (v: number) => void;
  mode: AnalysisMode;
  onModeChange: (v: AnalysisMode) => void;
  hasApiKey: boolean;
  onApiKeySaved: () => void;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export default function SettingsPanel({ maxComments, onMaxCommentsChange, delay, onDelayChange, mode, onModeChange, hasApiKey, onApiKeySaved }: Props) {
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [settings, setSettings] = useState<SettingsData | null>(null);

  useEffect(() => { getSettings().then(setSettings).catch(() => {}); }, []);

  const handleSave = async () => {
    if (apiKeyInput.trim()) {
      await updateSettings({ api_key: apiKeyInput.trim(), analysis_mode: mode });
      setApiKeyInput('');
      getSettings().then(setSettings);
      onApiKeySaved();
    }
  };

  return (
    <div className="card" style={{ marginTop: '.75rem', padding: '1rem 1.25rem' }}>
      <div style={{ marginBottom: '1rem', padding: '.75rem', background: 'var(--bg)', borderRadius: '.5rem', border: '1px solid var(--border)' }}>
        <label className="text-xs text-secondary" style={{ display: 'block', marginBottom: '.25rem' }}>百炼 API Key</label>
        <div className="flex items-center gap-2">
          <input type="password" value={apiKeyInput} onChange={e => setApiKeyInput(e.target.value)}
            placeholder={settings?.has_api_key ? settings.api_key_preview : 'sk-...'}
            style={{ flex: 1, padding: '.375rem .5rem', fontSize: '.8125rem', background: 'var(--input-bg)', color: 'var(--text-primary)', border: '1px solid var(--input-border)', borderRadius: '.375rem', outline: 'none' }} />
          <button type="button" onClick={handleSave}
            style={{ padding: '.375rem .75rem', fontSize: '.75rem', fontWeight: 600, background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: '.375rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>保存</button>
        </div>
        {settings?.has_api_key && <p className="text-xs text-muted mt-1">已保存: {settings.api_key_preview}</p>}
      </div>
      <div className="flex items-center gap-6 flex-wrap">
        <div style={{ flex: '1 1 14rem' }}>
          <label className="text-xs text-secondary mb-1" style={{ display: 'block' }}>
            抓取评论总数（每页 20 条，预计 {Math.ceil(maxComments / 20)} 次请求约 {Math.round(Math.ceil(maxComments / 20) * delay)} 秒）
          </label>
          <div className="flex items-center gap-2">
            <input type="range" min="1" max="2000" value={Math.min(maxComments, 2000)}
              onChange={e => onMaxCommentsChange(Number(e.target.value))}
              style={{ flex: 1, accentColor: 'var(--accent)' }} />
            <input type="number" min="1" value={maxComments}
              onChange={e => onMaxCommentsChange(clamp(Number(e.target.value), 1, 99999))}
              style={{ width: '5rem', padding: '.25rem .375rem', fontSize: '.8125rem', textAlign: 'center', background: 'var(--input-bg)', color: 'var(--text-primary)', border: '1px solid var(--input-border)', borderRadius: '.375rem', outline: 'none' }} />
          </div>
        </div>
        <div style={{ flex: '1 1 12rem' }}>
          <label className="text-xs text-secondary mb-1" style={{ display: 'block' }}>请求间隔</label>
          <div className="flex items-center gap-2">
            <input type="range" min="1" max="10" step="0.5" value={delay}
              onChange={e => onDelayChange(Number(e.target.value))}
              style={{ flex: 1, accentColor: 'var(--accent)' }} />
            <input type="number" min="1" max="60" step="0.5" value={delay}
              onChange={e => onDelayChange(clamp(Number(e.target.value), 1, 60))}
              style={{ width: '4.5rem', padding: '.25rem .375rem', fontSize: '.8125rem', textAlign: 'center', background: 'var(--input-bg)', color: 'var(--text-primary)', border: '1px solid var(--input-border)', borderRadius: '.375rem', outline: 'none' }} />
            <span className="text-xs text-muted">秒</span>
          </div>
        </div>
      </div>
      {delay < 2 && (
        <div style={{ marginTop: '.75rem', padding: '.5rem .75rem', background: 'var(--red-soft)', border: '1px solid var(--red)', borderRadius: '.375rem' }}>
          <p className="text-xs" style={{ color: 'var(--red)', lineHeight: 1.5 }}>间隔过短可能触发风控，建议 3 秒以上。</p>
        </div>
      )}
    </div>
  );
}
