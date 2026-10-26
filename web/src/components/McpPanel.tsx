import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMcp, type LocalMcpServerStatus } from '../stores/mcp';
import { toast } from '../stores/toast';
import {
  fetchUserMcpConfig,
  saveUserMcpConfig,
  testUserMcpServer,
  type MCPConfig,
  type MCPServerSummary,
} from '../services/mcp';

const EXAMPLE = `{
  "mcp_servers": {
    "my-remote": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ..." }
    },
    "my-pc": {
      "url": "http://127.0.0.1:3001/mcp"
    }
  }
}`;

function localStatusText(
  status: LocalMcpServerStatus | undefined,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (!status) return t('settings.mcp.localPending');
  if (status.status === 'connected') {
    return t('settings.mcp.localConnected', { count: status.toolCount });
  }
  if (status.status === 'connecting') {
    return t('settings.mcp.localConnecting');
  }
  return status.error || t('settings.mcp.localError');
}

export function McpPanel() {
  const { t } = useTranslation();
  const servers = useMcp((s) => s.servers);
  const loading = useMcp((s) => s.loading);
  const localServers = useMcp((s) => s.localServers);
  const setConfigResponse = useMcp((s) => s.setConfigResponse);
  const setLoading = useMcp((s) => s.setLoading);

  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testedTools, setTestedTools] = useState<Record<string, string[]>>({});
  const [editorError, setEditorError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchUserMcpConfig();
      setConfigResponse(data);
      setText(JSON.stringify(data.config, null, 2));
      setEditorError('');
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setLoading(false);
    }
  }, [setConfigResponse, setLoading]);

  useEffect(() => {
    void load();
  }, [load]);

  const localById = useMemo(
    () => new Map(localServers.map((server) => [server.serverId, server])),
    [localServers],
  );

  const parseConfig = (): MCPConfig | null => {
    try {
      const parsed: unknown = JSON.parse(text);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setEditorError(t('settings.mcp.mustBeObject'));
        return null;
      }
      setEditorError('');
      return parsed as MCPConfig;
    } catch {
      setEditorError(t('settings.mcp.invalidJson'));
      return null;
    }
  };

  const save = async () => {
    const config = parseConfig();
    if (!config) return;
    setSaving(true);
    try {
      const data = await saveUserMcpConfig(config);
      setConfigResponse(data);
      setText(JSON.stringify(data.config, null, 2));
      toast(t('settings.mcp.saved'), 'success');
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  };

  const format = () => {
    const config = parseConfig();
    if (config) setText(JSON.stringify(config, null, 2));
  };

  const test = async (server: MCPServerSummary) => {
    setTestingId(server.id);
    try {
      const result = await testUserMcpServer(server.id);
      if (result.mode === 'local') {
        toast(t('settings.mcp.localPending'), 'success');
        return;
      }
      setTestedTools((current) => ({
        ...current,
        [server.id]: result.tools.map((tool) => tool.name),
      }));
      toast(t('settings.mcp.testOk', { count: result.tools.length }), 'success');
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setTestingId(null);
    }
  };

  return (
    <section>
      <h3>{t('settings.mcp.title')}</h3>
      <div className="mcp-hint">{t('settings.mcp.jsonHint')}</div>
      <textarea
        className="mcp-editor"
        name="mcp-config"
        rows={12}
        value={text}
        aria-label={t('settings.mcp.title')}
        spellCheck={false}
        placeholder={EXAMPLE}
        onChange={(event) => setText(event.target.value)}
      />
      {editorError && <div className="mcp-error">{editorError}</div>}
      <div className="mcp-actions">
        <button className="mini-btn" disabled={saving || loading} onClick={() => void save()}>
          {saving ? t('settings.mcp.saving') : t('settings.mcp.save')}
        </button>
        <button className="mini-btn" onClick={format}>
          {t('settings.mcp.format')}
        </button>
        <button className="mini-btn" disabled={loading} onClick={() => void load()}>
          {t('settings.mcp.reload')}
        </button>
      </div>
      <div className="mcp-hint">{t('settings.mcp.headersHint')}</div>

      <div className="mcp-list">
        {servers.map((server) => {
          const local = localById.get(server.id);
          const tested = testedTools[server.id];
          return (
            <div key={server.id} className="mcp-item">
              <div className="mcp-item-head">
                <div className="mcp-item-title">
                  <span>{server.name}</span>
                  <span className={`mcp-badge ${server.mode}`}>
                    {server.mode === 'local'
                      ? t('settings.mcp.modeLocal')
                      : t('settings.mcp.modeRemote')}
                  </span>
                  {server.transport === 'sse' && (
                    <span className="mcp-badge sse">SSE</span>
                  )}
                  {!server.enabled && (
                    <span className="mcp-badge">
                      {t('settings.mcp.disabled')}
                    </span>
                  )}
                </div>
              </div>
              <div className="mcp-url" title={server.url}>
                {server.url}
              </div>
              {server.mode === 'local' ? (
                <div className={`mcp-status ${local?.status ?? ''}`}>
                  {localStatusText(local, t)}
                </div>
              ) : (
                <>
                  {tested && (
                    <div className="mcp-tools">
                      {tested.length > 0
                        ? tested.join(', ')
                        : t('settings.mcp.noTools')}
                    </div>
                  )}
                  <div className="mcp-actions">
                    <button
                      className="mini-btn"
                      disabled={testingId === server.id}
                      onClick={() => void test(server)}
                    >
                      {testingId === server.id
                        ? t('settings.mcp.testing')
                        : t('settings.mcp.test')}
                    </button>
                  </div>
                </>
              )}
              {local && local.tools.length > 0 && (
                <div className="mcp-tools">{local.tools.join(', ')}</div>
              )}
            </div>
          );
        })}
      </div>

      {servers.length === 0 && !loading && (
        <div className="mcp-empty">{t('settings.mcp.noServers')}</div>
      )}

      <div className="mcp-hint">{t('settings.mcp.reconnectHint')}</div>
    </section>
  );
}
