import type { SessionInfo } from '../protocol/types';

export async function fetchSession(): Promise<SessionInfo | null> {
  try {
    const res = await fetch('/api/session', { credentials: 'include' });
    if (res.status === 401) return { authenticated: false, mode: 'oidc' };
    if (!res.ok) return null;
    return (await res.json()) as SessionInfo;
  } catch {
    return null;
  }
}

export function redirectToLogin() {
  const next = encodeURIComponent(location.pathname + location.search);
  location.href = `/auth/login?next=${next}`;
}

export function logout() {
  location.href = '/auth/logout';
}

export function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}${path}`;
}
