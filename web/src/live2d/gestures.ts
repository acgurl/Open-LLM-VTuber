import * as PIXI from 'pixi.js';
import { MotionPriority } from 'pixi-live2d-display-lipsyncpatch';
import { useSettings } from '../stores/settings';
import {
  MAX_ZOOM,
  MIN_ZOOM,
  type DrawableHost,
  type Framing,
  type Rect,
  type StageHost,
} from './framing';

const ZOOM_STEP = 1.05; // 每格滚轮 ±5%
const DRAG_THRESHOLD_PX = 5;
const TAP_MAX_MS = 350;
const TAP_GUARD_MS = 400;

type HitAreaDef = { id?: string; name?: string; index: number };
type HitAreaHost = { getHitAreaDefs?: () => HitAreaDef[] };

const hitPoint = new PIXI.Point();
const scratchBounds: Rect = { x: 0, y: 0, width: 0, height: 0 };

// 画布上的指针交互：命中测试、点击动作、拖拽、双指缩放与滚轮缩放。
export class Gestures {
  private canvas: HTMLCanvasElement | null = null;
  private pointers = new Map<number, { x: number; y: number }>();
  private pinch: { distance: number; zoom: number; mid: { x: number; y: number } } | null =
    null;
  private tapGuardUntil = 0;
  private dragArmed = false;
  private dragging = false;
  private hovering = false;
  private pointerDownAt = 0;
  private dragStart = { x: 0, y: 0 };
  private dragOrigin = { x: 0, y: 0 };

  constructor(
    private readonly host: StageHost,
    private readonly framing: Framing,
  ) {}

  attach(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    canvas.addEventListener('wheel', this.onWheel, { passive: false });
    canvas.addEventListener('pointerdown', this.onPointerDown);
    window.addEventListener('pointermove', this.onPointerMove);
    window.addEventListener('pointerup', this.onPointerUp);
    window.addEventListener('pointercancel', this.onPointerCancel);
  }

  private get pointerInteractive() {
    return this.host.info?.pointerInteractive ?? useSettings.getState().pointerInteractive;
  }

  private get scrollToResize() {
    return this.host.info?.scrollToResize ?? useSettings.getState().scrollToResize;
  }

  private hitKeysAt(x: number, y: number): string[] {
    const model = this.host.model;
    if (!model) return [];
    const point = model.toModelPosition(hitPoint.set(x, y), hitPoint);
    const internal = model.internalModel as unknown as HitAreaHost & DrawableHost;
    try {
      const defs = internal.getHitAreaDefs?.() ?? [];
      if (defs.length > 0) {
        const keys: string[] = [];
        for (const def of defs) {
          if (def.index < 0 || !this.pointInDrawable(def.index, point)) continue;
          if (def.id) keys.push(def.id);
          if (def.name && def.name !== def.id) keys.push(def.name);
        }
        return keys;
      }
    } catch {
      /* fall through to PIXI hit test */
    }
    try {
      return model.hitTest(x, y);
    } catch {
      return [];
    }
  }

  private pointInDrawable(index: number, point: { x: number; y: number }) {
    try {
      const internal = this.host.model?.internalModel as unknown as DrawableHost;
      const bounds = internal.getDrawableBounds(index, scratchBounds);
      return (
        point.x >= bounds.x &&
        point.x <= bounds.x + bounds.width &&
        point.y >= bounds.y &&
        point.y <= bounds.y + bounds.height
      );
    } catch {
      return false;
    }
  }

  // tapMotions 的值是权重不是索引：按命中区域取配置，没有命中则合并所有区域兜底。
  private handleTap(clientX: number, clientY: number, downAt: number) {
    if (Date.now() - downAt > TAP_MAX_MS) return;
    if (Date.now() < this.tapGuardUntil) return;
    if (!this.pointerInteractive) return;
    const tap = this.host.info?.tapMotions ?? {};
    if (Object.keys(tap).length === 0) return;

    const p = this.toStage(clientX, clientY);
    let motions: Record<string, number> = {};
    for (const key of new Set(this.hitKeysAt(p.x, p.y))) {
      const cfg = tap[key];
      if (!cfg) continue;
      motions = { ...cfg };
      break;
    }
    if (Object.keys(motions).length === 0) {
      for (const cfg of Object.values(tap)) {
        for (const [group, weight] of Object.entries(cfg)) {
          const value = Number(weight);
          if (!Number.isFinite(value)) continue;
          motions[group] = (motions[group] ?? 0) + value;
        }
      }
    }

    const entries = Object.entries(motions)
      .map(([group, weight]) => [group, Number(weight)] as [string, number])
      .filter(([, weight]) => Number.isFinite(weight) && weight > 0);
    const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
    if (total <= 0) return;

    let pick = Math.random() * total;
    let group = entries[entries.length - 1][0];
    for (const [name, weight] of entries) {
      pick -= weight;
      if (pick < 0) {
        group = name;
        break;
      }
    }
    void this.host.model?.motion(group, undefined, MotionPriority.FORCE).catch(() => undefined);
  }

  private toStage(clientX: number, clientY: number) {
    const rect = this.canvas?.getBoundingClientRect();
    return { x: clientX - (rect?.left ?? 0), y: clientY - (rect?.top ?? 0) };
  }

  private isOverModel(x: number, y: number) {
    const model = this.host.model;
    if (!model || !model.getBounds().contains(x, y)) return false;
    const drawableCount = this.framing.drawableCount;
    if (!drawableCount) return true;
    try {
      const point = model.toModelPosition(hitPoint.set(x, y), hitPoint);
      const internal = model.internalModel as unknown as DrawableHost;
      for (let i = 0; i < drawableCount; i++) {
        const b = internal.getDrawableBounds(i, scratchBounds);
        if (
          point.x >= b.x &&
          point.x <= b.x + b.width &&
          point.y >= b.y &&
          point.y <= b.y + b.height
        ) {
          return true;
        }
      }
      return false;
    } catch {
      return true;
    }
  }

  private setCursor(cursor: string) {
    if (this.canvas) this.canvas.style.cursor = cursor;
  }

  private onWheel = (e: WheelEvent) => {
    if (!this.scrollToResize) return;
    const p = this.toStage(e.clientX, e.clientY);
    if (!this.isOverModel(p.x, p.y)) return;
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP;
    const framing = this.framing;
    framing.zoomTarget = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, framing.zoomTarget * factor));
  };

  private onPointerDown = (e: PointerEvent) => {
    if (e.pointerType === 'touch') this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this.pointers.size >= 2) {
      this.beginPinch();
      return;
    }
    if (e.button !== 0) return;
    const p = this.toStage(e.clientX, e.clientY);
    if (!this.isOverModel(p.x, p.y)) return;
    this.dragArmed = true;
    this.pointerDownAt = Date.now();
    this.dragStart = { x: e.clientX, y: e.clientY };
    this.dragOrigin = { x: this.framing.offset.x, y: this.framing.offset.y };
  };

  private beginPinch() {
    const pts = [...this.pointers.values()];
    if (pts.length < 2) return;
    this.dragArmed = false;
    this.dragging = false;
    this.pinch = {
      distance: Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)),
      zoom: this.framing.zoom,
      mid: { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 },
    };
    this.setCursor('');
  }

  // 双指：以两指中点为焦点缩放，同时跟随中点平移
  private updatePinch() {
    const pinch = this.pinch;
    const pts = [...this.pointers.values()];
    if (!pinch || pts.length < 2) return;
    const rect = this.canvas?.getBoundingClientRect();
    const ox = rect?.left ?? 0;
    const oy = rect?.top ?? 0;
    const mid = {
      x: (pts[0].x + pts[1].x) / 2 - ox,
      y: (pts[0].y + pts[1].y) / 2 - oy,
    };
    const distance = Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y));
    const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, pinch.zoom * (distance / pinch.distance)));
    const framing = this.framing;
    framing.offset = {
      x: framing.offset.x + mid.x - pinch.mid.x,
      y: framing.offset.y + mid.y - pinch.mid.y,
    };
    pinch.mid = mid;
    framing.zoomTo(next, mid);
  }

  private onPointerMove = (e: PointerEvent) => {
    if (this.pointers.has(e.pointerId)) {
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }
    if (this.pinch && this.pointers.size >= 2) {
      this.updatePinch();
      return;
    }
    if (this.dragArmed || this.dragging) {
      const dx = e.clientX - this.dragStart.x;
      const dy = e.clientY - this.dragStart.y;
      if (!this.dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      if (!this.dragging) {
        this.dragging = true;
        this.dragArmed = false;
        this.setCursor('grabbing');
      }
      this.framing.offset = { x: this.dragOrigin.x + dx, y: this.dragOrigin.y + dy };
      this.framing.applyTransform();
      return;
    }
    if (e.pointerType === 'touch') return;
    const p = this.toStage(e.clientX, e.clientY);
    const over = this.isOverModel(p.x, p.y);
    if (over !== this.hovering) {
      this.hovering = over;
      this.setCursor(over ? 'grab' : '');
    }
  };

  private onPointerUp = (e: PointerEvent) => this.endPointer(e, true);

  private onPointerCancel = (e: PointerEvent) => this.endPointer(e, false);

  private endPointer(e: PointerEvent, allowTap: boolean) {
    const wasPinching = this.pinch !== null;
    if (this.pointers.delete(e.pointerId) && this.pinch) {
      this.pinch = null;
      this.tapGuardUntil = Date.now() + TAP_GUARD_MS;
      this.framing.zoomTarget = this.framing.zoom;
    }
    const wasArmed = this.dragArmed;
    const wasDragging = this.dragging;
    const downAt = this.pointerDownAt;
    const downX = this.dragStart.x;
    const downY = this.dragStart.y;
    this.dragArmed = false;
    if (this.dragging) {
      this.dragging = false;
      this.setCursor(this.hovering ? 'grab' : '');
    }
    if (allowTap && wasArmed && !wasDragging && !wasPinching && !this.pinch) {
      this.handleTap(downX, downY, downAt);
    }
  }
}
