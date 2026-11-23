import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { usePresence } from '../hooks/usePresence';
import { CheckIcon, ChevronDownIcon } from './icons';

const MENU_EXIT_MS = 160;

interface PickerOption {
  id: string | null;
  name: string;
  description?: string;
  reselect?: boolean;
}

interface PickerTab {
  id: string;
  label: string;
  icon: ReactNode;
  title: string;
}

interface TopBarPickerProps {
  kind: 'character' | 'model';
  name: string;
  label: string;
  icon: ReactNode;
  iconKey?: string;
  menuTitle: string;
  options: PickerOption[];
  selectedId: PickerOption['id'] | undefined;
  switching: boolean;
  disabled?: boolean;
  busy?: boolean;
  statusText?: string;
  emptyHint?: string;
  tabs?: { items: PickerTab[]; activeId: string; onChange: (id: string) => void };
  onOpen: () => boolean | void;
  onSelect: (id: PickerOption['id']) => void;
}

export function TopBarPicker({
  kind, name, label, icon, iconKey, menuTitle, options, selectedId, switching, disabled = false,
  busy, statusText, emptyHint, tabs, onOpen, onSelect,
}: TopBarPickerProps) {
  const [open, setOpen] = useState(false);
  const blocked = disabled || switching;
  const expanded = open && !blocked;
  const { mounted, closing } = usePresence(expanded, MENU_EXIT_MS);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const activeTabRef = useRef<HTMLButtonElement>(null);
  const tabListRef = useRef<HTMLDivElement>(null);
  const [tabThumb, setTabThumb] = useState<{ x: number; w: number } | null>(null);
  const menuId = useId();
  const hasOptions = options.length > 0;
  const activeTabId = tabs?.activeId;
  const tabCount = tabs?.items.length ?? 0;
  const setMenuRef = useCallback((node: HTMLDivElement | null) => {
    menuRef.current = node;
    if (node) node.inert = closing;
  }, [closing]);

  useLayoutEffect(() => {
    if (!mounted || !tabCount) {
      setTabThumb(null);
      return;
    }
    const list = tabListRef.current;
    if (!list) return;
    const measure = () => {
      const btn = list.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
      if (btn) setTabThumb({ x: btn.offsetLeft, w: btn.offsetWidth });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(list);
    return () => ro.disconnect();
  }, [mounted, activeTabId, tabCount]);

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

  // 带分类的菜单先聚焦当前页签；角色列表则在异步加载后聚焦当前选项。
  useEffect(() => {
    if (!expanded || !mounted) return;
    const menu = menuRef.current;
    if (!menu) return;
    const target = activeTabRef.current ?? menu.querySelector<HTMLElement>('[role="option"][aria-selected="true"]') ??
      menu.querySelector<HTMLElement>('[role="option"]') ?? menu;
    target.focus();
  }, [expanded, mounted, hasOptions, activeTabId]);

  const toggle = () => {
    if (blocked) return;
    if (expanded) setOpen(false);
    else if (onOpen() !== false) setOpen(true);
  };

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus({ preventScroll: true });
    // Tab 的默认动作在 React 提交关闭动画之前也不能进入出场中的控件。
    if (menuRef.current) menuRef.current.inert = true;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!expanded) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    const menu = menuRef.current;
    const target = e.target as HTMLElement;
    const tab = target.getAttribute('role') === 'tab';
    const items = Array.from(menu?.querySelectorAll<HTMLElement>('[role="option"]') ?? []);
    if (e.key === 'Tab') {
      if (tabs && tab && !e.shiftKey) return;
      if (tabs && e.shiftKey && menu?.contains(target)) {
        e.preventDefault();
        if (tab) close();
        else activeTabRef.current?.focus();
        return;
      }
      close();
      return;
    }
    if (!menu?.contains(target)) return;
    if (tabs && tab && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
      const buttons = Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
      const index = buttons.indexOf(target as HTMLButtonElement);
      const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1 :
        (index + (e.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      e.preventDefault();
      tabs.onChange(tabs.items[next].id);
      buttons[next].focus();
      return;
    }
    if (!items.length || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const index = items.indexOf(target);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 :
      index < 0 ? Math.max(0, items.findIndex((item) => item.getAttribute('aria-selected') === 'true')) :
      (index + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next].focus();
  };

  const renderOptions = () => options.map((option, index) => {
    const selected = option.id === selectedId;
    return (
      <button
        type="button"
        key={option.id === null ? 'default' : `option:${option.id}`}
        role="option"
        aria-selected={selected}
        className={`picker-option${selected ? ' selected' : ''}`}
        tabIndex={tabs && (selected || (selectedId === undefined && index === 0)) ? 0 : -1}
        onClick={() => {
          close();
          if (!selected || option.reselect) onSelect(option.id);
        }}
      >
        <span className="picker-option-text">
          <span className="picker-option-name">{option.name}</span>
          {option.description && <span className="picker-option-desc">{option.description}</span>}
        </span>
        <span className="picker-option-check" aria-hidden="true">{selected && <CheckIcon />}</span>
      </button>
    );
  });

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
        aria-haspopup={tabs ? 'dialog' : 'listbox'}
        aria-expanded={expanded}
        aria-controls={mounted ? menuId : undefined}
        aria-disabled={blocked || undefined}
        aria-label={label}
        title={label}
        onClick={toggle}
      >
        <span className={`picker-pill-icon${iconKey ? ' icon-swap' : ''}`} key={iconKey} aria-hidden="true">{icon}</span>
        <span className="picker-pill-name" key={name}>{name}</span>
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
          role={tabs ? 'dialog' : 'listbox'}
          aria-label={menuTitle}
          tabIndex={-1}
        >
          <div className="picker-menu-title" aria-hidden="true">{menuTitle}</div>
          {tabs ? (
            <>
              <div ref={tabListRef} className="picker-tabs" role="tablist" aria-label={menuTitle}>
                {tabThumb && (
                  <span
                    className="picker-tab-thumb"
                    aria-hidden="true"
                    style={{ transform: `translateX(${tabThumb.x}px)`, width: tabThumb.w }}
                  />
                )}
                {tabs.items.map((item) => {
                  const active = item.id === tabs.activeId;
                  return (
                    <button
                      key={item.id}
                      ref={active ? activeTabRef : undefined}
                      id={`${menuId}-tab-${item.id}`}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      aria-controls={`${menuId}-panel-${item.id}`}
                      title={item.title}
                      tabIndex={active ? 0 : -1}
                      onClick={() => tabs.onChange(item.id)}
                    >
                      <span aria-hidden="true">{item.icon}</span>{item.label}
                    </button>
                  );
                })}
              </div>
              {tabs.items.map((item) => (
                <div
                  key={item.id}
                  className="picker-tab-panel"
                  id={`${menuId}-panel-${item.id}`}
                  role="tabpanel"
                  aria-labelledby={`${menuId}-tab-${item.id}`}
                  hidden={item.id !== tabs.activeId}
                >
                  {item.id === tabs.activeId && (
                    <div className="picker-options" role="listbox" aria-label={item.title}>
                      {renderOptions()}
                    </div>
                  )}
                </div>
              ))}
            </>
          ) : (
            <>
              {renderOptions()}
              {!hasOptions && <div className="picker-menu-hint" role="status">{emptyHint}</div>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
