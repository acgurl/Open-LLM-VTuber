import { memo, useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../services/api';
import { sendText } from '../services/actions';
import {
  authOpac,
  cancelWechatLogin,
  fetchCucAuthStatus,
  pollWechatLogin,
  startMailAuth,
  startWechatLogin,
  submitMailSms,
  type MailAuthResult,
  type WechatLoginTask,
} from '../services/cucAuth';
import type { CucAuthEntry } from '../stores/chat';
import { useConnection } from '../stores/connection';
import { useCucAuth } from '../stores/cucAuth';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { CheckIcon, QrCodeIcon } from './icons';

const WECHAT_POLL_TIMEOUT_MS = 20000;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isWechatInFlight(task: WechatLoginTask | null): task is WechatLoginTask {
  return task !== null && (task.status === 'pending' || task.status === 'scanned');
}

export const CucAuthCard = memo(function CucAuthCard({ entry }: { entry: CucAuthEntry }) {
  const { t } = useTranslation();
  const available = useCucAuth((s) => s.available);
  const activeCardId = useCucAuth((s) => s.activeCardId);
  const confirmedAtService = useCucAuth((s) => s.confirmedAt[entry.service]);
  const confirmedAtSso = useCucAuth((s) => s.confirmedAt.sso);
  const online = useConnection((s) => s.status === 'online');

  const [localConfirmed, setLocalConfirmed] = useState(false);
  const [ssoStatusLoggedIn, setSsoStatusLoggedIn] = useState<boolean | null>(null);
  const [wechatTask, setWechatTask] = useState<WechatLoginTask | null>(null);
  const [mailTask, setMailTask] = useState<MailAuthResult | null>(null);
  const [mailSmsCode, setMailSmsCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [retried, setRetried] = useState(false);

  const mountedRef = useRef(true);
  const taskRef = useRef<WechatLoginTask | null>(null);
  taskRef.current = wechatTask;

  const isConfirmed = localConfirmed || confirmedAtService > entry.createdAt;
  const ssoReady = confirmedAtSso > entry.createdAt || ssoStatusLoggedIn === true;

  const cancelTaskBestEffort = useCallback((task: WechatLoginTask | null) => {
    if (!isWechatInFlight(task)) return;
    void cancelWechatLogin(task.taskId).catch(() => {});
  }, []);

  const startQr = useCallback(async () => {
    if (!mountedRef.current) return;
    useCucAuth.getState().claimActiveCard(entry.id);
    setBusy(true);
    setErrorMsg('');
    try {
      const task = await startWechatLogin();
      if (!mountedRef.current || useCucAuth.getState().activeCardId !== entry.id) {
        void cancelWechatLogin(task.taskId).catch(() => {});
        return;
      }
      useCucAuth.getState().setAvailable(true);
      setWechatTask(task);
    } catch (error) {
      if (!mountedRef.current) return;
      if (error instanceof ApiError && error.status === 404) {
        useCucAuth.getState().setAvailable(false);
        return;
      }
      setErrorMsg(errorText(error));
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, [entry.id]);

  // 仅实况卡片在挂载时主动检查状态或拉起二维码；历史回放卡片不自动发起网络请求。
  useEffect(() => {
    mountedRef.current = true;
    if (entry.fromHistory || isConfirmed || available === false) {
      return () => {
        mountedRef.current = false;
      };
    }

    let cancelled = false;
    const init = async () => {
      if (entry.service === 'sso') {
        await startQr();
        return;
      }
      try {
        const status = await fetchCucAuthStatus();
        if (cancelled || !mountedRef.current) return;
        useCucAuth.getState().setAvailable(true);
        setSsoStatusLoggedIn(status.sso.loggedIn);
        if (entry.service === 'mail' && !status.sso.loggedIn) {
          await startQr();
        }
      } catch (error) {
        if (cancelled || !mountedRef.current) return;
        if (error instanceof ApiError && error.status === 404) {
          useCucAuth.getState().setAvailable(false);
        } else {
          setErrorMsg(errorText(error));
        }
      }
    };

    void init();
    return () => {
      cancelled = true;
      mountedRef.current = false;
    };
    // 仅在卡片首次挂载时初始化，避免状态切换重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 卸载时释放占用与未完成的微信扫码任务，避免触及后端每用户 2 个任务上限
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      cancelTaskBestEffort(taskRef.current);
      useCucAuth.getState().releaseActiveCard(entry.id);
    };
  }, [cancelTaskBestEffort, entry.id]);

  // 当另一张卡片或设置面板接管/完成登录时，及时清理本卡挂起的扫码任务
  useEffect(() => {
    if (isConfirmed && isWechatInFlight(wechatTask)) {
      cancelTaskBestEffort(wechatTask);
      setWechatTask(null);
      useCucAuth.getState().releaseActiveCard(entry.id);
      return;
    }
    if (activeCardId !== null && activeCardId !== entry.id && isWechatInFlight(wechatTask)) {
      cancelTaskBestEffort(wechatTask);
      setWechatTask(null);
    }
  }, [activeCardId, cancelTaskBestEffort, entry.id, isConfirmed, wechatTask]);

  const wechatTaskId = wechatTask?.taskId ?? null;
  const wechatActive =
    !isConfirmed &&
    activeCardId === entry.id &&
    isWechatInFlight(wechatTask);

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
          if (stopped || ac.signal.aborted || !mountedRef.current) return;

          if (next.status === 'confirmed') {
            setWechatTask(null);
            setSsoStatusLoggedIn(true);
            useCucAuth.getState().releaseActiveCard(entry.id);
            useCucAuth.getState().notifyConfirmed('sso');
            if (entry.service === 'sso') {
              setLocalConfirmed(true);
            }
            toast(t('settings.cuc.ssoConfirmed'), 'success');
            return;
          }

          if (
            next.status === 'expired' ||
            next.status === 'cancelled' ||
            next.status === 'failed'
          ) {
            setWechatTask(next);
            useCucAuth.getState().releaseActiveCard(entry.id);
            return;
          }

          setWechatTask((prev) => ({
            ...next,
            qrBase64: next.qrBase64 ?? prev?.qrBase64,
            qrMimeType: next.qrMimeType ?? prev?.qrMimeType ?? null,
          }));
        } catch (error) {
          if (stopped || ac.signal.aborted || !mountedRef.current) return;
          setErrorMsg(errorText(error));
          setWechatTask(null);
          useCucAuth.getState().releaseActiveCard(entry.id);
          return;
        }
      }
    };

    void loop();
    return () => {
      stopped = true;
      ac.abort();
    };
  }, [entry.id, entry.service, t, wechatActive, wechatTaskId]);

  if (available === false) return null;

  const handleCancelWechat = async () => {
    const current = wechatTask;
    setWechatTask(null);
    useCucAuth.getState().releaseActiveCard(entry.id);
    if (current) {
      try {
        await cancelWechatLogin(current.taskId);
      } catch {
        // 忽略已过期任务的取消错误
      }
    }
  };

  const handleConnectMail = async () => {
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await startMailAuth();
      useCucAuth.getState().setAvailable(true);
      if (res.status === 'confirmed') {
        setMailTask(null);
        setMailSmsCode('');
        setLocalConfirmed(true);
        useCucAuth.getState().notifyConfirmed('mail');
        toast(res.message || t('settings.cuc.mailConfirmed'), 'success');
      } else {
        setMailTask(res);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        useCucAuth.getState().setAvailable(false);
        return;
      }
      setErrorMsg(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const handleSubmitMailSms = async (e: FormEvent) => {
    e.preventDefault();
    if (!mailTask?.taskId || !mailSmsCode.trim()) return;
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await submitMailSms(mailTask.taskId, mailSmsCode.trim());
      setMailTask(null);
      setMailSmsCode('');
      setLocalConfirmed(true);
      useCucAuth.getState().notifyConfirmed('mail');
      toast(res.message || t('settings.cuc.mailConfirmed'), 'success');
    } catch (error) {
      setErrorMsg(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const handleAuthOpac = async () => {
    setBusy(true);
    setErrorMsg('');
    try {
      const res = await authOpac();
      useCucAuth.getState().setAvailable(true);
      setLocalConfirmed(true);
      useCucAuth.getState().notifyConfirmed('opac');
      toast(res.message || t('settings.cuc.opacConfirmed'), 'success');
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        useCucAuth.getState().setAvailable(false);
        return;
      }
      setErrorMsg(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const handleOpenSettings = () => {
    useSettings.getState().setSettingsOpen(true);
  };

  const handleRetry = () => {
    if (!entry.retryPrompt || !online || retried) return;
    setRetried(true);
    sendText(entry.retryPrompt);
  };

  const qrSrc =
    wechatTask?.qrBase64 && wechatTask.qrMimeType
      ? `data:${wechatTask.qrMimeType};base64,${wechatTask.qrBase64}`
      : wechatTask?.qrPath || '';

  const badgeText = isConfirmed
    ? t('cucAuth.badge.bound')
    : wechatTask?.status === 'scanned'
      ? t('cucAuth.badge.scanned')
      : isWechatInFlight(wechatTask)
        ? t('cucAuth.badge.waiting')
        : t('cucAuth.badge.unbound');

  const badgeClass = isConfirmed
    ? 'ok'
    : isWechatInFlight(wechatTask)
      ? 'pending'
      : '';

  const title = t(`cucAuth.title.${entry.service}`);
  const subtitle = isConfirmed
    ? t('cucAuth.confirmedSub')
    : t(`cucAuth.reason.${entry.reason}`);

  return (
    <div className="tool-card cuc-auth-card">
      <div className="cuc-auth-head">
        <span className="cuc-auth-glyph" aria-hidden="true">
          <QrCodeIcon />
        </span>
        <div className="cuc-auth-titles">
          <strong className="cuc-auth-name">{title}</strong>
          <span className="cuc-auth-sub">{subtitle}</span>
        </div>
        <span className={`cuc-auth-badge${badgeClass ? ` ${badgeClass}` : ''}`}>
          {badgeText}
        </span>
      </div>

      <div className="cuc-auth-body">
        {isConfirmed ? (
          <div className="cuc-auth-done">
            <CheckIcon />
            <span>{t(`cucAuth.done.${entry.service}`)}</span>
          </div>
        ) : (
          <>
            {errorMsg && <div className="cuc-auth-error">{errorMsg}</div>}

            {wechatTask ? (
              <div className="cuc-auth-qr-box">
                {entry.service === 'mail' && (
                  <div className="cuc-flow-msg">{t('cucAuth.needSsoForMail')}</div>
                )}
                {isWechatInFlight(wechatTask) && qrSrc && (
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
                      type="button"
                      className="mini-btn"
                      disabled={busy}
                      onClick={() => void startQr()}
                    >
                      {t('cucAuth.retryQr')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="mini-btn"
                    onClick={() => void handleCancelWechat()}
                  >
                    {t('cucAuth.cancel')}
                  </button>
                </div>
              </div>
            ) : entry.service === 'sso' ? (
              <div className="cuc-auth-actions">
                {busy ? (
                  <span className="cuc-flow-msg">{t('cucAuth.loadingQr')}</span>
                ) : (
                  <button
                    type="button"
                    className="cuc-auth-primary"
                    onClick={() => void startQr()}
                  >
                    {t('cucAuth.scanWechat')}
                  </button>
                )}
              </div>
            ) : entry.service === 'mail' ? (
              mailTask?.status === 'sms_required' && mailTask.taskId ? (
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
                      disabled={busy || !mailSmsCode.trim()}
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
                      {t('cucAuth.cancel')}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="cuc-auth-actions">
                  {ssoReady ? (
                    <button
                      type="button"
                      className="cuc-auth-primary"
                      disabled={busy}
                      onClick={() => void handleConnectMail()}
                    >
                      {busy ? t('settings.cuc.starting') : t('cucAuth.connectMail')}
                    </button>
                  ) : (
                    <>
                      <span className="cuc-flow-msg">{t('cucAuth.needSsoForMail')}</span>
                      <button
                        type="button"
                        className="cuc-auth-primary"
                        disabled={busy}
                        onClick={() => void startQr()}
                      >
                        {busy ? t('cucAuth.loadingQr') : t('cucAuth.scanWechat')}
                      </button>
                    </>
                  )}
                </div>
              )
            ) : entry.service === 'net' ? (
              <div className="cuc-auth-actions">
                <button
                  type="button"
                  className="cuc-auth-primary"
                  onClick={handleOpenSettings}
                >
                  {t('cucAuth.openSettingsNet')}
                </button>
              </div>
            ) : (
              <div className="cuc-auth-actions">
                <button
                  type="button"
                  className="cuc-auth-primary"
                  disabled={busy}
                  onClick={() => void handleAuthOpac()}
                >
                  {busy ? t('settings.cuc.starting') : t('cucAuth.refreshOpac')}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <div className="cuc-auth-foot">
        {isConfirmed && entry.retryPrompt && (
          <button
            type="button"
            className="cuc-auth-primary"
            disabled={!online || retried}
            onClick={handleRetry}
          >
            {retried ? t('cucAuth.continued') : t('cucAuth.continueQuery')}
          </button>
        )}
        <button type="button" className="mini-btn" onClick={handleOpenSettings}>
          {t('cucAuth.openSettings')}
        </button>
      </div>
    </div>
  );
});
