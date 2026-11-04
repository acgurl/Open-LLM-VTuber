import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display-lipsyncpatch';
import type { Actions, ModelInfo } from '../protocol/types';
import { cacheModelAssets } from '../services/modelCache';
import { applyBreathScale, applyFocusScale, Framing, type StageHost } from './framing';
import { Gestures } from './gestures';
import { setVoiceLevel } from './stageFx';

(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

// 启动幕等待“舞台就位”：首次装载尝试结束（成功、失败或无模型）时派发一次。
export const STAGE_SETTLED_EVENT = 'vtuber:stage-settled';

type MotionManagerLike = {
  lipSyncIds?: string[];
  groups?: { idle?: string };
};
type UpdateHookHost = { on(event: string, fn: () => void): void };

// 封装 pixi 画布与 Live2D 模型：加载、口型、表情动作与待机；构图见 framing.ts，指针交互见 gestures.ts。
class Live2DController {
  private app: PIXI.Application | null = null;
  private model: Live2DModel | null = null;
  private info: ModelInfo | null = null;
  private pendingInfo: ModelInfo | null = null;
  private lipValue = 0;
  private lipSyncIds: string[] = ['ParamMouthOpenY'];
  private mouthKind: 'cubism4' | 'cubism2' | null = null;
  private readonly host: StageHost = this.createHost();
  private readonly framing = new Framing(this.host);
  private readonly gestures = new Gestures(this.host, this.framing);
  // pixi 的 resizeTo 把画布尺寸推迟到下一帧才更新；先同步 resize，否则构图会拿到旧的 screen 尺寸
  private resizeHandler = () => {
    this.app?.resize();
    this.framing.layout();
  };
  private loadSeq = 0;
  private loadingUrl: string | null = null;
  private stageSettled = false;

  // 构图/手势模块通过它读取控制器的当前 app/model/info，而不是各自保存一份
  private createHost(): StageHost {
    const self = this;
    return {
      get app() {
        return self.app;
      },
      get model() {
        return self.model;
      },
      get info() {
        return self.info;
      },
    };
  }

  mount(canvas: HTMLCanvasElement) {
    if (this.app) return;
    this.app = new PIXI.Application({
      view: canvas,
      resizeTo: window,
      backgroundAlpha: 0,
      autoDensity: true,
      // 4K 屏按 DPR 2 出图已足够；再高只是放大离屏画布和逐像素扫描成本。
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    });
    this.app.ticker.add(() => this.framing.stepZoom());
    window.addEventListener('resize', this.resizeHandler);
    this.gestures.attach(canvas);
    if (this.pendingInfo !== null) {
      const info = this.pendingInfo;
      this.pendingInfo = null;
      void this.load(info);
    }
  }

  get isStageSettled() {
    return this.stageSettled;
  }

  private settleStage() {
    if (this.stageSettled) return;
    this.stageSettled = true;
    window.dispatchEvent(new Event(STAGE_SETTLED_EVENT));
  }

  async load(info: ModelInfo | null) {
    const url = info?.url ?? null;
    const previousUrl = this.info?.url ?? null;
    if (url !== previousUrl) this.framing.resetView();
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
      if (this.model) this.framing.layout();
      return;
    }
    const seq = ++this.loadSeq;
    if (this.model) {
      this.app.stage.removeChild(this.model);
      this.model.destroy();
      this.model = null;
      this.mouthKind = null;
      this.lipSyncIds = ['ParamMouthOpenY'];
      this.framing.clearModel();
    }
    this.loadingUrl = url;
    if (url === null) {
      this.loadingUrl = null;
      this.settleStage();
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
      applyFocusScale(internal, info?.focusScale);
      applyBreathScale(internal, info?.breathScale);
      this.framing.measureContent();
      this.framing.layout();
      void cacheModelAssets(url);
      this.settleStage();
    } catch (err) {
      if (seq === this.loadSeq) {
        console.error('Live2D load failed', err);
        this.settleStage();
      }
    } finally {
      if (seq === this.loadSeq) this.loadingUrl = null;
    }
  }

  setLipSync(v: number) {
    this.lipValue = Math.max(0, Math.min(1, v));
    setVoiceLevel(this.lipValue);
  }

  setSpeaking(speaking: boolean) {
    if (!speaking) {
      this.lipValue = 0;
      setVoiceLevel(0);
    }
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

  setReservedLeft(px: number) {
    this.framing.setReservedLeft(px);
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
}

export const live2d = new Live2DController();
