import { wsUrl, redirectToLogin } from './session';
import { useConnection } from '../stores/connection';
import { toast } from '../stores/toast';
import { LIMITS, type ClientMessage } from '../protocol/types';
import { handleServerMessage, onConnected } from './incoming';
import i18n from '../i18n';

// /client-ws 连接机：心跳、看门狗、断线重连、关闭码处理。
class WSClient {
  private ws: WebSocket | null = null;
  private hbTimer: number | null = null;
  private hbWatchdog: number | null = null;
  private reconnectTimer: number | null = null;
  private attempts = 0;
  private gaveUp = false;

  get ready(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect() {
    this.gaveUp = false;
    this.clearReconnect();
    useConnection
      .getState()
      .setStatus(this.attempts > 0 ? 'reconnecting' : 'connecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl('/client-ws'));
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      useConnection.getState().setStatus('online');
      this.startHeartbeat();
      onConnected();
    };
    ws.onmessage = (ev) => {
      try {
        handleServerMessage(JSON.parse(String(ev.data)));
      } catch {
        /* 非法帧忽略，与后端行为一致 */
      }
    };
    ws.onclose = (ev) => this.onClose(ev);
    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    };
  }

  send(msg: ClientMessage): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      return true;
    }
    return false;
  }

  markAlive() {
    if (this.hbWatchdog !== null) {
      clearTimeout(this.hbWatchdog);
      this.hbWatchdog = null;
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.hbTimer = window.setInterval(() => {
      if (!this.send({ type: 'heartbeat' })) return;
      this.hbWatchdog = window.setTimeout(() => {
        try {
          this.ws?.close();
        } catch {
          /* ignore */
        }
      }, LIMITS.heartbeatTimeoutMs);
    }, LIMITS.heartbeatIntervalMs);
  }

  private stopHeartbeat() {
    if (this.hbTimer !== null) {
      clearInterval(this.hbTimer);
      this.hbTimer = null;
    }
    this.markAlive();
  }

  private onClose(ev: CloseEvent) {
    this.stopHeartbeat();
    if (this.gaveUp) return;
    const t = i18n.t.bind(i18n);
    if (ev.code === 4401) {
      useConnection.getState().setStatus('unauthorized');
      this.gaveUp = true;
      toast(t('error.authRequired'), 'error');
      setTimeout(redirectToLogin, 800);
      return;
    }
    if (ev.code === 1008) {
      toast(t('error.originNotAllowed'), 'error');
    } else if (ev.code === 1013) {
      toast(t('error.tooManyConnections'), 'error');
    }
    useConnection.getState().setStatus('reconnecting');
    this.scheduleReconnect();
  }

  private scheduleReconnect() {
    if (this.gaveUp) return;
    const delay = Math.min(15000, 800 * 2 ** this.attempts) + Math.random() * 400;
    this.attempts += 1;
    this.clearReconnect();
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
  }

  private clearReconnect() {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

export const wsClient = new WSClient();
