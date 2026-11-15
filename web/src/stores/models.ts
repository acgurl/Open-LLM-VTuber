import { create } from 'zustand';
import type { ModelEntry } from '../protocol/types';

interface ModelsState {
  models: ModelEntry[]; // 当前账号可选的模型；空表示后台没开这个功能
  current: string | null; // 正在使用的模型 id；null 表示跟随角色预设
  switching: boolean; // 已发 switch-model，等服务端确认
  setList: (models: ModelEntry[], current: string | null) => void;
  requestSwitch: () => void;
  confirmSwitch: (current: string | null) => void;
  cancelSwitch: () => void;
}

export const useModels = create<ModelsState>((set) => ({
  models: [],
  current: null,
  switching: false,
  setList: (models, current) => set({ models, current, switching: false }),
  requestSwitch: () => set({ switching: true }),
  confirmSwitch: (current) => set({ current, switching: false }),
  cancelSwitch: () => set((s) => (s.switching ? { switching: false } : s)),
}));
