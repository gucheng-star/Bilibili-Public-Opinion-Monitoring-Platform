import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import GlassNotice from './GlassNotice';
import { NoticeContext, type NoticeInput } from './NoticeContext';

interface ActiveNotice extends Required<NoticeInput> {
  id: number;
  leaving: boolean;
}

const AUTO_DISMISS_MS = 5000;
const EXIT_ANIMATION_MS = 260;

/** Application-wide, single-slot notification channel for non-blocking feedback. */
export function NoticeProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<ActiveNotice | null>(null);
  const idRef = useRef(0);
  const dismissTimerRef = useRef<number | null>(null);
  const removeTimerRef = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    if (dismissTimerRef.current !== null) window.clearTimeout(dismissTimerRef.current);
    if (removeTimerRef.current !== null) window.clearTimeout(removeTimerRef.current);
    dismissTimerRef.current = null;
    removeTimerRef.current = null;
  }, []);

  const clearNotice = useCallback(() => {
    clearTimers();
    setNotice(null);
  }, [clearTimers]);

  const beginExit = useCallback((id: number) => {
    dismissTimerRef.current = null;
    setNotice(current => current?.id === id ? { ...current, leaving: true } : current);
    removeTimerRef.current = window.setTimeout(() => {
      setNotice(current => current?.id === id ? null : current);
      removeTimerRef.current = null;
    }, EXIT_ANIMATION_MS);
  }, []);

  const showNotice = useCallback((input: NoticeInput) => {
    clearTimers();
    const id = ++idRef.current;
    setNotice({ ...input, tone: input.tone || 'success', id, leaving: false });
    dismissTimerRef.current = window.setTimeout(() => beginExit(id), AUTO_DISMISS_MS);
  }, [beginExit, clearTimers]);

  useEffect(() => clearTimers, [clearTimers]);

  return <NoticeContext.Provider value={{ showNotice, clearNotice }}>
    {children}
    {notice && <GlassNotice title={notice.title} tone={notice.tone} leaving={notice.leaving} onClear={clearNotice}>{notice.message}</GlassNotice>}
  </NoticeContext.Provider>;
}
