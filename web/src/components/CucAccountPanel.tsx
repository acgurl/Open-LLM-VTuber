import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useCucAuth } from '../stores/cucAuth';
import { toast } from '../stores/toast';
import { ApiError } from '../services/api';
import {
  authOpac,
  cancelNetLogin,
  cancelWechatLogin,
  fetchCucAuthStatus,
  logoutCucMail,
  logoutCucNet,
  logoutCucOpac,
  logoutCucSso,
  pollWechatLogin,
  startMailAuth,
  startNetLogin,
  startWechatLogin,
  submitMailSms,
  submitNetLogin,
  submitNetSms,
  verifyCucAuthStatus,
  type CucAuthStatus,
  type CucLiveVerifyResult,
  type MailAuthResult,
  type NetLoginResult,
  type WechatLoginTask,
} from '../services/cucAuth';

type ServiceKey = 'sso' | 'mail' | 'net' | 'opac';

const CONFIRM_WINDOW_MS = 3000;
const WECHAT_POLL_TIMEOUT_MS = 20000;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function CucAccountPanel({ open }: { open: boolean }) {
  const { t, i18n } = useTranslation();
  // undefined：加载中；null：部署方未开启 CUC 账号绑定，整块隐藏
  const [status, setStatus] = useState<CucAuthStatus | null | undefined>(undefined);
  const [liveResult, setLiveResult] = useState<CucLiveVerifyResult | null>(null);
  const [loadError, setLoadError] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState<ServiceKey | null>(null);
  const [busyKey, setBusyKey] = useState<ServiceKey | null>(null);

  const [wechatTask, setWechatTask] = useState<WechatLoginTask | null>(null);
  const [mailTask, setMailTask] = useState<MailAuthResult | null>(null);
  const [mailSmsCode, setMailSmsCode] = useState('');

  const [netTask, setNetTask] = useState<NetLoginResult | null>(null);
  const [netUsername, setNetUsername] = useState('');
  const [netPassword, setNetPassword] = useState('');
  const [netVerifyCode, setNetVerifyCode] = useState('');
  const [netSmsCode, setNetSmsCode] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await fetchCucAuthStatus();
      setStatus(data);
      setLoadError('');
      useCucAuth.getState().setAvailable(true);
      return data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setStatus(null);
        useCucAuth.getState().setAvailable(false);
      } else {
        setLoadError(errorText(error));
      }
      return null;
    }
  }, []);

  useEffect(() => {
    if (open) {
      void load();
    } else {
      setNetPassword('');
    }
  }, [open, load]);

  useEffect(() => {
    if (!confirmLogout) return;
    const timer = window.setTimeout(() => setConfirmLogout(null), CONFIRM_WINDOW_MS);
    return () => window.clearTimeout(timer);
  }, [confirmLogout]);

  // 微信扫码长轮询：仅在抽屉打开且任务处于 pending/scanned 时运行
  const wechatTaskId = wechatTask?.taskId ?? null;
  const wechatActive =
    open &&
    wechatTask !== null &&
    (wechatTask.status === 'pending' || wechatTask.status === 'scanned');

  useEffect(() => {
    if (!wechatActive || !wechatTaskId) return;
    const ac = new AbortController();
    let stopped = false;

    const loop = async () => {
      while (!stopped && !ac.signal.aborted) {
        try {
          const next = await pollWechatLogin(wechatTaskId, {
            wait: true,
            timeout: WECHAT_POLL_TIMEOUT_MS,
            signal: ac.signal,
          });
          if (stopped || ac.signal.aborted) return;
          if (next.status === 'confirmed') {
            setWechatTask(null);
            setLiveResult(null);
            useCucAuth.getState().notifyConfirmed('sso');
            toast(t('settings.cuc.ssoConfirmed'), 'success');
            await load();
            return;
          }
          if (
            next.status === 'expired' ||
            next.status === 'cancelled' ||
            next.status === 'failed'
          ) {
            setWechatTask(next);
            return;
          }
          setWechatTask((prev) => ({
            ...next,
            qrBase64: next.qrBase64 ?? prev?.qrBase64,
            qrMimeType: next.qrMimeType ?? prev?.qrMimeType ?? null,
          }));
        } catch (error) {
          if (stopped || ac.signal.aborted) return;
          toast(errorText(error), 'error');
          setWechatTask(null);
          return;
        }
      }
    };

    void loop();
    return () => {
      stopped = true;
      ac.abort();
    };
  }, [wechatActive, wechatTaskId, load, t]);

  if (status === null) return null;

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

  const handleVerify = async () => {
    setVerifying(true);
    try {
      const live = await verifyCucAuthStatus();
      setLiveResult(live);
      await load();
      toast(
        live.valid || live.sso ? t('settings.cuc.verifyValid') : t('settings.cuc.verifyInvalid'),
        live.valid || live.sso ? 'success' : 'error',
      );
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setVerifying(false);
    }
  };

  const handleStartWechat = async () => {
    setBusyKey('sso');
    try {
      const task = await startWechatLogin();
      setWechatTask(task);
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleCancelWechat = async () => {
    if (!wechatTask) return;
    const id = wechatTask.taskId;
    setWechatTask(null);
    try {
      await cancelWechatLogin(id);
    } catch {
      // 忽略已过期任务的取消错误
    }
  };

  const handleStartMail = async () => {
    setBusyKey('mail');
    try {
      const res = await startMailAuth();
      if (res.status === 'confirmed') {
        setMailTask(null);
        setMailSmsCode('');
        useCucAuth.getState().notifyConfirmed('mail');
        toast(res.message || t('settings.cuc.mailConfirmed'), 'success');
        await load();
      } else {
        setMailTask(res);
      }
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleSubmitMailSms = async (e: FormEvent) => {
    e.preventDefault();
    if (!mailTask?.taskId || !mailSmsCode.trim()) return;
    setBusyKey('mail');
    try {
      const res = await submitMailSms(mailTask.taskId, mailSmsCode.trim());
      setMailTask(null);
      setMailSmsCode('');
      useCucAuth.getState().notifyConfirmed('mail');
      toast(res.message || t('settings.cuc.mailConfirmed'), 'success');
      await load();
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleStartNet = async () => {
    setBusyKey('net');
    try {
      const res = await startNetLogin();
      setNetTask(res);
      setNetPassword('');
      setNetVerifyCode('');
      setNetSmsCode('');
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleCancelNet = async () => {
    const id = netTask?.taskId;
    setNetTask(null);
    setNetPassword('');
    setNetVerifyCode('');
    setNetSmsCode('');
    if (id) {
      try {
        await cancelNetLogin(id);
      } catch {
        // 忽略已过期任务
      }
    }
  };

  const handleSubmitNet = async (e: FormEvent) => {
    e.preventDefault();
    if (!netTask?.taskId || !netPassword || !netVerifyCode.trim()) return;
    const passwordSnapshot = netPassword;
    const verifyCodeSnapshot = netVerifyCode.trim();
    const usernameSnapshot = netUsername.trim();
    setNetPassword('');
    setBusyKey('net');
    try {
      const res = await submitNetLogin(netTask.taskId, {
        ...(usernameSnapshot ? { username: usernameSnapshot } : {}),
        password: passwordSnapshot,
        verifyCode: verifyCodeSnapshot,
      });
      if (res.status === 'sms_required') {
        setNetTask(res);
      } else {
        setNetTask(null);
        setNetVerifyCode('');
        setNetSmsCode('');
        useCucAuth.getState().notifyConfirmed('net');
        toast(res.message || t('settings.cuc.netConfirmed'), 'success');
        await load();
      }
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleSubmitNetSms = async (e: FormEvent) => {
    e.preventDefault();
    if (!netTask?.taskId || !netSmsCode.trim()) return;
    setBusyKey('net');
    try {
      const res = await submitNetSms(netTask.taskId, netSmsCode.trim());
      setNetTask(null);
      setNetVerifyCode('');
      setNetSmsCode('');
      useCucAuth.getState().notifyConfirmed('net');
      toast(res.message || t('settings.cuc.netConfirmed'), 'success');
      await load();
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleAuthOpac = async () => {
    setBusyKey('opac');
    try {
      const res = await authOpac();
      useCucAuth.getState().notifyConfirmed('opac');
      toast(res.message || t('settings.cuc.opacConfirmed'), 'success');
      await load();
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const handleLogout = async (key: ServiceKey) => {
    if (confirmLogout !== key) {
      setConfirmLogout(key);
      return;
    }
    setConfirmLogout(null);
    setBusyKey(key);
    try {
      if (key === 'sso') {
        await logoutCucSso();
        setLiveResult(null);
      } else if (key === 'mail') {
        await logoutCucMail();
      } else if (key === 'net') {
        await logoutCucNet();
      } else {
        await logoutCucOpac();
      }
      toast(t('settings.cuc.loggedOut'), 'success');
      await load();
    } catch (error) {
      toast(errorText(error), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const qrSrc =
    wechatTask?.qrBase64 && wechatTask.qrMimeType
      ? `data:${wechatTask.qrMimeType};base64,${wechatTask.qrBase64}`
      : wechatTask?.qrPath || '';

  const captchaSrc =
    netTask?.captchaBase64 && netTask.captchaMimeType
      ? `data:${netTask.captchaMimeType};base64,${netTask.captchaBase64}`
      : netTask?.captchaPath || '';

  return (
    <section className="cuc-panel">
      <h3>{t('settings.cuc.title')}</h3>
      <div className="mcp-hint">{t('settings.cuc.hint')}</div>

      {status === undefined && !loadError && (
        <div className="mcp-hint">{t('settings.cuc.loading')}</div>
      )}

      {loadError && (
        <div className="connector-notice error">
          <span>{loadError}</span>
          <button className="mini-btn" onClick={() => void load()}>
            {t('settings.cuc.retry')}
          </button>
        </div>
      )}

      {status && (
        <ul className="cuc-services">
          {/* 1. 统一认证（微信扫码） */}
          <li className="mcp-item cuc-card">
            <div className="mcp-item-head">
              <div className="mcp-item-title">
                <span
                  className={`connector-dot ${status.sso.loggedIn ? 'running' : ''}`}
                  aria-hidden="true"
                />
                <span>{t('settings.cuc.ssoTitle')}</span>
                <span className={`mcp-badge ${status.sso.loggedIn ? 'remote' : ''}`}>
                  {status.sso.loggedIn ? t('settings.cuc.bound') : t('settings.cuc.unbound')}
                </span>
              </div>
              <div className="cuc-head-actions">
                {status.sso.loggedIn && (
                  <button
                    className="mini-btn"
                    disabled={verifying}
                    onClick={() => void handleVerify()}
                  >
                    {verifying ? t('settings.cuc.verifying') : t('settings.cuc.verify')}
                  </button>
                )}
                {status.sso.loggedIn && (
                  <button
                    className={`mini-btn danger${confirmLogout === 'sso' ? ' confirming' : ''}`}
                    disabled={busyKey === 'sso'}
                    onClick={() => void handleLogout('sso')}
                  >
                    {confirmLogout === 'sso' ? t('settings.cuc.confirmLogout') : t('settings.cuc.logout')}
                  </button>
                )}
              </div>
            </div>

            {status.sso.loggedIn && (
              <div className="mcp-url">
                {[
                  status.sso.source ? `${t('settings.cuc.source')}: ${status.sso.source}` : '',
                  formatDate(status.sso.updatedAt),
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            )}

            {liveResult && status.sso.loggedIn && (
              <div className="cuc-live-row">
                <span className={`cuc-live-pill ${liveResult.sso ? 'ok' : 'warn'}`}>
                  SSO {liveResult.sso ? '✓' : '×'}
                </span>
                <span className={`cuc-live-pill ${liveResult.timetable ? 'ok' : 'warn'}`}>
                  {t('settings.cuc.siteTimetable')} {liveResult.timetable ? '✓' : '×'}
                </span>
                <span className={`cuc-live-pill ${liveResult.card ? 'ok' : 'warn'}`}>
                  {t('settings.cuc.siteCard')} {liveResult.card ? '✓' : '×'}
                </span>
                <span className={`cuc-live-pill ${liveResult.lms ? 'ok' : 'warn'}`}>
                  {t('settings.cuc.siteLms')} {liveResult.lms ? '✓' : '×'}
                </span>
              </div>
            )}

            {wechatTask ? (
              <div className="cuc-flow-box">
                {(wechatTask.status === 'pending' || wechatTask.status === 'scanned') && qrSrc && (
                  <div className="cuc-qr-wrap">
                    <img className="cuc-qr-img" src={qrSrc} alt={t('settings.cuc.qrAlt')} />
                  </div>
                )}
                <div className="cuc-flow-msg">{wechatTask.message}</div>
                <div className="mcp-actions">
                  {(wechatTask.status === 'expired' ||
                    wechatTask.status === 'cancelled' ||
                    wechatTask.status === 'failed') && (
                    <button
                      className="mini-btn"
                      disabled={busyKey === 'sso'}
                      onClick={() => void handleStartWechat()}
                    >
                      {t('settings.cuc.retryQr')}
                    </button>
                  )}
                  <button className="mini-btn" onClick={() => void handleCancelWechat()}>
                    {t('settings.cuc.cancel')}
                  </button>
                </div>
              </div>
            ) : (
              <div className="mcp-actions">
                <button
                  className="mini-btn"
                  disabled={busyKey === 'sso'}
                  onClick={() => void handleStartWechat()}
                >
                  {busyKey === 'sso'
                    ? t('settings.cuc.starting')
                    : status.sso.loggedIn
                      ? t('settings.cuc.reloginWechat')
                      : t('settings.cuc.loginWechat')}
                </button>
              </div>
            )}
          </li>

          {/* 2. 校内邮箱 */}
          <li className="mcp-item cuc-card">
            <div className="mcp-item-head">
              <div className="mcp-item-title">
                <span
                  className={`connector-dot ${status.mail.loggedIn ? 'running' : ''}`}
                  aria-hidden="true"
                />
                <span>{t('settings.cuc.mailTitle')}</span>
                <span className={`mcp-badge ${status.mail.loggedIn ? 'remote' : ''}`}>
                  {status.mail.loggedIn ? t('settings.cuc.bound') : t('settings.cuc.unbound')}
                </span>
              </div>
              {status.mail.loggedIn && (
                <button
                  className={`mini-btn danger${confirmLogout === 'mail' ? ' confirming' : ''}`}
                  disabled={busyKey === 'mail'}
                  onClick={() => void handleLogout('mail')}
                >
                  {confirmLogout === 'mail' ? t('settings.cuc.confirmLogout') : t('settings.cuc.logout')}
                </button>
              )}
            </div>
            {(status.mail.email || status.mail.updatedAt) && (
              <div className="mcp-url">
                {[status.mail.email, formatDate(status.mail.updatedAt)].filter(Boolean).join(' · ')}
              </div>
            )}
            {mailTask?.status === 'sms_required' && mailTask.taskId ? (
              <form className="cuc-flow-box" onSubmit={(e) => void handleSubmitMailSms(e)}>
                <div className="cuc-flow-msg">{mailTask.message}</div>
                <div className="cuc-inline-form">
                  <input
                    className="cuc-input"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder={t('settings.cuc.smsPlaceholder')}
                    value={mailSmsCode}
                    onChange={(e) => setMailSmsCode(e.target.value)}
                  />
                  <button
                    className="mini-btn"
                    type="submit"
                    disabled={busyKey === 'mail' || !mailSmsCode.trim()}
                  >
                    {t('settings.cuc.submit')}
                  </button>
                  <button
                    className="mini-btn"
                    type="button"
                    onClick={() => {
                      setMailTask(null);
                      setMailSmsCode('');
                    }}
                  >
                    {t('settings.cuc.cancel')}
                  </button>
                </div>
              </form>
            ) : (
              <div className="mcp-actions">
                <button
                  className="mini-btn"
                  disabled={busyKey === 'mail' || !status.sso.loggedIn}
                  title={!status.sso.loggedIn ? t('settings.cuc.needSsoFirst') : undefined}
                  onClick={() => void handleStartMail()}
                >
                  {busyKey === 'mail'
                    ? t('settings.cuc.starting')
                    : status.mail.loggedIn
                      ? t('settings.cuc.refresh')
                      : t('settings.cuc.connect')}
                </button>
              </div>
            )}
          </li>

          {/* 3. 校园网自助服务 */}
          <li className="mcp-item cuc-card">
            <div className="mcp-item-head">
              <div className="mcp-item-title">
                <span
                  className={`connector-dot ${status.net.loggedIn ? 'running' : ''}`}
                  aria-hidden="true"
                />
                <span>{t('settings.cuc.netTitle')}</span>
                <span className={`mcp-badge ${status.net.loggedIn ? 'remote' : ''}`}>
                  {status.net.loggedIn ? t('settings.cuc.bound') : t('settings.cuc.unbound')}
                </span>
              </div>
              {status.net.loggedIn && (
                <button
                  className={`mini-btn danger${confirmLogout === 'net' ? ' confirming' : ''}`}
                  disabled={busyKey === 'net'}
                  onClick={() => void handleLogout('net')}
                >
                  {confirmLogout === 'net' ? t('settings.cuc.confirmLogout') : t('settings.cuc.logout')}
                </button>
              )}
            </div>
            {(status.net.username || status.net.updatedAt) && (
              <div className="mcp-url">
                {[status.net.username, formatDate(status.net.updatedAt)].filter(Boolean).join(' · ')}
              </div>
            )}

            {netTask?.status === 'captcha_required' && (
              <form className="cuc-flow-box cuc-form" onSubmit={(e) => void handleSubmitNet(e)}>
                <div className="cuc-flow-msg">{netTask.message}</div>
                {captchaSrc && (
                  <div className="cuc-captcha-row">
                    <img
                      className="cuc-captcha-img"
                      src={captchaSrc}
                      alt={t('settings.cuc.captchaAlt')}
                    />
                    <button
                      type="button"
                      className="mini-btn"
                      disabled={busyKey === 'net'}
                      onClick={() => void handleStartNet()}
                    >
                      {t('settings.cuc.reloadCaptcha')}
                    </button>
                  </div>
                )}
                <input
                  className="cuc-input"
                  type="text"
                  autoComplete="username"
                  placeholder={t('settings.cuc.netUsernamePlaceholder')}
                  value={netUsername}
                  onChange={(e) => setNetUsername(e.target.value)}
                />
                <input
                  className="cuc-input"
                  type="password"
                  autoComplete="current-password"
                  placeholder={t('settings.cuc.netPasswordPlaceholder')}
                  value={netPassword}
                  onChange={(e) => setNetPassword(e.target.value)}
                />
                <input
                  className="cuc-input"
                  type="text"
                  autoComplete="off"
                  placeholder={t('settings.cuc.captchaPlaceholder')}
                  value={netVerifyCode}
                  onChange={(e) => setNetVerifyCode(e.target.value)}
                />
                <div className="mcp-actions">
                  <button
                    className="mini-btn"
                    type="submit"
                    disabled={busyKey === 'net' || !netPassword || !netVerifyCode.trim()}
                  >
                    {t('settings.cuc.submit')}
                  </button>
                  <button
                    className="mini-btn"
                    type="button"
                    onClick={() => void handleCancelNet()}
                  >
                    {t('settings.cuc.cancel')}
                  </button>
                </div>
              </form>
            )}

            {netTask?.status === 'sms_required' && (
              <form className="cuc-flow-box" onSubmit={(e) => void handleSubmitNetSms(e)}>
                <div className="cuc-flow-msg">{netTask.message}</div>
                <div className="cuc-inline-form">
                  <input
                    className="cuc-input"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder={t('settings.cuc.smsPlaceholder')}
                    value={netSmsCode}
                    onChange={(e) => setNetSmsCode(e.target.value)}
                  />
                  <button
                    className="mini-btn"
                    type="submit"
                    disabled={busyKey === 'net' || !netSmsCode.trim()}
                  >
                    {t('settings.cuc.submit')}
                  </button>
                  <button
                    className="mini-btn"
                    type="button"
                    onClick={() => void handleCancelNet()}
                  >
                    {t('settings.cuc.cancel')}
                  </button>
                </div>
              </form>
            )}

            {!netTask && (
              <div className="mcp-actions">
                <button
                  className="mini-btn"
                  disabled={busyKey === 'net'}
                  onClick={() => void handleStartNet()}
                >
                  {busyKey === 'net'
                    ? t('settings.cuc.starting')
                    : status.net.loggedIn
                      ? t('settings.cuc.relogin')
                      : t('settings.cuc.connect')}
                </button>
              </div>
            )}
          </li>

          {/* 4. 图书馆馆藏检索 (OPAC) */}
          <li className="mcp-item cuc-card">
            <div className="mcp-item-head">
              <div className="mcp-item-title">
                <span
                  className={`connector-dot ${status.opac.loggedIn ? 'running' : ''}`}
                  aria-hidden="true"
                />
                <span>{t('settings.cuc.opacTitle')}</span>
                <span className={`mcp-badge ${status.opac.loggedIn ? 'remote' : ''}`}>
                  {status.opac.loggedIn ? t('settings.cuc.bound') : t('settings.cuc.unbound')}
                </span>
              </div>
              {status.opac.loggedIn && (
                <button
                  className={`mini-btn danger${confirmLogout === 'opac' ? ' confirming' : ''}`}
                  disabled={busyKey === 'opac'}
                  onClick={() => void handleLogout('opac')}
                >
                  {confirmLogout === 'opac' ? t('settings.cuc.confirmLogout') : t('settings.cuc.logout')}
                </button>
              )}
            </div>
            {status.opac.updatedAt && (
              <div className="mcp-url">{formatDate(status.opac.updatedAt)}</div>
            )}
            <div className="mcp-actions">
              <button
                className="mini-btn"
                disabled={busyKey === 'opac'}
                onClick={() => void handleAuthOpac()}
              >
                {busyKey === 'opac'
                  ? t('settings.cuc.starting')
                  : status.opac.loggedIn
                    ? t('settings.cuc.refresh')
                    : t('settings.cuc.connect')}
              </button>
            </div>
          </li>
        </ul>
      )}
    </section>
  );
}
