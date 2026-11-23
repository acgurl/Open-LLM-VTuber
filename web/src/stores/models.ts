import { create } from 'zustand';
import type { ModelEntry, ModelKind } from '../protocol/types';

interface ModelCatalog {
  options: ModelEntry[];
  current: string | null; // null 表示跟随角色预设
  characterDefault?: ModelEntry;
}

interface ModelSwitch {
  kind: ModelKind;
  id: string | null;
}

interface ModelsState {
  catalogs: Record<ModelKind, ModelCatalog>;
  pending: ModelSwitch | null;
  thinking: string | null; // 当前 LLM 的思考档位
  lastThinkingOn: Record<string, string>;
  setList: (catalogs: ModelsState['catalogs'], thinking: string | null) => void;
  requestSwitch: (request: ModelSwitch) => void;
  confirmSwitch: (kind: ModelKind, current: string | null, thinking: string | null) => void;
  cancelSwitch: (kind?: ModelKind) => void;
  setThinking: (level: string) => void;
}

const OFF_IDS = new Set(['off', 'none']);

// 记下“开着思考”的档位，供关掉后再打开时恢复。
const remember = (s: ModelsState, current: string | null, level: string | null) =>
  current && level && !OFF_IDS.has(level)
    ? { lastThinkingOn: { ...s.lastThinkingOn, [current]: level } }
    : {};

export const useModels = create<ModelsState>((set) => ({
  catalogs: {
    llm: { options: [], current: null },
    tts: { options: [], current: null },
    asr: { options: [], current: null },
  },
  pending: null,
  thinking: null,
  lastThinkingOn: {},
  // 异步目录刷新不是切换回执，不能把尚未完成的切换提前解锁。
  setList: (catalogs, thinking) =>
    set((s) => ({ catalogs, thinking, ...remember(s, catalogs.llm.current ?? catalogs.llm.characterDefault?.id ?? null, thinking) })),
  requestSwitch: (pending) => set({ pending }),
  confirmSwitch: (kind, current, thinking) => set((s) => ({
    catalogs: { ...s.catalogs, [kind]: { ...s.catalogs[kind], current } },
    pending: s.pending?.kind === kind ? null : s.pending,
    ...(kind === 'llm' ? { thinking, ...remember(s, current ?? s.catalogs.llm.characterDefault?.id ?? null, thinking) } : {}),
  })),
  cancelSwitch: (kind) => set((s) =>
    s.pending && (kind === undefined || s.pending.kind === kind) ? { pending: null } : s,
  ),
  setThinking: (thinking) => set((s) => ({
    thinking,
    ...remember(s, s.catalogs.llm.current ?? s.catalogs.llm.characterDefault?.id ?? null, thinking),
  })),
}));
