// Minimal MCP Streamable HTTP client that runs in the browser.
// The backend never dials the user's localhost; the browser does, and only
// schemas/results travel over /client-ws.

export interface LocalMcpTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface LocalMcpCallResult {
  contentItems: Array<Record<string, unknown>>;
  isError: boolean;
}

export interface LocalMcpClientLike {
  initialize(): Promise<void>;
  listTools(): Promise<LocalMcpTool[]>;
  callTool(
    name: string,
    args: Record<string, unknown>,
  ): Promise<LocalMcpCallResult>;
  close(): Promise<void>;
}

export interface JsonRpcMessage {
  jsonrpc?: string;
  id?: number | string;
  result?: unknown;
  error?: { code?: number; message?: string };
}

export const PROTOCOL_VERSION = '2025-03-26';
export const CLIENT_INFO = { name: 'ollmvt-web', version: '1.0.0' };
const MAX_TOOLS = 200;
const MAX_PAGES = 10;
const RESERVED_HEADERS = new Set([
  'accept',
  'content-type',
  'mcp-protocol-version',
  'mcp-session-id',
]);

export function localMcpErrorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return '本地 MCP 响应超时';
  }
  if (error instanceof TypeError) {
    return '无法连接本地 MCP：请确认服务已启动、允许本站跨域；HTTPS 页面可能需要在浏览器允许本地网络访问';
  }
  if (error instanceof Error) return error.message;
  return '本地 MCP 连接失败';
}

function timeoutSignal(ms: number): AbortSignal {
  return AbortSignal.timeout(ms);
}

function parseSseMessage(chunk: string): JsonRpcMessage | null {
  const data = chunk
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
  if (!data) return null;
  try {
    const parsed = JSON.parse(data);
    return parsed && typeof parsed === 'object' ? (parsed as JsonRpcMessage) : null;
  } catch {
    return null;
  }
}

export function filterCustomHeaders(
  headers: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(headers).filter(
      ([key]) => !RESERVED_HEADERS.has(key.toLowerCase()),
    ),
  );
}

export function normalizeContent(
  items: unknown[],
): Array<Record<string, unknown>> {
  const normalized: Array<Record<string, unknown>> = [];
  for (const item of items.slice(0, 64)) {
    if (!item || typeof item !== 'object') continue;
    const record = item as Record<string, unknown>;
    if (record.type === 'resource' && record.resource && typeof record.resource === 'object') {
      const resource = record.resource as Record<string, unknown>;
      normalized.push({
        type: 'text',
        text:
          typeof resource.text === 'string'
            ? resource.text
            : JSON.stringify(resource),
      });
      continue;
    }
    const out: Record<string, unknown> = {
      type: typeof record.type === 'string' ? record.type : 'text',
    };
    for (const key of ['text', 'data', 'mimeType', 'url', 'altText'] as const) {
      if (typeof record[key] === 'string') out[key] = record[key];
    }
    normalized.push(out);
  }
  return normalized;
}

export function errorFromHttp(status: number, body: string): Error {
  if (status === 401 || status === 403) {
    return new Error('本地 MCP 拒绝了网页请求（检查 CORS / Origin 配置）');
  }
  const detail = body.trim().slice(0, 200);
  return new Error(`本地 MCP 返回 HTTP ${status}${detail ? `：${detail}` : ''}`);
}

type RpcRequest = (
  method: string,
  params: Record<string, unknown>,
  timeoutMs: number,
) => Promise<JsonRpcMessage>;

/** Page through `tools/list`, skipping duplicate names and capping the total. */
export async function listToolsPaged(
  request: RpcRequest,
  label: string,
): Promise<LocalMcpTool[]> {
  const tools: LocalMcpTool[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const params = cursor ? { cursor } : {};
    const response = await request('tools/list', params, 15_000);
    const result = response.result;
    const pageTools =
      result && typeof result === 'object'
        ? (result as Record<string, unknown>).tools
        : undefined;
    if (!Array.isArray(pageTools)) {
      throw new Error(`${label} 返回了无效的工具列表`);
    }
    for (const tool of pageTools) {
      if (!tool || typeof tool !== 'object') continue;
      const record = tool as Record<string, unknown>;
      if (typeof record.name !== 'string' || seen.has(record.name)) continue;
      seen.add(record.name);
      tools.push({
        name: record.name,
        description: typeof record.description === 'string' ? record.description : '',
        inputSchema:
          record.inputSchema && typeof record.inputSchema === 'object'
            ? (record.inputSchema as Record<string, unknown>)
            : { type: 'object', properties: {} },
      });
      if (tools.length >= MAX_TOOLS) return tools;
    }
    const next =
      result && typeof result === 'object'
        ? (result as Record<string, unknown>).nextCursor
        : undefined;
    cursor = typeof next === 'string' && next ? next : undefined;
    if (!cursor) break;
  }
  return tools;
}

/** Issue `tools/call` and normalize the returned content items. */
export async function callToolVia(
  request: RpcRequest,
  label: string,
  name: string,
  args: Record<string, unknown>,
): Promise<LocalMcpCallResult> {
  const response = await request(
    'tools/call',
    { name, arguments: args ?? {} },
    35_000,
  );
  if (response.error) {
    throw new Error(response.error.message || `${label} 工具调用失败`);
  }
  const result = response.result;
  if (!result || typeof result !== 'object') {
    throw new Error(`${label} 未返回结果`);
  }
  const record = result as Record<string, unknown>;
  const items = Array.isArray(record.content) ? record.content : [];
  const normalized = normalizeContent(items);
  return {
    contentItems:
      normalized.length > 0 ? normalized : [{ type: 'text', text: '' }],
    isError: Boolean(record.isError),
  };
}

export class LocalMcpClient implements LocalMcpClientLike {
  private readonly url: string;
  private readonly customHeaders: Record<string, string>;
  private sessionId: string | null = null;
  private protocolVersion = PROTOCOL_VERSION;
  private initialized = false;
  private nextId = 1;

  constructor(url: string, headers: Record<string, string> = {}) {
    this.url = url;
    this.customHeaders = filterCustomHeaders(headers);
  }

  async initialize(): Promise<void> {
    const response = await this.request(
      'initialize',
      {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: CLIENT_INFO,
      },
      10_000,
    );
    const result = response.result;
    if (result && typeof result === 'object') {
      const version = (result as Record<string, unknown>).protocolVersion;
      if (typeof version === 'string' && version) this.protocolVersion = version;
    }
    await this.notify('notifications/initialized');
    this.initialized = true;
  }

  async listTools(): Promise<LocalMcpTool[]> {
    return listToolsPaged(this.request.bind(this), '本地 MCP');
  }

  async callTool(
    name: string,
    args: Record<string, unknown>,
  ): Promise<LocalMcpCallResult> {
    return callToolVia(this.request.bind(this), '本地 MCP', name, args);
  }

  async close(): Promise<void> {
    const sessionId = this.sessionId;
    this.sessionId = null;
    this.initialized = false;
    if (!sessionId) return;
    try {
      await fetch(this.url, {
        method: 'DELETE',
        headers: this.headers(),
        credentials: 'omit',
        signal: timeoutSignal(3000),
      });
    } catch {
      /* best effort */
    }
  }

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      ...this.customHeaders,
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
    };
    if (this.sessionId) headers['Mcp-Session-Id'] = this.sessionId;
    if (this.initialized) headers['MCP-Protocol-Version'] = this.protocolVersion;
    return headers;
  }

  private captureSession(response: Response): void {
    const sessionId = response.headers.get('Mcp-Session-Id');
    if (sessionId) this.sessionId = sessionId;
  }

  private async notify(method: string): Promise<void> {
    const response = await fetch(this.url, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ jsonrpc: '2.0', method }),
      credentials: 'omit',
      signal: timeoutSignal(5000),
    });
    this.captureSession(response);
    if (!response.ok && response.status !== 202) {
      throw errorFromHttp(response.status, await response.text());
    }
  }

  private async request(
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<JsonRpcMessage> {
    const id = this.nextId++;
    const response = await fetch(this.url, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
      credentials: 'omit',
      signal: timeoutSignal(timeoutMs),
    });
    this.captureSession(response);
    if (response.status === 202) return { jsonrpc: '2.0', id };
    if (!response.ok) {
      throw errorFromHttp(response.status, await response.text());
    }

    const contentType = response.headers.get('content-type') ?? '';
    const message = contentType.includes('text/event-stream')
      ? await this.readSse(response, id, timeoutMs)
      : await this.readJson(response, id);
    if (message.error) {
      throw new Error(message.error.message || '本地 MCP 请求失败');
    }
    return message;
  }

  private async readJson(response: Response, id: number): Promise<JsonRpcMessage> {
    const data: unknown = await response.json();
    if (Array.isArray(data)) {
      const match = data.find(
        (item) => item && typeof item === 'object' && (item as JsonRpcMessage).id === id,
      );
      if (!match) throw new Error('本地 MCP 返回了不匹配的响应');
      return match as JsonRpcMessage;
    }
    if (!data || typeof data !== 'object') {
      throw new Error('本地 MCP 返回了无效响应');
    }
    return data as JsonRpcMessage;
  }

  private async readSse(
    response: Response,
    id: number,
    timeoutMs: number,
  ): Promise<JsonRpcMessage> {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('本地 MCP 没有返回可读流');
    const decoder = new TextDecoder();
    let buffer = '';
    const deadline = Date.now() + timeoutMs;
    try {
      while (Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.search(/\r?\n\r?\n/);
        while (boundary !== -1) {
          const chunk = buffer.slice(0, boundary);
          const match = buffer.slice(boundary).match(/^\r?\n\r?\n/);
          buffer = buffer.slice(boundary + (match ? match[0].length : 0));
          const message = parseSseMessage(chunk);
          if (message && message.id === id) return message;
          boundary = buffer.search(/\r?\n\r?\n/);
        }
      }
      throw new Error('本地 MCP 响应超时');
    } finally {
      try {
        await reader.cancel();
      } catch {
        /* ignore */
      }
    }
  }
}
