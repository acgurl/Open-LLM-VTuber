import type * as PIXI from 'pixi.js';
import type { Live2DModel } from 'pixi-live2d-display-lipsyncpatch';
import type { ModelInfo } from '../protocol/types';
import { readSetting, writeSetting } from '../utils/storage';
import { setStageCenter } from './stageFx';

export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 5;
const ZOOM_EASING = 0.3;
// 默认构图：头部与上半身取景。轮廓高度取视口的 1.39 倍，头顶固定在 12% 处，
// 下半身溢出视口自然裁掉；窄屏时退回宽度上限，保证不会左右切到模型。
// 半身像等轮廓较矮的模型可在 model_dict 里用 frameHeightRatio / frameTopRatio 覆盖。
const FRAME_HEIGHT_RATIO = 1.39;
const FRAME_TOP_RATIO = 0.12;
const FRAME_WIDTH_RATIO = 0.92;
const ALPHA_THRESHOLD = 24;

export type Rect = { x: number; y: number; width: number; height: number };
export type DrawableHost = {
  getDrawableIDs(): string[];
  getDrawableBounds(index: number, bounds?: Rect): Rect;
};

// 控制器向构图与手势模块暴露的只读视图：每次访问都读控制器的当前值。
export interface StageHost {
  readonly app: PIXI.Application | null;
  readonly model: Live2DModel | null;
  readonly info: ModelInfo | null;
}

const scratchBounds: Rect = { x: 0, y: 0, width: 0, height: 0 };

// 鼠标跟踪会在动作之上再叠加头部 ±30° / 身体 ±10°；按模型的 focusScale 缩小头身转动，
// 眼球仍按原幅度跟随。只对 Cubism 4 生效，缺省或 >= 1 时不改动。
export function applyFocusScale(internal: Record<string, any>, scale: number | undefined) {
  if (typeof scale !== 'number' || !(scale >= 0 && scale < 1)) return;
  if (typeof internal?.updateFocus !== 'function' || !internal.focusController) return;
  const original = internal.updateFocus.bind(internal) as () => void;
  internal.updateFocus = () => {
    const fc = internal.focusController as { x: number; y: number };
    const { x, y } = fc;
    fc.x = x * scale;
    fc.y = y * scale;
    original();
    fc.x = x;
    fc.y = y;
    const core = internal.coreModel;
    core.addParameterValueById(internal.idParamEyeBallX, x - x * scale);
    core.addParameterValueById(internal.idParamEyeBallY, y - y * scale);
  };
}

// 运行时自带的“呼吸”会给头身角度叠加持续的正弦摆动；自带待机摆动的模型可用 breathScale 缩小它
// （只缩角度，不动 ParamBreath 本身）。
export function applyBreathScale(internal: Record<string, any>, scale: number | undefined) {
  if (typeof scale !== 'number' || !(scale >= 0 && scale < 1)) return;
  const params = internal?.breath?.getParameters?.() as
    | { parameterId: unknown; peak: number }[]
    | undefined;
  if (!Array.isArray(params)) return;
  for (const p of params) {
    if (p.parameterId !== internal.idParamBreath) p.peak *= scale;
  }
}

// 取景状态：像素轮廓测量、构图、缩放与平移偏移、聊天列让位。
export class Framing {
  // 左侧聊天列占掉的宽度：人物在剩余空间里取景，避免站在文字后面
  private reservedLeft = 0;
  private baseScale = 1;
  frameCenter = { x: 0, y: 0 };
  private contentCenter = { x: 0, y: 0 };
  private contentBounds: Rect | null = null;
  zoom = 1;
  zoomTarget = 1;
  offset = { x: 0, y: 0 };
  drawableCount = 0;

  constructor(private readonly host: StageHost) {}

  // 换模型时回到默认缩放与位置
  resetView() {
    this.zoom = 1;
    this.zoomTarget = 1;
    this.offset = { x: 0, y: 0 };
  }

  // 卸载旧模型时清掉它的测量结果
  clearModel() {
    this.drawableCount = 0;
    this.contentBounds = null;
  }

  // 取渲染出来的实际像素轮廓来构图：几何轮廓会把不可见网格算进去，主体会偏小。
  measureContent() {
    const app = this.host.app;
    const model = this.host.model;
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
    const url = this.host.info?.url;
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
    const app = this.host.app;
    const model = this.host.model;
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
    const model = this.host.model;
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

  layout() {
    const app = this.host.app;
    const model = this.host.model;
    if (!app || !model) return;
    const w = app.screen.width;
    const h = app.screen.height;
    const internal = model.internalModel as unknown as { width: number; height: number };
    const canvasW = internal.width || model.width || 1;
    const canvasH = internal.height || model.height || 1;
    const content = this.contentBounds ?? { x: 0, y: 0, width: canvasW, height: canvasH };
    const heightRatio = this.host.info?.frameHeightRatio ?? FRAME_HEIGHT_RATIO;
    const topRatio = this.host.info?.frameTopRatio ?? FRAME_TOP_RATIO;
    this.baseScale = Math.min(
      (h * heightRatio) / content.height,
      (w * FRAME_WIDTH_RATIO) / content.width,
    );
    this.contentCenter = {
      x: content.x + content.width / 2,
      y: content.y + content.height / 2,
    };
    this.frameCenter = {
      x: this.frameCenterX(w, content.width * this.baseScale),
      y: h * topRatio + (content.height * this.baseScale) / 2,
    };
    this.applyTransform();
  }

  // 只在聊天列真的挡到人物时右移，而且最多移到剩余空间的正中；宽屏仍然居中
  private frameCenterX(w: number, contentW: number) {
    const center = w / 2;
    const reserved = this.reservedLeft;
    if (reserved <= 0) return center;
    const clear = reserved + contentW * 0.4;
    const roomCenter = reserved + (w - reserved) / 2;
    return Math.max(center, Math.min(clear, roomCenter));
  }

  setReservedLeft(px: number) {
    const next = Math.max(0, Math.round(px));
    if (next === this.reservedLeft) return;
    this.reservedLeft = next;
    this.layout();
  }

  applyTransform() {
    const model = this.host.model;
    if (!model) return;
    const scale = this.baseScale * this.zoom;
    model.anchor.set(0, 0);
    model.scale.set(scale);
    model.x = this.frameCenter.x + this.offset.x - this.contentCenter.x * scale;
    model.y = this.frameCenter.y + this.offset.y - this.contentCenter.y * scale;
    setStageCenter(this.frameCenter.x + this.offset.x);
  }

  stepZoom() {
    if (this.zoom === this.zoomTarget) return;
    const next = this.zoom + (this.zoomTarget - this.zoom) * ZOOM_EASING;
    this.zoom = Math.abs(this.zoomTarget - next) < 0.0005 ? this.zoomTarget : next;
    this.applyTransform();
  }

  // 保持 focal 处的画面不动来缩放
  zoomTo(next: number, focal: { x: number; y: number }) {
    if (!this.host.model || next === this.zoom) return;
    const ratio = next / this.zoom;
    this.offset = {
      x: focal.x - this.frameCenter.x - (focal.x - this.frameCenter.x - this.offset.x) * ratio,
      y: focal.y - this.frameCenter.y - (focal.y - this.frameCenter.y - this.offset.y) * ratio,
    };
    this.zoom = next;
    this.zoomTarget = next;
    this.applyTransform();
  }
}
