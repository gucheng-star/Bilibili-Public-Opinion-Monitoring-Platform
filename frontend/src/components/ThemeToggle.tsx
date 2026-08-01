import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';

interface ViewTransitionHandle {
  ready: Promise<void>;
  finished: Promise<void>;
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => ViewTransitionHandle;
};

export default function ThemeToggle() {
  const [dark, setDark] = useState(() => {
    if (typeof document !== 'undefined') {
      const saved = localStorage.getItem('theme');
      if (saved === 'dark' || saved === 'light') return saved === 'dark';
      return document.documentElement.dataset.theme === 'dark' ||
        (!document.documentElement.dataset.theme &&
         window.matchMedia('(prefers-color-scheme: dark)').matches);
    }
    return false;
  });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const animatingRef = useRef(false);
  const [transitioning, setTransitioning] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }, [dark]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      const saved = localStorage.getItem('theme');
      if (!saved) setDark(e.matches);
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const toggle = async () => {
    if (animatingRef.current || !buttonRef.current) return;
    animatingRef.current = true;
    setTransitioning(true);

    const goingDark = !dark;
    const rect = buttonRef.current.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const maxR = Math.hypot(
      Math.max(cx, window.innerWidth - cx),
      Math.max(cy, window.innerHeight - cy),
    );
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const applyTheme = () => {
      document.documentElement.dataset.theme = goingDark ? 'dark' : 'light';
      localStorage.setItem('theme', goingDark ? 'dark' : 'light');
      flushSync(() => setDark(goingDark));
    };

    try {
      if (reduceMotion) {
        applyTheme();
        return;
      }

      const transitionDocument = document as ViewTransitionDocument;
      if (transitionDocument.startViewTransition) {
        const transition = transitionDocument.startViewTransition(applyTheme);
        await transition.ready;
        const pseudoElement = goingDark ? '::view-transition-old(root)' : '::view-transition-new(root)';
        const clipPath = goingDark
          ? [`circle(${maxR}px at ${cx}px ${cy}px)`, `circle(0px at ${cx}px ${cy}px)`]
          : [`circle(0px at ${cx}px ${cy}px)`, `circle(${maxR}px at ${cx}px ${cy}px)`];
        await document.documentElement.animate(
          { clipPath },
          { duration: 560, easing: 'cubic-bezier(.4,0,.2,1)', fill:'forwards', pseudoElement },
        ).finished;
        await transition.finished;
        return;
      }

      const oldBackground = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
      applyTheme();
      const newBackground = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
      const overlay = document.createElement('div');
      const startRadius = goingDark ? maxR : 0;
      const endRadius = goingDark ? 0 : maxR;
      overlay.style.cssText = `position:fixed;inset:0;z-index:9999;pointer-events:none;background:${goingDark ? oldBackground : newBackground};clip-path:circle(${startRadius}px at ${cx}px ${cy}px);`;
      document.body.appendChild(overlay);
      await overlay.animate(
        { clipPath:[`circle(${startRadius}px at ${cx}px ${cy}px)`,`circle(${endRadius}px at ${cx}px ${cy}px)`] },
        { duration:560, easing:'cubic-bezier(.4,0,.2,1)' },
      ).finished;
      overlay.remove();
    } finally {
      animatingRef.current = false;
      setTransitioning(false);
    }
  };

  return (
    <button
      ref={buttonRef}
      className="theme-toggle"
      onClick={toggle}
      disabled={transitioning}
      aria-label={dark ? '切换为浅色模式' : '切换为深色模式'}
      title={dark ? '切换为浅色模式' : '切换为深色模式'}
    >
      {dark ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
          <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
        </svg>
      )}
    </button>
  );
}
