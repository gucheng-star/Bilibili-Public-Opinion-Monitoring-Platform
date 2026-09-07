export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const PREFERENCE_KEY = 'appearance-theme-preference';
const THEME_CHANGE_EVENT = 'bili:theme-change';
let sessionThemeOverride: ResolvedTheme | null = null;

function hasBrowserEnvironment() {
  return typeof window !== 'undefined' && typeof document !== 'undefined';
}

export function getThemePreference(): ThemePreference {
  if (!hasBrowserEnvironment()) return 'system';
  const value = window.localStorage.getItem(PREFERENCE_KEY);
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system';
}

export function getResolvedTheme(preference = getThemePreference()): ResolvedTheme {
  if (sessionThemeOverride) return sessionThemeOverride;
  if (preference === 'dark') return 'dark';
  if (preference === 'light') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme() {
  if (!hasBrowserEnvironment()) return;
  const preference = getThemePreference();
  const resolved = getResolvedTheme(preference);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = preference;
  document.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT));
}

export function initializeTheme() {
  if (!hasBrowserEnvironment()) return;
  // 旧版顶部按钮曾写入这个键；新版只接受设置中心的明确选择。
  window.localStorage.removeItem('theme');
  applyTheme();
}

export function setThemePreference(preference: ThemePreference) {
  if (!hasBrowserEnvironment()) return;
  window.localStorage.setItem(PREFERENCE_KEY, preference);
  sessionThemeOverride = null;
  applyTheme();
}

export function setTemporaryTheme(theme: ResolvedTheme) {
  if (!hasBrowserEnvironment()) return;
  sessionThemeOverride = theme;
  applyTheme();
}

export function subscribeToThemeChange(listener: () => void) {
  if (!hasBrowserEnvironment()) return () => undefined;
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  const onChange = () => {
    if (!sessionThemeOverride && getThemePreference() === 'system') applyTheme();
    listener();
  };
  document.addEventListener(THEME_CHANGE_EVENT, listener);
  mediaQuery.addEventListener('change', onChange);
  return () => {
    document.removeEventListener(THEME_CHANGE_EVENT, listener);
    mediaQuery.removeEventListener('change', onChange);
  };
}
