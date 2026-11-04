import { toast } from '../stores/toast';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import { wsClient } from './websocket';
import { interrupt } from './actions';
import { audioPlayer } from './audioPlayer';
import { camera } from './camera';
import type { ImagePayload } from '../protocol/types';
import i18n from '../i18n';

type VadInstance = { start: () => void; pause: () => void; destroy: () => void };

const CHUNK_SAMPLES = 1600; // 100ms @16k
const START_TIMEOUT_MS = 20_000;
const SLOW_HINT_MS = 1_200;

// 前端 VAD（vad-web，silero）：语音段内分块发 mic-audio-data，结束发 mic-audio-end。
// onSpeechStart 之后先在本地缓冲，onSpeechRealStart（达到 minSpeechFrames）才开始推流；
// onVADMisfire（咳嗽、点击等过短片段）直接丢弃缓冲，不发 mic-audio-end。
class MicController {
  private vad: VadInstance | null = null;
  private starting: Promise<boolean> | null = null;
  // stop() 递增它，让进行中的 doStart 作废
  private startGen = 0;
  private speaking = false;
  private confirmed = false;
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
    const starting: Promise<boolean> = this.doStart().finally(() => {
      if (this.starting === starting) this.starting = null;
    });
    this.starting = starting;
    return starting;
  }

  stop() {
    this.startGen++;
    this.starting = null;
    destroyQuietly(this.vad);
    this.vad = null;
    this.speaking = false;
    this.confirmed = false;
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
    const gen = ++this.startGen;
    const slowTimer = window.setTimeout(() => toast(t('error.micSlow')), SLOW_HINT_MS);
    let timeoutTimer: number | undefined;
    let pending: Promise<VadInstance> | null = null;
    try {
      const { MicVAD } = await import('@ricky0123/vad-web');
      pending = MicVAD.new({
        baseAssetPath: assetBase(),
        onnxWASMBasePath: assetBase(),
        onSpeechStart: () => {
          this.speaking = true;
          this.confirmed = false;
          // barge-in：AI 还在生成或播放时用户开口 → 打断
          if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
        },
        onSpeechRealStart: () => {
          if (!this.speaking) return;
          this.confirmed = true;
          this.sendChunks();
        },
        onVADMisfire: () => {
          this.resetSpeech();
        },
        onSpeechEnd: () => {
          // SpeechEnd 只在达到 minSpeechFrames 时触发，缓冲一律视为有效语音
          this.confirmed = true;
          this.flush();
          // 坑 19：有音频才发 mic-audio-end
          if (this.sentAny) void this.endTurn();
          this.resetSpeech();
        },
        onFrameProcessed: (_probs: unknown, frame: Float32Array) => {
          if (!this.speaking) return;
          for (let i = 0; i < frame.length; i++) this.buffer.push(frame[i]);
          if (this.confirmed) this.sendChunks();
        },
      } as Record<string, unknown>) as Promise<VadInstance>;
      const vad = await Promise.race([
        pending,
        new Promise<never>((_, reject) => {
          timeoutTimer = window.setTimeout(
            () => reject(new Error('mic-timeout')),
            START_TIMEOUT_MS,
          );
        }),
      ]);
      // 等待期间被 stop() 取消：释放这个实例，不再置 micOn
      if (gen !== this.startGen) {
        destroyQuietly(vad);
        return false;
      }
      vad.start();
      this.vad = vad;
      useSettings.getState().setMicOn(true);
      return true;
    } catch (err) {
      // 超时（或取消）后 MicVAD.new 仍可能晚到：到了就销毁，释放麦克风
      pending?.then(destroyQuietly, () => undefined);
      if (gen !== this.startGen) return false;
      toast(mapMicError(err), 'error');
      return false;
    } finally {
      clearTimeout(slowTimer);
      clearTimeout(timeoutTimer);
    }
  }

  private resetSpeech() {
    this.speaking = false;
    this.confirmed = false;
    this.buffer = [];
    this.sentAny = false;
  }

  private sendChunks() {
    while (this.buffer.length >= CHUNK_SAMPLES) {
      const chunk = this.buffer.splice(0, CHUNK_SAMPLES);
      if (wsClient.send({ type: 'mic-audio-data', audio: chunk })) this.sentAny = true;
    }
  }

  private flush() {
    this.sendChunks();
    if (this.buffer.length === 0) return;
    const chunk = this.buffer.splice(0);
    if (wsClient.send({ type: 'mic-audio-data', audio: chunk })) this.sentAny = true;
  }

  // 实况摄像头开着时，本轮语音再附一帧画面
  private async endTurn() {
    // 和文字发送一致：提交本轮前补一次打断。用户开口时新一轮 chain-start 可能还没到
    // （busy 仍为 false），那次 barge-in 会漏判，这里保证旧 TTS 不会压在新一轮前面
    if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
    const images: ImagePayload[] = [];
    if (camera.isLive) {
      const frame = await camera.grabImage().catch(() => null);
      if (frame) images.push(frame);
    }
    if (!wsClient.ready) return;
    wsClient.send({ type: 'mic-audio-end', ...(images.length ? { images } : {}) });
  }
}

function destroyQuietly(vad: VadInstance | null) {
  try {
    vad?.destroy();
  } catch {
    /* ignore */
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
