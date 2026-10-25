import type { AudioPayload } from '../protocol/types';
import { base64ToBytes } from '../utils/base64';
import { stripTags, buildTagSet } from '../utils/text';
import { useConnection } from '../stores/connection';
import { useChat } from '../stores/chat';
import { useGroup } from '../stores/group';
import { useSubtitle } from '../stores/subtitle';
import { useSettings } from '../stores/settings';
import { live2d } from '../live2d/controller';
import { wsClient } from './websocket';

// 串行播放一轮对话的音频载荷；负责字幕推进、口型、动作、播放完成回执。
class AudioPlayer {
  private queue: AudioPayload[] = [];
  private draining = false;
  private synthComplete = false;
  // 每轮打断递增；旧载荷的播放循环和进度回调据此自行退出
  private epoch = 0;
  private currentAudio: HTMLAudioElement | null = null;
  private finishCurrent: (() => void) | null = null;
  private rafId = 0;
  private heardBase = '';
  private heardPartial = '';

  resetChain() {
    this.heardBase = '';
    this.heardPartial = '';
  }

  getHeardText(): string {
    return this.heardBase + this.heardPartial;
  }

  enqueue(p: AudioPayload) {
    this.queue.push(p);
    void this.drain();
  }

  notifySynthComplete() {
    this.synthComplete = true;
    this.maybeAck();
  }

  // 静音只掐声音，不动播放进度；取消静音时当前句从原位置继续出声
  setMuted(muted: boolean) {
    if (this.currentAudio) this.currentAudio.muted = muted;
  }

  stopAll() {
    this.epoch += 1;
    this.synthComplete = false;
    this.queue.length = 0;
    try {
      this.currentAudio?.pause();
    } catch {
      /* ignore */
    }
    this.finishCurrent?.();
    this.heardPartial = '';
    live2d.setLipSync(0);
    live2d.setSpeaking(false);
    useSubtitle.getState().hide();
  }

  private maybeAck() {
    if (this.synthComplete && !this.draining && this.queue.length === 0) {
      this.synthComplete = false;
      live2d.resetExpression();
      wsClient.send({ type: 'frontend-playback-complete' });
    }
  }

  private async drain() {
    if (this.draining) return;
    this.draining = true;
    while (this.queue.length > 0) {
      const epoch = this.epoch;
      const p = this.queue.shift()!;
      await this.playOne(p, epoch);
      // 被 stopAll 打断后队列里只可能剩新一轮（stopAll 已清空旧队列）；
      // 继续交给下一轮迭代播放，否则结束
      if (epoch !== this.epoch && this.queue.length === 0) break;
    }
    this.draining = false;
    this.maybeAck();
  }

  private async playOne(p: AudioPayload, epoch: number) {
    if (epoch !== this.epoch) return;
    const modelInfo = useConnection.getState().modelInfo;
    const tagSet = buildTagSet(modelInfo);
    const rawText = p.display_text?.text ?? '';
    const isThinkMarker = rawText === '<think>' || rawText === '</think>';
    const clean = isThinkMarker ? '' : stripTags(rawText, tagSet);
    const name = p.display_text?.name ?? '';
    const avatar = p.display_text?.avatar;

    // streamed=true 的文本已通过 text-delta 上屏，不重复追加
    if (clean && !p.streamed) {
      useChat.getState().appendAiDelta(clean, name, avatar);
    }

    if (p.actions) live2d.applyActions(p.actions);

    if (p.audio && p.display_text && useGroup.getState().members.length > 1) {
      wsClient.send({ type: 'audio-play-start', display_text: p.display_text });
    }

    const showSubtitle = clean.length > 0;
    if (showSubtitle) {
      useSubtitle.getState().show(name, avatar, clean, p.audio ? 0 : clean.length);
    }

    if (p.audio && p.audio_mime) {
      live2d.setSpeaking(true);
      const bytes = base64ToBytes(p.audio);
      const blob = new Blob([bytes.buffer as ArrayBuffer], { type: p.audio_mime });
      await this.playBlob(blob, p.volumes ?? [], p.slice_length || 20, clean.length, epoch, (shown) => {
        if (epoch !== this.epoch) return;
        this.heardPartial = clean.slice(0, shown);
        if (showSubtitle) useSubtitle.getState().progress(shown);
      });
      if (epoch !== this.epoch) return;
      live2d.setLipSync(0);
      live2d.setSpeaking(false);
      this.heardBase += clean;
      this.heardPartial = '';
    } else if (clean) {
      // 无音频载荷：只显示不播，按长度短暂停留并允许被打断
      await this.holdDisplay(Math.min(3000, 600 + clean.length * 45), epoch);
      if (epoch !== this.epoch) return;
    }

    if (showSubtitle) useSubtitle.getState().hide();
  }

  private async holdDisplay(ms: number, epoch: number) {
    const end = performance.now() + ms;
    while (epoch === this.epoch) {
      const left = end - performance.now();
      if (left <= 0) return;
      await sleep(Math.min(50, left));
    }
  }

  private playBlob(
    blob: Blob,
    volumes: number[],
    sliceMs: number,
    totalChars: number,
    epoch: number,
    onProgress: (shownChars: number) => void,
  ): Promise<void> {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(blob);
      const el = new Audio(url);
      el.muted = !useSettings.getState().ttsOn;
      this.currentAudio = el;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        cancelAnimationFrame(this.rafId);
        URL.revokeObjectURL(url);
        if (this.currentAudio === el) this.currentAudio = null;
        if (this.finishCurrent === finish) this.finishCurrent = null;
        resolve();
      };
      this.finishCurrent = finish;
      const gain = useConnection.getState().modelInfo?.lipSyncGain ?? 1;
      const tick = () => {
        if (epoch !== this.epoch) {
          finish();
          return;
        }
        const t = el.currentTime * 1000;
        if (volumes.length > 0) {
          const idx = Math.min(volumes.length - 1, Math.max(0, Math.floor(t / sliceMs)));
          live2d.setLipSync((volumes[idx] ?? 0) * gain);
        }
        const durMs = (el.duration && Number.isFinite(el.duration) ? el.duration : 0) * 1000;
        const ratio = durMs > 0 ? Math.min(1, t / durMs) : 0;
        onProgress(Math.round(ratio * totalChars));
        this.rafId = requestAnimationFrame(tick);
      };
      el.onended = () => {
        onProgress(totalChars);
        finish();
      };
      el.onerror = finish;
      this.rafId = requestAnimationFrame(tick);
      el.play().catch(finish);
    });
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export const audioPlayer = new AudioPlayer();
