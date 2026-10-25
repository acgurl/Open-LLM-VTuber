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
  private stopped = false;
  private currentAudio: HTMLAudioElement | null = null;
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
    this.stopped = false;
    this.queue.push(p);
    void this.drain();
  }

  notifySynthComplete() {
    this.synthComplete = true;
    this.maybeAck();
  }

  stopAll() {
    this.stopped = true;
    this.synthComplete = false;
    this.queue.length = 0;
    try {
      this.currentAudio?.pause();
    } catch {
      /* ignore */
    }
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
      const p = this.queue.shift()!;
      await this.playOne(p);
      if (this.stopped) {
        this.queue.length = 0;
        break;
      }
    }
    this.draining = false;
    this.maybeAck();
  }

  private async playOne(p: AudioPayload) {
    if (this.stopped) return;
    const ttsOn = useSettings.getState().ttsOn;
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

    if (ttsOn && p.audio && p.display_text && useGroup.getState().members.length > 1) {
      wsClient.send({ type: 'audio-play-start', display_text: p.display_text });
    }

    const showSubtitle = clean.length > 0;
    if (showSubtitle) {
      useSubtitle.getState().show(name, avatar, clean, ttsOn && p.audio ? 0 : clean.length);
    }

    if (ttsOn && p.audio && p.audio_mime) {
      live2d.setSpeaking(true);
      const bytes = base64ToBytes(p.audio);
      const blob = new Blob([bytes.buffer as ArrayBuffer], { type: p.audio_mime });
      await this.playBlob(blob, p.volumes ?? [], p.slice_length || 20, clean.length, (shown) => {
        this.heardPartial = clean.slice(0, shown);
        if (showSubtitle) useSubtitle.getState().progress(shown);
      });
      live2d.setLipSync(0);
      live2d.setSpeaking(false);
      this.heardBase += clean;
      this.heardPartial = '';
    } else if (clean && !this.stopped) {
      // 静音载荷：只显示不播，按长度短暂停留
      await sleep(Math.min(3000, 600 + clean.length * 45));
    }

    if (showSubtitle) useSubtitle.getState().hide();
  }

  private playBlob(
    blob: Blob,
    volumes: number[],
    sliceMs: number,
    totalChars: number,
    onProgress: (shownChars: number) => void,
  ): Promise<void> {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(blob);
      const el = new Audio(url);
      this.currentAudio = el;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        cancelAnimationFrame(this.rafId);
        URL.revokeObjectURL(url);
        if (this.currentAudio === el) this.currentAudio = null;
        resolve();
      };
      const gain = useConnection.getState().modelInfo?.lipSyncGain ?? 1;
      const tick = () => {
        if (this.stopped) {
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
