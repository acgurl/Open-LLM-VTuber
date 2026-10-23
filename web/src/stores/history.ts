import { create } from 'zustand';
import type { HistorySummary } from '../protocol/types';

interface HistoryState {
  histories: HistorySummary[];
  currentUid: string | null;
  setHistories: (h: HistorySummary[]) => void;
  setCurrentUid: (uid: string | null) => void;
  removeHistory: (uid: string) => void;
}

export const useHistory = create<HistoryState>((set) => ({
  histories: [],
  currentUid: null,
  setHistories: (histories) => set({ histories }),
  setCurrentUid: (currentUid) => set({ currentUid }),
  removeHistory: (uid) =>
    set((s) => ({
      histories: s.histories.filter((h) => h.uid !== uid),
      currentUid: s.currentUid === uid ? null : s.currentUid,
    })),
}));
