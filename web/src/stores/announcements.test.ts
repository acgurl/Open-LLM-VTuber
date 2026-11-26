import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Announcement } from '../services/announcements';
import {
  countUnread,
  hasUnreadPopup,
  isAnnouncementUnread,
  parseReadMap,
  useAnnouncements,
} from './announcements';

function createMemoryStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
  };
}

const sampleItems: Announcement[] = [
  {
    id: 'pinned-1',
    title: 'Maintenance Notice',
    content: 'Maintenance tonight.',
    level: 'warning',
    pinned: true,
    popup: true,
    starts_at: null,
    ends_at: null,
    updated_at: '2026-11-26T10:00:00+00:00',
  },
  {
    id: 'info-2',
    title: 'New Model Added',
    content: 'Try the new model.',
    level: 'info',
    pinned: false,
    popup: false,
    starts_at: null,
    ends_at: null,
    updated_at: '2026-11-25T10:00:00+00:00',
  },
];

describe('announcements store helpers', () => {
  it('parses valid read maps and ignores malformed JSON', () => {
    expect(parseReadMap(null)).toEqual({});
    expect(parseReadMap('not-json')).toEqual({});
    expect(parseReadMap('["a"]')).toEqual({});
    expect(
      parseReadMap(JSON.stringify({ a: '2026-01-01', bad: 123, '': 'x' })),
    ).toEqual({ a: '2026-01-01' });
  });

  it('tracks unread state by id and updated_at revision', () => {
    const readMap = {
      'pinned-1': '2026-11-26T10:00:00+00:00',
    };
    expect(isAnnouncementUnread(sampleItems[0], readMap)).toBe(false);
    expect(isAnnouncementUnread(sampleItems[1], readMap)).toBe(true);
    expect(countUnread(sampleItems, readMap)).toBe(1);
    expect(hasUnreadPopup(sampleItems, readMap)).toBe(false);

    // Updating updated_at marks the announcement unread again and enables popup.
    const edited = { ...sampleItems[0], updated_at: '2026-11-26T12:00:00+00:00' };
    expect(isAnnouncementUnread(edited, readMap)).toBe(true);
    expect(hasUnreadPopup([edited, sampleItems[1]], readMap)).toBe(true);
  });
});

describe('useAnnouncements store', () => {
  beforeEach(() => {
    const memoryStorage = createMemoryStorage();
    vi.stubGlobal('localStorage', memoryStorage);
    vi.stubGlobal('document', { cookie: '' });
    useAnnouncements.setState({
      items: [],
      readMap: {},
      open: false,
      loaded: false,
      loading: false,
      error: null,
      autoPopupHandled: false,
    });
  });

  it('auto-opens once for unread popup announcements and clears unread after markAllRead', () => {
    useAnnouncements.setState({
      items: sampleItems,
      readMap: {},
      loaded: true,
      autoPopupHandled: false,
    });

    useAnnouncements.getState().maybeAutoPopup();
    expect(useAnnouncements.getState().open).toBe(true);
    expect(useAnnouncements.getState().autoPopupHandled).toBe(true);

    useAnnouncements.getState().markAllRead();
    useAnnouncements.getState().setOpen(false);

    const { items, readMap } = useAnnouncements.getState();
    expect(countUnread(items, readMap)).toBe(0);
    expect(hasUnreadPopup(items, readMap)).toBe(false);
    expect(localStorage.getItem('ollmvt.announcements.read')).toContain('pinned-1');

    // Subsequent maybeAutoPopup calls stay closed.
    useAnnouncements.setState({ autoPopupHandled: false });
    useAnnouncements.getState().maybeAutoPopup();
    expect(useAnnouncements.getState().open).toBe(false);
  });
});
