import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { usePresence } from '../hooks/usePresence';
import { CheckIcon, ChevronDownIcon } from './icons';

const MENU_EXIT_MS = 160;

interface PickerOption {
  id: string | null;
  name: string;
  description?: string;
}

interface TopBarPickerProps {
  kind: 'character' | 'model';
  name: string;
  label: string;
  icon: ReactNode;
  menuTitle: string;
  options: PickerOption[];
  selectedId: PickerOption['id'] | undefined;
  switching: boolean;
  disabled?: boolean;
  busy?: boolean;
  statusText?: string;
  emptyHint?: string;
  onOpen: () => boolean | void;
  onSelect: (id: PickerOption['id']) => void;
}

export function TopBarPicker({
  kind, name, label, icon, menuTitle, options, selectedId, switching, disabled = false,
  busy, statusText, emptyHint, onOpen, onSelect,
}: TopBarPickerProps) {
  const [open, setOpen] = useState(false);
  const blocked = disabled || switching;
  const expanded = open && !blocked;
  const { mounted, closing } = usePresence(expanded, MENU_EXIT_MS);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();
  const hasOptions = options.length > 0;
  const setMenuRef = useCallback((node: HTMLDivElement | null) => {
    menuRef.current = node;
    if (node) node.inert = closing;
  }, [closing]);

  useEffect(() => {
    if (!blocked || !open) return;
    if (menuRef.current?.contains(document.activeElement)) {
      buttonRef.current?.focus({ preventScroll: true });
    }
    setOpen(false);
  }, [blocked, open]);

  useEffect(() => {
    if (!expanded) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !e.composedPath().includes(rootRef.current)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [expanded]);

  // 角色列表可能在打开后才返回；有选项时再把焦点从面板移到当前选项。
  useEffect(() => {
    if (!expanded || !mounted) return;
    const menu = menuRef.current;
    if (!menu) return;
    const target = menu.querySelector<HTMLElement>('[aria-selected="true"]') ??
      menu.querySelector<HTMLElement>('[role="option"]') ?? menu;
    target.focus();
  }, [expanded, mounted, hasOptions]);

  const toggle = () => {
    if (blocked) return;
    if (expanded) setOpen(false);
    else if (onOpen() !== false) setOpen(true);
  };

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus({ preventScroll: true });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!expanded) return;
    if (e.key === 'Escape' || e.key === 'Tab') {
      // Tab 从触发按钮继续走，不遍历已关闭菜单里的选项。
      if (e.key === 'Escape') e.preventDefault();
      close();
      return;
    }
    if (!menuRef.current?.contains(e.target as Node)) return;
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
    const items = Array.from(menuRef.current.querySelectorAll<HTMLElement>('[role="option"]'));
    if (!items.length) return;
    e.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    let next = 0;
    if (e.key === 'End') next = items.length - 1;
    else if (e.key === 'ArrowDown') next = (index + 1) % items.length;
    else if (e.key === 'ArrowUp') next = (Math.max(index, 0) - 1 + items.length) % items.length;
    items[next].focus();
  };

  return (
    <div
      className={`topbar-picker ${kind}-picker`}
      ref={rootRef}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
      onKeyDown={onKeyDown}
    >
      <button
        type="button"
        ref={buttonRef}
        className={`picker-pill${busy ? ' busy' : ''}${switching ? ' switching' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={expanded}
        aria-controls={mounted ? menuId : undefined}
        aria-disabled={blocked || undefined}
        aria-label={label}
        title={label}
        onClick={toggle}
      >
        <span className="picker-pill-icon" aria-hidden="true">{icon}</span>
        <span className="picker-pill-name">{name}</span>
        <span className="topbar-status" aria-live="polite">
          {statusText && <span className="topbar-status-text" key={statusText}>{statusText}</span>}
        </span>
        <span className="picker-pill-chevron" aria-hidden="true"><ChevronDownIcon /></span>
      </button>
      {mounted && (
        <div
          ref={setMenuRef}
          id={menuId}
          className={`picker-menu ${kind}-menu${closing ? ' closing' : ''}`}
          role="listbox"
          aria-label={menuTitle}
          tabIndex={-1}
        >
          <div className="picker-menu-title" aria-hidden="true">{menuTitle}</div>
          {options.map((option) => {
            const selected = option.id === selectedId;
            return (
              <button
                type="button"
                key={option.id ?? ''}
                role="option"
                aria-selected={selected}
                className={`picker-option${selected ? ' selected' : ''}`}
                tabIndex={-1}
                onClick={() => {
                  close();
                  if (!selected) onSelect(option.id);
                }}
              >
                <span className="picker-option-text">
                  <span className="picker-option-name">{option.name}</span>
                  {option.description && <span className="picker-option-desc">{option.description}</span>}
                </span>
                <span className="picker-option-check" aria-hidden="true">{selected && <CheckIcon />}</span>
              </button>
            );
          })}
          {!hasOptions && <div className="picker-menu-hint" role="status">{emptyHint}</div>}
        </div>
      )}
    </div>
  );
}
