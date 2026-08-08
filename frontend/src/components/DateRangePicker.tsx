import { useEffect, useMemo, useRef, useState } from 'react';

interface Props {
  dateFrom: string;
  dateTo: string;
  onChange: (range: { dateFrom: string; dateTo: string }) => void;
}

type TimePreset = 'all' | 'last7' | 'last30' | 'thisMonth' | 'lastMonth' | 'custom';

const PRESETS: Array<{ value: TimePreset; label: string }> = [
  { value: 'all', label: '全部时间' },
  { value: 'last7', label: '近 7 天' },
  { value: 'last30', label: '近 30 天' },
  { value: 'thisMonth', label: '本月' },
  { value: 'lastMonth', label: '上月' },
  { value: 'custom', label: '自定义' },
];

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
const startOfMonth = (date: Date) => new Date(date.getFullYear(), date.getMonth(), 1);
const addDays = (date: Date, days: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
const addMonths = (date: Date, months: number) => new Date(date.getFullYear(), date.getMonth() + months, 1);
const toIsoDate = (date: Date) => [
  date.getFullYear(),
  String(date.getMonth() + 1).padStart(2, '0'),
  String(date.getDate()).padStart(2, '0'),
].join('-');
const parseIsoDate = (value: string) => {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
};

function presetRange(preset: TimePreset, today: Date) {
  const currentMonth = startOfMonth(today);
  const previousMonth = addMonths(currentMonth, -1);
  switch (preset) {
    case 'all': return { dateFrom: '', dateTo: '' };
    case 'last7': return { dateFrom: toIsoDate(addDays(today, -6)), dateTo: toIsoDate(today) };
    case 'last30': return { dateFrom: toIsoDate(addDays(today, -29)), dateTo: toIsoDate(today) };
    case 'thisMonth': return { dateFrom: toIsoDate(currentMonth), dateTo: toIsoDate(today) };
    case 'lastMonth': return {
      dateFrom: toIsoDate(previousMonth),
      dateTo: toIsoDate(addDays(currentMonth, -1)),
    };
    default: return null;
  }
}

function detectPreset(dateFrom: string, dateTo: string, today: Date): TimePreset {
  for (const preset of PRESETS) {
    if (preset.value === 'custom') continue;
    const range = presetRange(preset.value, today);
    if (range?.dateFrom === dateFrom && range.dateTo === dateTo) return preset.value;
  }
  return 'custom';
}

function calendarAnchor(dateFrom: string, today: Date) {
  const latestAnchor = addMonths(startOfMonth(today), -1);
  if (!dateFrom) return latestAnchor;
  const selectedMonth = startOfMonth(parseIsoDate(dateFrom));
  return selectedMonth > latestAnchor ? latestAnchor : selectedMonth;
}

function CalendarMonth({
  month, dateFrom, dateTo, today, previous, next, nextDisabled, onSelect,
}: {
  month: Date;
  dateFrom: string;
  dateTo: string;
  today: Date;
  previous?: () => void;
  next?: () => void;
  nextDisabled?: boolean;
  onSelect: (date: string) => void;
}) {
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const leading = month.getDay();
  const cells = [
    ...Array.from({ length: leading }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ];

  return (
    <section className="calendar-month" aria-label={`${month.getFullYear()}年${month.getMonth() + 1}月`}>
      <header className="calendar-month-header">
        {previous ? <button type="button" onClick={previous} aria-label="查看上个月">‹</button> : <span />}
        <strong>{month.getFullYear()}年{month.getMonth() + 1}月</strong>
        {next ? <button type="button" onClick={next} disabled={nextDisabled} aria-label="查看下个月">›</button> : <span />}
      </header>
      <div className="calendar-weekdays" aria-hidden="true">
        {WEEKDAYS.map(day => <span key={day}>{day}</span>)}
      </div>
      <div className="calendar-days">
        {cells.map((day, index) => {
          if (day === null) return <span className="calendar-day-empty" key={`empty-${index}`} />;
          const date = new Date(month.getFullYear(), month.getMonth(), day);
          const iso = toIsoDate(date);
          const disabled = date > today;
          const endpoint = iso === dateFrom || iso === dateTo;
          const inRange = Boolean(dateFrom && dateTo && iso > dateFrom && iso < dateTo);
          return (
            <button
              type="button"
              key={iso}
              disabled={disabled}
              className={`${endpoint ? 'range-endpoint' : ''} ${inRange ? 'in-range' : ''}`}
              aria-label={`选择 ${month.getFullYear()}年${month.getMonth() + 1}月${day}日`}
              onClick={() => onSelect(iso)}
            >
              {day}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default function DateRangePicker({ dateFrom, dateTo, onChange }: Props) {
  const today = useMemo(() => startOfDay(new Date()), []);
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const [anchor, setAnchor] = useState(() => calendarAnchor(dateFrom, today));
  const activePreset = detectPreset(dateFrom, dateTo, today);
  const displayedPreset = customMode ? 'custom' : activePreset;
  const activeLabel = PRESETS.find(item => item.value === displayedPreset)?.label || '自定义';
  const latestAnchor = addMonths(startOfMonth(today), -1);

  useEffect(() => {
    if (open) setAnchor(calendarAnchor(dateFrom, today));
  }, [open, dateFrom, today]);

  useEffect(() => {
    if (activePreset !== 'custom') setCustomMode(false);
  }, [activePreset]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const choosePreset = (preset: TimePreset) => {
    if (preset === 'custom') {
      setCustomMode(true);
      return;
    }
    const range = presetRange(preset, today);
    if (range) onChange(range);
    setCustomMode(false);
    setOpen(false);
  };

  const chooseDate = (date: string) => {
    setCustomMode(true);
    if (!dateFrom || dateTo) {
      onChange({ dateFrom: date, dateTo: '' });
      return;
    }
    const range = date < dateFrom
      ? { dateFrom: date, dateTo: dateFrom }
      : { dateFrom, dateTo: date };
    onChange(range);
    setOpen(false);
  };

  return (
    <div className={`date-range-picker${open ? ' is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className={`date-range-trigger ${open ? 'open' : ''}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen(current => !current)}
      >
        <span>时间维度</span>
        <strong>{activeLabel}</strong>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="date-range-popover" role="dialog" aria-label="选择时间范围">
          <nav className="date-range-presets" aria-label="快捷时间范围">
            {PRESETS.map(preset => (
              <button
                type="button"
                key={preset.value}
                className={displayedPreset === preset.value ? 'active' : ''}
                onClick={() => choosePreset(preset.value)}
              >
                <span>{preset.label}</span>
                {displayedPreset === preset.value && <span aria-hidden="true">✓</span>}
              </button>
            ))}
          </nav>
          <div className="date-range-calendars">
            <CalendarMonth
              month={anchor}
              dateFrom={dateFrom}
              dateTo={dateTo}
              today={today}
              previous={() => setAnchor(current => addMonths(current, -1))}
              onSelect={chooseDate}
            />
            <CalendarMonth
              month={addMonths(anchor, 1)}
              dateFrom={dateFrom}
              dateTo={dateTo}
              today={today}
              next={() => setAnchor(current => addMonths(current, 1))}
              nextDisabled={anchor >= latestAnchor}
              onSelect={chooseDate}
            />
          </div>
        </div>
      )}
    </div>
  );
}
