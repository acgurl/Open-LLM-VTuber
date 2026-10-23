import { create } from 'zustand';

interface SubtitleState {
  active: boolean;
  name: string;
  avatar?: string;
  fullText: string;
  shownChars: number;
  show: (name: string, avatar: string | undefined, fullText: string, shownChars: number) => void;
  progress: (shownChars: number) => void;
  hide: () => void;
}

export const useSubtitle = create<SubtitleState>((set) => ({
  active: false,
  name: '',
  avatar: undefined,
  fullText: '',
  shownChars: 0,
  show: (name, avatar, fullText, shownChars) =>
    set({ active: true, name, avatar, fullText, shownChars }),
  progress: (shownChars) => set({ shownChars }),
  hide: () => set({ active: false, fullText: '', shownChars: 0 }),
}));
