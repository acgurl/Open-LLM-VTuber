import i18n from '../i18n';
import { toast } from '../stores/toast';
import { mapMicError } from './mic';
import { redirectToLogin } from './session';

const TARGET_SAMPLE_RATE = 16_000;
const MAX_RECORDING_SECONDS = 115; // 留出余量，低于后端 MAX_AUDIO_SECONDS (120s)
const MIN_RECORDING_MS = 350;

const WORKLET_CODE = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length > 0) {
      this.port.postMessage(new Float32Array(input[0]));
    }
    return true;
  }
}
registerProcessor('pcm-capture-processor', PcmCaptureProcessor);
`;

export interface PttCallbacks {
  onReady?: () => void;
  onLevel?: (level: number) => void;
  onAutoStop?: () => void;
}

export type PttStopResult =
  | { status: 'ok'; wav: Blob; durationMs: number }
  | { status: 'too-short' }
  | { status: 'empty' };

class PttController {
  private sessionGen = 0;
  private active = false;
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processorNode: AudioNode | null = null;
  private sinkGain: GainNode | null = null;
  private chunks: Float32Array[] = [];
  private totalSamples = 0;
  private sampleRate = TARGET_SAMPLE_RATE;
  private autoStopped = false;
  private callbacks: PttCallbacks = {};

  get isActive(): boolean {
    return this.active;
  }

  async start(callbacks: PttCallbacks): Promise<boolean> {
    const t = i18n.t.bind(i18n);
    if (!window.isSecureContext) {
      toast(t('error.micInsecure'), 'error');
      return false;
    }

    this.cleanup();
    const gen = ++this.sessionGen;
    this.active = true;
    this.autoStopped = false;
    this.chunks = [];
    this.totalSamples = 0;
    this.callbacks = callbacks;

    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      if (!this.active || gen !== this.sessionGen) {
        stopTracks(stream);
        return false;
      }

      ctx = createAudioContext();
      await ctx.resume().catch(() => undefined);

      if (!this.active || gen !== this.sessionGen) {
        stopTracks(stream);
        void ctx.close().catch(() => undefined);
        return false;
      }

      this.stream = stream;
      this.ctx = ctx;
      this.sampleRate = ctx.sampleRate || TARGET_SAMPLE_RATE;
      this.source = ctx.createMediaStreamSource(stream);
      this.sinkGain = ctx.createGain();
      this.sinkGain.gain.value = 0;

      const attached = await this.attachCaptureNode(ctx, this.source, this.sinkGain, gen);
      if (!attached || !this.active || gen !== this.sessionGen) {
        this.cleanup();
        return false;
      }

      this.callbacks.onReady?.();
      return true;
    } catch (err) {
      stopTracks(stream);
      if (ctx) void ctx.close().catch(() => undefined);
      if (gen === this.sessionGen && this.active) {
        this.cleanup();
        toast(mapMicError(err), 'error');
      }
      return false;
    }
  }

  cancel(): void {
    this.sessionGen += 1;
    this.cleanup();
  }

  stopAndEncode(): PttStopResult {
    this.sessionGen += 1;
    const chunks = this.chunks;
    const totalSamples = this.totalSamples;
    const sampleRate = this.sampleRate;
    this.cleanup();

    if (totalSamples === 0 || chunks.length === 0) {
      return { status: 'empty' };
    }

    const durationMs = (totalSamples / sampleRate) * 1000;
    if (durationMs < MIN_RECORDING_MS) {
      return { status: 'too-short' };
    }

    const merged = mergeChunks(chunks, totalSamples);
    const resampled = downsampleTo16k(merged, sampleRate);
    const maxSamples = TARGET_SAMPLE_RATE * MAX_RECORDING_SECONDS;
    const trimmed = resampled.length > maxSamples ? resampled.subarray(0, maxSamples) : resampled;
    const wav = encodePcmWav(trimmed, TARGET_SAMPLE_RATE);

    return { status: 'ok', wav, durationMs };
  }

  private async attachCaptureNode(
    ctx: AudioContext,
    source: MediaStreamAudioSourceNode,
    sinkGain: GainNode,
    gen: number,
  ): Promise<boolean> {
    if (typeof AudioWorkletNode !== 'undefined' && ctx.audioWorklet) {
      let blobUrl: string | null = null;
      try {
        blobUrl = URL.createObjectURL(new Blob([WORKLET_CODE], { type: 'application/javascript' }));
        await ctx.audioWorklet.addModule(blobUrl);
        if (!this.active || gen !== this.sessionGen) return false;
        const worklet = new AudioWorkletNode(ctx, 'pcm-capture-processor');
        worklet.port.onmessage = (event: MessageEvent<Float32Array>) => {
          if (!this.active || gen !== this.sessionGen) return;
          if (event.data?.length) this.pushFrame(event.data);
        };
        source.connect(worklet);
        worklet.connect(sinkGain);
        sinkGain.connect(ctx.destination);
        this.processorNode = worklet;
        return true;
      } catch {
        // Fallback to ScriptProcessorNode below if AudioWorklet is blocked or unsupported.
      } finally {
        if (blobUrl) URL.revokeObjectURL(blobUrl);
      }
    }

    if (typeof ctx.createScriptProcessor === 'function') {
      const sp = ctx.createScriptProcessor(4096, 1, 1);
      sp.onaudioprocess = (event) => {
        if (!this.active || gen !== this.sessionGen) return;
        const channel = event.inputBuffer.getChannelData(0);
        if (channel.length > 0) this.pushFrame(new Float32Array(channel));
      };
      source.connect(sp);
      sp.connect(sinkGain);
      sinkGain.connect(ctx.destination);
      this.processorNode = sp;
      return true;
    }

    return false;
  }

  private pushFrame(frame: Float32Array): void {
    this.chunks.push(frame);
    this.totalSamples += frame.length;

    let sumSquares = 0;
    for (let i = 0; i < frame.length; i += 1) {
      const s = frame[i];
      sumSquares += s * s;
    }
    const rms = Math.sqrt(sumSquares / frame.length);
    const level = Math.min(1, Math.pow(rms * 6.5, 0.68));
    this.callbacks.onLevel?.(level);

    if (!this.autoStopped && this.totalSamples / this.sampleRate >= MAX_RECORDING_SECONDS) {
      this.autoStopped = true;
      this.callbacks.onAutoStop?.();
    }
  }

  private cleanup(): void {
    this.active = false;
    this.callbacks = {};
    this.chunks = [];
    this.totalSamples = 0;

    try {
      if (this.processorNode && 'port' in this.processorNode) {
        (this.processorNode as AudioWorkletNode).port.onmessage = null;
      }
      if (this.processorNode && 'onaudioprocess' in this.processorNode) {
        (this.processorNode as ScriptProcessorNode).onaudioprocess = null;
      }
      this.processorNode?.disconnect();
      this.source?.disconnect();
      this.sinkGain?.disconnect();
    } catch {
      /* ignore */
    }
    this.processorNode = null;
    this.source = null;
    this.sinkGain = null;

    stopTracks(this.stream);
    this.stream = null;

    if (this.ctx) {
      const ctx = this.ctx;
      this.ctx = null;
      void ctx.close().catch(() => undefined);
    }
  }
}

function createAudioContext(): AudioContext {
  const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  try {
    return new Ctor({ sampleRate: TARGET_SAMPLE_RATE });
  } catch {
    return new Ctor();
  }
}

function stopTracks(stream: MediaStream | null): void {
  if (!stream) return;
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch {
      /* ignore */
    }
  }
}

function mergeChunks(chunks: Float32Array[], totalLength: number): Float32Array {
  const out = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function downsampleTo16k(samples: Float32Array, sourceRate: number): Float32Array {
  if (sourceRate === TARGET_SAMPLE_RATE) return samples;
  const ratio = sourceRate / TARGET_SAMPLE_RATE;
  const outLength = Math.max(1, Math.floor(samples.length / ratio));
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    const count = end - start;
    if (count > 0) {
      let sum = 0;
      for (let j = start; j < end; j += 1) sum += samples[j];
      out[i] = sum / count;
    } else {
      out[i] = samples[Math.min(samples.length - 1, start)];
    }
  }
  return out;
}

function encodePcmWav(samples: Float32Array, sampleRate: number): Blob {
  const dataBytes = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataBytes, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: 'audio/wav' });
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

export async function transcribeWav(wav: Blob, signal?: AbortSignal): Promise<string> {
  const t = i18n.t.bind(i18n);
  const form = new FormData();
  form.append('file', wav, 'recording.wav');

  const response = await fetch('/asr', {
    method: 'POST',
    credentials: 'include',
    body: form,
    signal,
  });

  if (response.status === 401) {
    redirectToLogin();
    throw new Error(t('error.authRequired'));
  }

  let data: { text?: unknown; error?: unknown } | null = null;
  try {
    data = (await response.json()) as { text?: unknown; error?: unknown };
  } catch {
    data = null;
  }

  if (!response.ok) {
    if (response.status === 429) {
      throw new Error(t('error.asrBusy'));
    }
    const message =
      typeof data?.error === 'string' && data.error ? data.error : t('error.generic');
    throw new Error(message);
  }

  return typeof data?.text === 'string' ? data.text.trim() : '';
}

export const ptt = new PttController();
