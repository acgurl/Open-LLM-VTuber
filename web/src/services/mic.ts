import { toast } from '../stores/toast';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import { wsClient } from './websocket';
import { interrupt } from './actions';
import { camera } from './camera';
import type { ImagePayload } from '../protocol/types';
import i18n from '../i18n';

type VadInstance = { start: () => void; pause: () => void; destroy: () => void };

const CHUNK_SAMPLES = 1600; // 100ms @16k
const START_TIMEOUT_MS = 20_000;
const SLOW_HINT_MS = 1_200;

// 前端 VAD（vad-web，silero）：语音段内分块发 mic-audio-data，结束发 mic-audio-end。
class MicController {
  private vad: VadInstance | null = null;
  private starting: Promise<boolean> | null = null;
  private speaking = false;
  private buffer: number[] = [];
  private sentAny = false;

  get active(): boolean {
    return this.vad !== null;
  }

  async toggle(): Promise<void> {
    if (this.active) this.stop();
    else await this.start();
  }

  start(): Promise<boolean> {
    if (this.vad) return Promise.resolve(true);
    if (this.starting) return this.starting;
    this.starting = this.doStart().finally(() => {
      this.starting = null;
    });
    return this.starting;
  }

  stop() {
    try {
      this.vad?.destroy();
    } catch {
      /* ignore */
    }
    this.vad = null;
    this.speaking = false;
    this.buffer = [];
    this.sentAny = false;
    useSettings.getState().setMicOn(false);
  }

  private async doStart(): Promise<boolean> {
    const t = i18n.t.bind(i18n);
    if (!window.isSecureContext) {
      toast(t('error.micInsecure'), 'error');
      return false;
    }
    const slowTimer = window.setTimeout(() => toast(t('error.micSlow')), SLOW_HINT_MS);
    try {
      const { MicVAD } = await import('@ricky0123/vad-web');
      const vad = (await Promise.race([
        MicVAD.new({
          baseAssetPath: assetBase(),
          onnxWASMBasePath: assetBase(),
          onSpeechStart: () => {
            this.speaking = true;
            // barge-in：AI 正在说话时用户开口 → 打断
            if (useConnection.getState().busy) interrupt();
          },
          onSpeechEnd: () => {
            this.speaking = false;
            this.flush();
            // 坑 19：有音频才发 mic-audio-end
            if (this.sentAny) void this.endTurn();
            this.sentAny = false;
          },
          onFrameProcessed: (_probs: unknown, frame: Float32Array) => {
            if (!this.speaking) return;
            for (let i = 0; i < frame.length; i++) this.buffer.push(frame[i]);
            while (this.buffer.length >= CHUNK_SAMPLES) {
              const chunk = this.buffer.splice(0, CHUNK_SAMPLES);
              if (wsClient.send({ type: 'mic-audio-data', audio: chunk })) this.sentAny = true;
            }
          },
        } as Record<string, unknown>),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('mic-timeout')), START_TIMEOUT_MS),
        ),
      ])) as VadInstance;
      vad.start();
      this.vad = vad;
      useSettings.getState().setMicOn(true);
      return true;
    } catch (err) {
      toast(mapMicError(err), 'error');
      return false;
    } finally {
      clearTimeout(slowTimer);
    }
  }

  private flush() {
    if (this.buffer.length === 0) return;
    const chunk = this.buffer.splice(0);
    if (wsClient.send({ type: 'mic-audio-data', audio: chunk })) this.sentAny = true;
  }

  // 实况摄像头开着时，本轮语音再附一帧画面
  private async endTurn() {
    const images: ImagePayload[] = [];
    if (camera.isLive) {
      const frame = await camera.grabImage().catch(() => null);
      if (frame) images.push(frame);
    }
    if (!wsClient.ready) return;
    wsClient.send({ type: 'mic-audio-end', ...(images.length ? { images } : {}) });
  }
}

function assetBase(): string {
  // base './' 构建后 index.html 可能不在根路径，用绝对路径以同源部署为准
  return '/libs/';
}

function mapMicError(err: unknown): string {
  const t = i18n.t.bind(i18n);
  if (err instanceof Error && err.message === 'mic-timeout') return t('error.micTimeout');
  const name = (err as DOMException | null)?.name ?? '';
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return t('error.micPermissionDenied');
    case 'NotFoundError':
    case 'OverconstrainedError':
      return t('error.micNoDevice');
    case 'NotReadableError':
      return t('error.micInUse');
    default:
      return t('error.generic');
  }
}

export const mic = new MicController();
