import { useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
}

interface Props<T extends string> {
  value: T;
  options: SegmentedOption<T>[];
  label: string;
  onChange: (value: T, origin: HTMLElement) => void;
}

// 少量互斥选项用分段控件代替原生 <select>：原生下拉的弹出层是系统样式，
// 在玻璃面板里格格不入。滑块跟随选中项测量位置，radiogroup 语义 + 方向键切换。
export function Segmented<T extends string>({ value, options, label, onChange }: Props<T>) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null);
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const measure = () => {
      const btn = root.querySelectorAll<HTMLElement>('.seg-opt')[index];
      if (btn) setThumb({ x: btn.offsetLeft, w: btn.offsetWidth });
    };
    measure();
    // 字体加载/语言切换会改变宽度
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => ro.disconnect();
  }, [index, options]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    let next = index;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % options.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp')
      next = (index - 1 + options.length) % options.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = options.length - 1;
    else return;
    e.preventDefault();
    const btn = rootRef.current?.querySelectorAll<HTMLElement>('.seg-opt')[next];
    if (!btn) return;
    btn.focus();
    onChange(options[next].value, btn);
  };

  return (
    <div ref={rootRef} className="segmented" role="radiogroup" aria-label={label} onKeyDown={onKeyDown}>
      {thumb && (
        <span
          className="seg-thumb"
          aria-hidden
          style={{ transform: `translateX(${thumb.x}px)`, width: thumb.w }}
        />
      )}
      {options.map((o, i) => {
        const active = i === index;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            className={`seg-opt${active ? ' active' : ''}`}
            onClick={(e) => onChange(o.value, e.currentTarget)}
          >
            {o.icon}
            <span>{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}
