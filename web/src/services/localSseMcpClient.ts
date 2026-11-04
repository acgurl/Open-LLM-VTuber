// Legacy MCP HTTP+SSE client for a server running in the user's browser.
//
// Flow: GET the SSE URL, the server sends an `endpoint` event, JSON-RPC
// requests are POSTed to that endpoint, and responses arrive on the SSE
// stream. Query parameters from the original URL (for example `?key=...`)
// are also appended to the endpoint because many local SSE servers use them
// for authentication on both paths.

import {
  CLIENT_INFO,
  PROTOCOL_VERSION,
  type JsonRpcMessage,
  type LocalMcpCallResult,
  type LocalMcpClientLike,
  type LocalMcpTool,
  callToolVia,
  errorFromHttp,
  filterCustomHeaders,
  listToolsPaged,
  parseSseEvent,
  type SseEvent,
  takeSseFrames,
} from './localMcpClient';

interface PendingRequest {
  resolve: (message: JsonRpcMessage) => void;
  reject: (error: Error) => void;
  timer: number;
}

export class LocalSseMcpClient implements LocalMcpClientLike {
  private readonly url: URL;
  private readonly customHeaders: Record<string, string>;
  private readonly abort = new AbortController();
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private endpoint: URL | null = null;
  private endpointReady: Promise<void>;
  private resolveEndpoint!: () => void;
  private rejectEndpoint!: (error: Error) => void;
  private nextId = 1;
  private readonly pending = new Map<string, PendingRequest>();
  private closed = false;

  constructor(url: string, headers: Record<string, string> = {}) {
    this.url = new URL(url);
    this.customHeaders = filterCustomHeaders(headers);
    this.endpointReady = new Promise((resolve, reject) => {
      this.resolveEndpoint = resolve;
      this.rejectEndpoint = reject;
    });
  }

  async initialize(): Promise<void> {
    await this.openStream();
    await this.request(
      'initialize',
      {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: CLIENT_INFO,
      },
      10_000,
    );
    await this.notify('notifications/initialized');
  }

  async listTools(): Promise<LocalMcpTool[]> {
    return listToolsPaged(this.request.bind(this), '本地 SSE MCP');
  }

  async callTool(
    name: string,
    args: Record<string, unknown>,
  ): Promise<LocalMcpCallResult> {
    return callToolVia(this.request.bind(this), '本地 SSE MCP', name, args);
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.abort.abort();
    this.rejectAllPending(new Error('本地 SSE MCP 已断开'));
    try {
      await this.reader?.cancel();
    } catch {
      /* ignore */
    }
  }

  private async openStream(): Promise<void> {
    const response = await fetch(this.url, {
      method: 'GET',
      headers: {
        ...this.customHeaders,
        Accept: 'text/event-stream',
      },
      credentials: 'omit',
      signal: this.abort.signal,
    });
    if (!response.ok) {
      throw errorFromHttp(response.status, await response.text());
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error('本地 SSE MCP 没有返回可读流');
    this.reader = reader;
    void this.readLoop(reader);
    let timer: number | undefined;
    try {
      await Promise.race([
        this.endpointReady,
        new Promise<never>((_, reject) => {
          timer = window.setTimeout(
            () => reject(new Error('本地 SSE MCP 未返回消息端点')),
            15_000,
          );
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  private async readLoop(
    reader: ReadableStreamDefaultReader<Uint8Array>,
  ): Promise<void> {
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (!this.closed) {
        const { value, done } = await reader.read();
        if (done) break;
        const { frames, rest } = takeSseFrames(
          buffer + decoder.decode(value, { stream: true }),
        );
        buffer = rest;
        for (const frame of frames) this.handleEvent(parseSseEvent(frame));
      }
      if (!this.closed) {
        // The server ended the stream: no response can arrive any more, so
        // fail pending and future requests now instead of waiting for timeouts.
        this.closed = true;
        const reason = new Error('本地 SSE MCP 连接已关闭');
        this.rejectEndpoint(reason);
        this.rejectAllPending(reason);
      }
    } catch (error) {
      if (this.closed) return;
      const reason =
        error instanceof Error ? error : new Error(String(error));
      this.rejectEndpoint(reason);
      this.rejectAllPending(reason);
    }
  }

  private rejectAllPending(reason: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(reason);
    }
    this.pending.clear();
  }

  /** Forget a request whose POST failed; the caller gets the POST error instead. */
  private dropPending(id: number): void {
    const pending = this.pending.get(String(id));
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(String(id));
  }

  private handleEvent(event: SseEvent | null): void {
    if (!event) return;
    if (event.event === 'endpoint') {
      const endpoint = new URL(event.data, this.url);
      for (const [key, value] of this.url.searchParams) {
        if (!endpoint.searchParams.has(key)) {
          endpoint.searchParams.set(key, value);
        }
      }
      this.endpoint = endpoint;
      this.resolveEndpoint();
      return;
    }

    try {
      const message = JSON.parse(event.data) as JsonRpcMessage;
      if (message.id === undefined) return;
      const pending = this.pending.get(String(message.id));
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(String(message.id));
      pending.resolve(message);
    } catch {
      /* ignore comments, pings and non-JSON events */
    }
  }

  private async request(
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<JsonRpcMessage> {
    await this.endpointReady;
    if (!this.endpoint) throw new Error('本地 SSE MCP 未提供消息端点');
    if (this.closed) throw new Error('本地 SSE MCP 连接已关闭');

    const id = this.nextId++;
    const promise = new Promise<JsonRpcMessage>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(String(id));
        reject(new Error('本地 SSE MCP 响应超时'));
      }, timeoutMs);
      this.pending.set(String(id), { resolve, reject, timer });
    });

    let response: Response;
    try {
      response = await fetch(this.endpoint, {
        method: 'POST',
        headers: {
          ...this.customHeaders,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
        credentials: 'omit',
        signal: this.abort.signal,
      });
    } catch (error) {
      this.dropPending(id);
      throw error;
    }
    if (!response.ok && response.status !== 202) {
      this.dropPending(id);
      throw errorFromHttp(response.status, await response.text());
    }
    return promise;
  }

  private async notify(method: string): Promise<void> {
    await this.endpointReady;
    if (!this.endpoint) throw new Error('本地 SSE MCP 未提供消息端点');
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: {
        ...this.customHeaders,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ jsonrpc: '2.0', method }),
      credentials: 'omit',
      signal: this.abort.signal,
    });
    if (!response.ok && response.status !== 202) {
      throw errorFromHttp(response.status, await response.text());
    }
  }
}
