import { create } from 'zustand';

export interface Toast {
  id: number;
  text: string;
  level: 'info' | 'error' | 'success';
  leaving: boolean;
}

let toastSeq = 0;

const LIFETIME = 4200;
const timers = new Map<number, number>();
const remaining = new Map<number, number>();
const startedAt = new Map<number, number>();

const clearTimer = (id: number) => {
  const handle = timers.get(id);
  if (handle !== undefined) window.clearTimeout(handle);
  timers.delete(id);
};

const arm = (id: number, ms: number) => {
  clearTimer(id);
  remaining.set(id, ms);
  startedAt.set(id, Date.now());
  timers.set(
    id,
    window.setTimeout(() => {
      timers.delete(id);
      remaining.delete(id);
      startedAt.delete(id);
      useToasts.getState().dismiss(id);
    }, ms),
  );
};

interface ToastState {
  toasts: Toast[];
  push: (text: string, level?: Toast['level']) => void;
  dismiss: (id: number) => void;
  // 悬停时停表，让长提示能读完再走；与进度条动画同步暂停
  hold: (id: number) => void;
  release: (id: number) => void;
}

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (text, level = 'info') => {
    const id = ++toastSeq;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, level, leaving: false }] }));
    arm(id, LIFETIME);
  },
  dismiss: (id) => {
    const current = get().toasts.find((t) => t.id === id);
    if (!current || current.leaving) return;

    clearTimer(id);
    remaining.delete(id);
    startedAt.delete(id);
    set((s) => ({
      toasts: s.toasts.map((t) => (t.id === id ? { ...t, leaving: true } : t)),
    }));
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, reducedMotion ? 0 : 160);
  },
  hold: (id) => {
    if (!timers.has(id)) return;
    clearTimer(id);
    const left = (remaining.get(id) ?? LIFETIME) - (Date.now() - (startedAt.get(id) ?? Date.now()));
    remaining.set(id, Math.max(0, left));
  },
  release: (id) => {
    if (timers.has(id)) return;
    const left = remaining.get(id);
    if (left === undefined) return;
    arm(id, left);
  },
}));

export const toast = (text: string, level: Toast['level'] = 'info') =>
  useToasts.getState().push(text, level);
