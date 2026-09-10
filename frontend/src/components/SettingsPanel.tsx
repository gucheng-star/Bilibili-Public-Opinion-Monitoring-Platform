import { useEffect, useState } from 'react';
import { createAgentSnapshot, getLLMModels, getSettings, testLLM, updateSettings } from '../services/api';
import { buildAgentMcpConfig, getDesktopMcpExecutablePath } from '../services/desktop';
import type { AgentSnapshotResponse, LLMProvider, LLMTask, LLMTaskSettings, LLMTaskUpdate, SettingsResponse } from '../types';
import FilterSelect, { type FilterSelectOption } from './FilterSelect';

interface Props {
  onSettingsChanged: (settings: SettingsResponse) => void;
  desktopMode?: boolean;
  onCheckUpdate?: () => void;
  updateChecking?: boolean;
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
  zhipu: { base_url: 'https://open.bigmodel.cn/api/paas/v4/', model: 'glm-4.7-flash', fallback_model: '' },
  custom: { base_url: '', model: '', fallback_model: '' },
};

const PROVIDER_NAMES: Record<LLMProvider, string> = {
  bailian: '阿里百炼',
  deepseek: 'DeepSeek',
  zhipu: '智谱 GLM',
  custom: '自定义兼容接口',
};

const PROVIDER_OPTIONS: readonly FilterSelectOption<LLMProvider>[] = (
  Object.keys(PROVIDER_NAMES) as LLMProvider[]
).map(provider => ({ value: provider, label: PROVIDER_NAMES[provider] }));

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
  const modelOptions: readonly FilterSelectOption<string>[] = models.length
    ? models.map(model => ({ value: model, label: model }))
    : [{ value: '', label: '请先获取模型列表' }];
  const fallbackOptions: readonly FilterSelectOption<string>[] = [
    { value: '', label: '不使用回退模型' },
    ...models.filter(model => model !== editor.model).map(model => ({ value: model, label: model })),
  ];
  const useManualModelInput = editor.provider === 'custom' && !models.length;

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
          <FilterSelect ariaLabel={`${title}供应商`} value={editor.provider} options={PROVIDER_OPTIONS} onChange={setProvider} disabled={busy !== null} />
        </label>
        <label><span>模型</span>
          {useManualModelInput ? (
            <input aria-label={`${title}模型名称`} value={editor.model} onChange={event => {
              const model = event.target.value;
              setEditor(current => ({ ...current, model, fallback_model: current.fallback_model === model ? '' : current.fallback_model }));
            }} placeholder="输入兼容接口的模型名称" disabled={busy !== null} />
          ) : (
            <FilterSelect ariaLabel={`${title}模型`} value={editor.model} options={modelOptions} onChange={model => {
              setEditor(current => ({ ...current, model, fallback_model: current.fallback_model === model ? '' : current.fallback_model }));
            }} disabled={busy !== null || !models.length} />
          )}
        </label>
        <label className="llm-base-url"><span>Base URL</span>
          <input value={editor.base_url} onChange={event => setBaseUrl(event.target.value)} placeholder="https://example.com/v1" disabled={busy !== null} />
        </label>
        <label><span>回退模型 <small>可选</small></span>
          <FilterSelect ariaLabel={`${title}回退模型`} value={editor.fallback_model} options={fallbackOptions} onChange={fallback_model => setEditor(current => ({ ...current, fallback_model }))} disabled={busy !== null || !models.length} />
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
        {storedKeyMatches && <button type="button" className="btn btn-danger llm-clear-key" onClick={clearKey} disabled={busy !== null}>{busy === 'clear' ? '清除中…' : '清除密钥'}</button>}
        {message && <span role="status" className={`llm-config-message ${message.kind}`}>{message.text}</span>}
      </div>
    </section>
  );
}

type AgentSnapshotMessage = { kind: 'ok' | 'error'; text: string };

function formatUtc(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return `${new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium', timeStyle: 'medium', hour12: false, timeZone: 'UTC',
  }).format(parsed)} UTC`;
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('浏览器未授予剪贴板权限，请手动复制配置。');
}

function AgentSnapshotSettings({ desktopMode }: Pick<Props, 'desktopMode'>) {
  const [snapshot, setSnapshot] = useState<AgentSnapshotResponse | null>(null);
  const [executablePath, setExecutablePath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<AgentSnapshotMessage | null>(null);

  const createSnapshot = async () => {
    if (!desktopMode) {
      setMessage({ kind: 'error', text: 'Agent 快照只能在桌面应用中生成；请从已安装的桌面程序打开此页。' });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const created = await createAgentSnapshot();
      setSnapshot(created);
      try {
        const path = await getDesktopMcpExecutablePath();
        setExecutablePath(path);
        setMessage({ kind: 'ok', text: '已生成新的本地静态快照。复制配置后，请在 MCP 客户端中手动更新并重新连接。' });
      } catch {
        setExecutablePath(null);
        setMessage({ kind: 'error', text: '快照已生成，但未能取得当前桌面程序路径；重启桌面应用后再复制配置。' });
      }
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '生成 Agent 快照失败，请稍后重试。' });
    } finally {
      setBusy(false);
    }
  };

  const copyConfig = async () => {
    if (!snapshot || !executablePath) return;
    try {
      await copyText(buildAgentMcpConfig(executablePath, snapshot.database_path));
      setMessage({ kind: 'ok', text: 'JSON 配置已复制。请按所用 MCP 客户端的格式合并；应用不会自动修改任何客户端配置。' });
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '复制配置失败，请手动复制。' });
    }
  };

  const copyGuide = async () => {
    if (!snapshot || !executablePath) return;
    const guide = [
      '1. 将以下 JSON 中的 bili-opinion-readonly 服务条目合并到 MCP 客户端配置。',
      '2. 保留 --mcp-stdio 和 BILI_MCP_DB_PATH；不要填写前端 Token、Cookie 或 API Key。',
      '3. 保存客户端配置后重新连接，再分别验证 initialize、tools/list 和一次只读查询。',
      '4. 生成新快照后，更新 BILI_MCP_DB_PATH 并重新连接；已有会话继续读取旧快照。',
      '',
      buildAgentMcpConfig(executablePath, snapshot.database_path),
    ].join('\n');
    try {
      await copyText(guide);
      setMessage({ kind: 'ok', text: '接入指引已复制。请自行检查和保存客户端配置。' });
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : '复制接入指引失败，请手动复制。' });
    }
  };

  return (
    <section className="agent-snapshot-settings" aria-labelledby="agent-snapshot-title">
      <div className="agent-snapshot-settings__heading">
        <div>
          <span className="settings-eyebrow">AGENT / MCP</span>
          <h3 id="agent-snapshot-title">生成只读 Agent 快照</h3>
          <p>创建一份一致的本地 SQLite 静态副本，供新的只读 MCP 会话使用。生成新快照不会替换正在使用的旧快照。</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={createSnapshot} disabled={busy || !desktopMode}>
          {busy ? '正在生成…' : '生成 Agent 快照'}
        </button>
      </div>
      {!desktopMode && <p className="agent-snapshot-settings__desktop-hint" role="status">当前为浏览器模式。Agent 快照需要桌面应用取得实际主程序路径后才能生成配置。</p>}
      <p className="agent-snapshot-settings__privacy-note">
        连接外部模型后，MCP 返回的统计数据，以及已移除工具级身份标识字段、经过长度截断的评论片段，可能会发送给该模型。Cookie、API Key 与 UID 不在 MCP 工具输出中；快照数据库仍是本地敏感文件。
      </p>
      {message && <p className={`agent-snapshot-settings__message ${message.kind}`} role="status">{message.text}</p>}
      {snapshot && <div className="agent-snapshot-settings__details" aria-label="最新 Agent 快照信息">
        <dl>
          <div><dt>快照 ID</dt><dd><code>{snapshot.snapshot_id}</code></dd></div>
          <div><dt>UTC 创建时间</dt><dd>{formatUtc(snapshot.created_at)}</dd></div>
          <div><dt>数据范围</dt><dd>{snapshot.record_counts.analyses} 个分析 · {snapshot.record_counts.comments} 条评论 · {snapshot.record_counts.events} 个事件</dd></div>
          <div><dt>数据库 SHA-256</dt><dd><code>{snapshot.database_sha256}</code></dd></div>
          <div><dt>契约 / 应用版本</dt><dd>v{snapshot.mcp_contract_version} / {snapshot.application_version}</dd></div>
          <div><dt>数据库</dt><dd className="agent-snapshot-settings__path"><code>{snapshot.database_path}</code></dd></div>
          <div><dt>清单</dt><dd className="agent-snapshot-settings__path"><code>{snapshot.manifest_path}</code></dd></div>
        </dl>
        {executablePath && <div className="agent-snapshot-settings__connect">
          <p><strong>当前桌面主程序</strong><code>{executablePath}</code></p>
          <div className="agent-snapshot-settings__actions">
            <button type="button" className="btn btn-ghost" onClick={copyConfig}>复制 JSON 配置</button>
            <button type="button" className="btn btn-ghost" onClick={copyGuide}>复制接入指引</button>
          </div>
          <p className="agent-snapshot-settings__config-hint">仅复制供你手动粘贴：不会自动写入或覆盖任何 MCP 客户端配置。</p>
        </div>}
      </div>}
    </section>
  );
}

export default function SettingsPanel({ onSettingsChanged, desktopMode = false, onCheckUpdate, updateChecking = false }: Props) {
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
        <LLMTaskEditor task="sentiment" title="情绪分析模型" description="为评论生成十分类情感标签" saved={settings.llm.sentiment} onSaved={handleSaved} />
        <LLMTaskEditor task="summary" title="智能总结模型" description="归纳筛选后的统计与代表观点" saved={settings.llm.summary} onSaved={handleSaved} />
      </div>}
      <AgentSnapshotSettings desktopMode={desktopMode} />
      {desktopMode && <section className="crawl-settings desktop-update-settings">
        <div>
          <label className="text-xs text-secondary mb-1" style={{ display: 'block' }}>便携版更新</label>
          <p className="text-xs text-muted">检查 GitHub Release 中是否有可用的新版本；更新会保留本机数据与配置。</p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onCheckUpdate} disabled={updateChecking}>
          {updateChecking ? '正在检查…' : '检查更新'}
        </button>
      </section>}
    </div>
  );
}
