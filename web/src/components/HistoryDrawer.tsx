import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettings } from '../stores/settings';
import { useHistory } from '../stores/history';
import { useConnection } from '../stores/connection';
import {
  refreshHistories,
  openHistory,
  newHistory,
  deleteHistory,
} from '../services/actions';
import { stripTags, buildTagSet } from '../utils/text';
import { usePresence } from '../hooks/usePresence';

export function HistoryDrawer() {
  const { t } = useTranslation();
  const open = useSettings((s) => s.historyOpen);
  const setOpen = useSettings((s) => s.setHistoryOpen);
  const histories = useHistory((s) => s.histories);
  const currentUid = useHistory((s) => s.currentUid);
  const modelInfo = useConnection((s) => s.modelInfo);
  const presence = usePresence(open, 220);

  // 抽屉打开时总是刷新列表
  useEffect(() => {
    if (open) refreshHistories();
  }, [open]);

  if (!presence.mounted) return null;
  const tagSet = buildTagSet(modelInfo);

  const snippet = (content?: string) => {
    if (!content) return '';
    const clean = stripTags(content.replace(/<\/?think>/gi, ''), tagSet);
    return clean.length > 60 ? `${clean.slice(0, 60)}…` : clean;
  };

  return (
    <>
      <button
        type="button"
        className={`drawer-mask${presence.closing ? ' closing' : ''}`}
        aria-label={t('drawer.close')}
        tabIndex={-1}
        onClick={() => setOpen(false)}
      />
      <aside className={`drawer left${presence.closing ? ' closing' : ''}`}>
        <div className="drawer-head">
          <span>{t('history.title')}</span>
          <button className="icon-btn" aria-label={t('drawer.close')} onClick={() => setOpen(false)}>
            ×
          </button>
        </div>
        <button
          className="drawer-action"
          onClick={() => {
            newHistory();
            setOpen(false);
          }}
        >
          + {t('history.new')}
        </button>
        <div className="drawer-body">
          {histories.length === 0 && <div className="drawer-empty">{t('history.empty')}</div>}
          {histories.map((h) => (
            <div
              key={h.uid}
              className={`history-item ${h.uid === currentUid ? 'current' : ''}`}
            >
              <button
                type="button"
                className="history-open"
                onClick={() => {
                  openHistory(h.uid);
                  setOpen(false);
                }}
              >
                <span className="history-snippet">{snippet(h.latest_message?.content)}</span>
                <span className="history-meta">
                  <span>{h.timestamp ?? h.latest_message?.timestamp ?? ''}</span>
                </span>
              </button>
              <button
                type="button"
                className="history-delete"
                aria-label={t('history.delete')}
                onClick={() => {
                  if (window.confirm(t('history.confirmDelete'))) deleteHistory(h.uid);
                }}
              >
                <TrashIcon />
              </button>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    </svg>
  );
}
