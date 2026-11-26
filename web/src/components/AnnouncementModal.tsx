import { lazy, Suspense, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useDialog } from '../hooks/useDialog';
import { usePresence } from '../hooks/usePresence';
import { isAnnouncementUnread, useAnnouncements } from '../stores/announcements';
import type { Announcement, AnnouncementLevel } from '../services/announcements';
import { BellIcon, CloseIcon } from './icons';

const MarkdownText = lazy(() => import('./MarkdownText'));

function formatAnnouncementTime(item: Announcement, locale: string): string {
  const raw = item.starts_at || item.updated_at;
  if (!raw) return '';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function levelLabelKey(level: AnnouncementLevel): string {
  switch (level) {
    case 'important':
      return 'announcements.levelImportant';
    case 'warning':
      return 'announcements.levelWarning';
    default:
      return 'announcements.levelInfo';
  }
}

export function AnnouncementModal() {
  const { t, i18n } = useTranslation();
  const open = useAnnouncements((s) => s.open);
  const items = useAnnouncements((s) => s.items);
  const readMap = useAnnouncements((s) => s.readMap);
  const loading = useAnnouncements((s) => s.loading);
  const error = useAnnouncements((s) => s.error);
  const load = useAnnouncements((s) => s.load);
  const setOpen = useAnnouncements((s) => s.setOpen);
  const markAllRead = useAnnouncements((s) => s.markAllRead);
  const presence = usePresence(open, 220);
  const panelRef = useRef<HTMLDivElement>(null);

  const handleClose = useCallback(() => {
    markAllRead();
    setOpen(false);
  }, [markAllRead, setOpen]);

  useDialog(open && presence.mounted, handleClose, panelRef);

  if (!presence.mounted) return null;

  return (
    <>
      <button
        type="button"
        className={`announcement-mask${presence.closing ? ' closing' : ''}`}
        aria-label={t('announcements.close')}
        tabIndex={-1}
        onClick={handleClose}
      />
      <div
        ref={panelRef}
        className={`announcement-modal${presence.closing ? ' closing' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={t('announcements.title')}
        tabIndex={-1}
      >
        <div className="announcement-head">
          <div className="announcement-head-title">
            <span className="announcement-glyph" aria-hidden="true">
              <BellIcon size={18} />
            </span>
            <span>{t('announcements.title')}</span>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label={t('announcements.close')}
            title={t('announcements.close')}
            onClick={handleClose}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="announcement-body">
          {loading && items.length === 0 ? (
            <div className="announcement-state">
              <span className="spinner" aria-hidden="true" />
              <span>{t('announcements.loading')}</span>
            </div>
          ) : error && items.length === 0 ? (
            <div className="announcement-state error">
              <p>{t('announcements.loadFailed')}</p>
              <button
                type="button"
                className="announcement-retry-btn"
                onClick={() => void load()}
              >
                {t('announcements.retry')}
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="announcement-state">{t('announcements.empty')}</div>
          ) : (
            <div className="announcement-list">
              {items.map((item) => {
                const unread = isAnnouncementUnread(item, readMap);
                const formattedTime = formatAnnouncementTime(item, i18n.language);
                return (
                  <article
                    key={item.id}
                    className={`announcement-card level-${item.level}${unread ? ' unread' : ''}`}
                  >
                    <header className="announcement-card-head">
                      <div className="announcement-badges">
                        <span className={`announcement-level level-${item.level}`}>
                          {t(levelLabelKey(item.level))}
                        </span>
                        {item.pinned && (
                          <span className="announcement-pinned">
                            {t('announcements.pinned')}
                          </span>
                        )}
                        {unread && (
                          <span className="announcement-unread-pill">
                            {t('announcements.unread')}
                          </span>
                        )}
                      </div>
                      {formattedTime && (
                        <time className="announcement-time" dateTime={item.updated_at}>
                          {formattedTime}
                        </time>
                      )}
                    </header>
                    <h3 className="announcement-card-title">{item.title}</h3>
                    <div className="announcement-content">
                      <Suspense fallback={<p>{item.content}</p>}>
                        <MarkdownText text={item.content} block />
                      </Suspense>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        <footer className="announcement-foot">
          <button
            type="button"
            className="announcement-ack-btn"
            onClick={handleClose}
          >
            {t('announcements.acknowledge')}
          </button>
        </footer>
      </div>
    </>
  );
}
