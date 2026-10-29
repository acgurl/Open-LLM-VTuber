import { create } from 'zustand';
import { flushSync } from 'react-dom';
import { readSetting, writeSetting } from '../utils/storage';

export type ThemeMode = 'auto' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

// AIRI 同款：整个界面由单一色相派生，主色、补色、第三色随它一起转。
export const DEFAULT_HUE = 220.44;

// 跟随系统时用系统的昼夜偏好作为自动切换源，系统切换后页面实时响应。
const systemLight = window.matchMedia('(prefers-color-scheme: light)');

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'auto') return systemLight.matches ? 'light' : 'dark';
  return mode;
}

function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', theme === 'light' ? '#f7f8fb' : '#121212');
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

// 明暗切换不做逐属性过渡：带 backdrop-filter 的玻璃层一帧帧重绘反而更卡。
// 交给 View Transitions 把新旧界面各拍一张快照，新的从触发按钮处圆形铺开，
// 裁切动画跑在合成器上，整屏只有一层参与。
function commitTheme(apply: () => void, origin?: Element | null): void {
  const start = document.startViewTransition?.bind(document);
  if (!start || reducedMotion.matches) {
    apply();
    return;
  }
  const rect = origin?.getBoundingClientRect();
  const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
  const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
  const root = document.documentElement;
  root.style.setProperty('--theme-x', `${x.toFixed(1)}px`);
  root.style.setProperty('--theme-y', `${y.toFixed(1)}px`);
  root.style.setProperty(
    '--theme-r',
    `${Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y)).toFixed(1)}px`,
  );
  const transition = start(() => {
    flushSync(apply);
  });
  void transition.finished.catch(() => undefined);
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
    if (theme === get().theme) {
      set({ mode });
      return;
    }
    commitTheme(() => {
      applyTheme(theme);
      set({ mode, theme });
    }, origin);
  },
  setHue: (hue) => {
    const next = normalizeHue(String(hue));
    writeSetting('theme.hue', next.toFixed(2));
    applyHue(next);
    set({ hue: next });
  },
  // 顶栏按钮只在昼夜之间切换；回到“跟随系统”走设置里的主题选择。
  toggle: (origin) => {
    get().setMode(get().theme === 'light' ? 'dark' : 'light', origin);
  },
}));

systemLight.addEventListener('change', () => {
  if (useTheme.getState().mode !== 'auto') return;
  const theme = resolveTheme('auto');
  applyTheme(theme);
  useTheme.setState({ theme });
});
