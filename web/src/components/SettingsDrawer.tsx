import { useEffect, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import { useGroup } from '../stores/group';
import { useTheme, type ThemeMode } from '../stores/theme';
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
import { usePresence } from '../hooks/usePresence';
import { McpPanel } from './McpPanel';

// 预设色相：默认蓝紫，其余覆盖常见角色主题色
const HUE_PRESETS = [220.44, 265, 320, 12, 150, 190];

export function SettingsDrawer() {
  const { t } = useTranslation();
  const open = useSettings((s) => s.settingsOpen);
  const setOpen = useSettings((s) => s.setSettingsOpen);
  const background = useSettings((s) => s.background);
  const setBackground = useSettings((s) => s.setBackground);
  const backgroundFiles = useSettings((s) => s.backgroundFiles);
  const configs = useSettings((s) => s.configs);
  const switching = useSettings((s) => s.switching);
  const pointerInteractive = useSettings((s) => s.pointerInteractive);
  const setPointerInteractive = useSettings((s) => s.setPointerInteractive);
  const scrollToResize = useSettings((s) => s.scrollToResize);
  const setScrollToResize = useSettings((s) => s.setScrollToResize);
  const themeMode = useTheme((s) => s.mode);
  const setThemeMode = useTheme((s) => s.setMode);
  const hue = useTheme((s) => s.hue);
  const setHue = useTheme((s) => s.setHue);
  const displayName = useConnection((s) => s.displayName);
  const userId = useConnection((s) => s.userId);
  const presence = usePresence(open, 220);

  useEffect(() => {
    if (open) {
      fetchConfigs();
      fetchBackgrounds();
      refreshGroup();
    }
  }, [open]);

  if (!presence.mounted) return null;

  return (
    <>
      <button
        type="button"
        className={`drawer-mask${presence.closing ? ' closing' : ''}`}
        aria-label={t('drawer.close')}
        tabIndex={-1}
        onClick={() => setOpen(false)}
      />
      <aside className={`drawer right${presence.closing ? ' closing' : ''}`}>
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
                aria-pressed={background === null}
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
                    aria-label={f}
                    aria-pressed={background === url}
                    onClick={() => setBackground(url)}
                  >
                    <img src={url} alt="" width={160} height={100} loading="lazy" />
                  </button>
                );
              })}
            </div>
          </section>

          <section>
            <h3>{t('settings.appearance')}</h3>
            <label className="setting-row">
              <span>{t('settings.theme')}</span>
              <select
                value={themeMode}
                onChange={(e) => setThemeMode(e.target.value as ThemeMode)}
              >
                <option value="auto">{t('settings.themeAuto')}</option>
                <option value="light">{t('settings.themeLight')}</option>
                <option value="dark">{t('settings.themeDark')}</option>
              </select>
            </label>
            <div className="hue-setting">
              <span>{t('settings.accent')}</span>
              <div className="hue-row" role="group" aria-label={t('settings.accent')}>
                {HUE_PRESETS.map((preset) => {
                  const active = Math.abs(hue - preset) < 0.5;
                  return (
                    <button
                      key={preset}
                      type="button"
                      className={`hue-dot${active ? ' active' : ''}`}
                      style={{ '--dot-hue': String(preset) } as CSSProperties}
                      aria-label={`${t('settings.accent')} ${Math.round(preset)}°`}
                      aria-pressed={active}
                      title={`${Math.round(preset)}°`}
                      onClick={() => setHue(preset)}
                    />
                  );
                })}
              </div>
            </div>
          </section>

          <section>
            <h3>{t('settings.live2d')}</h3>
            <label className="setting-row">
              <span>{t('settings.pointerInteractive')}</span>
              <input
                type="checkbox"
                checked={pointerInteractive}
                onChange={(e) => setPointerInteractive(e.target.checked)}
              />
            </label>
            <label className="setting-row">
              <span>{t('settings.scrollToResize')}</span>
              <input
                type="checkbox"
                checked={scrollToResize}
                onChange={(e) => setScrollToResize(e.target.checked)}
              />
            </label>
          </section>

          <section>
            <h3>{t('settings.title')}</h3>
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

          <McpPanel />

          <GroupPanel />

          <section>
            <h3>{t('settings.account')}</h3>
            {displayName && <div className="account-name">{displayName}</div>}
            {userId && (
              <div className="group-row">
                <span className="group-label">{t('settings.userId')}</span>
                <code className="group-uid" title={userId}>
                  {userId}
                </code>
                <button
                  type="button"
                  className="mini-btn"
                  aria-label={t('settings.copyUserId')}
                  title={t('settings.copyUserId')}
                  onClick={() => void navigator.clipboard?.writeText(userId)}
                >
                  ⧉
                </button>
              </div>
            )}
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
          type="button"
          className="mini-btn"
          aria-label={t('group.copyId')}
          title={t('group.copyId')}
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
          name="peer-uid"
          autoComplete="off"
          spellCheck={false}
          aria-label={t('group.invitePlaceholder')}
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
