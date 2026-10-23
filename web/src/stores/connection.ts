import { create } from 'zustand';
import type { ModelInfo } from '../protocol/types';

export type ConnectionStatus =
  | 'boot' // 还在做 session 探测
  | 'connecting'
  | 'online'
  | 'reconnecting'
  | 'unauthorized'
  | 'failed';

interface ConnectionState {
  status: ConnectionStatus;
  clientUid: string | null;
  modelInfo: ModelInfo | null;
  confName: string;
  confUid: string;
  displayName: string; // 登录用户显示名
  statusText: string; // full-text 状态提示（Thinking... 等）
  busy: boolean; // conversation-chain-start ~ end 之间
  setStatus: (s: ConnectionStatus) => void;
  setClientUid: (uid: string | null) => void;
  setModelConf: (info: ModelInfo, confName: string, confUid: string) => void;
  setDisplayName: (n: string) => void;
  setStatusText: (t: string) => void;
  setBusy: (b: boolean) => void;
}

export const useConnection = create<ConnectionState>((set) => ({
  status: 'boot',
  clientUid: null,
  modelInfo: null,
  confName: '',
  confUid: '',
  displayName: '',
  statusText: '',
  busy: false,
  setStatus: (status) => set({ status }),
  setClientUid: (clientUid) => set({ clientUid }),
  setModelConf: (modelInfo, confName, confUid) => set({ modelInfo, confName, confUid }),
  setDisplayName: (displayName) => set({ displayName }),
  setStatusText: (statusText) => set({ statusText }),
  setBusy: (busy) => set({ busy }),
}));
