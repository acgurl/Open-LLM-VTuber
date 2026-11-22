import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchConfigs, switchConfig } from '../services/actions';
import { useConnection } from '../stores/connection';
import { useSettings } from '../stores/settings';
import { CheckIcon, ChevronDownIcon } from './icons';

const DOT_CLASS: Record<string, string> = {
  online: 'dot online',
  connecting: 'dot pending',
  reconnecting: 'dot pending',
  boot: 'dot pending',
  unauthorized: 'dot error',
  failed: 'dot error',
};

export function CharacterPicker() {
  const { t } = useTranslation();
  const status = useConnection((s) => s.status);
  const confName = useConnection((s) => s.confName);
  const statusText = useConnection((s) => s.statusText);
  const busy = useConnection((s) => s.busy);
  const configs = useSettings((s) => s.configs);
  const configFile = useSettings((s) => s.configFile);
  const switching = useSettings((s) => s.switching);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const name = confName || t('app.title');
  const ready = status === 'online' && Boolean(confName) && !switching;
  const expanded = open && ready;

  useEffect(() => {
    if (!ready) setOpen(false);
  }, [ready]);

  useEffect(() => {
    if (!expanded) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [expanded]);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  // 服务端只回角色名；同名时优先标记本次连接中确认切到的文件。
  const currentFile =
    configs?.find((c) => c.filename === configFile && c.name === confName)?.filename ??
    configs?.find((c) => c.name === confName)?.filename;
  const nameCounts = new Map<string, number>();
  for (const config of configs ?? []) {
    nameCounts.set(config.name, (nameCounts.get(config.name) ?? 0) + 1);
  }

  return (
    <div
      ref={rootRef}
      className="character-picker"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(e) => {
        if (expanded && e.key === 'Escape') {
          e.preventDefault();
          close();
        }
      }}
    >
      <button
        type="button"
        ref={triggerRef}
        className={`topbar-center${busy ? ' busy' : ''}`}
        aria-disabled={!ready}
        aria-expanded={expanded}
        aria-controls={expanded ? menuId : undefined}
        aria-label={switching ? `${name} · ${t('status.switching')}` : t('character.pick', { name })}
        title={switching ? t('status.switching') : t('character.pick', { name })}
        onClick={() => {
          if (!ready) return;
          if (expanded) setOpen(false);
          else if (fetchConfigs()) setOpen(true);
        }}
      >
        <span className={DOT_CLASS[status] ?? 'dot'} aria-hidden="true" />
        <span className="topbar-name">{name}</span>
        <span className="topbar-status" aria-live="polite">
          {(switching || statusText) && (
            <span className="topbar-status-text" key={switching ? 'switching' : statusText}>
              {switching ? t('status.switching') : statusText}
            </span>
          )}
        </span>
        <span className="character-picker-indicator" aria-hidden="true">
          {switching ? <span className="spinner" /> : <ChevronDownIcon />}
        </span>
      </button>
      {expanded && (
        <div
          id={menuId}
          className="picker-menu character-menu"
          role="group"
          aria-label={t('character.title')}
        >
          <div className="picker-menu-title">{t('character.title')}</div>
          {configs?.length ? (
            <ul className="character-options">
              {configs.map((config) => {
                const selected = config.filename === currentFile;
                return (
                  <li key={config.filename}>
                    <button
                      type="button"
                      className={`picker-option${selected ? ' selected' : ''}`}
                      aria-current={selected ? 'true' : undefined}
                      onClick={() => {
                        close();
                        if (!selected) switchConfig(config.filename);
                      }}
                    >
                      <span className="picker-option-text">
                        <span className="picker-option-name">{config.name}</span>
                        {config.filename === 'conf.yaml' ? (
                          <span className="picker-option-desc">{t('character.default')}</span>
                        ) : (nameCounts.get(config.name) ?? 0) > 1 ? (
                          <span className="picker-option-desc">{config.filename.replace(/\.yaml$/, '')}</span>
                        ) : null}
                      </span>
                      <span className="picker-option-check">{selected && <CheckIcon />}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="character-menu-hint" role="status">
              {configs === null ? t('character.loading') : t('character.empty')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
