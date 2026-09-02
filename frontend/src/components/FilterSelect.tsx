import { useEffect, useId, useRef, useState } from 'react';

export interface FilterSelectOption<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  ariaLabel: string;
  value: T;
  options: readonly FilterSelectOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
}

export default function FilterSelect<T extends string>({
  ariaLabel,
  value,
  options,
  onChange,
  disabled = false,
}: Props<T>) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listboxId = useId();
  const selectedIndex = Math.max(0, options.findIndex(option => option.value === value));
  const selectedOption = options[selectedIndex];

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  useEffect(() => {
    if (open) optionRefs.current[activeIndex]?.focus();
  }, [activeIndex, open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const openAt = (index: number) => {
    setActiveIndex(index);
    setOpen(true);
  };

  const choose = (index: number) => {
    const option = options[index];
    if (!option) return;
    onChange(option.value);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const moveActive = (offset: number) => {
    setActiveIndex(current => (current + offset + options.length) % options.length);
  };

  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      openAt(open ? (activeIndex + 1) % options.length : selectedIndex);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      openAt(open ? (activeIndex - 1 + options.length) % options.length : selectedIndex);
    } else if (event.key === 'Home') {
      event.preventDefault();
      openAt(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      openAt(options.length - 1);
    } else if (open && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      choose(activeIndex);
    }
  };

  const handleOptionKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveActive(1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveActive(-1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      setActiveIndex(options.length - 1);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      choose(index);
    }
  };

  return (
    <div
      ref={rootRef}
      className={`filter-select${open ? ' is-open' : ''}${disabled ? ' is-disabled' : ''}`}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="filter-select__trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        disabled={disabled}
        onClick={() => {
          if (open) setOpen(false);
          else openAt(selectedIndex);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span>{selectedOption?.label ?? ''}</span>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>

      {open && (
        <div id={listboxId} className="filter-select__menu" role="listbox" aria-label={ariaLabel}>
          {options.map((option, index) => (
            <button
              key={option.value}
              ref={node => { optionRefs.current[index] = node; }}
              type="button"
              role="option"
              aria-selected={option.value === value}
              tabIndex={index === activeIndex ? 0 : -1}
              className={`filter-select__option${index === activeIndex ? ' is-active' : ''}`}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(index)}
              onKeyDown={event => handleOptionKeyDown(event, index)}
            >
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
