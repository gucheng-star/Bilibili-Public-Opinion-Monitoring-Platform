import { useEffect, useState } from 'react';

export default function ThemeToggle() {
  const [dark, setDark] = useState(() => {
    if (typeof document !== 'undefined') {
      return document.documentElement.dataset.theme === 'dark' ||
        (!document.documentElement.dataset.theme &&
         window.matchMedia('(prefers-color-scheme: dark)').matches);
    }
    return false;
  });

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

  const toggle = () => {
    const goingDark = !dark;
    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    const maxR = Math.hypot(cx, cy);

    // 1. 先切换 data-theme（页面立刻变为新主题）
    setDark(goingDark);

    // 2. 创建 overlay，颜色 = 旧主题背景色
    // 旧主题的颜色作为遮罩"被推开"
    const oldBg = goingDark ? '#F6F3F0' : '#070B14';
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position: fixed;
      inset: 0;
      z-index: 9999;
      pointer-events: none;
      background: ${oldBg};
      clip-path: circle(${maxR}px at ${cx}px ${cy}px);
    `;
    document.body.appendChild(overlay);

    // 3. 下一帧启动动画：从全屏圆形收缩到圆心点
    requestAnimationFrame(() => {
      overlay.style.transition = 'clip-path .5s cubic-bezier(.4,0,.2,1)';
      overlay.style.clipPath = `circle(0 at ${cx}px ${cy}px)`;
    });

    overlay.addEventListener('transitionend', () => overlay.remove());
  };

  return (
    <button
      className="theme-toggle"
      onClick={toggle}
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
