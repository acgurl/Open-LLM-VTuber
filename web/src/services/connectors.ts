import { request } from './api';

export type ConnectorState = 'connecting' | 'running' | 'error' | 'stopped';

export interface ConnectorSummary {
  id: string;
  name: string;
  platform: string;
  state: ConnectorState;
}

export interface ConnectorBinding {
  connector_id: string;
  connector_name: string | null;
  external_id: string;
  display_name: string | null;
  created_at: string | null;
}

export interface ConnectorOverview {
  eligible: boolean;
  allowed_email_domains: string[];
  connectors: ConnectorSummary[];
  bindings: ConnectorBinding[];
}

export interface BindCode {
  code: string;
  expires_in: number;
}

// 404 表示部署方没有开启连接器；调用方据此隐藏整块面板
export function fetchConnectors(): Promise<ConnectorOverview> {
  return request<ConnectorOverview>('/api/connectors');
}

export function createBindCode(): Promise<BindCode> {
  return request<BindCode>('/api/connectors/bind-code', { method: 'POST' });
}

export async function deleteBinding(binding: ConnectorBinding): Promise<void> {
  await request<null>(
    `/api/connectors/bindings/${encodeURIComponent(binding.connector_id)}/${encodeURIComponent(
      binding.external_id,
    )}`,
    { method: 'DELETE' },
  );
}
