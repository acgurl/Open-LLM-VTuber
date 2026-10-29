import { create } from 'zustand';
import type { HistorySummary } from '../protocol/types';
import { storageKey } from '../utils/storage';

// Keep the active history for the lifetime of this tab so a reconnect or a
// refresh resumes the conversation instead of silently starting a new one.
const CURRENT_HISTORY_KEY = storageKey('currentHistory');

function readCurrentUid(): string | null {
  try {
    return sessionStorage.getItem(CURRENT_HISTORY_KEY);
  } catch {
    return null;
  }
}

function writeCurrentUid(uid: string | null): void {
  try {
    if (uid) sessionStorage.setItem(CURRENT_HISTORY_KEY, uid);
    else sessionStorage.removeItem(CURRENT_HISTORY_KEY);
  } catch {
    /* ignore */
  }
}

interface HistoryState {
  histories: HistorySummary[];
  currentUid: string | null;
  setHistories: (h: HistorySummary[]) => void;
  setCurrentUid: (uid: string | null) => void;
  removeHistory: (uid: string) => void;
}

export const useHistory = create<HistoryState>((set) => ({
  histories: [],
  currentUid: readCurrentUid(),
  setHistories: (histories) => set({ histories }),
  setCurrentUid: (currentUid) => {
    writeCurrentUid(currentUid);
    set({ currentUid });
  },
  removeHistory: (uid) =>
    set((s) => {
      const isCurrent = s.currentUid === uid;
      if (isCurrent) writeCurrentUid(null);
      return {
        histories: s.histories.filter((h) => h.uid !== uid),
        currentUid: isCurrent ? null : s.currentUid,
      };
    }),
}));
