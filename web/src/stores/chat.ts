import { create } from 'zustand';

export interface ChatTextEntry {
  kind: 'text';
  id: string;
  role: 'human' | 'ai';
  text: string;
  name?: string;
  avatar?: string;
  ts: number;
  streaming?: boolean;
}

export interface ToolEntry {
  kind: 'tool';
  id: string;
  tool_id: string;
  tool_name: string;
  status: 'running' | 'completed' | 'error';
  content: string;
  timestamp: string;
  name?: string;
}

export type ChatEntry = ChatTextEntry | ToolEntry;

let seq = 0;
const nextId = () => `e${Date.now().toString(36)}_${seq++}`;

interface ChatState {
  entries: ChatEntry[];
  addUserMessage: (text: string, name?: string) => void;
  appendAiDelta: (delta: string, name?: string, avatar?: string) => void;
  finalizeStream: () => void;
  upsertTool: (t: Omit<ToolEntry, 'kind' | 'id'>) => void;
  loadHistory: (
    msgs: { role: string; content: string; name?: string; avatar?: string; timestamp?: string }[],
  ) => void;
  clear: () => void;
}

export const useChat = create<ChatState>((set) => ({
  entries: [],

  addUserMessage: (text, name) =>
    set((s) => ({
      entries: [
        ...s.entries,
        { kind: 'text', id: nextId(), role: 'human', text, name, ts: Date.now() },
      ],
    })),

  appendAiDelta: (delta, name, avatar) =>
    set((s) => {
      const entries = [...s.entries];
      const last = entries[entries.length - 1];
      if (last && last.kind === 'text' && last.role === 'ai' && last.streaming) {
        entries[entries.length - 1] = { ...last, text: last.text + delta };
        return { entries };
      }
      entries.push({
        kind: 'text',
        id: nextId(),
        role: 'ai',
        text: delta,
        name,
        avatar,
        ts: Date.now(),
        streaming: true,
      });
      return { entries };
    }),

  finalizeStream: () =>
    set((s) => {
      const entries = [...s.entries];
      const last = entries[entries.length - 1];
      if (last && last.kind === 'text' && last.streaming) {
        entries[entries.length - 1] = { ...last, streaming: false };
      }
      return { entries };
    }),

  upsertTool: (t) =>
    set((s) => {
      const idx = s.entries.findIndex((e) => e.kind === 'tool' && e.tool_id === t.tool_id);
      if (idx >= 0) {
        const entries = [...s.entries];
        entries[idx] = { ...(entries[idx] as ToolEntry), ...t };
        return { entries };
      }
      return { entries: [...s.entries, { kind: 'tool', id: nextId(), ...t }] };
    }),

  loadHistory: (msgs) =>
    set(() => ({
      entries: msgs
        .filter((m) => m.role === 'human' || m.role === 'ai')
        .map((m) => {
          const parsed = m.timestamp ? Date.parse(m.timestamp) : NaN;
          return {
            kind: 'text' as const,
            id: nextId(),
            role: m.role as 'human' | 'ai',
            text: m.content,
            name: m.name,
            avatar: m.avatar,
            ts: Number.isFinite(parsed) ? parsed : Date.now(),
            streaming: false,
          };
        }),
    })),

  clear: () => set({ entries: [] }),
}));
