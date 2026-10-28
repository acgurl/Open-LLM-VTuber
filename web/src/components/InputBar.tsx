import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useConnection } from '../stores/connection';
import { useSettings } from '../stores/settings';
import { useGroup } from '../stores/group';
import { toast } from '../stores/toast';
import { sendText, interrupt } from '../services/actions';
import { mic } from '../services/mic';
import { camera } from '../services/camera';
import { fileToBase64 } from '../utils/base64';
import { captureCamera, captureScreen } from '../utils/capture';
import { LIMITS, type ImagePayload, type ImageSource } from '../protocol/types';
import { usePresence } from '../hooks/usePresence';

interface PendingImage {
  payload: ImagePayload;
  preview: string;
}

export function InputBar() {
  const { t } = useTranslation();
  const busy = useConnection((s) => s.busy);
  const inGroup = useGroup((s) => s.members.length > 1);
  const micOn = useSettings((s) => s.micOn);
  const [text, setText] = useState('');
  const [images, setImages] = useState<PendingImage[]>([]);
  const [micStarting, setMicStarting] = useState(false);
  const [mediaMenuOpen, setMediaMenuOpen] = useState(false);
  const mediaMenuPresence = usePresence(mediaMenuOpen, 140);
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [text]);

  const grabAndAdd = async (source: 'camera' | 'screen') => {
    setMediaMenuOpen(false);
    try {
      let blob: Blob | null;
      // 实况窗口开着就直接从常驻流抓帧，免得二次开摄像头
      if (source === 'camera') blob = camera.isLive ? await camera.grabBlob() : await captureCamera();
      else blob = await captureScreen();
      if (blob) await addImage(blob, source, 'image/jpeg');
    } catch {
      toast(t('error.generic'), 'error');
    }
  };

  const addImage = async (file: File | Blob, source: ImageSource, mime: string) => {
    if (images.length >= LIMITS.maxImages) {
      toast(t('input.imageTooMany'), 'error');
      return;
    }
    const data = await fileToBase64(file);
    if (data.length > LIMITS.maxImageDataChars) {
      toast(t('input.imageTooLarge'), 'error');
      return;
    }
    setImages((prev) => [
      ...prev,
      { payload: { source, mime_type: mime, data }, preview: URL.createObjectURL(file) },
    ]);
  };

  const removeImage = (idx: number) => {
    setImages((prev) => {
      URL.revokeObjectURL(prev[idx].preview);
      return prev.filter((_, i) => i !== idx);
    });
  };

  const submit = async () => {
    const value = text.trim();
    if (!value && images.length === 0) return;
    if (value.length > LIMITS.textInputChars) {
      toast(t('input.tooLong'), 'error');
      return;
    }
    let payload = images.map((i) => i.payload);
    // 实况开着且没手动附图时，文字轮次也带一帧（对齐老前端）
    if (payload.length === 0 && camera.isLive) {
      const frame = await camera.grabImage().catch(() => null);
      if (frame) payload = [frame];
    }
    sendText(value, payload);
    images.forEach((i) => URL.revokeObjectURL(i.preview));
    setImages([]);
    setText('');
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  const onPaste = (e: React.ClipboardEvent) => {
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          void addImage(file, 'clipboard', item.type);
        }
        return;
      }
    }
  };

  const onMicClick = async () => {
    if (micOn) {
      mic.stop();
      return;
    }
    setMicStarting(true);
    await mic.start();
    setMicStarting(false);
  };

  // 群聊中一轮未结束时禁发
  const sendDisabled = inGroup && busy;
  const hasContent = text.trim().length > 0 || images.length > 0;

  return (
    <div className="input-bar">
      {images.length > 0 && (
        <div className="image-strip">
          {images.map((img, i) => (
            <div key={i} className="image-thumb">
              <img src={img.preview} alt="" width={60} height={60} />
              <button
                type="button"
                className="image-remove"
                aria-label={t('input.removeImage')}
                title={t('input.removeImage')}
                onClick={() => removeImage(i)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div className={`input-row${hasContent ? ' filled' : ''}`}>
        <div className="media-anchor">
          <button
            className="icon-btn"
            title={t('input.uploadImage')}
            aria-label={t('input.uploadImage')}
            aria-expanded={mediaMenuOpen}
            onClick={() => setMediaMenuOpen((v) => !v)}
          >
            <ImageIcon />
          </button>
          {mediaMenuPresence.mounted && (
            <div className={`media-menu${mediaMenuPresence.closing ? ' closing' : ''}`}>
              <button
                onClick={() => {
                  setMediaMenuOpen(false);
                  fileRef.current?.click();
                }}
              >
                {t('input.sourceUpload')}
              </button>
              <button onClick={() => void grabAndAdd('camera')}>{t('input.sourceCamera')}</button>
              <button onClick={() => void grabAndAdd('screen')}>{t('input.sourceScreen')}</button>
            </div>
          )}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          aria-label={t('input.uploadImage')}
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            for (const f of files) void addImage(f, 'upload', f.type || 'image/png');
            e.target.value = '';
          }}
        />
        <textarea
          ref={textRef}
          className="input-text"
          name="message"
          rows={1}
          value={text}
          placeholder={t('input.placeholder')}
          aria-label={t('input.message')}
          autoComplete="off"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
        />
        <button
          className={`icon-btn mic-btn ${micOn ? 'active' : ''}`}
          title={micOn ? t('input.micOn') : t('input.micOff')}
          aria-label={micOn ? t('input.micOn') : t('input.micOff')}
          disabled={micStarting}
          onClick={() => void onMicClick()}
        >
          {micStarting ? <span className="spinner" /> : <MicIcon on={micOn} />}
        </button>
        {busy ? (
          <button
            className="icon-btn stop-btn"
            title={t('input.stop')}
            aria-label={t('input.stop')}
            onClick={interrupt}
          >
            <StopIcon />
          </button>
        ) : (
          <button
            className="icon-btn send-btn"
            title={t('input.send')}
            aria-label={t('input.send')}
            disabled={sendDisabled || (!text.trim() && images.length === 0)}
            onClick={() => void submit()}
          >
            <SendIcon />
          </button>
        )}
      </div>
    </div>
  );
}

function ImageIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="M21 15l-5-5L5 21" />
    </svg>
  );
}

function MicIcon({ on }: { on: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 19v3" />
      {!on && <line x1="4" y1="4" x2="20" y2="20" />}
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 2L11 13" />
      <path d="M22 2l-7 20-4-9-9-4 20-7z" />
    </svg>
  );
}
