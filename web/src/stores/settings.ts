import { create } from 'zustand';
import type { ConfigFileEntry } from '../protocol/types';
import { readSetting, writeSetting } from '../utils/storage';

interface SettingsState {
  subtitlesOn: boolean;
  ttsOn: boolean;
  background: string | null; // /bg/<file> 完整路径或 null
  backgroundFiles: string[];
  configs: ConfigFileEntry[];
  micOn: boolean; // 运行时状态，不持久化（默认关）
  historyOpen: boolean;
  settingsOpen: boolean;
  switching: boolean; // 角色切换 loading
  pointerInteractive: boolean;
  scrollToResize: boolean;
  setSubtitlesOn: (v: boolean) => void;
  setTtsOn: (v: boolean) => void;
  setBackground: (url: string | null) => void;
  setBackgroundFiles: (f: string[]) => void;
  setConfigs: (c: ConfigFileEntry[]) => void;
  setMicOn: (v: boolean) => void;
  setHistoryOpen: (v: boolean) => void;
  setSettingsOpen: (v: boolean) => void;
  setSwitching: (v: boolean) => void;
  setPointerInteractive: (v: boolean) => void;
  setScrollToResize: (v: boolean) => void;
}

export const useSettings = create<SettingsState>((set) => ({
  subtitlesOn: readSetting('subtitles') !== '0',
  ttsOn: readSetting('tts') !== '0',
  background: readSetting('bg'),
  backgroundFiles: [],
  configs: [],
  micOn: false,
  historyOpen: false,
  settingsOpen: false,
  switching: false,
  pointerInteractive: readSetting('l2d.pointer') !== '0',
  scrollToResize: readSetting('l2d.scroll') !== '0',
  setSubtitlesOn: (subtitlesOn) => {
    writeSetting('subtitles', subtitlesOn ? '1' : '0');
    set({ subtitlesOn });
  },
  setTtsOn: (ttsOn) => {
    writeSetting('tts', ttsOn ? '1' : '0');
    set({ ttsOn });
  },
  setBackground: (background) => {
    writeSetting('bg', background);
    set({ background });
  },
  setBackgroundFiles: (backgroundFiles) => set({ backgroundFiles }),
  setConfigs: (configs) => set({ configs }),
  setMicOn: (micOn) => set({ micOn }),
  setHistoryOpen: (historyOpen) => set({ historyOpen }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setSwitching: (switching) => set({ switching }),
  setPointerInteractive: (pointerInteractive) => {
    writeSetting('l2d.pointer', pointerInteractive ? '1' : '0');
    set({ pointerInteractive });
  },
  setScrollToResize: (scrollToResize) => {
    writeSetting('l2d.scroll', scrollToResize ? '1' : '0');
    set({ scrollToResize });
  },
}));
