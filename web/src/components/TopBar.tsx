import { useTranslation } from 'react-i18next';
import { useSettings } from '../stores/settings';
import { useTheme } from '../stores/theme';
import { countUnread, useAnnouncements } from '../stores/announcements';
import { audioPlayer } from '../services/audioPlayer';
import { newHistory } from '../services/actions';
import { CharacterPicker } from './CharacterPicker';
import { ModelPicker } from './ModelPicker';
import {
  MenuIcon,
  NewChatIcon,
  VolumeIcon,
  SunIcon,
  MoonIcon,
  BellIcon,
  GearIcon,
} from './icons';

export function TopBar() {
  const { t } = useTranslation();
  const ttsOn = useSettings((s) => s.ttsOn);
  const setTtsOn = useSettings((s) => s.setTtsOn);
  const setHistoryOpen = useSettings((s) => s.setHistoryOpen);
  const setSettingsOpen = useSettings((s) => s.setSettingsOpen);
  const items = useAnnouncements((s) => s.items);
  const readMap = useAnnouncements((s) => s.readMap);
  const setAnnouncementsOpen = useAnnouncements((s) => s.setOpen);
  const loadAnnouncements = useAnnouncements((s) => s.load);
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);
  const unreadCount = countUnread(items, readMap);

  const openAnnouncements = () => {
    setAnnouncementsOpen(true);
    void loadAnnouncements();
  };

  const toggleTts = () => {
    const enabled = !ttsOn;
    setTtsOn(enabled);
    audioPlayer.setMuted(!enabled);
  };

  return (
    <header className="topbar">
      <div className="topbar-side">
        <button
          className="icon-btn history-btn"
          aria-label={t('drawer.history')}
          title={t('drawer.history')}
          onClick={() => setHistoryOpen(true)}
        >
          <MenuIcon />
        </button>
        <button
          className="icon-btn new-chat-btn"
          aria-label={t('history.new')}
          title={t('history.new')}
          onClick={newHistory}
        >
          <NewChatIcon />
        </button>
      </div>
      <div className="topbar-middle">
        <CharacterPicker />
        <ModelPicker />
        <button
          className={`icon-btn tts-toggle${ttsOn ? '' : ' off'}`}
          aria-label={t(ttsOn ? 'settings.ttsOn' : 'settings.ttsOff')}
          aria-pressed={ttsOn}
          title={t(ttsOn ? 'settings.ttsOn' : 'settings.ttsOff')}
          onClick={toggleTts}
        >
          <span className="icon-swap" key={ttsOn ? 'on' : 'off'}>
            <VolumeIcon muted={!ttsOn} />
          </span>
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
          className="icon-btn announcement-btn"
          aria-label={
            unreadCount > 0
              ? t('announcements.openUnread', { count: unreadCount })
              : t('announcements.open')
          }
          title={
            unreadCount > 0
              ? t('announcements.openUnread', { count: unreadCount })
              : t('announcements.open')
          }
          onClick={openAnnouncements}
        >
          <BellIcon />
          {unreadCount > 0 && <span className="announcement-dot" aria-hidden="true" />}
        </button>
        <button
          className="icon-btn settings-btn"
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
