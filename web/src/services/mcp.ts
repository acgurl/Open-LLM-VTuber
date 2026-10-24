import { redirectToLogin } from './session';

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
}

export interface MCPConfigResponse {
  config: MCPConfig;
  servers: MCPServerSummary[];
}

export interface MCPToolSummary {
  name: string;
  description?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    if (response.status === 401) redirectToLogin();
    const message =
      data && typeof data === 'object' && typeof (data as { error?: unknown }).error === 'string'
        ? (data as { error: string }).error
        : `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return data as T;
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
