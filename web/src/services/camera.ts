import { toast } from '../stores/toast';
import { useCamera } from '../stores/camera';
import { fileToBase64 } from '../utils/base64';
import type { ImagePayload } from '../protocol/types';
import i18n from '../i18n';

const CAPTURE_MAX_WIDTH = 640;
const CAPTURE_QUALITY = 0.8;

// 常驻摄像头：流一直开着做预览，语音轮次结束时从同一条流抓一帧随 mic-audio-end 发出。
class CameraController {
  private starting: Promise<boolean> | null = null;
  private captureVideo: HTMLVideoElement | null = null;

  get isLive(): boolean {
    return useCamera.getState().stream !== null;
  }

  start(): Promise<boolean> {
    if (this.isLive) return Promise.resolve(true);
    if (this.starting) return this.starting;
    this.starting = this.doStart().finally(() => {
      this.starting = null;
    });
    return this.starting;
  }

  stop() {
    useCamera.getState().stream?.getTracks().forEach((t) => t.stop());
    if (this.captureVideo) {
      this.captureVideo.srcObject = null;
      this.captureVideo = null;
    }
    const state = useCamera.getState();
    state.setStream(null);
    state.setStarting(false);
    state.setError('');
  }

  async grabBlob(): Promise<Blob | null> {
    const video = this.captureVideo;
    if (!video || video.readyState < 2 || !video.videoWidth) return null;
    const scale = Math.min(1, CAPTURE_MAX_WIDTH / video.videoWidth);
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', CAPTURE_QUALITY));
  }

  async grabImage(): Promise<ImagePayload | null> {
    const blob = await this.grabBlob();
    if (!blob) return null;
    return { source: 'camera', mime_type: 'image/jpeg', data: await fileToBase64(blob) };
  }

  private async doStart(): Promise<boolean> {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      return this.fail('error.camInsecure');
    }
    const state = useCamera.getState();
    state.setStarting(true);
    state.setError('');
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      // 抓帧用的隐藏 video：与预览元素解耦，窗口没渲染时也能拿到帧
      const video = document.createElement('video');
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      this.captureVideo = video;
      stream.getVideoTracks()[0]?.addEventListener('ended', () => this.stop());
      useCamera.getState().setStream(stream);
      useCamera.getState().setStarting(false);
      return true;
    } catch (err) {
      stream?.getTracks().forEach((t) => t.stop());
      this.captureVideo = null;
      return this.fail(cameraErrorKey(err));
    }
  }

  // 存 i18n key 而不是译文，切语言后窗口上的错误提示才跟着变
  private fail(key: string): boolean {
    const state = useCamera.getState();
    state.setStarting(false);
    state.setError(key);
    toast(i18n.t(key), 'error');
    return false;
  }
}

function cameraErrorKey(err: unknown): string {
  const name = (err as DOMException | null)?.name ?? '';
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'error.camPermissionDenied';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'error.camNoDevice';
    case 'NotReadableError':
    case 'AbortError':
      return 'error.camInUse';
    default:
      return 'error.generic';
  }
}

export const camera = new CameraController();
