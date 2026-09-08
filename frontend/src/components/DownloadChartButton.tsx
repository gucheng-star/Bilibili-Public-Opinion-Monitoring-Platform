import type { RefObject } from 'react';
import ReactECharts from 'echarts-for-react';
import { useCallback, useState } from 'react';
import { useNotice } from './NoticeContext';
import { savePngDataUrl } from '../utils/fileSave';

interface Props {
  /** One ECharts instance maps to exactly one PNG file. */
  echartRef: RefObject<ReactECharts | null>;
  label?: string;
  suggestedName?: string;
}

/** Exports a single chart through the shared save flow without compositing charts. */
export default function DownloadChartButton({ echartRef, label = '导出图片', suggestedName }: Props) {
  const [saving, setSaving] = useState(false);
  const { showNotice } = useNotice();

  const handleDownload = useCallback(async () => {
    if (saving) return;
    const instance = echartRef.current?.getEchartsInstance();
    if (!instance) {
      showNotice({ title: '图片导出失败', message: '图表尚未准备完成，请稍后重试。', tone: 'error' });
      return;
    }

    setSaving(true);
    try {
      const dataUrl = instance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: 'transparent' });
      const saved = await savePngDataUrl(dataUrl, suggestedName || `chart-${Date.now()}.png`);
      if (!saved) return;
      showNotice({
        title: 'PNG 导出完成',
        message: saved.path ? `保存成功：${saved.path}` : '保存成功。',
        tone: 'success',
      });
    } catch {
      showNotice({ title: '图片导出失败', message: '保存失败，请检查目标位置权限、可用空间及文件占用后重试。', tone: 'error' });
    } finally {
      setSaving(false);
    }
  }, [echartRef, saving, showNotice, suggestedName]);

  return <button
      type="button"
      className="ui-secondary-action chart-download-button"
      onClick={() => { void handleDownload(); }}
      title={label}
      disabled={saving}
      style={{
        padding: '.25rem .5rem',
        fontSize: '.6875rem',
        fontWeight: 500,
        borderRadius: '.375rem',
        cursor: saving ? 'wait' : 'pointer',
        lineHeight: 1.5,
        display: 'inline-flex',
        alignItems: 'center',
        gap: '.25rem',
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      {saving ? '正在保存…' : label}
    </button>;
}
