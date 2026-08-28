import { memo, useEffect, useMemo, useRef, useState } from 'react';
import 'echarts-wordcloud';
import ReactECharts from 'echarts-for-react';
import type { KeywordItem } from '../types';
import { isDarkMode } from '../utils';
import { getContainRect, type ImageSize } from '../utils/wordCloudMask';
import { buildOpacityFamily } from '../utils/wordCloudColors';
import DownloadChartButton from './DownloadChartButton';
import WordCloudStylePanel, { type WordCloudColorMode, type WordCloudFontFamily } from './WordCloudStylePanel';
import { useWordCloudMask } from '../hooks/useWordCloudMask';
import './WordCloudCard.css';

interface Props {
  keywords: KeywordItem[];
  className?: string;
  status?: 'ready' | 'loading' | 'error';
  scopeKey?: string;
}

const DEFAULT_PALETTE = ['#FB7299', '#2563EB', '#059669', '#D97706', '#7C3AED'];
const FONT_FAMILIES: Record<WordCloudFontFamily, string> = {
  system: '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif',
  'microsoft-yahei': '"Microsoft YaHei","微软雅黑",sans-serif',
  simsun: 'SimSun,"宋体",serif',
  simhei: 'SimHei,"黑体",sans-serif',
  kaiti: 'KaiTi,"楷体",serif',
};

const STYLE_UPDATE_DEBOUNCE_MS = 350;

function useDebouncedValue<T>(value: T, delay: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [delay, value]);
  return debounced;
}

function stableColor(word: string, colors: string[]) {
  let hash = 0;
  for (let index = 0; index < word.length; index += 1) hash = (hash * 31 + word.charCodeAt(index)) | 0;
  return colors[(hash >>> 0) % colors.length];
}

function WordCloudCard({ keywords, className, status = 'ready', scopeKey = 'default' }: Props) {
  const [dark, setDark] = useState(isDarkMode);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [styleExpanded, setStyleExpanded] = useState(false);
  const [maskEnabled, setMaskEnabled] = useState(false);
  const [colorMode, setColorMode] = useState<WordCloudColorMode>('default');
  const [singleColor, setSingleColor] = useState('#FB7299');
  const [customPalette, setCustomPalette] = useState(DEFAULT_PALETTE);
  const [familyColor, setFamilyColor] = useState('#FB7299');
  const [familyMinOpacity, setFamilyMinOpacity] = useState(0.3);
  const [minFontSize, setMinFontSize] = useState(10);
  const [maxFontSize, setMaxFontSize] = useState(56);
  const [fontFamily, setFontFamily] = useState<WordCloudFontFamily>('system');
  const [sourceImageVisible, setSourceImageVisible] = useState(false);
  const [sourceImageOpacity, setSourceImageOpacity] = useState(0.25);
  const [chartSize, setChartSize] = useState<ImageSize | null>(null);
  const [pendingMaskVersion, setPendingMaskVersion] = useState<number | null>(null);
  const chartRef = useRef<ReactECharts | null>(null);
  const chartAreaRef = useRef<HTMLDivElement | null>(null);
  const mask = useWordCloudMask(chartSize);
  const clearMask = mask.removeMask;

  // Theme changes happen outside this component's props. Listen locally so
  // memoization can safely ignore unrelated parent updates such as LLM polling.
  useEffect(() => {
    const syncTheme = () => setDark(isDarkMode());
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const observer = new MutationObserver(syncTheme);
    mediaQuery.addEventListener('change', syncTheme);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => {
      mediaQuery.removeEventListener('change', syncTheme);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const target = chartAreaRef.current;
    if (!target) return;
    const syncSize = (width: number, height: number) => {
      const next = { width: Math.round(width), height: Math.round(height) };
      if (!next.width || !next.height) return;
      setChartSize(current => current?.width === next.width && current.height === next.height ? current : next);
    };
    syncSize(target.clientWidth, target.clientHeight);
    const observer = new ResizeObserver(entries => {
      const entry = entries[0];
      if (entry) syncSize(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setMaskEnabled(false);
    setSourceImageVisible(false);
    setPendingMaskVersion(null);
    clearMask();
  }, [clearMask, scopeKey]);

  useEffect(() => {
    if (pendingMaskVersion !== null && mask.appliedVersion === pendingMaskVersion) {
      setMaskEnabled(true);
      setPendingMaskVersion(null);
    }
  }, [mask.appliedVersion, pendingMaskVersion]);

  const activeKeywords = useMemo(
    () => keywords.filter(k => !excluded.has(k.word)).slice(0, 200),
    [keywords, excluded]
  );

  const toggleWord = (word: string) => {
    setExcluded(prev => {
      const next = new Set(prev);
      if (next.has(word)) next.delete(word);
      else next.add(word);
      return next;
    });
  };

  const defaultColors = useMemo(() => dark
    ? ['#FB7299','#38BDF8','#34D399','#FBBF24','#A78BFA','#F87171','#FB923C','#22D3EE','#C084FC']
    : ['#FB7299','#2563EB','#059669','#D97706','#7C3AED','#DC2626','#EA580C','#0891B2','#9333EA'], [dark]);

  const renderedSingleColor = useDebouncedValue(singleColor, STYLE_UPDATE_DEBOUNCE_MS);
  const renderedCustomPalette = useDebouncedValue(customPalette, STYLE_UPDATE_DEBOUNCE_MS);
  const renderedFamilyColor = useDebouncedValue(familyColor, STYLE_UPDATE_DEBOUNCE_MS);
  const renderedFamilyMinOpacity = useDebouncedValue(familyMinOpacity, STYLE_UPDATE_DEBOUNCE_MS);
  const renderedSourceImageOpacity = useDebouncedValue(sourceImageOpacity, STYLE_UPDATE_DEBOUNCE_MS);
  const colors = useMemo(() => {
    if (colorMode === 'single') return [renderedSingleColor];
    if (colorMode === 'custom') return renderedCustomPalette;
    if (colorMode === 'family') return buildOpacityFamily(renderedFamilyColor, renderedFamilyMinOpacity);
    return defaultColors;
  }, [colorMode, defaultColors, renderedCustomPalette, renderedFamilyColor, renderedFamilyMinOpacity, renderedSingleColor]);
  const validFontRange = minFontSize < maxFontSize;
  const activeMask = maskEnabled ? mask.appliedMask : null;

  const resetStyle = () => {
    setMaskEnabled(false);
    setColorMode('default');
    setSingleColor('#FB7299');
    setCustomPalette(DEFAULT_PALETTE);
    setFamilyColor('#FB7299');
    setFamilyMinOpacity(0.3);
    setMinFontSize(10);
    setMaxFontSize(56);
    setFontFamily('system');
    setSourceImageVisible(false);
    setSourceImageOpacity(0.25);
    mask.resetMask();
  };

  const removeMask = () => {
    setMaskEnabled(false);
    setSourceImageVisible(false);
    mask.removeMask();
  };

  const sourceGraphic = useMemo(() => {
    if (!sourceImageVisible || !mask.sourcePreviewUrl || !mask.sourceSize || !chartSize) return [];
    const seriesSize = { width: chartSize.width * 0.95, height: chartSize.height * 0.95 };
    const rect = getContainRect(mask.sourceSize, seriesSize);
    return [{
      type: 'image',
      silent: true,
      z: -1,
      style: {
        image: mask.sourcePreviewUrl,
        x: rect.x + chartSize.width * 0.025,
        y: rect.y + chartSize.height * 0.025,
        width: rect.width,
        height: rect.height,
        opacity: renderedSourceImageOpacity,
      },
    }];
  }, [chartSize, mask.sourcePreviewUrl, mask.sourceSize, renderedSourceImageOpacity, sourceImageVisible]);

  const cloudOption = useMemo(() => ({
    tooltip: { show: true, formatter: '{b}: {c} \u6b21' },
    graphic: sourceGraphic,
    series: [{
      type: 'wordCloud',
      // The plugin still uses shape while searching mask pixels; square is neutral here.
      shape: activeMask ? 'square' : 'circle',
      maskImage: activeMask ?? undefined,
      left: 'center', top: 'center',
      width: '95%', height: '95%',
      sizeRange: validFontRange ? [minFontSize, maxFontSize] : [10, 56],
      rotationRange: [-45, 45],
      rotationStep: 15,
      gridSize: 6,
      drawOutOfBound: false,
      // Animated word placement finishes after ECharts' finished event and can truncate exports.
      layoutAnimation: false,
      keepAspect: Boolean(activeMask),
      textStyle: {
        fontFamily: FONT_FAMILIES[fontFamily],
        fontWeight: 'normal',
        color: (params: { name?: string }) => stableColor(params.name ?? '', colors),
      },
      emphasis: {
        focus: 'self',
        textStyle: { textShadowBlur: 10, textShadowColor: dark ? 'rgba(251,114,153,.4)' : 'rgba(251,114,153,.3)' },
      },
      data: activeKeywords.map(k => ({ name: k.word, value: k.count })),
    }],
  }), [activeKeywords, activeMask, colors, dark, fontFamily, maxFontSize, minFontSize, sourceGraphic, validFontRange]);

  const emptyText = status === 'loading' ? '正在按当前筛选重新统计关键词…'
    : status === 'error' ? '当前筛选的关键词加载失败，请重新应用筛选。'
      : activeKeywords.length === 0 && keywords.length ? '已全部排除' : '暂无关键词';

  return (
    <div className={"card" + (className ? " " + className : "")}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-secondary" style={{letterSpacing:'.05em'}}>{"\u8bcd\u4e91"}</h3>
        {keywords.length > 0 && <DownloadChartButton echartRefs={chartRef} />}
      </div>
      {keywords.length > 0 && <WordCloudStylePanel
        expanded={styleExpanded} onExpandedChange={setStyleExpanded}
        maskEnabled={maskEnabled} canEnableMask={mask.canEnableMask} onMaskEnabledChange={setMaskEnabled}
        sourcePreviewUrl={mask.sourcePreviewUrl} maskPreviewUrl={mask.maskPreviewUrl}
        threshold={mask.threshold} onThresholdChange={mask.setThreshold}
        inverted={mask.inverted} onInvertedChange={mask.setInverted}
        processing={mask.status !== 'idle'} message={mask.message} drawableRatio={mask.drawableRatio}
        onSelectFile={file => { void mask.selectFile(file).then(version => { if (version) setPendingMaskVersion(version); }); }}
        onRemoveMask={removeMask}
        sourceImageVisible={sourceImageVisible} onSourceImageVisibleChange={setSourceImageVisible}
        sourceImageOpacity={sourceImageOpacity} onSourceImageOpacityChange={setSourceImageOpacity}
        colorMode={colorMode} onColorModeChange={setColorMode}
        singleColor={singleColor} onSingleColorChange={setSingleColor}
        palette={customPalette} onPaletteChange={setCustomPalette}
        familyColor={familyColor} onFamilyColorChange={setFamilyColor}
        familyMinOpacity={familyMinOpacity} onFamilyMinOpacityChange={setFamilyMinOpacity}
        minFontSize={minFontSize} maxFontSize={maxFontSize}
        onMinFontSizeChange={setMinFontSize}
        onMaxFontSizeChange={setMaxFontSize}
        fontFamily={fontFamily} onFontFamilyChange={setFontFamily}
        onReset={resetStyle}
      />}
      <div className="wordcloud-card__layout">
        <div className="wordcloud-card__chart" ref={chartAreaRef}>
          {!keywords.length || activeKeywords.length === 0 || status !== 'ready' ? (
            <div className="flex items-center justify-center h-full text-muted text-sm" role={status === 'ready' ? undefined : 'status'}>{emptyText}</div>
          ) : (
            <ReactECharts
              ref={chartRef}
              option={cloudOption}
              notMerge
              style={{height:'300px',width:'100%'}}
            />
          )}
        </div>
        {keywords.length > 0 && <div className="wordcloud-card__keywords">
          <div className="text-xs text-muted mb-2" style={{fontWeight:500}}>
            {"\u8bcd\u9891\u5217\u8868"} ({keywords.length})
          </div>
          <div style={{display:'flex',flexDirection:'column',gap:'.25rem'}}>
            {keywords.map((k, i) => {
              const isExcluded = excluded.has(k.word);
              return (
                <button
                  key={k.word + "-" + i}
                  onClick={() => toggleWord(k.word)}
                  title={isExcluded ? "\u70b9\u51fb\u52a0\u5165\u8bcd\u4e91" : "\u70b9\u51fb\u6392\u9664"}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '.2rem .375rem', fontSize: '.6875rem',
                    borderRadius: '.25rem', cursor: 'pointer',
                    background: isExcluded ? 'var(--border)' : 'var(--accent-soft)',
                    color: isExcluded ? 'var(--text-muted)' : 'var(--text-primary)',
                    border: isExcluded ? '1px solid var(--border)' : '1px solid var(--border-accent)',
                    transition: 'all .12s ease',
                    textAlign: 'left',
                    width: '100%',
                    textDecoration: isExcluded ? 'line-through' : 'none',
                  }}
                >
                  <span style={{
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
                  }}>{k.word}</span>
                  <span style={{
                    marginLeft: '.5rem', fontSize: '.625rem',
                    color: isExcluded ? 'var(--text-muted)' : 'var(--text-secondary)',
                    flexShrink: 0,
                  }}>{k.count}</span>
                </button>
              );
            })}
          </div>
        </div>}
      </div>
    </div>
  );
}

export default memo(WordCloudCard);
