import { create } from 'zustand';
import type { ModelEntry } from '../protocol/types';

interface ModelsState {
  models: ModelEntry[]; // 当前账号可选的模型；空表示后台没开这个功能
  current: string | null; // 正在使用的模型 id；null 表示跟随角色预设
  switching: boolean; // 已发 switch-model，等服务端确认
  thinking: string | null; // 当前模型的思考档位；null 表示该模型没有档位可选
  lastThinkingOn: Record<string, string>; // 每个模型上次开启思考时的强度，重新打开时回到它
  setList: (models: ModelEntry[], current: string | null, thinking: string | null) => void;
  requestSwitch: () => void;
  confirmSwitch: (current: string | null, thinking: string | null) => void;
  cancelSwitch: () => void;
  setThinking: (level: string) => void;
}

const OFF_IDS = new Set(['off', 'none']);

// 记下“开着思考”的档位，供关掉后再打开时恢复
const remember = (s: ModelsState, current: string | null, level: string | null) =>
  current && level && !OFF_IDS.has(level)
    ? { lastThinkingOn: { ...s.lastThinkingOn, [current]: level } }
    : {};

export const useModels = create<ModelsState>((set) => ({
  models: [],
  current: null,
  switching: false,
  thinking: null,
  lastThinkingOn: {},
  setList: (models, current, thinking) =>
    set((s) => ({ models, current, thinking, switching: false, ...remember(s, current, thinking) })),
  requestSwitch: () => set({ switching: true }),
  confirmSwitch: (current, thinking) =>
    set((s) => ({ current, thinking, switching: false, ...remember(s, current, thinking) })),
  setThinking: (thinking) => set((s) => ({ thinking, ...remember(s, s.current, thinking) })),
  cancelSwitch: () => set((s) => (s.switching ? { switching: false } : s)),
}));
