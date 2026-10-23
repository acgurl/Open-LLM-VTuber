import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useCamera } from '../stores/camera';
import { camera } from '../services/camera';

export function CameraWindow() {
  const { t } = useTranslation();
  const stream = useCamera((s) => s.stream);
  const starting = useCamera((s) => s.starting);
  const error = useCamera((s) => s.error);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    el.srcObject = stream;
    if (stream) void el.play().catch(() => {});
  }, [stream]);

  if (!stream) {
    return (
      <div className="cam-window idle">
        <button className="cam-idle" disabled={starting} onClick={() => void camera.start()}>
          {starting ? <span className="spinner" /> : <CamIcon />}
          <span className="cam-idle-text">{error ? t(error) : t('camera.start')}</span>
        </button>
      </div>
    );
  }

  return (
    <div className="cam-window live">
      <video ref={videoRef} className="cam-video" autoPlay playsInline muted />
      <span className="cam-live">
        <i />
        {t('camera.live')}
      </span>
      <button
        className="cam-stop"
        title={t('camera.stop')}
        aria-label={t('camera.stop')}
        onClick={() => camera.stop()}
      >
        ×
      </button>
    </div>
  );
}

function CamIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M23 7l-7 5 7 5V7z" />
      <rect x="1" y="5" width="15" height="14" rx="2" />
    </svg>
  );
}
