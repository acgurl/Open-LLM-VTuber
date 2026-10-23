import { create } from 'zustand';

interface CameraState {
  stream: MediaStream | null; // 非 null 即视为实况中
  starting: boolean;
  error: string; // i18n key，空串表示无错误
  setStream: (stream: MediaStream | null) => void;
  setStarting: (starting: boolean) => void;
  setError: (error: string) => void;
}

export const useCamera = create<CameraState>((set) => ({
  stream: null,
  starting: false,
  error: '',
  setStream: (stream) => set({ stream }),
  setStarting: (starting) => set({ starting }),
  setError: (error) => set({ error }),
}));
