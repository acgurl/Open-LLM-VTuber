import { create } from 'zustand';
import { fetchAnnouncements, type Announcement } from '../services/announcements';
import { readSetting, writeSetting } from '../utils/storage';

const READ_STORAGE_KEY = 'announcements.read';
const MAX_STORED_READ_ENTRIES = 100;

export function parseReadMap(raw: string | null): Record<string, string> {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [key, val] of Object.entries(parsed)) {
      if (typeof key === 'string' && key && typeof val === 'string' && val) {
        out[key] = val;
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function announcementVersion(item: Pick<Announcement, 'updated_at'>): string {
  return item.updated_at || '1';
}

export function isAnnouncementUnread(
  item: Pick<Announcement, 'id' | 'updated_at'>,
  readMap: Record<string, string>,
): boolean {
  return readMap[item.id] !== announcementVersion(item);
}

export function countUnread(
  items: Pick<Announcement, 'id' | 'updated_at'>[],
  readMap: Record<string, string>,
): number {
  let count = 0;
  for (const item of items) {
    if (isAnnouncementUnread(item, readMap)) count += 1;
  }
  return count;
}

export function hasUnreadPopup(
  items: Pick<Announcement, 'id' | 'updated_at' | 'popup'>[],
  readMap: Record<string, string>,
): boolean {
  return items.some((item) => item.popup && isAnnouncementUnread(item, readMap));
}

function buildNextReadMap(
  items: Pick<Announcement, 'id' | 'updated_at'>[],
  prev: Record<string, string>,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const item of items) {
    next[item.id] = announcementVersion(item);
  }
  // Preserve recent read records for announcements that might temporarily expire,
  // capped so localStorage stays compact.
  for (const [id, version] of Object.entries(prev)) {
    if (Object.keys(next).length >= MAX_STORED_READ_ENTRIES) break;
    if (!(id in next)) next[id] = version;
  }
  return next;
}

interface AnnouncementsState {
  items: Announcement[];
  readMap: Record<string, string>;
  open: boolean;
  loaded: boolean;
  loading: boolean;
  error: string | null;
  autoPopupHandled: boolean;
  load: () => Promise<void>;
  setOpen: (open: boolean) => void;
  markAllRead: () => void;
  maybeAutoPopup: () => void;
}

export const useAnnouncements = create<AnnouncementsState>((set, get) => ({
  items: [],
  readMap: parseReadMap(readSetting(READ_STORAGE_KEY)),
  open: false,
  loaded: false,
  loading: false,
  error: null,
  autoPopupHandled: false,

  load: async () => {
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const items = await fetchAnnouncements();
      const readMap = parseReadMap(readSetting(READ_STORAGE_KEY));
      set({ items, readMap, loaded: true, loading: false, error: null });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load announcements';
      set({ loading: false, error: message });
    }
  },

  setOpen: (open) => set({ open }),

  markAllRead: () => {
    const { items, readMap } = get();
    if (items.length === 0) return;
    const next = buildNextReadMap(items, readMap);
    writeSetting(READ_STORAGE_KEY, JSON.stringify(next));
    set({ readMap: next });
  },

  maybeAutoPopup: () => {
    const { autoPopupHandled, loaded, items, readMap } = get();
    if (autoPopupHandled || !loaded) return;
    if (hasUnreadPopup(items, readMap)) {
      set({ open: true, autoPopupHandled: true });
    } else {
      set({ autoPopupHandled: true });
    }
  },
}));
