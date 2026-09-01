import { useEffect, useRef, type ReactNode } from 'react';
import './StyleDrawer.css';

interface Props {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export default function StyleDrawer({ open, onClose, children }: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      onCloseRef.current();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (!open) return null;

  return (
    <aside id="wordcloud-style-drawer" className="style-drawer" role="dialog" aria-modal="false" aria-label="词云样式设置">
      <div className="style-drawer__header">
        <h2>词云样式设置</h2>
        <button ref={closeButtonRef} type="button" aria-label="关闭词云样式设置" onClick={onClose}>关闭</button>
      </div>
      <div className="style-drawer__content">{children}</div>
    </aside>
  );
}
