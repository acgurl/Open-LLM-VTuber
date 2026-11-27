import { beforeEach, describe, expect, it, vi } from 'vitest';

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

describe('useSettings autoCollapseToolCards', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal('localStorage', createMemoryStorage());
    vi.stubGlobal('document', { cookie: '' });
  });

  it('defaults to false and persists changes to storage', async () => {
    const { useSettings } = await import('./settings');
    expect(useSettings.getState().autoCollapseToolCards).toBe(false);

    useSettings.getState().setAutoCollapseToolCards(true);
    expect(useSettings.getState().autoCollapseToolCards).toBe(true);
    expect(localStorage.getItem('ollmvt.tool.autoCollapse')).toBe('1');

    useSettings.getState().setAutoCollapseToolCards(false);
    expect(useSettings.getState().autoCollapseToolCards).toBe(false);
    expect(localStorage.getItem('ollmvt.tool.autoCollapse')).toBe('0');
  });

  it('restores persisted value on initialization', async () => {
    localStorage.setItem('ollmvt.tool.autoCollapse', '1');
    const { useSettings } = await import('./settings');
    expect(useSettings.getState().autoCollapseToolCards).toBe(true);
  });
});
