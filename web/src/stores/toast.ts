import { create } from 'zustand';

export interface Toast {
  id: number;
  text: string;
  level: 'info' | 'error' | 'success';
  leaving: boolean;
}

let toastSeq = 0;

interface ToastState {
  toasts: Toast[];
  push: (text: string, level?: Toast['level']) => void;
  dismiss: (id: number) => void;
}

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (text, level = 'info') => {
    const id = ++toastSeq;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, level, leaving: false }] }));
    setTimeout(() => {
      useToasts.getState().dismiss(id);
    }, 4200);
  },
  dismiss: (id) => {
    const current = get().toasts.find((t) => t.id === id);
    if (!current || current.leaving) return;

    set((s) => ({
      toasts: s.toasts.map((t) => (t.id === id ? { ...t, leaving: true } : t)),
    }));
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, reducedMotion ? 0 : 160);
  },
}));

export const toast = (text: string, level: Toast['level'] = 'info') =>
  useToasts.getState().push(text, level);
