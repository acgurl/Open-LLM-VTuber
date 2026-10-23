import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useCamera } from '../stores/camera';
import { camera } from '../services/camera';

const POS_KEY = 'ollmvt.camPos';
const EDGE = 8;
const DRAG_THRESHOLD = 4;

interface Pos {
  left: number;
  top: number;
}

function clampTo(pos: Pos, width = 0, height = 0): Pos {
  return {
    left: Math.min(Math.max(EDGE, pos.left), Math.max(EDGE, window.innerWidth - width - EDGE)),
    top: Math.min(Math.max(EDGE, pos.top), Math.max(EDGE, window.innerHeight - height - EDGE)),
  };
}

function loadPos(): Pos | null {
  try {
    const raw = localStorage.getItem(POS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Pos> | null;
    if (typeof parsed?.left !== 'number' || typeof parsed?.top !== 'number') return null;
    return clampTo({ left: parsed.left, top: parsed.top });
  } catch {
    return null;
  }
}

function savePos(pos: Pos) {
  try {
    localStorage.setItem(POS_KEY, JSON.stringify(pos));
  } catch {
    /* ignore */
  }
}

export function CameraWindow() {
  const { t } = useTranslation();
  const stream = useCamera((s) => s.stream);
  const starting = useCamera((s) => s.starting);
  const error = useCamera((s) => s.error);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [pos, setPos] = useState<Pos | null>(loadPos);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(
    null,
  );
  const posRef = useRef<Pos | null>(pos);
  const movedRef = useRef(false);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    el.srcObject = stream;
    if (stream) void el.play().catch(() => {});
  }, [stream]);

  useEffect(() => {
    const onResize = () => setPos((p) => (p ? clampTo(p) : p));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    drag.current = { x: e.clientX, y: e.clientY, left: rect.left, top: rect.top, moved: false };
    movedRef.current = false;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* 合成事件没有真实指针，忽略 */
    }
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      d.moved = true;
      movedRef.current = true;
      setDragging(true);
    }
    const next = clampTo(
      { left: d.left + dx, top: d.top + dy },
      e.currentTarget.offsetWidth,
      e.currentTarget.offsetHeight,
    );
    posRef.current = next;
    setPos(next);
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const moved = drag.current?.moved;
    drag.current = null;
    setDragging(false);
    if (moved && posRef.current) savePos(posRef.current);
    try {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    } catch {
      /* ignore */
    }
  };

  return (
    <div
      className={`cam-window ${stream ? 'live' : 'idle'}${dragging ? ' dragging' : ''}`}
      style={pos ? { left: pos.left, top: pos.top, right: 'auto' } : undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onClickCapture={(e) => {
        // 拖完松手会补一个 click，别让它顺手把摄像头开了/关了
        if (!movedRef.current) return;
        movedRef.current = false;
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {!stream ? (
        <button className="cam-idle" disabled={starting} onClick={() => void camera.start()}>
          {starting ? <span className="spinner" /> : <CamIcon />}
          <span className="cam-idle-text">{error ? t(error) : t('camera.start')}</span>
        </button>
      ) : (
        <>
          <video ref={videoRef} className="cam-video" autoPlay playsInline muted draggable={false} />
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
        </>
      )}
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
