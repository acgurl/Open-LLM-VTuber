// localStorage keys are scoped per account: a shared browser must not reuse the
// previous user's cached model, settings or language. The opaque user id comes
// from the JS-readable `vtuber_uid` cookie set at login; without it (single-user
// mode, or before login) keys stay unscoped for backwards compatibility.

const UID_COOKIE = 'vtuber_uid';

function currentUserId(): string {
  try {
    const match = document.cookie.match(/(?:^|;\s*)vtuber_uid=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  } catch {
    return '';
  }
}

export function storageKey(name: string): string {
  const uid = currentUserId();
  return uid ? `ollmvt.u${uid}.${name}` : `ollmvt.${name}`;
}

export function readSetting(name: string): string | null {
  try {
    return localStorage.getItem(storageKey(name));
  } catch {
    return null;
  }
}

export function writeSetting(name: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(storageKey(name));
    else localStorage.setItem(storageKey(name), value);
  } catch {
    /* ignore */
  }
}
