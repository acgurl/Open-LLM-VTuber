import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePresence } from '../hooks/usePresence';
import { toast } from '../stores/toast';
import { amapLink, appleLink, baiduLink, coordText, isIOS } from '../utils/mapLinks';
import type { Place } from '../utils/places';
import { ChevronDownIcon, CopyIcon, NavigateIcon } from './icons';

// 主按钮直接拉起高德（未装 App 落网页版）；caret 展开备选地图与复制坐标。
// 菜单向上弹：消息卡自带 backdrop-filter 会形成层叠上下文，向下会被后续气泡盖住。
export function MapAppMenu({ place }: { place: Place }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { mounted, closing } = usePresence(open, 160);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    // 捕获阶段拦截 Esc：全屏对话框里先关菜单，而不是连地图一起关掉
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const copyCoord = async () => {
    setOpen(false);
    try {
      await navigator.clipboard.writeText(coordText(place));
      toast(t('location.copied'), 'success');
    } catch {
      toast(t('location.copyFailed'), 'error');
    }
  };

  return (
    <div className="map-app" ref={rootRef}>
      <a
        className="map-app-primary"
        href={amapLink(place)}
        target="_blank"
        rel="noopener noreferrer"
      >
        <NavigateIcon />
        <span>{t('location.openInApp')}</span>
      </a>
      <button
        type="button"
        className="map-app-caret"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('location.moreMaps')}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDownIcon />
      </button>
      {mounted && (
        <div
          className={`map-app-menu${closing ? ' closing' : ''}`}
          role="menu"
          aria-label={t('location.moreMaps')}
        >
          <a
            role="menuitem"
            href={baiduLink(place)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
          >
            {t('location.baidu')}
          </a>
          {isIOS() && (
            <a
              role="menuitem"
              href={appleLink(place)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
            >
              {t('location.apple')}
            </a>
          )}
          <button type="button" role="menuitem" onClick={() => void copyCoord()}>
            <CopyIcon />
            <span>{t('location.copyCoord')}</span>
          </button>
        </div>
      )}
    </div>
  );
}
