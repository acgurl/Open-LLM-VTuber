import { request } from './api';

export type MCPServerMode = 'local' | 'remote';

export interface MCPServerEntry {
  url: string;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerEntry>;
}

export interface MCPServerSummary {
  id: string;
  name: string;
  url: string;
  headers: Record<string, string>; // values are masked as "***"
  enabled: boolean;
  mode: MCPServerMode;
  transport: 'http' | 'sse';
}

export interface MCPConfigResponse {
  config: MCPConfig;
  servers: MCPServerSummary[];
}

export interface MCPToolSummary {
  name: string;
  description?: string;
}

export async function fetchUserMcpConfig(): Promise<MCPConfigResponse> {
  return request<MCPConfigResponse>('/api/mcp/config');
}

export async function saveUserMcpConfig(
  config: MCPConfig,
): Promise<MCPConfigResponse> {
  return request<MCPConfigResponse>('/api/mcp/config', {
    method: 'PUT',
    body: JSON.stringify({ config }),
  });
}

export async function testUserMcpServer(
  serverId: string,
): Promise<{ mode: MCPServerMode; tools: MCPToolSummary[] }> {
  return request<{ mode: MCPServerMode; tools: MCPToolSummary[] }>(
    '/api/mcp/config/test',
    {
      method: 'POST',
      body: JSON.stringify({ server_id: serverId }),
    },
  );
}
