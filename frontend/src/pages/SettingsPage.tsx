import { useState } from 'react';
import { Link } from 'react-router-dom';
import SettingsPanel from '../components/SettingsPanel';
import type { SettingsResponse } from '../types';
import './SettingsPage.css';

export interface SettingsPageProps {
  maxComments: number;
  onMaxCommentsChange: (value: number) => void;
  delay: number;
  onDelayChange: (value: number) => void;
  onSettingsChanged: (settings: SettingsResponse) => void;
  desktopMode?: boolean;
  onCheckUpdate?: () => void;
  onLogout: () => Promise<void>;
}

export default function SettingsPage({
  maxComments,
  onMaxCommentsChange,
  delay,
  onDelayChange,
  onSettingsChanged,
  desktopMode = false,
  onCheckUpdate,
  onLogout,
}: SettingsPageProps) {
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const handleLogout = async () => {
    setLogoutBusy(true);
    setLogoutError(null);
    try {
      await onLogout();
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : '退出登录失败，请稍后重试。');
    } finally {
      setLogoutBusy(false);
    }
  };

  return (
    <main className="settings-page">
      <Link className="ui-secondary-action settings-page__exit" to="/" aria-label="退出设置并返回分析工作台">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="m14.5 5-7 7 7 7M8 12h9" />
        </svg>
        退出设置
      </Link>
      <div className="settings-page__header">
        <div>
          <span className="settings-page__eyebrow">视频信号观测台</span>
          <h1>设置中心</h1>
          <p>管理抓取节奏与智能分析模型配置。所有设置和敏感信息仅保留在本机。</p>
        </div>
      </div>

      <SettingsPanel
        maxComments={maxComments}
        onMaxCommentsChange={onMaxCommentsChange}
        delay={delay}
        onDelayChange={onDelayChange}
        onSettingsChanged={onSettingsChanged}
        desktopMode={desktopMode}
        onCheckUpdate={onCheckUpdate}
      />

      <section className="settings-page__danger-zone" aria-labelledby="settings-logout-title">
        <div>
          <span className="settings-page__danger-eyebrow">账户操作</span>
          <h2 id="settings-logout-title">退出登录</h2>
          <p>将清除本机保存的当前登录凭据，不会删除已有分析记录和模型配置。</p>
        </div>
        <div className="settings-page__danger-actions">
          <button type="button" className="settings-page__logout" onClick={() => { void handleLogout(); }} disabled={logoutBusy}>
            {logoutBusy ? '正在退出…' : '退出当前账号'}
          </button>
          {logoutError && <p className="settings-page__logout-error" role="alert">{logoutError}</p>}
        </div>
      </section>
    </main>
  );
}
