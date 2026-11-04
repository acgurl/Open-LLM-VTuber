import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
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
import { useDialog } from '../hooks/useDialog';
import type { HistorySummary } from '../protocol/types';
import { TrashIcon } from './icons';

// 第一次点删除只“上膛”，这段时间内再点一次才真的删
const CONFIRM_MS = 3000;

type Group = 'today' | 'yesterday' | 'earlier';

function historyTime(h: HistorySummary): number {
  const raw = h.timestamp ?? h.latest_message?.timestamp ?? '';
  const ms = Date.parse(raw);
  return Number.isFinite(ms) ? ms : NaN;
}

function groupOf(ms: number, now: Date): Group {
  if (!Number.isFinite(ms)) return 'earlier';
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (ms >= startOfToday) return 'today';
  if (ms >= startOfToday - 86_400_000) return 'yesterday';
  return 'earlier';
}

export function HistoryDrawer() {
  const { t, i18n } = useTranslation();
  const open = useSettings((s) => s.historyOpen);
  const setOpen = useSettings((s) => s.setHistoryOpen);
  const histories = useHistory((s) => s.histories);
  const currentUid = useHistory((s) => s.currentUid);
  const modelInfo = useConnection((s) => s.modelInfo);
  const presence = usePresence(open, 220);
  const [confirming, setConfirming] = useState<string | null>(null);
  const confirmTimer = useRef(0);
  const tagSet = useMemo(() => buildTagSet(modelInfo), [modelInfo]);

  // 抽屉打开时总是刷新列表
  useEffect(() => {
    if (open) refreshHistories();
    else setConfirming(null);
  }, [open]);

  useEffect(() => () => window.clearTimeout(confirmTimer.current), []);

  const panelRef = useRef<HTMLElement>(null);
  // 等面板真正挂载后再启用，否则首帧 ref 为空、焦点移不进去
  useDialog(open && presence.mounted, () => setOpen(false), panelRef);

  const rows = useMemo(() => {
    const now = new Date();
    return histories.map((h) => {
      const ms = historyTime(h);
      return { h, ms, group: groupOf(ms, now) };
    });
  }, [histories]);

  if (!presence.mounted) return null;

  const snippet = (content?: string) => {
    if (!content) return '';
    const clean = stripTags(content.replace(/<\/?think>/gi, ''), tagSet);
    return clean.length > 60 ? `${clean.slice(0, 60)}…` : clean;
  };

  const formatTime = (ms: number, group: Group, fallback: string) => {
    if (!Number.isFinite(ms)) return fallback;
    const d = new Date(ms);
    const time = d.toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' });
    if (group !== 'earlier') return time;
    const sameYear = d.getFullYear() === new Date().getFullYear();
    const date = d.toLocaleDateString(i18n.language, {
      ...(sameYear ? {} : { year: 'numeric' }),
      month: '2-digit',
      day: '2-digit',
    });
    return `${date} ${time}`;
  };

  const onDelete = (uid: string) => {
    window.clearTimeout(confirmTimer.current);
    if (confirming === uid) {
      setConfirming(null);
      deleteHistory(uid);
      return;
    }
    setConfirming(uid);
    confirmTimer.current = window.setTimeout(() => setConfirming(null), CONFIRM_MS);
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
      <aside
        ref={panelRef}
        className={`drawer left${presence.closing ? ' closing' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={t('history.title')}
        tabIndex={-1}
      >
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
          {rows.map(({ h, ms, group }, i) => (
            <Fragment key={h.uid}>
              {(i === 0 || rows[i - 1].group !== group) && (
                <div className="history-group">{t(`history.${group}`)}</div>
              )}
              <div
                className={`history-item${h.uid === currentUid ? ' current' : ''}${
                  confirming === h.uid ? ' confirming' : ''
                }`}
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
                    <time dateTime={Number.isFinite(ms) ? new Date(ms).toISOString() : undefined}>
                      {formatTime(ms, group, h.timestamp ?? h.latest_message?.timestamp ?? '')}
                    </time>
                  </span>
                </button>
                <button
                  type="button"
                  className={`history-delete${confirming === h.uid ? ' armed' : ''}`}
                  aria-label={
                    confirming === h.uid ? t('history.confirmDelete') : t('history.delete')
                  }
                  title={confirming === h.uid ? t('history.confirmDelete') : t('history.delete')}
                  onClick={() => onDelete(h.uid)}
                  onBlur={() => {
                    if (confirming === h.uid) setConfirming(null);
                  }}
                >
                  <TrashIcon />
                  {confirming === h.uid && (
                    <span className="history-delete-label">{t('history.confirmShort')}</span>
                  )}
                </button>
              </div>
            </Fragment>
          ))}
        </div>
      </aside>
    </>
  );
}
