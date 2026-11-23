import { describe, expect, it, vi } from 'vitest';
import {
  callToolVia,
  errorFromHttp,
  filterCustomHeaders,
  listToolsPaged,
  localMcpErrorMessage,
  parseSseEvent,
  takeSseFrames,
} from './localMcpClient';

describe('takeSseFrames and parseSseEvent', () => {
  it('splits CRLF and LF SSE frames while keeping incomplete tail', () => {
    const raw = 'event: endpoint\r\ndata: /msg\r\n\r\ndata: {"id":1}\n\ndata: partial';
    expect(takeSseFrames(raw)).toEqual({
      frames: ['event: endpoint\r\ndata: /msg', 'data: {"id":1}'],
      rest: 'data: partial',
    });
  });

  it('parses event type, skips comment lines, and joins multi-line data', () => {
    const chunk = ': keepalive\nevent: custom\ndata: line 1\ndata:  line 2';
    expect(parseSseEvent(chunk)).toEqual({
      event: 'custom',
      data: 'line 1\nline 2',
    });
    expect(parseSseEvent(': only comment')).toBeNull();
  });
});

describe('header filtering and error formatting', () => {
  it('strips reserved MCP transport headers case-insensitively', () => {
    expect(
      filterCustomHeaders({
        Authorization: 'Bearer secret',
        'Content-Type': 'text/plain',
        'MCP-Session-Id': '123',
        Accept: 'application/json',
        'X-Custom': 'ok',
      }),
    ).toEqual({
      Authorization: 'Bearer secret',
      'X-Custom': 'ok',
    });
  });

  it('formats CORS/auth errors and generic HTTP errors', () => {
    expect(errorFromHttp(403, 'denied').message).toContain('CORS / Origin');
    expect(errorFromHttp(500, '  server boom  ').message).toBe(
      '本地 MCP 返回 HTTP 500：server boom',
    );
    expect(localMcpErrorMessage(new DOMException('aborted', 'AbortError'))).toBe(
      '本地 MCP 响应超时',
    );
    expect(localMcpErrorMessage(new TypeError('Failed to fetch'))).toContain(
      '无法连接本地 MCP',
    );
  });
});

describe('listToolsPaged', () => {
  it('pages across cursors, deduplicates names, and supplies default schema', async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        result: {
          tools: [
            { name: 'search', description: 'Search docs' },
            { description: 'missing name' },
          ],
          nextCursor: 'page-2',
        },
      })
      .mockResolvedValueOnce({
        result: {
          tools: [
            { name: 'search', description: 'Duplicate' },
            {
              name: 'fetch',
              inputSchema: { type: 'object', properties: { url: { type: 'string' } } },
            },
          ],
        },
      });

    const tools = await listToolsPaged(request, '本地 MCP');
    expect(request).toHaveBeenNthCalledWith(1, 'tools/list', {}, 15_000);
    expect(request).toHaveBeenNthCalledWith(2, 'tools/list', { cursor: 'page-2' }, 15_000);
    expect(tools).toEqual([
      {
        name: 'search',
        description: 'Search docs',
        inputSchema: { type: 'object', properties: {} },
      },
      {
        name: 'fetch',
        description: '',
        inputSchema: { type: 'object', properties: { url: { type: 'string' } } },
      },
    ]);
  });

  it('throws when tools list is missing', async () => {
    const request = vi.fn().mockResolvedValueOnce({ result: {} });
    await expect(listToolsPaged(request, '本地 MCP')).rejects.toThrow(
      '本地 MCP 返回了无效的工具列表',
    );
  });
});

describe('callToolVia', () => {
  it('normalizes resource items and falls back to empty text item', async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        result: {
          content: [
            { type: 'resource', resource: { text: 'embedded body' } },
            { type: 'text', text: 'hello', extraField: 123 },
          ],
          isError: false,
        },
      })
      .mockResolvedValueOnce({
        result: {
          content: [],
          isError: true,
        },
      });

    expect(await callToolVia(request, '本地 MCP', 'ping', { x: 1 })).toEqual({
      contentItems: [
        { type: 'text', text: 'embedded body' },
        { type: 'text', text: 'hello' },
      ],
      isError: false,
    });

    expect(await callToolVia(request, '本地 MCP', 'empty', {})).toEqual({
      contentItems: [{ type: 'text', text: '' }],
      isError: true,
    });
  });

  it('propagates JSON-RPC errors', async () => {
    const request = vi.fn().mockResolvedValueOnce({
      error: { message: 'tool crashed' },
    });
    await expect(callToolVia(request, '本地 MCP', 'bad', {})).rejects.toThrow(
      'tool crashed',
    );
  });
});
