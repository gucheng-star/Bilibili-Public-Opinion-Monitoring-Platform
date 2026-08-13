import type { ReactNode } from 'react';
import './DataPanels.css';

interface Props {
  current: number;
  total: number;
  statusText: string;
  ariaLabel: string;
  title?: string;
  detail?: string;
  action?: ReactNode;
  variant?: 'card' | 'workspace';
}

export default function AnalysisProgress({
  current,
  total,
  statusText,
  ariaLabel,
  title = '分析进度',
  detail,
  action,
  variant = 'card',
}: Props) {
  const safeTotal = Math.max(0, total);
  const safeCurrent = Math.max(0, current);
  const progressCurrent = Math.min(safeCurrent, safeTotal);
  const percentage = safeTotal > 0 ? Math.round((progressCurrent / safeTotal) * 100) : 0;

  return (
    <section className={`analysis-progress analysis-progress--${variant}`} aria-live="polite" aria-atomic="true">
      <div className="analysis-progress__eyebrow">{title}</div>
      <div className="analysis-progress__summary">
        <strong>{progressCurrent} / {safeTotal}</strong>
        <span>{percentage}%</span>
      </div>
      <div
        className="analysis-progress__track"
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={safeTotal}
        aria-valuenow={progressCurrent}
        aria-valuetext={`${progressCurrent} / ${safeTotal}，${percentage}%`}
      >
        <div className="analysis-progress__bar" style={{ width: `${percentage}%` }} />
      </div>
      <p>{statusText || '正在准备分析…'}</p>
      {detail && <small>{detail}</small>}
      {action && <div className="analysis-progress__action">{action}</div>}
    </section>
  );
}
