import { request } from './api';

export type AnnouncementLevel = 'info' | 'warning' | 'important';

export interface Announcement {
  id: string;
  title: string;
  content: string;
  level: AnnouncementLevel;
  pinned: boolean;
  popup: boolean;
  starts_at: string | null;
  ends_at: string | null;
  updated_at: string;
}

export async function fetchAnnouncements(): Promise<Announcement[]> {
  const data = await request<{ announcements?: Announcement[] }>('/api/announcements');
  return Array.isArray(data?.announcements) ? data.announcements : [];
}
