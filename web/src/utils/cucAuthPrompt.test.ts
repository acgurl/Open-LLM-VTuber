import { describe, expect, it } from 'vitest';
import { parseCucAuthPrompt } from './cucAuthPrompt';

describe('parseCucAuthPrompt', () => {
  it('ignores running status and non-CUC tools', () => {
    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_timetable',
        status: 'running',
        content: 'HTTP 401 未登录',
      }),
    ).toBeNull();

    expect(
      parseCucAuthPrompt({
        tool_name: 'kb_search',
        status: 'error',
        content: 'Error: HTTP 401 未登录',
      }),
    ).toBeNull();
  });

  it('detects HTTP 401 across SSO, mail, net, and opac tools', () => {
    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_timetable',
        status: 'error',
        content: 'Error: cuc 服务调用失败（HTTP 401）：未登录或登录已过期',
      }),
    ).toEqual({ service: 'sso', reason: 'expired', toolName: 'cuc_timetable' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_card',
        status: 'error',
        content: 'Error: cuc 服务调用失败（HTTP 401）：请先登录',
      }),
    ).toEqual({ service: 'sso', reason: 'auth_required', toolName: 'cuc_card' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_jw',
        status: 'error',
        content: 'Error: AUTH_REQUIRED',
      }),
    ).toEqual({ service: 'sso', reason: 'auth_required', toolName: 'cuc_jw' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_mail',
        status: 'error',
        content: 'Error: cuc 服务调用失败（HTTP 401）：校内邮箱未登录',
      }),
    ).toEqual({ service: 'mail', reason: 'auth_required', toolName: 'cuc_mail' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_net',
        status: 'error',
        content: 'Error: 校园网自助平台未登录或会话已过期，请运行 cuc net login',
      }),
    ).toEqual({ service: 'net', reason: 'expired', toolName: 'cuc_net' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_library_book',
        status: 'error',
        content: 'Error: cuc 服务调用失败（HTTP 401）：馆藏检索会话失效',
      }),
    ).toEqual({ service: 'opac', reason: 'expired', toolName: 'cuc_library_book' });
  });

  it('ignores non-401 HTTP errors even on CUC tools', () => {
    for (const statusCode of [400, 404, 500, 502, 504]) {
      expect(
        parseCucAuthPrompt({
          tool_name: 'cuc_timetable',
          status: 'error',
          content: `Error: cuc 服务调用失败（HTTP ${statusCode}）：上游服务异常，会话已过期检查失败`,
        }),
      ).toBeNull();
    }
  });

  it('detects completed cuc_status and cuc_mail unauthenticated payloads', () => {
    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_status',
        status: 'completed',
        content: JSON.stringify({ loggedIn: false }),
      }),
    ).toEqual({ service: 'sso', reason: 'not_logged_in', toolName: 'cuc_status' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_status',
        status: 'completed',
        content: JSON.stringify({ loggedIn: true, valid: false }),
      }),
    ).toEqual({ service: 'sso', reason: 'expired', toolName: 'cuc_status' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_status',
        status: 'completed',
        content: JSON.stringify({ loggedIn: true, valid: true }),
      }),
    ).toBeNull();

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_mail',
        status: 'completed',
        content: JSON.stringify({ loggedIn: false }),
      }),
    ).toEqual({ service: 'mail', reason: 'not_logged_in', toolName: 'cuc_mail' });

    expect(
      parseCucAuthPrompt({
        tool_name: 'cuc_mail',
        status: 'completed',
        content: JSON.stringify({ loggedIn: true, email: 'user@cuc.edu.cn' }),
      }),
    ).toBeNull();
  });
});
