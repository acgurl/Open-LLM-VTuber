import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import { useGroup } from '../stores/group';
import { setLanguage } from '../i18n';
import { logout } from '../services/session';
import {
  fetchConfigs,
  switchConfig,
  fetchBackgrounds,
  proactiveSpeak,
  inviteToGroup,
  removeFromGroup,
  refreshGroup,
} from '../services/actions';
import { backgroundUrl } from '../utils/text';
import i18n from '../i18n';

export function SettingsDrawer() {
  const { t } = useTranslation();
  const open = useSettings((s) => s.settingsOpen);
  const setOpen = useSettings((s) => s.setSettingsOpen);
  const subtitlesOn = useSettings((s) => s.subtitlesOn);
  const setSubtitlesOn = useSettings((s) => s.setSubtitlesOn);
  const background = useSettings((s) => s.background);
  const setBackground = useSettings((s) => s.setBackground);
  const backgroundFiles = useSettings((s) => s.backgroundFiles);
  const configs = useSettings((s) => s.configs);
  const switching = useSettings((s) => s.switching);
  const displayName = useConnection((s) => s.displayName);

  useEffect(() => {
    if (open) {
      fetchConfigs();
      fetchBackgrounds();
      refreshGroup();
    }
  }, [open]);

  if (!open) return null;

  return (
    <>
      <div className="drawer-mask" onClick={() => setOpen(false)} />
      <aside className="drawer right">
        <div className="drawer-head">
          <span>{t('settings.title')}</span>
          <button className="icon-btn" aria-label={t('drawer.close')} onClick={() => setOpen(false)}>
            ×
          </button>
        </div>
        <div className="drawer-body">
          <section>
            <h3>{t('settings.character')}</h3>
            <div className="config-list">
              {configs.map((c) => (
                <button
                  key={c.filename}
                  className="config-item"
                  disabled={switching}
                  onClick={() => switchConfig(c.filename)}
                >
                  <span>{c.name}</span>
                  <span className="config-file">{c.filename}</span>
                </button>
              ))}
            </div>
            {switching && (
              <div className="switching-hint">
                <span className="spinner" /> {t('status.switching')}
              </div>
            )}
          </section>

          <section>
            <h3>{t('settings.background')}</h3>
            <div className="bg-grid">
              <button
                className={`bg-cell ${background === null ? 'active' : ''}`}
                onClick={() => setBackground(null)}
              >
                {t('settings.noBackground')}
              </button>
              {backgroundFiles.map((f) => {
                const url = backgroundUrl(f);
                return (
                  <button
                    key={f}
                    className={`bg-cell ${background === url ? 'active' : ''}`}
                    onClick={() => setBackground(url)}
                  >
                    <img src={url} alt={f} loading="lazy" />
                  </button>
                );
              })}
            </div>
          </section>

          <section>
            <h3>{t('settings.title')}</h3>
            <label className="setting-row">
              <span>{t('settings.subtitles')}</span>
              <input
                type="checkbox"
                checked={subtitlesOn}
                onChange={(e) => setSubtitlesOn(e.target.checked)}
              />
            </label>
            <label className="setting-row">
              <span>{t('settings.language')}</span>
              <select
                value={i18n.language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </label>
            <button className="drawer-action" onClick={proactiveSpeak}>
              {t('settings.proactiveSpeak')}
            </button>
          </section>

          <GroupPanel />

          <section>
            <h3>{t('settings.account')}</h3>
            {displayName && <div className="account-name">{displayName}</div>}
            <button className="drawer-action danger" onClick={logout}>
              {t('settings.logout')}
            </button>
          </section>
        </div>
      </aside>
    </>
  );
}

function GroupPanel() {
  const { t } = useTranslation();
  const clientUid = useConnection((s) => s.clientUid);
  const members = useGroup((s) => s.members);
  const isOwner = useGroup((s) => s.isOwner);
  const peers = useGroup((s) => s.peers);
  const [inviteUid, setInviteUid] = useState('');

  const short = (uid: string) => `${uid.slice(0, 8)}…`;
  const inGroup = members.length > 1;
  const invitable = peers.filter((p) => !members.includes(p.uid));

  return (
    <section>
      <h3>{t('group.title')}</h3>
      <div className="group-row">
        <span className="group-label">{t('group.thisId')}</span>
        <code className="group-uid">{clientUid ?? '—'}</code>
        <button
          className="mini-btn"
          disabled={!clientUid}
          onClick={() => clientUid && void navigator.clipboard?.writeText(clientUid)}
        >
          ⧉
        </button>
      </div>

      {!inGroup && <div className="group-hint">{t('group.inviteHint')}</div>}

      {invitable.length > 0 && (
        <div className="group-peers">
          {invitable.map((p) => (
            <div key={p.uid} className="group-row">
              <code className="group-uid">{short(p.uid)}</code>
              <button className="mini-btn" onClick={() => inviteToGroup(p.uid)}>
                {t('group.invite')}
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="group-row">
        <input
          className="group-input"
          placeholder={t('group.invitePlaceholder')}
          value={inviteUid}
          onChange={(e) => setInviteUid(e.target.value)}
        />
        <button
          className="mini-btn"
          disabled={!inviteUid.trim()}
          onClick={() => {
            inviteToGroup(inviteUid.trim());
            setInviteUid('');
          }}
        >
          {t('group.invite')}
        </button>
      </div>

      {inGroup ? (
        <div className="group-members">
          {members.map((m) => {
            const isSelf = m === clientUid;
            const canRemove = isOwner || isSelf;
            return (
              <div key={m} className="group-row">
                <code className="group-uid">{short(m)}</code>
                {isSelf && <span className="group-badge">{t('group.you')}</span>}
                {m === members[0] && <span className="group-badge owner">{t('group.owner')}</span>}
                {canRemove && (
                  <button className="mini-btn danger" onClick={() => removeFromGroup(m)}>
                    {isSelf ? t('group.leave') : t('group.remove')}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="group-hint">{t('group.notInGroup')}</div>
      )}
    </section>
  );
}
