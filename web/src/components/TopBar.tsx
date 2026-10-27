import { useTranslation } from 'react-i18next';
import { useConnection } from '../stores/connection';
import { useSettings } from '../stores/settings';
import { useTheme } from '../stores/theme';
import { audioPlayer } from '../services/audioPlayer';

const DOT_CLASS: Record<string, string> = {
  online: 'dot online',
  connecting: 'dot pending',
  reconnecting: 'dot pending',
  boot: 'dot pending',
  unauthorized: 'dot error',
  failed: 'dot error',
};

export function TopBar() {
  const { t } = useTranslation();
  const status = useConnection((s) => s.status);
  const confName = useConnection((s) => s.confName);
  const statusText = useConnection((s) => s.statusText);
  const busy = useConnection((s) => s.busy);
  const ttsOn = useSettings((s) => s.ttsOn);
  const setTtsOn = useSettings((s) => s.setTtsOn);
  const setHistoryOpen = useSettings((s) => s.setHistoryOpen);
  const setSettingsOpen = useSettings((s) => s.setSettingsOpen);
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);

  const toggleTts = () => {
    const enabled = !ttsOn;
    setTtsOn(enabled);
    audioPlayer.setMuted(!enabled);
  };

  return (
    <header className="topbar">
      <button
        className="icon-btn"
        aria-label={t('drawer.history')}
        title={t('drawer.history')}
        onClick={() => setHistoryOpen(true)}
      >
        <MenuIcon />
      </button>
      <div className="topbar-middle">
        <div className={`topbar-center${busy ? ' busy' : ''}`}>
          <span className={DOT_CLASS[status] ?? 'dot'} />
          <span className="topbar-name">{confName || t('app.title')}</span>
          <span className="topbar-status" aria-live="polite">
            {statusText && (
              <span className="topbar-status-text" key={statusText}>
                {statusText}
              </span>
            )}
          </span>
        </div>
        <button
          className={`icon-btn tts-toggle${ttsOn ? '' : ' off'}`}
          aria-label={t(ttsOn ? 'settings.ttsOn' : 'settings.ttsOff')}
          aria-pressed={ttsOn}
          title={t(ttsOn ? 'settings.ttsOn' : 'settings.ttsOff')}
          onClick={toggleTts}
        >
          <VolumeIcon muted={!ttsOn} />
        </button>
        <button
          className="icon-btn theme-toggle"
          aria-label={t(theme === 'light' ? 'theme.toDark' : 'theme.toLight')}
          title={t(theme === 'light' ? 'theme.toDark' : 'theme.toLight')}
          onClick={toggleTheme}
        >
          {theme === 'light' ? <MoonIcon /> : <SunIcon />}
        </button>
      </div>
      <button
        className="icon-btn"
        aria-label={t('drawer.settings')}
        title={t('drawer.settings')}
        onClick={() => setSettingsOpen(true)}
      >
        <GearIcon />
      </button>
    </header>
  );
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}

function VolumeIcon({ muted }: { muted: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 5 6 9H3v6h3l5 4z" />
      {muted ? (
        <path d="m16 9 5 6m0-6-5 6" />
      ) : (
        <>
          <path d="M15.5 8.5a5 5 0 0 1 0 7" />
          <path d="M18.5 5.5a9 9 0 0 1 0 13" />
        </>
      )}
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.09a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}
