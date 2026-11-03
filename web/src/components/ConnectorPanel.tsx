import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from '../stores/toast';
import { ApiError } from '../services/api';
import {
  createBindCode,
  deleteBinding,
  fetchConnectors,
  type ConnectorBinding,
  type ConnectorOverview,
  type ConnectorState,
} from '../services/connectors';

// 生成绑定码后轮询，用户在机器人那边 /bind 成功时这里能立刻看到
const POLL_INTERVAL_MS = 4000;
const CONFIRM_WINDOW_MS = 3000;

interface ActiveCode {
  code: string;
  expiresAt: number;
  ttl: number;
}

function bindingKey(binding: ConnectorBinding): string {
  return `${binding.connector_id}/${binding.external_id}`;
}

// 同一平台账号重新绑定时 key 不变，带上绑定时间才能识别出“新绑定”
function bindingStamp(binding: ConnectorBinding): string {
  return `${bindingKey(binding)}@${binding.created_at ?? ''}`;
}

function formatRemaining(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function ConnectorPanel({ open }: { open: boolean }) {
  const { t, i18n } = useTranslation();
  // undefined：还没加载；null：部署方没有开启连接器，整块不显示
  const [overview, setOverview] = useState<ConnectorOverview | null | undefined>(undefined);
  const [loadError, setLoadError] = useState('');
  const [code, setCode] = useState<ActiveCode | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [issuing, setIssuing] = useState(false);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [removingKey, setRemovingKey] = useState<string | null>(null);
  const knownBindings = useRef<Set<string> | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchConnectors();
      setOverview(data);
      setLoadError('');
      return data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setOverview(null);
      } else {
        setLoadError(error instanceof Error ? error.message : String(error));
      }
      return null;
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const remaining = code ? Math.max(0, Math.ceil((code.expiresAt - now) / 1000)) : 0;
  const expired = code !== null && remaining === 0;

  // 倒计时 + 轮询：只在抽屉打开且码未过期时运行
  useEffect(() => {
    if (!open || !code || expired) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const poll = window.setInterval(() => {
      void load().then((data) => {
        const known = knownBindings.current;
        if (!data || !known) return;
        const added = data.bindings.find((binding) => !known.has(bindingStamp(binding)));
        if (added) {
          setCode(null);
          toast(t('settings.connectors.bound', { name: added.connector_name ?? added.connector_id }), 'success');
        }
      });
    }, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(tick);
      window.clearInterval(poll);
    };
  }, [open, code, expired, load, t]);

  useEffect(() => {
    if (!confirmKey) return;
    const timer = window.setTimeout(() => setConfirmKey(null), CONFIRM_WINDOW_MS);
    return () => window.clearTimeout(timer);
  }, [confirmKey]);

  if (overview === null) return null;

  const issue = async () => {
    setIssuing(true);
    try {
      const result = await createBindCode();
      knownBindings.current = new Set((overview?.bindings ?? []).map(bindingStamp));
      const issuedAt = Date.now();
      setNow(issuedAt);
      setCode({
        code: result.code,
        expiresAt: issuedAt + result.expires_in * 1000,
        ttl: result.expires_in,
      });
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setIssuing(false);
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(t('settings.connectors.copied'), 'success');
    } catch {
      toast(t('settings.connectors.copyFailed'), 'error');
    }
  };

  const remove = async (binding: ConnectorBinding) => {
    const key = bindingKey(binding);
    if (confirmKey !== key) {
      setConfirmKey(key);
      return;
    }
    setConfirmKey(null);
    setRemovingKey(key);
    try {
      await deleteBinding(binding);
      toast(t('settings.connectors.unbound'), 'success');
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setRemovingKey(null);
    }
  };

  const stateLabel = (state: ConnectorState) => t(`settings.connectors.state.${state}`);
  const formatDate = (value: string | null) => {
    if (!value) return '';
    const parsed = Date.parse(value);
    return Number.isNaN(parsed)
      ? ''
      : new Date(parsed).toLocaleString(i18n.language, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        });
  };

  return (
    <section className="connector-panel">
      <h3>{t('settings.connectors.title')}</h3>

      {overview === undefined && !loadError && (
        <div className="mcp-hint">{t('settings.connectors.loading')}</div>
      )}
      {loadError && (
        <div className="connector-notice error">
          <span>{loadError}</span>
          <button className="mini-btn" onClick={() => void load()}>
            {t('settings.connectors.retry')}
          </button>
        </div>
      )}

      {overview && (
        <>
          {overview.connectors.length > 0 && (
            <ul className="connector-bots" aria-label={t('settings.connectors.bots')}>
              {overview.connectors.map((bot) => (
                <li key={bot.id} className="connector-bot">
                  <span className={`connector-dot ${bot.state}`} aria-hidden="true" />
                  <span className="connector-bot-name">{bot.name}</span>
                  <span className={`connector-state ${bot.state}`}>{stateLabel(bot.state)}</span>
                </li>
              ))}
            </ul>
          )}

          {!overview.eligible ? (
            <div className="connector-notice">
              {t('settings.connectors.ineligible', {
                domains: overview.allowed_email_domains.join('、'),
              })}
            </div>
          ) : code && !expired ? (
            <div className="connector-code-card" role="group" aria-label={t('settings.connectors.codeLabel')}>
              <div className="connector-code-row">
                <code className="connector-code" aria-live="polite">
                  {code.code}
                </code>
                <button
                  type="button"
                  className="mini-btn"
                  aria-label={t('settings.connectors.copyCode')}
                  title={t('settings.connectors.copyCode')}
                  onClick={() => void copy(`/bind ${code.code}`)}
                >
                  ⧉
                </button>
              </div>
              <div
                className="connector-countdown"
                role="progressbar"
                aria-label={t('settings.connectors.expiresIn', { time: formatRemaining(remaining) })}
                aria-valuemin={0}
                aria-valuemax={code.ttl}
                aria-valuenow={remaining}
              >
                <span style={{ transform: `scaleX(${remaining / code.ttl})` }} />
              </div>
              <div className="connector-code-meta">
                <span>{t('settings.connectors.expiresIn', { time: formatRemaining(remaining) })}</span>
                <span className="connector-waiting">{t('settings.connectors.waiting')}</span>
              </div>
              <ol className="connector-steps">
                <li>{t('settings.connectors.step1')}</li>
                <li>
                  {t('settings.connectors.step2Prefix')}
                  <code>/bind {code.code}</code>
                </li>
              </ol>
              <div className="mcp-actions">
                <button className="mini-btn" disabled={issuing} onClick={() => void issue()}>
                  {t('settings.connectors.regenerate')}
                </button>
                <button className="mini-btn" onClick={() => setCode(null)}>
                  {t('settings.connectors.cancel')}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="mcp-hint">
                {expired ? t('settings.connectors.expired') : t('settings.connectors.hint')}
              </div>
              <button className="drawer-action" disabled={issuing} onClick={() => void issue()}>
                {issuing ? t('settings.connectors.issuing') : t('settings.connectors.generate')}
              </button>
            </>
          )}

          <div className="connector-subtitle">{t('settings.connectors.bindings')}</div>
          {overview.bindings.length === 0 ? (
            <div className="mcp-empty">{t('settings.connectors.noBindings')}</div>
          ) : (
            <ul className="mcp-list">
              {overview.bindings.map((binding) => {
                const key = bindingKey(binding);
                const confirming = confirmKey === key;
                return (
                  <li key={key} className="mcp-item connector-binding">
                    <div className="mcp-item-head">
                      <div className="mcp-item-title">
                        <span>{binding.display_name || binding.external_id}</span>
                        <span className="mcp-badge remote">
                          {binding.connector_name ?? binding.connector_id}
                        </span>
                      </div>
                      <button
                        className={`mini-btn danger${confirming ? ' confirming' : ''}`}
                        disabled={removingKey === key}
                        onClick={() => void remove(binding)}
                      >
                        {confirming ? t('settings.connectors.confirmUnbind') : t('settings.connectors.unbind')}
                      </button>
                    </div>
                    <div className="mcp-url" title={binding.external_id}>
                      {[binding.display_name ? binding.external_id : '', formatDate(binding.created_at)]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="mcp-hint">{t('settings.connectors.commandsHint')}</div>
        </>
      )}
    </section>
  );
}
