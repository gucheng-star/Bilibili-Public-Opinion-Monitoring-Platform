import { useState } from 'react';
import { Link } from 'react-router-dom';
import SettingsPanel from '../components/SettingsPanel';
import type { SettingsResponse } from '../types';
import { getThemePreference, setThemePreference, type ThemePreference } from '../theme';
import './SettingsPage.css';

export interface SettingsPageProps {
  onSettingsChanged: (settings: SettingsResponse) => void;
  desktopMode?: boolean;
  onCheckUpdate?: () => void;
  onLogout: () => Promise<void>;
}

const themeChoices: Array<{ value: ThemePreference; label: string; description: string }> = [
  { value: 'light', label: '浅色', description: '始终使用浅色界面' },
  { value: 'dark', label: '暗色', description: '始终使用暗色界面' },
  { value: 'system', label: '跟随系统', description: '随系统外观自动切换' },
];

function ThemeChoiceIcon({ theme }: { theme: ThemePreference }) {
  if (theme === 'light') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></svg>;
  if (theme === 'dark') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.7 15.4A8.6 8.6 0 1 1 8.6 3.3 6.8 6.8 0 0 0 20.7 15.4Z" /></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4" /></svg>;
}

export default function SettingsPage({
  onSettingsChanged,
  desktopMode = false,
  onCheckUpdate,
  onLogout,
}: SettingsPageProps) {
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [themePreference, setThemePreferenceState] = useState<ThemePreference>(getThemePreference);

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

  const chooseTheme = (preference: ThemePreference) => {
    setThemePreferenceState(preference);
    setThemePreference(preference);
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
          <p>管理账号、应用与智能分析模型配置。所有设置和敏感信息仅保留在本机。</p>
        </div>
      </div>

      <section className="settings-page__appearance" aria-labelledby="appearance-theme-title">
        <div className="settings-page__appearance-copy">
          <span className="settings-page__appearance-eyebrow">界面外观</span>
          <h2 id="appearance-theme-title">外观主题</h2>
          <p>选择应用启动时的默认外观，立即生效。</p>
        </div>
        <div className="settings-page__theme-choices" role="radiogroup" aria-label="默认外观主题">
          {themeChoices.map(choice => <button key={choice.value} type="button" role="radio" aria-checked={themePreference === choice.value} className={`settings-page__theme-choice settings-page__theme-choice--${choice.value}${themePreference === choice.value ? ' is-active' : ''}`} onClick={() => chooseTheme(choice.value)} title={choice.description}>
            <ThemeChoiceIcon theme={choice.value} />
            <span>{choice.label}</span>
          </button>)}
        </div>
      </section>

      <SettingsPanel
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
