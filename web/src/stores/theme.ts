import { create } from 'zustand';
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
  setMode: (mode: ThemeMode) => void;
  setHue: (hue: number) => void;
  toggle: () => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  mode: bootMode,
  theme: bootTheme,
  hue: bootHue,
  setMode: (mode) => {
    writeSetting('theme', mode);
    const theme = resolveTheme(mode);
    applyTheme(theme);
    set({ mode, theme });
  },
  setHue: (hue) => {
    const next = normalizeHue(String(hue));
    writeSetting('theme.hue', next.toFixed(2));
    applyHue(next);
    set({ hue: next });
  },
  // 顶栏按钮只在昼夜之间切换；回到“跟随系统”走设置里的主题选择。
  toggle: () => {
    get().setMode(get().theme === 'light' ? 'dark' : 'light');
  },
}));

systemLight.addEventListener('change', () => {
  if (useTheme.getState().mode !== 'auto') return;
  const theme = resolveTheme('auto');
  applyTheme(theme);
  useTheme.setState({ theme });
});
