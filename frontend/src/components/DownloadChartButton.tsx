import ReactECharts from 'echarts-for-react';
import { useCallback, useMemo } from 'react';

interface Props {
  /** 单个或多个 ECharts 实例 ref */
  echartRefs: React.RefObject<ReactECharts | null> | React.RefObject<ReactECharts | null>[];
  label?: string;
}

/**
 * 图表下载按钮：取 ECharts 实例的截图并触发下载为 PNG。
 */
export default function DownloadChartButton({ echartRefs, label = '下载' }: Props) {
  const refs = useMemo(
    () => (Array.isArray(echartRefs) ? echartRefs : [echartRefs]),
    [echartRefs],
  );

  const handleDownload = useCallback(async () => {
    const dataUrls: string[] = [];
    for (const ref of refs) {
      const instance = ref.current?.getEchartsInstance();
      if (!instance) continue;
      const url = instance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: 'transparent' });
      dataUrls.push(url);
    }
    if (!dataUrls.length) return;

    // 单图直接下载
    if (dataUrls.length === 1) {
      const link = document.createElement('a');
      link.download = `chart_${Date.now()}.png`;
      link.href = dataUrls[0];
      link.click();
      return;
    }

    // 多图合并为一张
    const loadImg = (src: string): Promise<HTMLImageElement> =>
      new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = src;
      });

    const imgs = await Promise.all(dataUrls.map(u => loadImg(u)));
    const maxW = Math.max(...imgs.map(i => i.width));
    const totalH = imgs.reduce((s, i) => s + i.height + 8, -8);

    const canvas = document.createElement('canvas');
    canvas.width = maxW;
    canvas.height = totalH;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--bg').trim() || '#fff';
    ctx.fillRect(0, 0, maxW, totalH);

    let y = 0;
    for (const img of imgs) {
      ctx.drawImage(img, 0, y, img.width, img.height);
      y += img.height + 8;
    }

    const link = document.createElement('a');
    link.download = `chart_${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }, [refs]);

  return (
    <button
      type="button"
      onClick={handleDownload}
      title={label}
      style={{
        padding: '.25rem .5rem',
        fontSize: '.6875rem',
        fontWeight: 500,
        background: 'transparent',
        color: 'var(--text-secondary)',
        border: '1px solid var(--border)',
        borderRadius: '.375rem',
        cursor: 'pointer',
        lineHeight: 1.5,
        transition: 'all .15s ease',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '.25rem',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'var(--accent-soft)';
        e.currentTarget.style.color = 'var(--accent)';
        e.currentTarget.style.borderColor = 'var(--accent)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'transparent';
        e.currentTarget.style.color = 'var(--text-secondary)';
        e.currentTarget.style.borderColor = 'var(--border)';
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      {label}
    </button>
  );
}
