import { useTranslation } from 'react-i18next';
import { useConnection } from '../stores/connection';
import { useSettings } from '../stores/settings';
import { useTheme } from '../stores/theme';
import { audioPlayer } from '../services/audioPlayer';
import { newHistory } from '../services/actions';
import { MenuIcon, NewChatIcon, VolumeIcon, SunIcon, MoonIcon, GearIcon } from './icons';

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
      <div className="topbar-side">
        <button
          className="icon-btn"
          aria-label={t('drawer.history')}
          title={t('drawer.history')}
          onClick={() => setHistoryOpen(true)}
        >
          <MenuIcon />
        </button>
        <button
          className="icon-btn"
          aria-label={t('history.new')}
          title={t('history.new')}
          onClick={newHistory}
        >
          <NewChatIcon />
        </button>
      </div>
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
          onClick={(e) => toggleTheme(e.currentTarget)}
        >
          {theme === 'light' ? <MoonIcon /> : <SunIcon />}
        </button>
      </div>
      <div className="topbar-side end">
        <button
          className="icon-btn"
          aria-label={t('drawer.settings')}
          title={t('drawer.settings')}
          onClick={() => setSettingsOpen(true)}
        >
          <GearIcon />
        </button>
      </div>
    </header>
  );
}
