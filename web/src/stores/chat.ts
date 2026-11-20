import { create } from 'zustand';
import type { HistoryToolCall } from '../protocol/types';
import { parsePlaces, placeKey, type Place } from '../utils/places';

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

// 地点卡：工具结果里带 places 时派生出的独立条目，插在工具卡之后、回答之前。
// 工具卡完成会自动折叠，地图不能藏在折叠详情里，所以与工具卡同级而不是嵌套。
export interface PlaceEntry {
  kind: 'place';
  id: string;
  tool_id: string;
  places: Place[];
  timestamp: string;
}

export type ChatEntry = ChatTextEntry | ToolEntry | PlaceEntry;

let seq = 0;
const nextId = () => `e${Date.now().toString(36)}_${seq++}`;

const makePlaceEntry = (
  t: { tool_id: string; content: string; timestamp: string },
  seen: Set<string>,
): PlaceEntry | null => {
  const places = parsePlaces(t.content).filter((p) => {
    const key = placeKey(p);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (places.length === 0) return null;
  return { kind: 'place', id: nextId(), tool_id: t.tool_id, places, timestamp: t.timestamp };
};

// 同一轮里并行/重复的工具调用可能返回相同地点：只与本轮已展示的地点去重
const turnSeenKeys = (entries: ChatEntry[]): Set<string> => {
  const seen = new Set<string>();
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const e = entries[i];
    if (e.kind === 'text' && e.role === 'human') break;
    if (e.kind === 'place') e.places.forEach((p) => seen.add(placeKey(p)));
  }
  return seen;
};

// 工具卡会插在文本气泡之后，流式气泡不一定在队尾，收尾时必须全量清理
const stopStreaming = (entries: ChatEntry[]): ChatEntry[] => {
  if (!entries.some((e) => e.kind === 'text' && e.streaming)) return entries;
  return entries.map((e) => (e.kind === 'text' && e.streaming ? { ...e, streaming: false } : e));
};

interface ChatState {
  entries: ChatEntry[];
  addUserMessage: (text: string, name?: string) => void;
  addAiMessage: (text: string, name?: string, avatar?: string) => void;
  appendAiDelta: (delta: string, name?: string, avatar?: string) => void;
  finalizeStream: () => void;
  upsertTool: (t: Omit<ToolEntry, 'kind' | 'id'>) => void;
  loadHistory: (
    msgs: { role: string; content: string; name?: string; avatar?: string; timestamp?: string }[],
    toolCalls?: HistoryToolCall[],
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

  addAiMessage: (text, name, avatar) =>
    set((s) => ({
      entries: [
        ...s.entries,
        { kind: 'text', id: nextId(), role: 'ai', text, name, avatar, ts: Date.now() },
      ],
    })),

  appendAiDelta: (delta, name, avatar) =>
    set((s) => {
      const last = s.entries[s.entries.length - 1];
      if (last && last.kind === 'text' && last.role === 'ai' && last.streaming) {
        return { entries: [...s.entries.slice(0, -1), { ...last, text: last.text + delta }] };
      }
      // 旧气泡已被工具卡或消息隔断，不再增长，先收尾再另起一条
      return {
        entries: [
          ...stopStreaming(s.entries),
          {
            kind: 'text',
            id: nextId(),
            role: 'ai',
            text: delta,
            name,
            avatar,
            ts: Date.now(),
            streaming: true,
          },
        ],
      };
    }),

  finalizeStream: () => set((s) => ({ entries: stopStreaming(s.entries) })),

  upsertTool: (t) =>
    set((s) => {
      const idx = s.entries.findIndex((e) => e.kind === 'tool' && e.tool_id === t.tool_id);
      let entries: ChatEntry[];
      let toolIdx: number;
      if (idx >= 0) {
        entries = [...s.entries];
        entries[idx] = { ...(entries[idx] as ToolEntry), ...t };
        toolIdx = idx;
      } else {
        // 新工具卡意味着这段文本已经说完，后续 text-delta 会另起气泡
        entries = [...stopStreaming(s.entries), { kind: 'tool', id: nextId(), ...t }];
        toolIdx = entries.length - 1;
      }
      // 完成态才解析地点：running 的 content 只是入参，没有结果
      if (
        t.status === 'completed' &&
        !entries.some((e) => e.kind === 'place' && e.tool_id === t.tool_id)
      ) {
        const place = makePlaceEntry(t, turnSeenKeys(entries));
        if (place) entries.splice(toolIdx + 1, 0, place);
      }
      return { entries };
    }),

  // 历史里的工具卡没有独立消息位：按 turn_index 挂回对应提问之后，
  // 这样刷新后工具卡仍出现在「问题之后、回答之前」。
  loadHistory: (msgs, toolCalls = []) =>
    set(() => {
      const byTurn = new Map<number, HistoryToolCall[]>();
      for (const call of toolCalls) {
        const list = byTurn.get(call.turn_index) ?? [];
        list.push(call);
        byTurn.set(call.turn_index, list);
      }

      const toolEntries = (turn: number): ChatEntry[] => {
        const seen = new Set<string>();
        const out: ChatEntry[] = [];
        for (const call of byTurn.get(turn) ?? []) {
          out.push({
            kind: 'tool',
            id: nextId(),
            tool_id: call.tool_id,
            tool_name: call.tool_name,
            status: call.status,
            content: call.content,
            timestamp: call.timestamp,
          });
          // 历史里的 content 与直播同形状，地点卡刷新后同样能复原
          if (call.status === 'completed') {
            const place = makePlaceEntry(call, seen);
            if (place) out.push(place);
          }
        }
        return out;
      };

      const entries: ChatEntry[] = [];
      let turn = 0;
      for (const m of msgs) {
        if (m.role !== 'human' && m.role !== 'ai') continue;
        const parsed = m.timestamp ? Date.parse(m.timestamp) : NaN;
        entries.push({
          kind: 'text',
          id: nextId(),
          role: m.role,
          text: m.content,
          name: m.name,
          avatar: m.avatar,
          ts: Number.isFinite(parsed) ? parsed : Date.now(),
          streaming: false,
        });
        if (m.role === 'human') {
          entries.push(...toolEntries(turn));
          byTurn.delete(turn);
          turn += 1;
        }
      }
      // 找不到对应提问的调用（历史被裁剪等）放到末尾，至少不丢。
      [...byTurn.keys()]
        .sort((a, b) => a - b)
        .forEach((index) => entries.push(...toolEntries(index)));
      return { entries };
    }),

  clear: () => set({ entries: [] }),
}));
