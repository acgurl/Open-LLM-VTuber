import { create } from 'zustand';

export interface Toast {
  id: number;
  text: string;
  level: 'info' | 'error' | 'success';
}

let toastSeq = 0;

interface ToastState {
  toasts: Toast[];
  push: (text: string, level?: Toast['level']) => void;
  dismiss: (id: number) => void;
}

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (text, level = 'info') => {
    const id = ++toastSeq;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, level }] }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 4200);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = (text: string, level: Toast['level'] = 'info') =>
  useToasts.getState().push(text, level);
