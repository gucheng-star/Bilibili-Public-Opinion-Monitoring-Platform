import { useEffect, useId, useRef, useState } from 'react';
import FilterSelect, { type FilterSelectOption } from './FilterSelect';
import { buildOpacityFamily } from '../utils/wordCloudColors';

export type WordCloudColorMode = 'default' | 'single' | 'family' | 'custom';
export type WordCloudFontFamily = 'system' | 'microsoft-yahei' | 'simsun' | 'simhei' | 'kaiti';

const COLOR_MODE_OPTIONS: readonly FilterSelectOption<WordCloudColorMode>[] = [
  { value: 'default', label: '默认多色' },
  { value: 'single', label: '单色' },
  { value: 'family', label: '家族多色' },
  { value: 'custom', label: '自定义调色板' },
];

const FONT_FAMILY_OPTIONS: readonly FilterSelectOption<WordCloudFontFamily>[] = [
  { value: 'system', label: '系统默认' },
  { value: 'microsoft-yahei', label: '微软雅黑' },
  { value: 'simsun', label: '宋体' },
  { value: 'simhei', label: '黑体' },
  { value: 'kaiti', label: '楷体' },
];

interface BoundedNumberInputProps {
  label: string;
  value: number;
  min: number;
  max: number;
  invalid: boolean;
  onCommit: (value: number) => void;
}

function BoundedNumberInput({ label, value, min, max, invalid, onCommit }: BoundedNumberInputProps) {
  const [draft, setDraft] = useState(String(value));

  useEffect(() => setDraft(String(value)), [value]);

  const commit = () => {
    const parsed = Number(draft);
    const next = draft.trim() && Number.isFinite(parsed)
      ? Math.max(min, Math.min(max, Math.round(parsed)))
      : value;
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };

  return (
    <label>{label}<input
      type="number"
      min={min}
      max={max}
      inputMode="numeric"
      value={draft}
      aria-invalid={invalid}
      onChange={event => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={event => {
        if (event.key === 'Enter') event.currentTarget.blur();
        if (event.key === 'Escape') {
          setDraft(String(value));
          event.currentTarget.blur();
        }
      }}
    /></label>
  );
}

interface Props {
  maskEnabled: boolean;
  canEnableMask: boolean;
  onMaskEnabledChange: (enabled: boolean) => void;
  sourcePreviewUrl: string | null;
  maskPreviewUrl: string | null;
  threshold: number;
  onThresholdChange: (value: number) => void;
  inverted: boolean;
  onInvertedChange: (value: boolean) => void;
  processing: boolean;
  message: string | null;
  drawableRatio: number | null;
  onSelectFile: (file: File) => void;
  onRemoveMask: () => void;
  sourceImageVisible: boolean;
  onSourceImageVisibleChange: (visible: boolean) => void;
  sourceImageOpacity: number;
  onSourceImageOpacityChange: (opacity: number) => void;
  colorMode: WordCloudColorMode;
  onColorModeChange: (mode: WordCloudColorMode) => void;
  singleColor: string;
  onSingleColorChange: (color: string) => void;
  palette: string[];
  onPaletteChange: (palette: string[]) => void;
  familyColor: string;
  onFamilyColorChange: (color: string) => void;
  familyMinOpacity: number;
  onFamilyMinOpacityChange: (opacity: number) => void;
  minFontSize: number;
  maxFontSize: number;
  onMinFontSizeChange: (value: number) => void;
  onMaxFontSizeChange: (value: number) => void;
  fontFamily: WordCloudFontFamily;
  onFontFamilyChange: (font: WordCloudFontFamily) => void;
  onReset: () => void;
}

export default function WordCloudStylePanel({
  maskEnabled, canEnableMask, onMaskEnabledChange,
  sourcePreviewUrl, maskPreviewUrl, threshold, onThresholdChange, inverted, onInvertedChange,
  processing, message, drawableRatio, onSelectFile, onRemoveMask,
  sourceImageVisible, onSourceImageVisibleChange, sourceImageOpacity, onSourceImageOpacityChange,
  colorMode, onColorModeChange, singleColor, onSingleColorChange, palette, onPaletteChange,
  familyColor, onFamilyColorChange, familyMinOpacity, onFamilyMinOpacityChange,
  minFontSize, maxFontSize, onMinFontSizeChange, onMaxFontSizeChange,
  fontFamily, onFontFamilyChange, onReset,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const tabId = useId();
  const [activeTab, setActiveTab] = useState<'basic' | 'mask'>('basic');
  const fontSizeError = minFontSize >= maxFontSize;
  const minFontSizeMax = Math.min(40, maxFontSize - 1);
  const maxFontSizeMin = Math.max(24, minFontSize + 1);
  const familyPreview = buildOpacityFamily(familyColor, familyMinOpacity);

  const updatePalette = (index: number, color: string) => {
    const next = [...palette];
    next[index] = color;
    onPaletteChange(next);
  };

  return (
    <section className="wordcloud-style" aria-label="词云样式">
      <div className="wordcloud-style__tabs" role="tablist" aria-label="词云样式分类">
        <button id={`${tabId}-basic-tab`} type="button" role="tab" aria-selected={activeTab === 'basic'} aria-controls={`${tabId}-basic-panel`} onClick={() => setActiveTab('basic')}>基础样式</button>
        <button id={`${tabId}-mask-tab`} type="button" role="tab" aria-selected={activeTab === 'mask'} aria-controls={`${tabId}-mask-panel`} onClick={() => setActiveTab('mask')}>轮廓蒙版</button>
      </div>
      {activeTab === 'mask' && <div id={`${tabId}-mask-panel`} className="wordcloud-style__tab-panel" role="tabpanel" aria-labelledby={`${tabId}-mask-tab`}>
        <div className="wordcloud-style__section">
          <div className="wordcloud-style__section-header">
            <div><strong>轮廓蒙版</strong><small>图片仅在本机内存处理，不会上传或保存。</small></div>
            <label className="wordcloud-style__switch"><input type="checkbox" aria-label="启用轮廓蒙版" checked={maskEnabled} disabled={!canEnableMask} onChange={event => onMaskEnabledChange(event.target.checked)} /><span>{maskEnabled ? '已启用' : '未启用'}</span></label>
          </div>
          <div className="wordcloud-style__mask-actions">
            <input ref={inputRef} className="wordcloud-style__file-input" type="file" accept="image/jpeg,image/png,image/webp" aria-hidden="true" tabIndex={-1} onChange={event => {
              const file = event.target.files?.[0];
              if (file) onSelectFile(file);
              event.currentTarget.value = '';
            }} />
            <button type="button" className="wordcloud-style__button" onClick={() => inputRef.current?.click()}>{sourcePreviewUrl ? '更换图片' : '选择图片'}</button>
            {sourcePreviewUrl && <button type="button" className="wordcloud-style__button wordcloud-style__button--danger" onClick={onRemoveMask}>移除蒙版</button>}
          </div>
          {processing && <p className="wordcloud-style__notice" role="status">正在本地处理图片…</p>}
          {sourcePreviewUrl && <>
            <div className="wordcloud-style__previews">
              <figure><img src={sourcePreviewUrl} alt="原图缩略图" /><figcaption>原图</figcaption></figure>
              <figure>{maskPreviewUrl ? <img src={maskPreviewUrl} alt="词云蒙版预览，黑色为词语区域" /> : <div className="wordcloud-style__preview-placeholder">处理中</div>}<figcaption>词语区域预览</figcaption></figure>
            </div>
            <label className="wordcloud-style__range"><span>阈值 <b>{threshold}</b></span><input type="range" min="0" max="255" value={threshold} onChange={event => onThresholdChange(Number(event.target.value))} /></label>
            <label className="wordcloud-style__check"><input type="checkbox" checked={inverted} onChange={event => onInvertedChange(event.target.checked)} />反转词语区域</label>
            {drawableRatio !== null && <p className="wordcloud-style__area">预计词语区域：{Math.round(drawableRatio * 100)}%</p>}
            <div className="wordcloud-style__source-overlay">
              <label className="wordcloud-style__check"><input type="checkbox" checked={sourceImageVisible} onChange={event => onSourceImageVisibleChange(event.target.checked)} />在词云中叠加原图</label>
              {sourceImageVisible && <label className="wordcloud-style__range"><span>原图透明度 <b>{Math.round(sourceImageOpacity * 100)}%</b></span><input type="range" min="0" max="80" value={Math.round(sourceImageOpacity * 100)} onChange={event => onSourceImageOpacityChange(Number(event.target.value) / 100)} /></label>}
              <small>原图位于词语下方，下载图片时也会保留。</small>
            </div>
          </>}
          {message && <p className="wordcloud-style__message" role="status">{message}</p>}
        </div>
      </div>}
      {activeTab === 'basic' && <div id={`${tabId}-basic-panel`} className="wordcloud-style__tab-panel" role="tabpanel" aria-labelledby={`${tabId}-basic-tab`}>
        <div className="wordcloud-style__section wordcloud-style__grid">
          <label>颜色方案<FilterSelect ariaLabel="颜色方案" value={colorMode} options={COLOR_MODE_OPTIONS} onChange={onColorModeChange} /></label>
          {colorMode === 'single' && <label>单色<input type="color" value={singleColor} onChange={event => onSingleColorChange(event.target.value)} /></label>}
          {colorMode === 'family' && <div className="wordcloud-style__family">
            <label>家族基色<input type="color" value={familyColor} onChange={event => onFamilyColorChange(event.target.value)} /></label>
            <label className="wordcloud-style__range"><span>最低透明度 <b>{Math.round(familyMinOpacity * 100)}%</b></span><input type="range" min="10" max="90" value={Math.round(familyMinOpacity * 100)} onChange={event => onFamilyMinOpacityChange(Number(event.target.value) / 100)} /></label>
            <div className="wordcloud-style__family-preview" aria-label="家族多色色板预览">{familyPreview.map((color, index) => <span key={color} style={{ background: color }} title={`透明度 ${Math.round((familyMinOpacity + (1 - familyMinOpacity) * index / Math.max(1, familyPreview.length - 1)) * 100)}%`} />)}</div>
          </div>}
          {colorMode === 'custom' && <div className="wordcloud-style__palette"><span>调色板</span><div>{palette.map((color, index) => <input key={`palette-${index}`} aria-label={`调色板颜色 ${index + 1}`} type="color" value={color} onChange={event => updatePalette(index, event.target.value)} />)}<button type="button" aria-label="增加调色板颜色" disabled={palette.length >= 8} onClick={() => onPaletteChange([...palette, '#2563EB'])}>+</button><button type="button" aria-label="减少调色板颜色" disabled={palette.length <= 3} onClick={() => onPaletteChange(palette.slice(0, -1))}>−</button></div></div>}
          <BoundedNumberInput label="最小字号" value={minFontSize} min={8} max={minFontSizeMax} invalid={fontSizeError} onCommit={value => onMinFontSizeChange(Math.min(value, maxFontSize - 1))} />
          <BoundedNumberInput label="最大字号" value={maxFontSize} min={maxFontSizeMin} max={100} invalid={fontSizeError} onCommit={value => onMaxFontSizeChange(Math.max(value, minFontSize + 1))} />
          <label>字体<FilterSelect ariaLabel="字体" value={fontFamily} options={FONT_FAMILY_OPTIONS} onChange={onFontFamilyChange} /></label>
          {fontSizeError && <p className="wordcloud-style__message" role="alert">最小字号必须小于最大字号。</p>}
        </div>
      </div>}
      <button type="button" className="wordcloud-style__reset" onClick={onReset}>恢复默认样式</button>
    </section>
  );
}
