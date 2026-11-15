import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useModels } from '../stores/models';
import { usePresence } from '../hooks/usePresence';
import { fetchModels, switchModel } from '../services/actions';
import { CheckIcon, ChevronDownIcon, SparkIcon } from './icons';

const MENU_EXIT_MS = 160;

// 顶栏的模型小岛：显示当前回答用的模型，点开下拉切换。
// 后台没有配置可选模型（或当前账号一个都不可用）时整个不渲染。
export function ModelPicker() {
  const { t } = useTranslation();
  const models = useModels((s) => s.models);
  const current = useModels((s) => s.current);
  const switching = useModels((s) => s.switching);
  const [open, setOpen] = useState(false);
  const { mounted, closing } = usePresence(open, MENU_EXIT_MS);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  // 打开后把焦点放到当前选中的那一项，方向键从这里开始走
  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      const menu = menuRef.current;
      const target =
        menu?.querySelector<HTMLElement>('[aria-selected="true"]') ??
        menu?.querySelector<HTMLElement>('[role="option"]');
      target?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  if (models.length === 0) return null;

  const options = [
    { id: null as string | null, name: t('model.default'), description: t('model.defaultDesc') },
    ...models,
  ];
  const active = options.find((o) => o.id === current) ?? options[0];

  const toggle = () => {
    // 每次打开都向服务端要一次最新列表：后台改了目录或权限时这里能看到
    if (!open) fetchModels();
    setOpen(!open);
  };

  const close = (restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) buttonRef.current?.focus({ preventScroll: true });
  };

  const choose = (id: string | null) => {
    close(true);
    switchModel(id);
  };

  const onMenuKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close(true);
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="option"]') ?? [],
    );
    if (items.length === 0) return;
    e.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    let next = index;
    if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = items.length - 1;
    else if (e.key === 'ArrowDown') next = (index + 1) % items.length;
    else next = (index - 1 + items.length) % items.length;
    items[next].focus({ preventScroll: true });
  };

  return (
    <div className="model-picker" ref={rootRef}>
      <button
        ref={buttonRef}
        className={`model-pill${open ? ' open' : ''}${switching ? ' switching' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('model.pick', { name: active.name })}
        title={t('model.pick', { name: active.name })}
        onClick={toggle}
      >
        <SparkIcon />
        <span className="model-pill-name">{active.name}</span>
        <ChevronDownIcon />
      </button>
      {mounted && (
        <div
          ref={menuRef}
          className={`model-menu${closing ? ' closing' : ''}`}
          role="listbox"
          aria-label={t('model.title')}
          onKeyDown={onMenuKeyDown}
        >
          <div className="model-menu-title">{t('model.title')}</div>
          {options.map((option) => {
            const selected = option.id === active.id;
            return (
              <button
                key={option.id ?? ''}
                role="option"
                aria-selected={selected}
                className={`model-option${selected ? ' selected' : ''}`}
                disabled={switching}
                onClick={() => choose(option.id)}
              >
                <span className="model-option-text">
                  <span className="model-option-name">{option.name}</span>
                  {option.description && (
                    <span className="model-option-desc">{option.description}</span>
                  )}
                </span>
                <span className="model-option-check">{selected && <CheckIcon />}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
