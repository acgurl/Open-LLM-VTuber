import * as PIXI from 'pixi.js';
import { Live2DModel, MotionPriority } from 'pixi-live2d-display-lipsyncpatch';
import type { Actions, ModelInfo } from '../protocol/types';
import { cacheModelAssets } from '../services/modelCache';
import { useSettings } from '../stores/settings';
import { readSetting, writeSetting } from '../utils/storage';

(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 5;
const ZOOM_STEP = 1.05; // 每格滚轮 ±5%
const ZOOM_EASING = 0.3;
const DRAG_THRESHOLD_PX = 5;
const TAP_MAX_MS = 350;
// 默认构图：模型可见轮廓高度占视口 81%，顶部留白 10%，窄屏时宽度不超过 92%
const FRAME_HEIGHT_RATIO = 0.81;
const FRAME_TOP_RATIO = 0.1;
const FRAME_WIDTH_RATIO = 0.92;
const ALPHA_THRESHOLD = 24;
const TAP_GUARD_MS = 400;

type Rect = { x: number; y: number; width: number; height: number };
type DrawableHost = {
  getDrawableIDs(): string[];
  getDrawableBounds(index: number, bounds?: Rect): Rect;
};
type HitAreaDef = { id?: string; name?: string; index: number };
type HitAreaHost = { getHitAreaDefs?: () => HitAreaDef[] };
type MotionManagerLike = {
  lipSyncIds?: string[];
  groups?: { idle?: string };
};
type UpdateHookHost = { on(event: string, fn: () => void): void };

const hitPoint = new PIXI.Point();
const scratchBounds: Rect = { x: 0, y: 0, width: 0, height: 0 };

// 封装 pixi 画布与 Live2D 模型：加载、定位、口型、表情动作、待机与点击。
class Live2DController {
  private app: PIXI.Application | null = null;
  private model: Live2DModel | null = null;
  private info: ModelInfo | null = null;
  private pendingInfo: ModelInfo | null = null;
  private lipValue = 0;
  private lipSyncIds: string[] = ['ParamMouthOpenY'];
  private mouthKind: 'cubism4' | 'cubism2' | null = null;
  private resizeHandler = () => this.layout();
  private canvas: HTMLCanvasElement | null = null;
  private baseScale = 1;
  private frameCenter = { x: 0, y: 0 };
  private contentCenter = { x: 0, y: 0 };
  private contentBounds: Rect | null = null;
  private zoom = 1;
  private zoomTarget = 1;
  private offset = { x: 0, y: 0 };
  private drawableCount = 0;
  private pointers = new Map<number, { x: number; y: number }>();
  private pinch: { distance: number; zoom: number; mid: { x: number; y: number } } | null =
    null;
  private tapGuardUntil = 0;
  private loadSeq = 0;
  private loadingUrl: string | null = null;
  private dragArmed = false;
  private dragging = false;
  private hovering = false;
  private pointerDownAt = 0;
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
      // 4K 屏按 DPR 2 出图已足够；再高只是放大离屏画布和逐像素扫描成本。
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    });
    this.app.ticker.add(() => this.stepZoom());
    window.addEventListener('resize', this.resizeHandler);
    canvas.addEventListener('wheel', this.onWheel, { passive: false });
    canvas.addEventListener('pointerdown', this.onPointerDown);
    window.addEventListener('pointermove', this.onPointerMove);
    window.addEventListener('pointerup', this.onPointerUp);
    window.addEventListener('pointercancel', this.onPointerCancel);
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
    if (this.model) {
      this.app.stage.removeChild(this.model);
      this.model.destroy();
      this.model = null;
      this.mouthKind = null;
      this.lipSyncIds = ['ParamMouthOpenY'];
      this.drawableCount = 0;
      this.contentBounds = null;
    }
    this.loadingUrl = url;
    if (url === null) {
      this.loadingUrl = null;
      return;
    }
    try {
      const model = (await Live2DModel.from(url, {
        autoHitTest: false,
        autoFocus: true,
      })) as Live2DModel;
      if (seq !== this.loadSeq) {
        model.destroy();
        return;
      }
      this.model = model;
      this.app.stage.addChild(model);
      // 必须挂在模型 update 的最后一刻写口型，否则会被动作/参数回滚覆盖。
      (model.internalModel as unknown as UpdateHookHost).on(
        'beforeModelUpdate',
        this.applyLipSync,
      );
      const internal = model.internalModel as unknown as Record<string, any>;
      if (internal?.coreModel?.setParameterValueById) this.mouthKind = 'cubism4';
      else if (internal?.live2DModel) this.mouthKind = 'cubism2';
      const manager = internal?.motionManager as MotionManagerLike | undefined;
      if (Array.isArray(manager?.lipSyncIds) && manager.lipSyncIds.length > 0) {
        this.lipSyncIds = [...manager.lipSyncIds];
      } else {
        this.lipSyncIds =
          this.mouthKind === 'cubism4' ? ['ParamMouthOpenY'] : ['PARAM_MOUTH_OPEN_Y'];
      }
      const idleGroup = info?.idleMotionGroupName;
      if (manager?.groups && idleGroup) {
        try {
          manager.groups.idle = idleGroup;
        } catch {
          /* ignore */
        }
      }
      this.measureContent();
      this.layout();
      void cacheModelAssets(url);
    } catch (err) {
      if (seq === this.loadSeq) console.error('Live2D load failed', err);
    } finally {
      if (seq === this.loadSeq) this.loadingUrl = null;
    }
  }

  private get pointerInteractive() {
    return this.info?.pointerInteractive ?? useSettings.getState().pointerInteractive;
  }

  private get scrollToResize() {
    return this.info?.scrollToResize ?? useSettings.getState().scrollToResize;
  }

  setLipSync(v: number) {
    this.lipValue = Math.max(0, Math.min(1, v));
  }

  setSpeaking(speaking: boolean) {
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
        void this.model.motion(m.group, m.index).catch(() => undefined);
      } catch {
        /* 模型没有该动作 */
      }
    }
  }

  // 回到模型默认表情：优先 model_dict 的 defaultEmotion，否则用第 0 个表情。
  resetExpression() {
    const model = this.model;
    if (!model) return;
    try {
      const manager = (model.internalModel as unknown as {
        motionManager?: { expressionManager?: { definitions?: unknown[] } };
      }).motionManager;
      const count = manager?.expressionManager?.definitions?.length ?? 0;
      if (count === 0) return;
      const target = this.info?.defaultEmotion ?? 0;
      void model.expression(target);
    } catch {
      /* ignore */
    }
  }

  private hitKeysAt(x: number, y: number): string[] {
    const model = this.model;
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
      const bounds = (this.model?.internalModel as unknown as DrawableHost).getDrawableBounds(
        index,
        scratchBounds,
      );
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
    const tap = this.info?.tapMotions ?? {};
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
    void this.model?.motion(group, undefined, MotionPriority.FORCE).catch(() => undefined);
  }

  // 取渲染出来的实际像素轮廓来构图：几何轮廓会把不可见网格算进去，主体会偏小。
  private measureContent() {
    const app = this.app;
    const model = this.model;
    if (!app || !model) return;
    const internal = model.internalModel as unknown as { width: number; height: number };
    const canvasW = internal.width || model.width || 1;
    const canvasH = internal.height || model.height || 1;
    const w = app.screen.width;
    const h = app.screen.height;
    try {
      this.drawableCount = (model.internalModel as unknown as DrawableHost).getDrawableIDs()
        .length;
    } catch {
      this.drawableCount = 0;
    }

    // 轮廓只取决于模型本身，算一次即可；否则每次刷新都要回读整张画布。
    const cached = this.readCachedBounds();
    if (cached) {
      this.contentBounds = cached;
      return;
    }

    // 先整幅缩放塞进视口，保证轮廓不被裁掉
    const probeScale = Math.min((w * 0.9) / canvasW, (h * 0.9) / canvasH);
    model.anchor.set(0, 0);
    model.scale.set(probeScale);
    model.x = (w - canvasW * probeScale) / 2;
    model.y = (h - canvasH * probeScale) / 2;

    const pixelBounds = this.scanVisiblePixels(probeScale);
    this.contentBounds = pixelBounds ?? this.geometryBounds(canvasW, canvasH);
    if (pixelBounds) this.writeCachedBounds(pixelBounds);
  }

  private boundsKey(): string | null {
    const url = this.info?.url;
    return url ? `bounds.v1.${url}` : null;
  }

  private readCachedBounds(): Rect | null {
    const key = this.boundsKey();
    if (!key) return null;
    try {
      const raw = readSetting(key);
      if (!raw) return null;
      const b = JSON.parse(raw) as Rect;
      const values = [b.x, b.y, b.width, b.height];
      if (!values.every((v) => Number.isFinite(v)) || b.width <= 0 || b.height <= 0) return null;
      return b;
    } catch {
      return null;
    }
  }

  private writeCachedBounds(bounds: Rect) {
    const key = this.boundsKey();
    if (!key) return;
    writeSetting(key, JSON.stringify(bounds));
  }

  private scanVisiblePixels(scale: number): Rect | null {
    const app = this.app;
    const model = this.model;
    if (!app || !model) return null;
    const width = app.renderer.width;
    const height = app.renderer.height;
    const resolution = app.renderer.resolution || 1;
    try {
      app.renderer.render(app.stage);
      if (!app.renderer.extract) return null;
      const pixels = app.renderer.extract.pixels();
      if (pixels.length !== width * height * 4) return null;
      let minX = width;
      let minY = height;
      let maxX = -1;
      let maxY = -1;
      for (let y = 0; y < height; y++) {
        const row = y * width * 4;
        for (let x = 0; x < width; x++) {
          if (pixels[row + x * 4 + 3] <= ALPHA_THRESHOLD) continue;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
      if (maxX < minX || maxY < minY) return null;
      return {
        x: (minX / resolution - model.x) / scale,
        y: (minY / resolution - model.y) / scale,
        width: (maxX - minX + 1) / resolution / scale,
        height: (maxY - minY + 1) / resolution / scale,
      };
    } catch {
      return null;
    }
  }

  private geometryBounds(canvasW: number, canvasH: number): Rect {
    const model = this.model;
    const fallback = { x: 0, y: 0, width: canvasW, height: canvasH };
    if (!model) return fallback;
    const internal = model.internalModel as unknown as DrawableHost;
    let count = 0;
    try {
      count = internal.getDrawableIDs().length;
    } catch {
      count = 0;
    }
    if (!count) return fallback;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    try {
      for (let i = 0; i < count; i++) {
        const b = internal.getDrawableBounds(i, scratchBounds);
        if (!(b.width > 0) || !(b.height > 0)) continue;
        minX = Math.min(minX, b.x);
        minY = Math.min(minY, b.y);
        maxX = Math.max(maxX, b.x + b.width);
        maxY = Math.max(maxY, b.y + b.height);
      }
    } catch {
      return fallback;
    }
    if (minX === Infinity || maxX <= minX || maxY <= minY) return fallback;
    return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
  }

  private layout() {
    const app = this.app;
    const model = this.model;
    if (!app || !model) return;
    const w = app.screen.width;
    const h = app.screen.height;
    const internal = model.internalModel as unknown as { width: number; height: number };
    const canvasW = internal.width || model.width || 1;
    const canvasH = internal.height || model.height || 1;
    const content = this.contentBounds ?? { x: 0, y: 0, width: canvasW, height: canvasH };
    this.baseScale = Math.min(
      (h * FRAME_HEIGHT_RATIO) / content.height,
      (w * FRAME_WIDTH_RATIO) / content.width,
    );
    this.contentCenter = {
      x: content.x + content.width / 2,
      y: content.y + content.height / 2,
    };
    this.frameCenter = {
      x: w / 2,
      y: h * FRAME_TOP_RATIO + (content.height * this.baseScale) / 2,
    };
    this.applyTransform();
  }

  private applyTransform() {
    const model = this.model;
    if (!model) return;
    const scale = this.baseScale * this.zoom;
    model.anchor.set(0, 0);
    model.scale.set(scale);
    model.x = this.frameCenter.x + this.offset.x - this.contentCenter.x * scale;
    model.y = this.frameCenter.y + this.offset.y - this.contentCenter.y * scale;
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
    if (!this.scrollToResize) return;
    const p = this.toStage(e.clientX, e.clientY);
    if (!this.isOverModel(p.x, p.y)) return;
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP;
    this.zoomTarget = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.zoomTarget * factor));
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
    this.dragOrigin = { x: this.offset.x, y: this.offset.y };
  };

  private beginPinch() {
    const pts = [...this.pointers.values()];
    if (pts.length < 2) return;
    this.dragArmed = false;
    this.dragging = false;
    this.pinch = {
      distance: Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y)),
      zoom: this.zoom,
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
    this.offset = {
      x: this.offset.x + mid.x - pinch.mid.x,
      y: this.offset.y + mid.y - pinch.mid.y,
    };
    pinch.mid = mid;
    this.zoomTo(next, mid);
  }

  // 保持 focal 处的画面不动来缩放
  private zoomTo(next: number, focal: { x: number; y: number }) {
    if (!this.model || next === this.zoom) return;
    const ratio = next / this.zoom;
    this.offset = {
      x: focal.x - this.frameCenter.x - (focal.x - this.frameCenter.x - this.offset.x) * ratio,
      y: focal.y - this.frameCenter.y - (focal.y - this.frameCenter.y - this.offset.y) * ratio,
    };
    this.zoom = next;
    this.zoomTarget = next;
    this.applyTransform();
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
      this.offset = { x: this.dragOrigin.x + dx, y: this.dragOrigin.y + dy };
      this.applyTransform();
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
      this.zoomTarget = this.zoom;
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

  private applyLipSync = () => {
    if (!this.model || !this.mouthKind) return;
    const v = this.lipValue;
    try {
      const internal = this.model.internalModel as unknown as Record<string, any>;
      for (const id of this.lipSyncIds) {
        if (this.mouthKind === 'cubism4') {
          internal.coreModel.setParameterValueById(id, v);
        } else {
          internal.live2DModel.setParamFloat?.(id, v);
        }
      }
    } catch {
      /* 模型结构异常时忽略 */
    }
  };

  destroy() {
    window.removeEventListener('resize', this.resizeHandler);
    window.removeEventListener('pointermove', this.onPointerMove);
    window.removeEventListener('pointerup', this.onPointerUp);
    window.removeEventListener('pointercancel', this.onPointerCancel);
    this.canvas?.removeEventListener('wheel', this.onWheel);
    this.canvas?.removeEventListener('pointerdown', this.onPointerDown);
    this.canvas = null;
    this.dragArmed = false;
    this.dragging = false;
    this.pointers.clear();
    this.pinch = null;
    this.app?.destroy(true);
    this.app = null;
    this.model = null;
  }
}

export const live2d = new Live2DController();
