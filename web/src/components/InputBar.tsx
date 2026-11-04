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
import { ImageIcon, MicIcon, StopIcon, SendIcon } from './icons';

interface PendingImage {
  id: number;
  payload: ImagePayload;
  preview: string;
}

let imageSeq = 0;

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
  const barRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  // 已占用的附图名额：多张图并发编码时 images 状态还没更新，靠它同步计数才能守住上限
  const imageSlots = useRef(0);

  // 窄屏聊天区贴输入框上沿，输入条自身会长高（换行、附图条），高度得上报给 CSS
  useEffect(() => {
    const el = barRef.current;
    if (!el) return;
    const apply = () => {
      document.documentElement.style.setProperty('--input-bar-h', `${el.offsetHeight}px`);
    };
    apply();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

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
    if (imageSlots.current >= LIMITS.maxImages) {
      toast(t('input.imageTooMany'), 'error');
      return;
    }
    imageSlots.current += 1;
    const data = await fileToBase64(file).catch(() => null);
    if (data === null || data.length > LIMITS.maxImageDataChars) {
      imageSlots.current -= 1;
      toast(t(data === null ? 'error.generic' : 'input.imageTooLarge'), 'error');
      return;
    }
    setImages((prev) => [
      ...prev,
      {
        id: ++imageSeq,
        payload: { source, mime_type: mime, data },
        preview: URL.createObjectURL(file),
      },
    ]);
  };

  const removeImage = (id: number) => {
    imageSlots.current = Math.max(0, imageSlots.current - 1);
    setImages((prev) => {
      const target = prev.find((img) => img.id === id);
      if (target) URL.revokeObjectURL(target.preview);
      return prev.filter((img) => img.id !== id);
    });
  };

  // 来源菜单：点菜单外或按 Esc 收起
  useEffect(() => {
    if (!mediaMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!anchorRef.current?.contains(e.target as Node)) setMediaMenuOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setMediaMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [mediaMenuOpen]);

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
    imageSlots.current = 0;
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
    <div className="input-bar" ref={barRef}>
      {images.length > 0 && (
        <div className="image-strip">
          {images.map((img) => (
            <div key={img.id} className="image-thumb">
              <img src={img.preview} alt="" width={60} height={60} />
              <button
                type="button"
                className="image-remove"
                aria-label={t('input.removeImage')}
                title={t('input.removeImage')}
                onClick={() => removeImage(img.id)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div className={`input-row${hasContent ? ' filled' : ''}`}>
        <div className="media-anchor" ref={anchorRef}>
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
            // 超出的部分整批丢弃并只提示一次，不要每张多余的图各弹一条
            const room = Math.max(0, LIMITS.maxImages - imageSlots.current);
            if (files.length > room) toast(t('input.imageTooMany'), 'error');
            for (const f of files.slice(0, room)) void addImage(f, 'upload', f.type || 'image/png');
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
