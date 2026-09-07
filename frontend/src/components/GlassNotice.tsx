import type { ReactNode } from 'react';
import './GlassNotice.css';

interface Props {
  title: string;
  children: ReactNode;
  onClear: () => void;
}

/** A reusable, non-blocking notice with an explicit clear action. */
export default function GlassNotice({ title, children, onClear }: Props) {
  return (
    <aside className="glass-notice" role="status" aria-live="polite">
      <div className="glass-notice__content">
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
      <button type="button" className="glass-notice__clear" onClick={onClear} aria-label={`清除提示：${title}`}>清除</button>
    </aside>
  );
}
