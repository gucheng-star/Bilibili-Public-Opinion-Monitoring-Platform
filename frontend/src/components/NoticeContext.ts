import { createContext, useContext } from 'react';

export type NoticeTone = 'success' | 'error';

export interface NoticeInput {
  title: string;
  message: string;
  tone?: NoticeTone;
}

interface NoticeContextValue {
  showNotice: (notice: NoticeInput) => void;
  clearNotice: () => void;
}

export const NoticeContext = createContext<NoticeContextValue | null>(null);

export function useNotice(): NoticeContextValue {
  const context = useContext(NoticeContext);
  if (!context) throw new Error('useNotice 必须在 NoticeProvider 内使用');
  return context;
}
