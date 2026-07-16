/** Check if dark mode is active */
export function isDarkMode(): boolean {
  if (typeof document === 'undefined') return false;
  const theme = document.documentElement.dataset.theme;
  if (theme === 'dark') return true;
  if (theme === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Get chart tooltip style based on theme */
export function chartTooltip() {
  const dark = isDarkMode();
  return {
    backgroundColor: dark ? '#1A2030' : '#FFFFFF',
    borderColor: dark ? 'rgba(148,163,184,.12)' : 'rgba(0,0,0,.08)',
    textStyle: { color: dark ? '#E2E8F0' : '#1A1A2E', fontSize: 12 },
  };
}

/** Get chart text color */
export function chartTextColor() { return isDarkMode() ? '#94A3B8' : '#6B7280'; }