import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useCamera } from '../stores/camera';
import { camera } from '../services/camera';
import { readSetting, writeSetting } from '../utils/storage';

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
    const raw = readSetting('camPos');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Pos> | null;
    if (typeof parsed?.left !== 'number' || typeof parsed?.top !== 'number') return null;
    return clampTo({ left: parsed.left, top: parsed.top });
  } catch {
    return null;
  }
}

function savePos(pos: Pos) {
  writeSetting('camPos', JSON.stringify(pos));
}

export function CameraWindow() {
  const { t } = useTranslation();
  const stream = useCamera((s) => s.stream);
  const starting = useCamera((s) => s.starting);
  const error = useCamera((s) => s.error);
  const videoRef = useRef<HTMLVideoElement>(null);
  const winRef = useRef<HTMLDivElement>(null);
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
    const el = winRef.current;
    if (!el) return;
    // 空闲胶囊和实况窗口尺寸不同：切换和缩放时都按当前尺寸重新夹取，别把框体探出视口。
    // 用布局尺寸和 computed left/top：getBoundingClientRect 会带上入场动画的 scale。
    const fit = () => {
      const cs = window.getComputedStyle(el);
      const left = Number.parseFloat(cs.left);
      const top = Number.parseFloat(cs.top);
      if (!Number.isFinite(left) || !Number.isFinite(top)) return;
      const next = clampTo({ left, top }, el.offsetWidth, el.offsetHeight);
      if (next.left === left && next.top === top) return;
      posRef.current = next;
      setPos(next);
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [stream]);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    drag.current = { x: e.clientX, y: e.clientY, left: rect.left, top: rect.top, moved: false };
    movedRef.current = false;
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
      try {
        // 越过阈值才捕获指针：在 pointerdown 就捕获会把后续 click 重定向到窗口，按钮点不动
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        /* 合成事件没有真实指针，忽略 */
      }
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
      ref={winRef}
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
        <button
          className={`cam-idle${error ? ' error' : ''}`}
          disabled={starting}
          onClick={() => void camera.start()}
        >
          <span className="cam-idle-icon">
            {starting ? <span className="spinner" /> : <CamIcon />}
          </span>
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
