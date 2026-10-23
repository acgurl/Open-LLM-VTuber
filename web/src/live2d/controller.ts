import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display-lipsyncpatch';
import type { Actions, ModelInfo } from '../protocol/types';

(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 5;
const ZOOM_STEP = 1.05; // 每格滚轮 ±5%
const ZOOM_EASING = 0.3;
const DRAG_THRESHOLD_PX = 5;

type Rect = { x: number; y: number; width: number; height: number };
type DrawableHost = {
  getDrawableIDs(): string[];
  getDrawableBounds(index: number, bounds?: Rect): Rect;
};

const hitPoint = new PIXI.Point();
const scratchBounds: Rect = { x: 0, y: 0, width: 0, height: 0 };

// 封装 pixi 画布与 Live2D 模型：加载、定位、口型、表情动作、待机与点击。
class Live2DController {
  private app: PIXI.Application | null = null;
  private model: Live2DModel | null = null;
  private info: ModelInfo | null = null;
  private pendingInfo: ModelInfo | null = null;
  private lipValue = 0;
  private speaking = false;
  private mouthKind: 'cubism4' | 'cubism2' | null = null;
  private idleTimer: number | null = null;
  private resizeHandler = () => this.layout();
  private canvas: HTMLCanvasElement | null = null;
  private baseScale = 1;
  private baseX = 0;
  private baseY = 0;
  private zoom = 1;
  private zoomTarget = 1;
  private offset = { x: 0, y: 0 };
  private drawableCount = 0;
  private loadSeq = 0;
  private loadingUrl: string | null = null;
  private dragArmed = false;
  private dragging = false;
  private hovering = false;
  private dragStart = { x: 0, y: 0 };
  private dragOrigin = { x: 0, y: 0 };

  mount(canvas: HTMLCanvasElement) {
    if (this.app) return;
    this.canvas = canvas;
    this.app = new PIXI.Application({
      view: canvas,
      resizeTo: window,
      backgroundAlpha: 0,
      autoDensity: true,
      resolution: window.devicePixelRatio || 1,
    });
    this.app.ticker.add(() => this.applyLipSync());
    this.app.ticker.add(() => this.stepZoom());
    window.addEventListener('resize', this.resizeHandler);
    canvas.addEventListener('wheel', this.onWheel, { passive: false });
    canvas.addEventListener('pointerdown', this.onPointerDown);
    window.addEventListener('pointermove', this.onPointerMove);
    window.addEventListener('pointerup', this.onPointerUp);
    window.addEventListener('pointercancel', this.onPointerUp);
    if (this.pendingInfo !== null) {
      const info = this.pendingInfo;
      this.pendingInfo = null;
      void this.load(info);
    }
  }

  async load(info: ModelInfo | null) {
    const url = info?.url ?? null;
    const previousUrl = this.info?.url ?? null;
    if (url !== previousUrl) {
      this.zoom = 1;
      this.zoomTarget = 1;
      this.offset = { x: 0, y: 0 };
    }
    this.info = info;
    if (!this.app) {
      this.pendingInfo = info;
      return;
    }
    // 首屏先用本地缓存渲染；随后服务端配置到达时 URL 未变，只更新参数，
    // 不销毁重载，避免闪烁和重复下载。
    if (
      url !== null &&
      (url === this.loadingUrl || (url === previousUrl && this.model !== null))
    ) {
      if (this.model) this.layout();
      return;
    }
    const seq = ++this.loadSeq;
    this.stopIdle();
    if (this.model) {
      this.app.stage.removeChild(this.model);
      this.model.destroy();
      this.model = null;
      this.mouthKind = null;
      this.drawableCount = 0;
    }
    this.loadingUrl = url;
    if (url === null) {
      this.loadingUrl = null;
      return;
    }
    try {
      const model = (await Live2DModel.from(url, {
        autoInteract: true,
      })) as Live2DModel;
      if (seq !== this.loadSeq) {
        model.destroy();
        return;
      }
      this.model = model;
      this.app.stage.addChild(model);
      const internal = model.internalModel as unknown as Record<string, any>;
      if (internal?.coreModel?.setParameterValueById) this.mouthKind = 'cubism4';
      else if (internal?.live2DModel) this.mouthKind = 'cubism2';
      try {
        this.drawableCount = (internal as unknown as DrawableHost).getDrawableIDs().length;
      } catch {
        this.drawableCount = 0;
      }
      const bindInfo = this.info ?? info;
      if (bindInfo) this.bindTap(model, bindInfo);
      this.layout();
      this.startIdle();
    } catch (err) {
      if (seq === this.loadSeq) console.error('Live2D load failed', err);
    } finally {
      if (seq === this.loadSeq) this.loadingUrl = null;
    }
  }

  setLipSync(v: number) {
    this.lipValue = Math.max(0, Math.min(1, v));
  }

  setSpeaking(speaking: boolean) {
    this.speaking = speaking;
    if (!speaking) this.lipValue = 0;
  }

  applyActions(actions: Actions | null | undefined) {
    if (!actions || !this.model) return;
    for (const expr of actions.expressions ?? []) {
      try {
        void this.model.expression(expr);
      } catch {
        /* 模型没有该表情 */
      }
    }
    for (const m of actions.motions ?? []) {
      try {
        void this.model.motion(m.group, m.index);
      } catch {
        /* 模型没有该动作 */
      }
    }
  }

  private bindTap(model: Live2DModel, info: ModelInfo) {
    const tap = info.tapMotions ?? {};
    if (Object.keys(tap).length === 0) return;
    (model as unknown as { on(e: string, fn: (areas: string[]) => void): void }).on(
      'hit',
      (hitAreas: string[]) => {
        if (this.dragging || this.dragArmed) return;
        for (const area of hitAreas) {
          const motions = tap[area];
          if (!motions) continue;
          for (const [group, index] of Object.entries(motions)) {
            try {
              void this.model?.motion(group || (info.idleMotionGroupName ?? 'Idle'), index);
            } catch {
              /* ignore */
            }
          }
        }
      },
    );
  }

  private layout() {
    const app = this.app;
    const model = this.model;
    if (!app || !model) return;
    const w = app.screen.width;
    const h = app.screen.height;
    const info = this.info ?? {};
    const internal = model.internalModel as unknown as { width: number; height: number };
    const mw = internal.width || model.width || 1;
    const mh = internal.height || model.height || 1;
    const fit = Math.min((w * 0.9) / mw, (h * 0.95) / mh);
    this.baseScale = fit * (info.kScale ?? 1);
    this.baseX = w / 2 + (info.kXOffset ?? 0) + (info.initialXshift ?? 0);
    this.baseY = h + (info.initialYshift ?? 0);
    this.applyTransform();
  }

  private applyTransform() {
    const model = this.model;
    if (!model) return;
    model.anchor.set(0.5, 1);
    model.scale.set(this.baseScale * this.zoom);
    model.x = this.baseX + this.offset.x;
    model.y = this.baseY + this.offset.y;
  }

  private stepZoom() {
    if (this.zoom === this.zoomTarget) return;
    const next = this.zoom + (this.zoomTarget - this.zoom) * ZOOM_EASING;
    this.zoom = Math.abs(this.zoomTarget - next) < 0.0005 ? this.zoomTarget : next;
    this.applyTransform();
  }

  private toStage(clientX: number, clientY: number) {
    const rect = this.canvas?.getBoundingClientRect();
    return { x: clientX - (rect?.left ?? 0), y: clientY - (rect?.top ?? 0) };
  }

  private isOverModel(x: number, y: number) {
    const model = this.model;
    if (!model || !model.getBounds().contains(x, y)) return false;
    if (!this.drawableCount) return true;
    try {
      const point = model.toModelPosition(hitPoint.set(x, y), hitPoint);
      const internal = model.internalModel as unknown as DrawableHost;
      for (let i = 0; i < this.drawableCount; i++) {
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
    const p = this.toStage(e.clientX, e.clientY);
    if (!this.isOverModel(p.x, p.y)) return;
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP;
    this.zoomTarget = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.zoomTarget * factor));
  };

  private onPointerDown = (e: PointerEvent) => {
    if (e.button !== 0) return;
    const p = this.toStage(e.clientX, e.clientY);
    if (!this.isOverModel(p.x, p.y)) return;
    this.dragArmed = true;
    this.dragStart = { x: e.clientX, y: e.clientY };
    this.dragOrigin = { x: this.offset.x, y: this.offset.y };
  };

  private onPointerMove = (e: PointerEvent) => {
    if (this.dragArmed || this.dragging) {
      const dx = e.clientX - this.dragStart.x;
      const dy = e.clientY - this.dragStart.y;
      if (!this.dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      if (!this.dragging) {
        this.dragging = true;
        this.dragArmed = false;
        this.setCursor('grabbing');
      }
      this.offset = { x: this.dragOrigin.x + dx, y: this.dragOrigin.y + dy };
      this.applyTransform();
      return;
    }
    const p = this.toStage(e.clientX, e.clientY);
    const over = this.isOverModel(p.x, p.y);
    if (over !== this.hovering) {
      this.hovering = over;
      this.setCursor(over ? 'grab' : '');
    }
  };

  private onPointerUp = () => {
    this.dragArmed = false;
    if (this.dragging) {
      this.dragging = false;
      this.setCursor(this.hovering ? 'grab' : '');
    }
  };

  private applyLipSync() {
    if (!this.model || !this.mouthKind) return;
    const v = this.lipValue;
    try {
      const internal = this.model.internalModel as unknown as Record<string, any>;
      if (this.mouthKind === 'cubism4') {
        internal.coreModel.setParameterValueById('ParamMouthOpenY', v);
      } else {
        internal.live2DModel.setParamFloat?.('PARAM_MOUTH_OPEN_Y', v);
      }
    } catch {
      /* 模型结构异常时忽略 */
    }
  }

  private startIdle() {
    this.stopIdle();
    const group = this.info?.idleMotionGroupName;
    if (!group || !this.model) return;
    const tick = () => {
      if (!this.speaking && this.model) {
        try {
          void this.model.motion(group);
        } catch {
          /* ignore */
        }
      }
      this.idleTimer = window.setTimeout(tick, 9000 + Math.random() * 8000);
    };
    this.idleTimer = window.setTimeout(tick, 4000);
  }

  private stopIdle() {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  destroy() {
    window.removeEventListener('resize', this.resizeHandler);
    window.removeEventListener('pointermove', this.onPointerMove);
    window.removeEventListener('pointerup', this.onPointerUp);
    window.removeEventListener('pointercancel', this.onPointerUp);
    this.canvas?.removeEventListener('wheel', this.onWheel);
    this.canvas?.removeEventListener('pointerdown', this.onPointerDown);
    this.canvas = null;
    this.dragArmed = false;
    this.dragging = false;
    this.stopIdle();
    this.app?.destroy(true);
    this.app = null;
    this.model = null;
  }
}

export const live2d = new Live2DController();
