export type CucAuthService = 'sso' | 'mail' | 'net' | 'opac';
export type CucAuthReason = 'not_logged_in' | 'expired' | 'auth_required';

export interface CucAuthPrompt {
  service: CucAuthService;
  reason: CucAuthReason;
  toolName: string;
}

const CUC_TOOL_SERVICES: Record<string, CucAuthService> = {
  cuc_status: 'sso',
  cuc_timetable: 'sso',
  cuc_jw: 'sso',
  cuc_card: 'sso',
  cuc_activity: 'sso',
  cuc_message: 'sso',
  cuc_notice: 'sso',
  cuc_portal: 'sso',
  cuc_visitor: 'sso',
  cuc_lms: 'sso',
  cuc_library_seat: 'sso',
  cuc_library_space: 'sso',
  cuc_room: 'sso',
  cuc_request: 'sso',
  cuc_mail: 'mail',
  cuc_net: 'net',
  cuc_library_book: 'opac',
};

const NON_401_HTTP_RE = /HTTP\s+(?!401\b)\d{3}/i;
const HTTP_401_RE = /HTTP\s*401\b/i;
const AUTH_TEXT_RE =
  /未登录|登录已过期|会话已过期|登录态已过期|需要统一认证|需要重新登录|AUTH_REQUIRED|cuc login|cuc net login|cuc mail auth/i;
const EXPIRED_TEXT_RE = /过期|失效/;

function tryParseObject(content: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(content);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function parseCucAuthPrompt(tool: {
  tool_name: string;
  status: 'running' | 'completed' | 'error';
  content: string;
}): CucAuthPrompt | null {
  if (tool.status === 'running') return null;

  const service = CUC_TOOL_SERVICES[tool.tool_name];
  if (!service) return null;

  if (tool.status === 'error') {
    if (NON_401_HTTP_RE.test(tool.content)) return null;
    if (!HTTP_401_RE.test(tool.content) && !AUTH_TEXT_RE.test(tool.content)) return null;
    const reason: CucAuthReason = EXPIRED_TEXT_RE.test(tool.content) ? 'expired' : 'auth_required';
    return { service, reason, toolName: tool.tool_name };
  }

  if (tool.status === 'completed') {
    if (tool.tool_name !== 'cuc_status' && tool.tool_name !== 'cuc_mail') return null;
    const data = tryParseObject(tool.content);
    if (!data) return null;

    if (tool.tool_name === 'cuc_status') {
      if (data.loggedIn === false) {
        return { service: 'sso', reason: 'not_logged_in', toolName: tool.tool_name };
      }
      if (data.loggedIn === true && data.valid === false) {
        return { service: 'sso', reason: 'expired', toolName: tool.tool_name };
      }
      return null;
    }

    if (tool.tool_name === 'cuc_mail' && data.loggedIn === false) {
      return { service: 'mail', reason: 'not_logged_in', toolName: tool.tool_name };
    }
  }

  return null;
}
