import { create } from 'zustand';
import { flushSync } from 'react-dom';
import { readSetting, writeSetting } from '../utils/storage';

export type ThemeMode = 'auto' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

// AIRI 同款：整个界面由单一色相派生，主色、补色、第三色随它一起转。
const DEFAULT_HUE = 220.44;

// 跟随系统时用系统的昼夜偏好作为自动切换源，系统切换后页面实时响应。
const systemLight = window.matchMedia('(prefers-color-scheme: light)');

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'auto') return systemLight.matches ? 'light' : 'dark';
  return mode;
}

function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement;
  const bg = theme === 'light' ? '#f7f8fb' : '#121212';
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  // index.html 的首屏脚本把画布底色写成了内联样式，这里必须同步，否则切到白天后底下仍是黑的
  root.style.background = bg;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg);
}

function normalizeHue(value: string | null): number {
  const hue = Number.parseFloat(value ?? '');
  if (!Number.isFinite(hue)) return DEFAULT_HUE;
  return ((hue % 360) + 360) % 360;
}

function applyHue(hue: number): void {
  document.documentElement.style.setProperty('--hue', hue.toFixed(2));
}

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

const SHIFT_MS = 720;
// 日出先快后缓，像光一下子漫出来。日落也必须一起步就动：收缩的圆起点半径够到最远的角，
// 边缘起初几乎都在屏外，若再先缓后快，前三百来毫秒画面纹丝不动，看着就是顿了一下。
// 所以日落起步利落、末段缓缓吸进按钮。
const DAWN_EASE = 'cubic-bezier(0.32, 0.72, 0.24, 1)';
const DUSK_EASE = 'cubic-bezier(0.3, 0.55, 0.25, 1)';

// 切换中途再点不能另开 View Transition：新的会跳过旧的，画面先跳到旧的终态再拍快照，必闪。
// 打断就地倒放：所有动画从当前进度原路退回；退到头时画面只剩旧快照，
// 这时再把 DOM 换回原主题，最后才放过渡结束。全程只有一个过渡，没有跳变。
interface Shift {
  from: ResolvedTheme;
  target: ResolvedTheme;
  reversed: boolean;
  animations: Animation[];
}

let shift: Shift | null = null;
let shiftSeq = 0;

function heading(s: Shift): ResolvedTheme {
  return s.reversed ? s.from : s.target;
}

function reverseShift(s: Shift): void {
  s.reversed = !s.reversed;
  s.animations.forEach((animation) => animation.reverse());
}

// 关着过渡改主题并强制算一次样式，让终态直接落地，不在实时快照里渐变
function applyInstantly(apply: () => void): void {
  const root = document.documentElement;
  root.classList.add('theme-switching');
  flushSync(apply);
  void root.offsetWidth;
  root.classList.remove('theme-switching');
}

// 明暗切换不做逐属性过渡：带 backdrop-filter 的玻璃层一帧帧重绘反而更卡。
// 交给 View Transitions 把新旧界面各拍一张快照，只动快照的裁切、缩放和亮度：
// 切到白天时亮面从按钮处漫开，切到黑夜时亮面收回按钮，边缘各带一圈光晕。
function commitTheme(
  from: ResolvedTheme,
  next: ResolvedTheme,
  apply: () => void,
  revert: () => void,
  origin?: Element | null,
): void {
  const start = document.startViewTransition?.bind(document);
  if (!start || reducedMotion.matches) {
    apply();
    return;
  }
  const rect = origin?.getBoundingClientRect();
  const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
  const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
  const r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const dawn = next === 'light';
  const root = document.documentElement;
  const seq = ++shiftSeq;
  const state: Shift = { from, target: next, reversed: false, animations: [] };
  shift = state;
  root.dataset.themeShift = dawn ? 'dawn' : 'dusk';

  // 光晕环放在新界面里：新快照是实时画面，环的动画会跟着画进去。
  // 日出时环在亮面的内缘，日落时环在收缩亮面的外缘、落在新的暗面上。
  const ring = document.createElement('div');
  ring.className = `theme-ring theme-ring--${dawn ? 'dawn' : 'dusk'}`;
  ring.setAttribute('aria-hidden', 'true');
  Object.assign(ring.style, {
    left: `${x - r}px`,
    top: `${y - r}px`,
    width: `${r * 2}px`,
    height: `${r * 2}px`,
  });

  // 新快照是实时画面：各元素自带的 color/background 过渡会在圆里从旧色渐变过去，
  // 白天铺开时先露出一圈黑再变亮，看着就是闪一下。切换期间关掉过渡，新快照直接是终态。
  const transition = start(() => {
    root.classList.add('theme-switching');
    flushSync(apply);
    document.body.appendChild(ring);
    // 关着过渡时强制算一次样式，让终态落成过渡的起点；否则摘掉类名后才首次计算，照样会渐变
    void root.offsetWidth;
  });

  // 守门动画挂在 ::view-transition 上：只要它在跑，过渡就不会结束。
  // 倒放退到头时要先换回原主题、等实时快照画好，再放行，否则会露出一帧新主题。
  let gate: Animation | undefined;
  const land = () => {
    if (shift !== state) return;
    shift = null;
    if (state.reversed) applyInstantly(revert);
    requestAnimationFrame(() => requestAnimationFrame(() => gate?.cancel()));
  };

  const begin = () => {
    root.classList.remove('theme-switching');
    const timing: KeyframeAnimationOptions = {
      duration: SHIFT_MS,
      easing: dawn ? DAWN_EASE : DUSK_EASE,
      fill: 'both',
    };
    const at = `at ${x.toFixed(1)}px ${y.toFixed(1)}px`;
    const closed = `circle(0px ${at})`;
    const open = `circle(${r.toFixed(1)}px ${at})`;
    // 亮面始终在上层动裁切；暗面在下层只做景深：日出时被推远压暗，日落时从近处落定
    const light = dawn ? '::view-transition-new(root)' : '::view-transition-old(root)';
    const dark = dawn ? '::view-transition-old(root)' : '::view-transition-new(root)';
    gate = root.animate({ opacity: [1, 1] }, { duration: SHIFT_MS * 20, pseudoElement: '::view-transition' });
    const clip = root.animate(
      { clipPath: dawn ? [closed, open] : [open, closed] },
      { ...timing, pseudoElement: light },
    );
    state.animations.push(
      clip,
      root.animate(
        dawn
          ? {
              transform: ['scale(1)', 'scale(1.035)'],
              filter: ['brightness(1)', 'brightness(0.72)'],
            }
          : {
              transform: ['scale(1.05)', 'scale(1)'],
              filter: ['brightness(0.6)', 'brightness(1)'],
            },
        { ...timing, pseudoElement: dark },
      ),
      ring.animate(
        [
          { transform: `scale(${dawn ? 0 : 1})`, opacity: 0 },
          { opacity: 1, offset: 0.12 },
          { opacity: 1, offset: 0.7 },
          { transform: `scale(${dawn ? 1 : 0})`, opacity: 0 },
        ],
        timing,
      ),
    );
    // 图标在圆心处最先被看到：新图标转着长出来
    const icon = origin?.querySelector('svg')?.animate(
      [
        { transform: `rotate(${dawn ? -90 : 90}deg) scale(0.4)`, opacity: 0 },
        { transform: 'rotate(0deg) scale(1)', opacity: 1 },
      ],
      {
        duration: 560,
        delay: 80,
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
        fill: 'backwards',
      },
    );
    if (icon) state.animations.push(icon);
    // 裁切走到任一端（正放到头或倒放退回起点）就是落地
    clip.onfinish = land;
    // 快照就绪前就被打断：动画一建好就从起点倒放，立刻落回原主题
    if (state.reversed) state.animations.forEach((animation) => animation.reverse());
  };

  // 挂在 html 伪元素上的动画在过渡结束后不会自己消失，fill 会留到下一次同名伪元素上，结束时必须取消
  const cleanup = () => {
    if (shift === state) {
      shift = null;
      if (state.reversed) applyInstantly(revert);
    }
    // 晚到的收尾不能动新切换的标记，否则新切换在动画挂上前会整屏露出亮面
    if (seq === shiftSeq) {
      root.classList.remove('theme-switching');
      delete root.dataset.themeShift;
    }
    ring.remove();
    gate?.cancel();
    state.animations.forEach((animation) => animation.cancel());
  };
  void transition.ready.then(begin, cleanup);
  void transition.finished.then(cleanup, cleanup);
}

function initialMode(): ThemeMode {
  const saved = readSetting('theme');
  return saved === 'light' || saved === 'dark' ? saved : 'auto';
}

const bootMode = initialMode();
const bootTheme = resolveTheme(bootMode);
const bootHue = normalizeHue(readSetting('theme.hue'));
applyHue(bootHue);
applyTheme(bootTheme);

interface ThemeState {
  mode: ThemeMode;
  theme: ResolvedTheme;
  hue: number;
  // origin 是触发切换的元素，动画圆心取它的中心
  setMode: (mode: ThemeMode, origin?: Element | null) => void;
  setHue: (hue: number) => void;
  toggle: (origin?: Element | null) => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  mode: bootMode,
  theme: bootTheme,
  hue: bootHue,
  setMode: (mode, origin) => {
    writeSetting('theme', mode);
    const theme = resolveTheme(mode);
    if (shift) {
      // 切换途中：要去的方向和当前走向相反就就地倒放，相同则什么都不用做
      if (theme !== heading(shift)) reverseShift(shift);
      set({ mode });
      return;
    }
    if (theme === get().theme) {
      set({ mode });
      return;
    }
    const from = get().theme;
    commitTheme(
      from,
      theme,
      () => {
        applyTheme(theme);
        set({ mode, theme });
      },
      () => {
        applyTheme(from);
        set({ theme: from });
      },
      origin,
    );
  },
  setHue: (hue) => {
    const next = normalizeHue(String(hue));
    writeSetting('theme.hue', next.toFixed(2));
    applyHue(next);
    set({ hue: next });
  },
  // 顶栏按钮只在昼夜之间切换；回到“跟随系统”走设置里的主题选择。
  // 切换途中以动画当前的走向为准，连点才是来回打断而不是重复同一个方向
  toggle: (origin) => {
    const current = shift ? heading(shift) : get().theme;
    get().setMode(current === 'light' ? 'dark' : 'light', origin);
  },
}));

systemLight.addEventListener('change', () => {
  if (useTheme.getState().mode !== 'auto') return;
  const theme = resolveTheme('auto');
  if (shift) {
    if (theme !== heading(shift)) reverseShift(shift);
    return;
  }
  applyTheme(theme);
  useTheme.setState({ theme });
});
