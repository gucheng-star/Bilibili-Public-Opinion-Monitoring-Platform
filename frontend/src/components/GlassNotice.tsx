import type { ReactNode } from 'react';
import './GlassNotice.css';

interface Props {
  title: string;
  children: ReactNode;
  onClear: () => void;
  tone?: 'success' | 'error';
  leaving?: boolean;
}

/** A reusable, non-blocking notice with an explicit clear action. */
export default function GlassNotice({ title, children, onClear, tone = 'success', leaving = false }: Props) {
  return (
    <aside className={`glass-notice glass-notice--${tone}${leaving ? ' glass-notice--leaving' : ''}`} role="status" aria-live="polite">
      <div className="glass-notice__content">
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
      <button type="button" className="glass-notice__clear" onClick={onClear} aria-label={`清除提示：${title}`}>清除</button>
    </aside>
  );
}
