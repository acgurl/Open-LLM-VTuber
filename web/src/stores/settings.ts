import { create } from 'zustand';
import type { ConfigFileEntry } from '../protocol/types';
import { readSetting, writeSetting } from '../utils/storage';

interface SettingsState {
  ttsOn: boolean;
  background: string | null; // /bg/<file> 完整路径或 null
  backgroundFiles: string[];
  configs: ConfigFileEntry[];
  micOn: boolean; // 运行时状态，不持久化（默认关）
  historyOpen: boolean;
  settingsOpen: boolean;
  switching: boolean; // 角色切换 loading
  // 最近一次切换成功的预设文件：同名预设（如 conf.yaml 与它的副本）只高亮真正选中的那个
  configFile: string | null;
  requestedFile: string | null;
  pointerInteractive: boolean;
  scrollToResize: boolean;
  setTtsOn: (v: boolean) => void;
  setBackground: (url: string | null) => void;
  setBackgroundFiles: (f: string[]) => void;
  setConfigs: (c: ConfigFileEntry[]) => void;
  setMicOn: (v: boolean) => void;
  setHistoryOpen: (v: boolean) => void;
  setSettingsOpen: (v: boolean) => void;
  setSwitching: (v: boolean) => void;
  requestConfig: (file: string) => void;
  confirmConfig: () => void;
  setPointerInteractive: (v: boolean) => void;
  setScrollToResize: (v: boolean) => void;
}

export const useSettings = create<SettingsState>((set) => ({
  ttsOn: readSetting('tts') !== '0',
  background: readSetting('bg'),
  backgroundFiles: [],
  configs: [],
  micOn: false,
  historyOpen: false,
  settingsOpen: false,
  switching: false,
  configFile: null,
  requestedFile: null,
  pointerInteractive: readSetting('l2d.pointer') !== '0',
  scrollToResize: readSetting('l2d.scroll') !== '0',
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
  requestConfig: (requestedFile) => set({ switching: true, requestedFile }),
  confirmConfig: () =>
    set((s) => ({ switching: false, configFile: s.requestedFile ?? s.configFile, requestedFile: null })),
  setPointerInteractive: (pointerInteractive) => {
    writeSetting('l2d.pointer', pointerInteractive ? '1' : '0');
    set({ pointerInteractive });
  },
  setScrollToResize: (scrollToResize) => {
    writeSetting('l2d.scroll', scrollToResize ? '1' : '0');
    set({ scrollToResize });
  },
}));
