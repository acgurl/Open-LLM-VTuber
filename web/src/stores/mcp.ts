import { create } from 'zustand';
import type { MCPConfig, MCPServerSummary } from '../services/mcp';

export type LocalMcpConnectionStatus = 'connecting' | 'connected' | 'error';

export interface LocalMcpServerStatus {
  serverId: string;
  name: string;
  url: string;
  status: LocalMcpConnectionStatus;
  toolCount: number;
  tools: string[];
  error: string;
}

interface McpState {
  config: MCPConfig | null;
  servers: MCPServerSummary[];
  loading: boolean;
  localServers: LocalMcpServerStatus[];
  setConfigResponse: (response: {
    config: MCPConfig;
    servers: MCPServerSummary[];
  }) => void;
  setLoading: (loading: boolean) => void;
  retainLocalServers: (ids: Set<string>) => void;
  upsertLocalServer: (server: {
    server_id: string;
    name: string;
    url: string;
  }) => void;
  setLocalServerStatus: (
    serverId: string,
    status: LocalMcpConnectionStatus,
    extra?: { toolCount?: number; tools?: string[]; error?: string },
  ) => void;
}

export const useMcp = create<McpState>((set) => ({
  config: null,
  servers: [],
  loading: false,
  localServers: [],
  setConfigResponse: ({ config, servers }) => set({ config, servers }),
  setLoading: (loading) => set({ loading }),
  retainLocalServers: (ids) =>
    set((state) => ({
      localServers: state.localServers.filter((server) =>
        ids.has(server.serverId),
      ),
    })),
  upsertLocalServer: (server) =>
    set((state) => {
      const existing = state.localServers.find(
        (item) => item.serverId === server.server_id,
      );
      if (existing) {
        return {
          localServers: state.localServers.map((item) =>
            item.serverId === server.server_id
              ? { ...item, name: server.name, url: server.url }
              : item,
          ),
        };
      }
      return {
        localServers: [
          ...state.localServers,
          {
            serverId: server.server_id,
            name: server.name,
            url: server.url,
            status: 'connecting',
            toolCount: 0,
            tools: [],
            error: '',
          },
        ],
      };
    }),
  setLocalServerStatus: (serverId, status, extra) =>
    set((state) => ({
      localServers: state.localServers.map((server) =>
        server.serverId === serverId
          ? {
              ...server,
              status,
              ...(extra?.toolCount !== undefined
                ? { toolCount: extra.toolCount }
                : {}),
              ...(extra?.tools !== undefined ? { tools: extra.tools } : {}),
              ...(extra?.error !== undefined ? { error: extra.error } : {}),
              ...(status === 'connected' || status === 'connecting'
                ? { error: '' }
                : {}),
            }
          : server,
      ),
    })),
}));
