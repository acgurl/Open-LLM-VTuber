import { useMcp } from '../stores/mcp';
import type { LocalMcpServerConfig, ServerMessage } from '../protocol/types';
import { wsClient } from './websocket';
import {
  LocalMcpClient,
  type LocalMcpClientLike,
  localMcpErrorMessage,
} from './localMcpClient';
import { LocalSseMcpClient } from './localSseMcpClient';

interface ClientEntry {
  client: LocalMcpClientLike;
  fingerprint: string;
}

function createClient(config: LocalMcpServerConfig): LocalMcpClientLike {
  if (config.transport === 'sse') {
    return new LocalSseMcpClient(config.url, config.headers);
  }
  return new LocalMcpClient(config.url, config.headers);
}

const clients = new Map<string, ClientEntry>();
let queue: Promise<void> = Promise.resolve();

function fingerprint(config: LocalMcpServerConfig): string {
  return `${config.transport}\n${config.url}\n${JSON.stringify(
    config.headers ?? {},
  )}`;
}

async function registerServer(config: LocalMcpServerConfig): Promise<void> {
  const store = useMcp.getState();
  store.setLocalServerStatus(config.server_id, 'connecting');

  try {
    const expected = fingerprint(config);
    let entry = clients.get(config.server_id);
    if (entry && entry.fingerprint !== expected) {
      await entry.client.close();
      clients.delete(config.server_id);
      entry = undefined;
    }

    if (!entry) {
      const client = createClient(config);
      await client.initialize();
      entry = { client, fingerprint: expected };
      clients.set(config.server_id, entry);
    }

    let tools;
    try {
      tools = await entry.client.listTools();
    } catch {
      // The local MCP session may have expired while the socket was down.
      await entry.client.close();
      const client = createClient(config);
      await client.initialize();
      entry = { client, fingerprint: expected };
      clients.set(config.server_id, entry);
      tools = await client.listTools();
    }

    const sent = wsClient.send({
      type: 'register-local-mcp',
      server_id: config.server_id,
      name: config.name,
      tools: tools.map((tool) => ({
        name: tool.name,
        description: tool.description ?? '',
        inputSchema:
          tool.inputSchema ?? { type: 'object', properties: {} },
      })),
    });
    if (!sent) throw new Error('WebSocket 未连接');
    store.setLocalServerStatus(config.server_id, 'connecting', {
      toolCount: tools.length,
    });
  } catch (error) {
    store.setLocalServerStatus(config.server_id, 'error', {
      error: localMcpErrorMessage(error),
    });
  }
}

async function applyConfig(servers: LocalMcpServerConfig[]): Promise<void> {
  const ids = new Set(servers.map((server) => server.server_id));

  for (const [serverId, entry] of Array.from(clients.entries())) {
    if (!ids.has(serverId)) {
      await entry.client.close();
      clients.delete(serverId);
    }
  }

  useMcp.getState().retainLocalServers(ids);
  for (const server of servers) {
    useMcp.getState().upsertLocalServer(server);
  }
  await Promise.all(servers.map((server) => registerServer(server)));
}

export function configureLocalMcpServers(
  servers: LocalMcpServerConfig[],
): Promise<void> {
  queue = queue.then(() => applyConfig(servers)).catch(() => undefined);
  return queue;
}

export async function handleLocalToolCall(
  message: Extract<ServerMessage, { type: 'local-tool-call' }>,
): Promise<void> {
  const reply = (
    isError: boolean,
    contentItems: Array<Record<string, unknown>>,
  ) => {
    wsClient.send({
      type: 'local-tool-result',
      request_id: message.request_id,
      server_id: message.server_id,
      is_error: isError,
      content_items: contentItems,
    });
  };

  const entry = clients.get(message.server_id);
  if (!entry) {
    reply(true, [{ type: 'error', text: '本地 MCP 未连接' }]);
    return;
  }

  try {
    const result = await entry.client.callTool(
      message.tool_name,
      message.arguments ?? {},
    );
    reply(result.isError, result.contentItems);
  } catch (error) {
    reply(true, [{ type: 'error', text: localMcpErrorMessage(error) }]);
  }
}

export function onLocalMcpRegistered(
  message: Extract<ServerMessage, { type: 'local-mcp-registered' }>,
): void {
  useMcp.getState().setLocalServerStatus(message.server_id, 'connected', {
    toolCount: message.tools.length,
    tools: message.tools,
  });
}

export function onLocalMcpError(
  message: Extract<ServerMessage, { type: 'local-mcp-error' }>,
): void {
  useMcp.getState().setLocalServerStatus(message.server_id, 'error', {
    error: message.message,
  });
}

export function onLocalMcpUnregistered(
  message: Extract<ServerMessage, { type: 'local-mcp-unregistered' }>,
): void {
  if (!message.success) return;
  // The next local-mcp-config will reconcile the list; nothing else to do.
}
