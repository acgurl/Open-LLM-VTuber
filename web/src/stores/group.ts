import { create } from 'zustand';

export interface GroupPeer {
  uid: string;
  seen: number;
}

interface GroupState {
  members: string[];
  isOwner: boolean;
  peers: GroupPeer[]; // 同账号其它标签页的 client_uid（BroadcastChannel 发现）
  setGroup: (members: string[], isOwner: boolean) => void;
  setPeers: (peers: GroupPeer[]) => void;
}

export const useGroup = create<GroupState>((set) => ({
  members: [],
  isOwner: false,
  peers: [],
  setGroup: (members, isOwner) => set({ members, isOwner }),
  setPeers: (peers) => set({ peers }),
}));
