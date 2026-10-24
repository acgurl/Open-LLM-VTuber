import { create } from 'zustand';
import type { ConfigFileEntry } from '../protocol/types';

interface SettingsState {
  subtitlesOn: boolean;
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

const persisted = (key: string): string | null => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};

export const useSettings = create<SettingsState>((set) => ({
  subtitlesOn: persisted('ollmvt.subtitles') !== '0',
  background: persisted('ollmvt.bg'),
  backgroundFiles: [],
  configs: [],
  micOn: false,
  historyOpen: false,
  settingsOpen: false,
  switching: false,
  pointerInteractive: persisted('ollmvt.l2d.pointer') !== '0',
  scrollToResize: persisted('ollmvt.l2d.scroll') !== '0',
  setSubtitlesOn: (subtitlesOn) => {
    try {
      localStorage.setItem('ollmvt.subtitles', subtitlesOn ? '1' : '0');
    } catch { /* ignore */ }
    set({ subtitlesOn });
  },
  setBackground: (background) => {
    try {
      if (background) localStorage.setItem('ollmvt.bg', background);
      else localStorage.removeItem('ollmvt.bg');
    } catch { /* ignore */ }
    set({ background });
  },
  setBackgroundFiles: (backgroundFiles) => set({ backgroundFiles }),
  setConfigs: (configs) => set({ configs }),
  setMicOn: (micOn) => set({ micOn }),
  setHistoryOpen: (historyOpen) => set({ historyOpen }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setSwitching: (switching) => set({ switching }),
  setPointerInteractive: (pointerInteractive) => {
    try {
      localStorage.setItem('ollmvt.l2d.pointer', pointerInteractive ? '1' : '0');
    } catch { /* ignore */ }
    set({ pointerInteractive });
  },
  setScrollToResize: (scrollToResize) => {
    try {
      localStorage.setItem('ollmvt.l2d.scroll', scrollToResize ? '1' : '0');
    } catch { /* ignore */ }
    set({ scrollToResize });
  },
}));
