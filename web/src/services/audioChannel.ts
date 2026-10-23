import { wsUrl } from './session';
import { handleServerMessage } from './incoming';

// /audio-ws 音频下行通道。未连接时后端会回落到 /client-ws，所以这里只做尽力维护。
class AudioChannel {
  private ws: WebSocket | null = null;
  private uid: string | null = null;
  private retryTimer: number | null = null;

  connect(uid: string) {
    if (this.uid === uid && this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    this.disconnect();
    this.uid = uid;
    let ws: WebSocket;
    try {
      ws = new WebSocket(`${wsUrl('/audio-ws')}?client_uid=${encodeURIComponent(uid)}`);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.ws = ws;
    ws.onmessage = (ev) => {
      try {
        handleServerMessage(JSON.parse(String(ev.data)));
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => {
      if (this.uid) this.scheduleRetry();
    };
  }

  disconnect() {
    this.uid = null;
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.onclose = null;
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
  }

  private scheduleRetry() {
    if (this.retryTimer !== null || !this.uid) return;
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      if (this.uid) this.connect(this.uid);
    }, 3000);
  }
}

export const audioChannel = new AudioChannel();
