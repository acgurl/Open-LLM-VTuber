import { request } from './api';

export interface CucSsoStatus {
  loggedIn: boolean;
  source: string | null;
  updatedAt: string | null;
}

export interface CucMailStatus {
  loggedIn: boolean;
  email: string | null;
  updatedAt: string | null;
}

export interface CucNetStatus {
  loggedIn: boolean;
  username: string | null;
  updatedAt: string | null;
}

export interface CucOpacStatus {
  loggedIn: boolean;
  updatedAt: string | null;
}

export interface CucAuthStatus {
  profile: string;
  sso: CucSsoStatus;
  mail: CucMailStatus;
  net: CucNetStatus;
  opac: CucOpacStatus;
  corrupted?: boolean;
}

export interface CucLiveVerifyResult {
  loggedIn: boolean;
  valid?: boolean;
  sso?: boolean;
  timetable?: boolean;
  card?: boolean;
  lms?: boolean;
  activity?: boolean;
  message?: boolean;
  visitor?: boolean;
}

export interface WechatLoginTask {
  taskId: string;
  profile: string;
  status: 'pending' | 'scanned' | 'confirmed' | 'expired' | 'cancelled' | 'failed';
  message: string;
  confirmUrl: string | null;
  qrPath: string;
  qrMimeType: string | null;
  qrBase64?: string;
  refreshed: boolean;
  expiresAt: string;
  error: string | null;
}

export interface MailAuthResult {
  taskId?: string;
  profile: string;
  status: 'confirmed' | 'sms_required';
  source?: string;
  email?: string | null;
  mobile?: string | null;
  message: string;
  expiresAt?: string;
}

export interface NetLoginResult {
  taskId: string;
  profile: string;
  status: 'captcha_required' | 'sms_required' | 'confirmed' | 'cancelled';
  message: string;
  captchaPath?: string;
  captchaMimeType?: string;
  captchaBase64?: string;
  username?: string | null;
  expiresAt?: string;
}

// 404 表示部署方没有开启 CUC 账号绑定；调用方据此隐藏整块面板
export function fetchCucAuthStatus(): Promise<CucAuthStatus> {
  return request<CucAuthStatus>('/api/cuc/auth/status');
}

export function verifyCucAuthStatus(): Promise<CucLiveVerifyResult> {
  return request<CucLiveVerifyResult>('/api/cuc/auth/status?verify=1');
}

export function startWechatLogin(): Promise<WechatLoginTask> {
  return request<WechatLoginTask>('/api/cuc/auth/wechat/start', { method: 'POST' });
}

export function pollWechatLogin(
  taskId: string,
  options?: { wait?: boolean; timeout?: number; signal?: AbortSignal },
): Promise<WechatLoginTask> {
  const params = new URLSearchParams();
  if (options?.wait !== undefined) params.set('wait', options.wait ? '1' : '0');
  if (options?.timeout !== undefined) params.set('timeout', String(options.timeout));
  const qs = params.toString();
  return request<WechatLoginTask>(
    `/api/cuc/auth/wechat/${encodeURIComponent(taskId)}${qs ? `?${qs}` : ''}`,
    { signal: options?.signal },
  );
}

export function cancelWechatLogin(taskId: string): Promise<WechatLoginTask> {
  return request<WechatLoginTask>(`/api/cuc/auth/wechat/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  });
}

export function logoutCucSso(): Promise<{ loggedOut: boolean; cleared: boolean }> {
  return request('/api/cuc/auth/logout', { method: 'POST' });
}

export function startMailAuth(): Promise<MailAuthResult> {
  return request<MailAuthResult>('/api/cuc/auth/mail/start', { method: 'POST' });
}

export function submitMailSms(taskId: string, code: string): Promise<MailAuthResult> {
  return request<MailAuthResult>(`/api/cuc/auth/mail/${encodeURIComponent(taskId)}/sms`, {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

export function logoutCucMail(): Promise<{ loggedOut: boolean; cleared: boolean }> {
  return request('/api/cuc/auth/mail/logout', { method: 'POST' });
}

export function startNetLogin(): Promise<NetLoginResult> {
  return request<NetLoginResult>('/api/cuc/auth/net/start', { method: 'POST' });
}

export function submitNetLogin(
  taskId: string,
  payload: { username?: string; password: string; verifyCode: string },
): Promise<NetLoginResult> {
  return request<NetLoginResult>(`/api/cuc/auth/net/${encodeURIComponent(taskId)}/submit`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function submitNetSms(taskId: string, smsCode: string): Promise<NetLoginResult> {
  return request<NetLoginResult>(`/api/cuc/auth/net/${encodeURIComponent(taskId)}/sms`, {
    method: 'POST',
    body: JSON.stringify({ smsCode }),
  });
}

export function cancelNetLogin(taskId: string): Promise<NetLoginResult> {
  return request<NetLoginResult>(`/api/cuc/auth/net/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  });
}

export function logoutCucNet(): Promise<{ loggedOut: boolean; cleared: boolean }> {
  return request('/api/cuc/auth/net/logout', { method: 'POST' });
}

export function authOpac(): Promise<{ authenticated: boolean; message: string }> {
  return request('/api/cuc/auth/opac/auth', { method: 'POST' });
}

export function logoutCucOpac(): Promise<{ loggedOut: boolean; cleared: boolean }> {
  return request('/api/cuc/auth/opac/logout', { method: 'POST' });
}
