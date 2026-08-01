import { useEffect, useState } from 'react';
import { getLLMModels, getSettings, testLLM, updateSettings } from '../services/api';
import type { LLMProvider, LLMTask, LLMTaskSettings, LLMTaskUpdate, SettingsResponse } from '../types';

interface Props {
  maxComments: number;
  onMaxCommentsChange: (value: number) => void;
  delay: number;
  onDelayChange: (value: number) => void;
  onSettingsChanged: (settings: SettingsResponse) => void;
}

interface EditorState {
  provider: LLMProvider;
  base_url: string;
  model: string;
  fallback_model: string;
  api_key: string;
}

const PROVIDER_DEFAULTS: Record<LLMProvider, Pick<EditorState, 'base_url' | 'model' | 'fallback_model'>> = {
  bailian: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen3.6-plus', fallback_model: '' },
  deepseek: { base_url: 'https://api.deepseek.com', model: 'deepseek-v4-flash', fallback_model: '' },
  custom: { base_url: '', model: '', fallback_model: '' },
};

const PROVIDER_NAMES: Record<LLMProvider, string> = {
  bailian: '阿里百炼',
  deepseek: 'DeepSeek',
  custom: '自定义兼容接口',
};

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);
const toEditor = (settings: LLMTaskSettings): EditorState => ({
  provider: settings.provider,
  base_url: settings.base_url,
  model: settings.model,
  fallback_model: settings.fallback_model || '',
  api_key: '',
});
const currentModelOptions = (settings: LLMTaskSettings) => (
  [...new Set([settings.model, settings.fallback_model].filter(Boolean))]
);

function LLMTaskEditor({ task, title, description, saved, onSaved }: {
  task: LLMTask;
  title: string;
  description: string;
  saved: LLMTaskSettings;
  onSaved: (settings: SettingsResponse) => void;
}) {
  const [editor, setEditor] = useState<EditorState>(() => toEditor(saved));
  const [models, setModels] = useState<string[]>(() => currentModelOptions(saved));
  const [busy, setBusy] = useState<'models' | 'save' | 'test' | 'clear' | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const storedKeyMatches = saved.provider === editor.provider && saved.has_api_key;
  const keyReady = storedKeyMatches || Boolean(editor.api_key.trim());
  const keyStatus = editor.api_key.trim() ? '已输入新密钥' : storedKeyMatches ? '密钥就绪' : '未配置密钥';

  useEffect(() => {
    setEditor(toEditor(saved));
    setModels(currentModelOptions(saved));
  }, [saved]);

  const setProvider = (provider: LLMProvider) => {
    setEditor({ provider, api_key: '', ...PROVIDER_DEFAULTS[provider], model: '', fallback_model: '' });
    setModels([]);
    setMessage(null);
  };
  const setBaseUrl = (base_url: string) => {
    setEditor(current => ({ ...current, base_url, model: '', fallback_model: '' }));
    setModels([]);
    setMessage(null);
  };
  const payload = (): LLMTaskUpdate => ({
    provider: editor.provider,
    base_url: editor.base_url.trim(),
    model: editor.model.trim(),
    fallback_model: editor.fallback_model.trim(),
    ...(editor.api_key.trim() ? { api_key: editor.api_key.trim() } : {}),
  });
  const fetchModels = async () => {
    setBusy('models'); setMessage(null);
    try {
      const result = await getLLMModels(task, payload());
      const nextModel = result.models.includes(editor.model) ? editor.model : result.models[0];
      const nextFallback = result.models.includes(editor.fallback_model) && editor.fallback_model !== nextModel
        ? editor.fallback_model
        : '';
      setModels(result.models);
      setEditor(current => ({ ...current, model: nextModel, fallback_model: nextFallback }));
      setMessage({ kind: 'ok', text: `已获取 ${result.models.length} 个可用模型` });
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '获取模型列表失败' });
    } finally { setBusy(null); }
  };
  const save = async () => {
    setBusy('save'); setMessage(null);
    try {
      const settings = await updateSettings({ llm: { [task]: payload() } });
      setEditor(current => ({ ...current, api_key: '' }));
      onSaved(settings);
      setMessage({ kind: 'ok', text: '配置已保存' });
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '保存失败' });
    } finally { setBusy(null); }
  };
  const test = async () => {
    setBusy('test'); setMessage(null);
    try {
      const result = await testLLM(task, payload());
      setMessage({ kind: 'ok', text: `连接成功 · ${result.model} · ${result.latency_ms} ms` });
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '连接失败' });
    } finally { setBusy(null); }
  };
  const clearKey = async () => {
    setBusy('clear'); setMessage(null);
    try {
      const settings = await updateSettings({ llm: { [task]: { ...payload(), clear_api_key: true } } });
      setEditor(current => ({ ...current, api_key: '' }));
      onSaved(settings);
      setMessage({ kind: 'ok', text: '密钥已清除' });
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '清除失败' });
    } finally { setBusy(null); }
  };

  return (
    <section className="llm-config-block" aria-labelledby={`llm-${task}-title`}>
      <div className="llm-config-heading">
        <div>
          <h3 id={`llm-${task}-title`}>{title}</h3>
          <p>{description}</p>
        </div>
        <span className={`llm-key-status ${keyReady ? 'ready' : ''}`}>
          {keyStatus}
        </span>
      </div>
      <div className="llm-config-grid">
        <label><span>供应商</span>
          <select value={editor.provider} onChange={event => setProvider(event.target.value as LLMProvider)} className="select-sm" disabled={busy !== null}>
            {(Object.keys(PROVIDER_NAMES) as LLMProvider[]).map(provider => (
              <option key={provider} value={provider}>{PROVIDER_NAMES[provider]}</option>
            ))}
          </select>
        </label>
        <label><span>模型</span>
          <select value={editor.model} onChange={event => {
            const model = event.target.value;
            setEditor(current => ({ ...current, model, fallback_model: current.fallback_model === model ? '' : current.fallback_model }));
          }} disabled={busy !== null || !models.length}>
            {!models.length && <option value="">请先获取模型列表</option>}
            {models.map(model => <option key={model} value={model}>{model}</option>)}
          </select>
        </label>
        <label className="llm-base-url"><span>Base URL</span>
          <input value={editor.base_url} onChange={event => setBaseUrl(event.target.value)} placeholder="https://example.com/v1" disabled={busy !== null} />
        </label>
        <label><span>回退模型 <small>可选</small></span>
          <select value={editor.fallback_model} onChange={event => setEditor({ ...editor, fallback_model: event.target.value })} disabled={busy !== null || !models.length}>
            <option value="">不使用回退模型</option>
            {models.filter(model => model !== editor.model).map(model => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </label>
        <label className="llm-api-key"><span>API Key</span>
          <input type="password" value={editor.api_key} autoComplete="off"
            onChange={event => setEditor({ ...editor, api_key: event.target.value })}
            disabled={busy !== null}
            placeholder={storedKeyMatches ? saved.api_key_preview : 'sk-...'} />
        </label>
      </div>
      <div className="llm-config-actions">
        <button type="button" className="btn btn-ghost llm-fetch-models" onClick={fetchModels} disabled={busy !== null}>{busy === 'models' ? '获取中…' : '获取模型列表'}</button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy !== null || !editor.model}>{busy === 'save' ? '保存中…' : '保存配置'}</button>
        <button type="button" className="btn btn-ghost" onClick={test} disabled={busy !== null || !editor.model}>{busy === 'test' ? '测试中…' : '测试连接'}</button>
        {storedKeyMatches && <button type="button" className="btn btn-ghost llm-clear-key" onClick={clearKey} disabled={busy !== null}>{busy === 'clear' ? '清除中…' : '清除密钥'}</button>}
        {message && <span role="status" className={`llm-config-message ${message.kind}`}>{message.text}</span>}
      </div>
    </section>
  );
}

export default function SettingsPanel({ maxComments, onMaxCommentsChange, delay, onDelayChange, onSettingsChanged }: Props) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  useEffect(() => { getSettings().then(setSettings).catch(() => {}); }, []);
  const handleSaved = (next: SettingsResponse) => { setSettings(next); onSettingsChanged(next); };

  return (
    <div className="card settings-panel">
      <div className="settings-intro">
        <div><span className="settings-eyebrow">模型路由</span><h2>为两项 AI 工作分别选择模型</h2></div>
        <p>密钥只保存在本机后端，页面仅显示掩码。调用模型可能产生费用。</p>
      </div>
      {settings && <div className="llm-task-layout">
        <LLMTaskEditor task="sentiment" title="情绪分析模型" description="为评论生成八分类情绪标签" saved={settings.llm.sentiment} onSaved={handleSaved} />
        <LLMTaskEditor task="summary" title="智能总结模型" description="归纳筛选后的统计与代表观点" saved={settings.llm.summary} onSaved={handleSaved} />
      </div>}
      <section className="crawl-settings">
        <div style={{ flex: '1 1 14rem' }}>
          <label className="text-xs text-secondary mb-1" style={{ display: 'block' }}>抓取评论总数（每页 20 条，预计 {Math.ceil(maxComments / 20)} 次请求约 {Math.round(Math.ceil(maxComments / 20) * delay)} 秒）</label>
          <div className="flex items-center gap-2">
            <input type="range" min="1" max="2000" value={Math.min(maxComments, 2000)} onChange={event => onMaxCommentsChange(Number(event.target.value))} style={{ flex: 1, accentColor: 'var(--accent)' }} />
            <input type="number" min="1" value={maxComments} onChange={event => onMaxCommentsChange(clamp(Number(event.target.value), 1, 99999))} className="settings-number-input" />
          </div>
        </div>
        <div style={{ flex: '1 1 12rem' }}>
          <label className="text-xs text-secondary mb-1" style={{ display: 'block' }}>请求间隔</label>
          <div className="flex items-center gap-2">
            <input type="range" min="1" max="10" step="0.5" value={delay} onChange={event => onDelayChange(Number(event.target.value))} style={{ flex: 1, accentColor: 'var(--accent)' }} />
            <input type="number" min="1" max="60" step="0.5" value={delay} onChange={event => onDelayChange(clamp(Number(event.target.value), 1, 60))} className="settings-number-input" />
            <span className="text-xs text-muted">秒</span>
          </div>
        </div>
      </section>
      {delay < 2 && <div className="settings-warning">间隔过短可能触发 B 站风控，建议设置为 3 秒以上。</div>}
    </div>
  );
}
