import { beforeEach, describe, expect, it } from 'vitest';
import { useChat } from './chat';

describe('useChat cuc_auth derivation', () => {
  beforeEach(() => {
    useChat.getState().clear();
  });

  it('inserts a cuc_auth entry on CUC 401 error and attaches retryPrompt', () => {
    const store = useChat.getState();
    store.addUserMessage('今天有什么课？');
    store.upsertTool({
      tool_id: 'call_1',
      tool_name: 'cuc_timetable',
      status: 'running',
      content: 'Input: {"action":"today"}',
      timestamp: '2026-11-26T06:00:00Z',
    });

    expect(useChat.getState().entries.some((e) => e.kind === 'cuc_auth')).toBe(false);

    useChat.getState().upsertTool({
      tool_id: 'call_1',
      tool_name: 'cuc_timetable',
      status: 'error',
      content: 'Error: cuc 服务调用失败（HTTP 401）：未登录或登录已过期',
      timestamp: '2026-11-26T06:00:01Z',
    });

    const authEntries = useChat.getState().entries.filter((e) => e.kind === 'cuc_auth');
    expect(authEntries).toHaveLength(1);
    expect(authEntries[0]).toMatchObject({
      kind: 'cuc_auth',
      tool_id: 'call_1',
      tool_name: 'cuc_timetable',
      service: 'sso',
      reason: 'expired',
      retryPrompt: '今天有什么课？',
      fromHistory: false,
    });
  });

  it('deduplicates same-service auth cards within one turn and allows a new card on the next turn', () => {
    const store = useChat.getState();
    store.addUserMessage('查课表和校园卡余额');
    store.upsertTool({
      tool_id: 'call_1',
      tool_name: 'cuc_timetable',
      status: 'error',
      content: 'Error: HTTP 401 未登录',
      timestamp: '2026-11-26T06:00:01Z',
    });
    store.upsertTool({
      tool_id: 'call_2',
      tool_name: 'cuc_card',
      status: 'error',
      content: 'Error: HTTP 401 未登录',
      timestamp: '2026-11-26T06:00:02Z',
    });

    expect(useChat.getState().entries.filter((e) => e.kind === 'cuc_auth')).toHaveLength(1);

    useChat.getState().addUserMessage('再查一次课表');
    useChat.getState().upsertTool({
      tool_id: 'call_3',
      tool_name: 'cuc_timetable',
      status: 'error',
      content: 'Error: HTTP 401 未登录',
      timestamp: '2026-11-26T06:00:03Z',
    });

    const authEntries = useChat.getState().entries.filter((e) => e.kind === 'cuc_auth');
    expect(authEntries).toHaveLength(2);
    expect(authEntries[1].retryPrompt).toBe('再查一次课表');
  });

  it('inserts a cuc_auth entry when cuc_status completes with loggedIn: false', () => {
    useChat.getState().addUserMessage('查一下我的成绩');
    useChat.getState().upsertTool({
      tool_id: 'call_status',
      tool_name: 'cuc_status',
      status: 'completed',
      content: JSON.stringify({ loggedIn: false }),
      timestamp: '2026-11-26T06:00:01Z',
    });

    const authEntries = useChat.getState().entries.filter((e) => e.kind === 'cuc_auth');
    expect(authEntries).toHaveLength(1);
    expect(authEntries[0]).toMatchObject({
      service: 'sso',
      reason: 'not_logged_in',
      retryPrompt: '查一下我的成绩',
    });
  });

  it('restores deduplicated fromHistory cuc_auth entries in loadHistory', () => {
    useChat.getState().loadHistory(
      [
        { role: 'human', content: '查今天课表和余额', timestamp: '2026-11-26T06:00:00Z' },
        { role: 'ai', content: '请先扫码登录', timestamp: '2026-11-26T06:00:05Z' },
      ],
      [
        {
          tool_id: 'h1',
          tool_name: 'cuc_timetable',
          status: 'error',
          content: 'Error: HTTP 401 未登录',
          timestamp: '2026-11-26T06:00:01Z',
          turn_index: 0,
        },
        {
          tool_id: 'h2',
          tool_name: 'cuc_card',
          status: 'error',
          content: 'Error: HTTP 401 未登录',
          timestamp: '2026-11-26T06:00:02Z',
          turn_index: 0,
        },
        {
          tool_id: 'h3',
          tool_name: 'cuc_mail',
          status: 'error',
          content: 'Error: HTTP 401 校内邮箱未登录',
          timestamp: '2026-11-26T06:00:03Z',
          turn_index: 0,
        },
      ],
    );

    const authEntries = useChat.getState().entries.filter((e) => e.kind === 'cuc_auth');
    expect(authEntries).toHaveLength(2);
    expect(authEntries[0]).toMatchObject({
      service: 'sso',
      fromHistory: true,
      retryPrompt: '查今天课表和余额',
    });
    expect(authEntries[1]).toMatchObject({
      service: 'mail',
      fromHistory: true,
      retryPrompt: '查今天课表和余额',
    });
  });
});
