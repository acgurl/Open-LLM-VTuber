import type { DeckSource, SlideDefinition, ThemeMode } from '../data/deck.ts';

export type TimerTone = 'idle' | 'running' | 'warn' | 'over';

export interface AnchorReachedState {
  readonly demo: boolean;
  readonly design: boolean;
  readonly closing: boolean;
}

export type DeckCommand =
  | { readonly type: 'NEXT_SLIDE' }
  | { readonly type: 'PREV_SLIDE' }
  | { readonly type: 'GO_TO_SLIDE'; readonly slide: number }
  | { readonly type: 'TOGGLE_THEME' }
  | { readonly type: 'SET_THEME'; readonly theme: ThemeMode }
  | { readonly type: 'SET_LIVE_URL'; readonly url: string }
  | { readonly type: 'RELOAD_LIVE_FRAME' }
  | { readonly type: 'MARK_PROMPT_COPIED'; readonly promptId: string }
  | { readonly type: 'CLEAR_COPIED_FLASH'; readonly promptId: string }
  | { readonly type: 'TOGGLE_TIMER' }
  | { readonly type: 'TICK_TIMER' }
  | { readonly type: 'RESET_TIMER' }
  | { readonly type: 'TOGGLE_TELEPROMPTER'; readonly force?: boolean }
  | { readonly type: 'TOGGLE_QA_MODAL'; readonly force?: boolean }
  | { readonly type: 'CLOSE_OVERLAYS' };

export type DeckKeyAction =
  | DeckCommand
  | { readonly type: 'OPEN_SPEAKER' }
  | { readonly type: 'TOGGLE_FULLSCREEN' };

export interface DeckState {
  readonly slide: number;
  readonly theme: ThemeMode;
  readonly liveUrl: string;
  readonly iframeReloadNonce: number;
  readonly copiedPromptId: string | null;
  readonly usedPromptIds: readonly string[];
  readonly timerSeconds: number;
  readonly timerRunning: boolean;
  readonly timerTone: TimerTone;
  readonly anchorsReached: AnchorReachedState;
  readonly teleprompterOpen: boolean;
  readonly qaModalOpen: boolean;
}

export interface KeyInputEvent {
  readonly key: string;
  readonly targetTag?: string;
  readonly isContentEditable?: boolean;
  readonly insideButton?: boolean;
  readonly hasModifier?: boolean;
}

export interface SpeakerSyncPayload {
  readonly slide: number;
  readonly totalSlides: number;
  readonly sec: number;
  readonly formattedTimer: string;
  readonly running: boolean;
  readonly timerTone: TimerTone;
  readonly theme: ThemeMode;
  readonly slideMeta: SlideDefinition;
  readonly nextSlideMeta: SlideDefinition | null;
  readonly anchorsReached: AnchorReachedState;
}

export interface DeckController {
  getState: () => DeckState;
  dispatch: (command: DeckCommand) => DeckState;
}

function clampSlide(slide: number, total: number): number {
  if (!Number.isFinite(slide)) return 1;
  return Math.max(1, Math.min(total, Math.trunc(slide)));
}

export function formatMMSS(sec: number): string {
  const safe = Math.max(0, Math.floor(sec));
  const m = Math.floor(safe / 60);
  const s = safe % 60;
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

export function formatTimerLabel(sec: number, limitSec: number): string {
  return `${formatMMSS(sec)} / ${formatMMSS(limitSec)}`;
}

function computeTimerTone(deck: DeckSource, sec: number, running: boolean): TimerTone {
  if (sec >= deck.meta.overAtSec) return 'over';
  if (sec >= deck.meta.warnAtSec) return 'warn';
  return running ? 'running' : 'idle';
}

function computeAnchorsReached(deck: DeckSource, sec: number): AnchorReachedState {
  const threshold = (id: 'demo' | 'design' | 'closing'): number =>
    deck.anchors.find((a) => a.id === id)?.atSeconds ?? Number.POSITIVE_INFINITY;
  return {
    demo: sec >= threshold('demo'),
    design: sec >= threshold('design'),
    closing: sec >= threshold('closing'),
  };
}

export function createDeckController(
  deck: DeckSource,
  options?: { readonly initialTheme?: ThemeMode },
): DeckController {
  const totalSlides = deck.slides.length;
  const allowedUrls = new Set(deck.slide3.endpoints.map((ep) => ep.url));
  const allowedPromptIds = new Set(deck.slide3.prompts.map((p) => p.id));
  const defaultLiveUrl = deck.slide3.endpoints[0]?.url ?? deck.meta.liveSiteUrl;

  let state: DeckState = {
    slide: 1,
    theme: options?.initialTheme === 'dark' ? 'dark' : 'light',
    liveUrl: defaultLiveUrl,
    iframeReloadNonce: 0,
    copiedPromptId: null,
    usedPromptIds: [],
    timerSeconds: 0,
    timerRunning: false,
    timerTone: 'idle',
    anchorsReached: computeAnchorsReached(deck, 0),
    teleprompterOpen: false,
    qaModalOpen: false,
  };

  const withTimerState = (sec: number, running: boolean): DeckState => ({
    ...state,
    timerSeconds: sec,
    timerRunning: running,
    timerTone: computeTimerTone(deck, sec, running),
    anchorsReached: computeAnchorsReached(deck, sec),
  });

  return {
    getState: () => state,
    dispatch: (command: DeckCommand) => {
      switch (command.type) {
        case 'NEXT_SLIDE':
          state = { ...state, slide: clampSlide(state.slide + 1, totalSlides) };
          return state;
        case 'PREV_SLIDE':
          state = { ...state, slide: clampSlide(state.slide - 1, totalSlides) };
          return state;
        case 'GO_TO_SLIDE':
          state = { ...state, slide: clampSlide(command.slide, totalSlides) };
          return state;
        case 'TOGGLE_THEME':
          state = { ...state, theme: state.theme === 'dark' ? 'light' : 'dark' };
          return state;
        case 'SET_THEME':
          state = { ...state, theme: command.theme };
          return state;
        case 'SET_LIVE_URL':
          if (allowedUrls.has(command.url)) {
            state = { ...state, liveUrl: command.url };
          }
          return state;
        case 'RELOAD_LIVE_FRAME':
          state = { ...state, iframeReloadNonce: state.iframeReloadNonce + 1 };
          return state;
        case 'MARK_PROMPT_COPIED': {
          if (!allowedPromptIds.has(command.promptId)) return state;
          const used = state.usedPromptIds.includes(command.promptId)
            ? state.usedPromptIds
            : [...state.usedPromptIds, command.promptId];
          state = { ...state, copiedPromptId: command.promptId, usedPromptIds: used };
          return state;
        }
        case 'CLEAR_COPIED_FLASH':
          if (state.copiedPromptId === command.promptId) {
            state = { ...state, copiedPromptId: null };
          }
          return state;
        case 'TOGGLE_TIMER':
          state = withTimerState(state.timerSeconds, !state.timerRunning);
          return state;
        case 'TICK_TIMER':
          if (!state.timerRunning) return state;
          state = withTimerState(state.timerSeconds + 1, true);
          return state;
        case 'RESET_TIMER':
          state = withTimerState(0, false);
          return state;
        case 'TOGGLE_TELEPROMPTER':
          state = {
            ...state,
            teleprompterOpen:
              typeof command.force === 'boolean' ? command.force : !state.teleprompterOpen,
          };
          return state;
        case 'TOGGLE_QA_MODAL':
          state = {
            ...state,
            qaModalOpen: typeof command.force === 'boolean' ? command.force : !state.qaModalOpen,
          };
          return state;
        case 'CLOSE_OVERLAYS':
          state = { ...state, qaModalOpen: false };
          return state;
      }
    },
  };
}

const SIMPLE_KEY_MAP: Record<string, DeckKeyAction> = {
  ArrowRight: { type: 'NEXT_SLIDE' },
  ArrowDown: { type: 'NEXT_SLIDE' },
  PageDown: { type: 'NEXT_SLIDE' },
  ArrowLeft: { type: 'PREV_SLIDE' },
  ArrowUp: { type: 'PREV_SLIDE' },
  PageUp: { type: 'PREV_SLIDE' },
  Escape: { type: 'CLOSE_OVERLAYS' },
  t: { type: 'TOGGLE_THEME' },
  T: { type: 'TOGGLE_THEME' },
  n: { type: 'TOGGLE_TELEPROMPTER' },
  N: { type: 'TOGGLE_TELEPROMPTER' },
  q: { type: 'TOGGLE_QA_MODAL' },
  Q: { type: 'TOGGLE_QA_MODAL' },
  r: { type: 'RESET_TIMER' },
  R: { type: 'RESET_TIMER' },
  p: { type: 'OPEN_SPEAKER' },
  P: { type: 'OPEN_SPEAKER' },
  f: { type: 'TOGGLE_FULLSCREEN' },
  F: { type: 'TOGGLE_FULLSCREEN' },
};

export function mapKeyToCommand(input: KeyInputEvent): DeckKeyAction | null {
  if (input.hasModifier) {
    return null;
  }
  const tag = (input.targetTag || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || input.isContentEditable) {
    return null;
  }

  const key = input.key;
  if (key === ' ') {
    if (tag === 'BUTTON' || tag === 'LABEL' || input.insideButton) {
      return null;
    }
    return { type: 'NEXT_SLIDE' };
  }
  if (key >= '1' && key <= '6') {
    return { type: 'GO_TO_SLIDE', slide: parseInt(key, 10) };
  }
  return SIMPLE_KEY_MAP[key] ?? null;
}

export function buildSpeakerSyncPayload(deck: DeckSource, state: DeckState): SpeakerSyncPayload {
  const slideMeta = deck.slides[state.slide - 1] ?? deck.slides[0];
  const nextSlideMeta = deck.slides[state.slide] ?? null;
  return {
    slide: state.slide,
    totalSlides: deck.slides.length,
    sec: state.timerSeconds,
    formattedTimer: formatTimerLabel(state.timerSeconds, deck.meta.safetyLimitSec),
    running: state.timerRunning,
    timerTone: state.timerTone,
    theme: state.theme,
    slideMeta,
    nextSlideMeta,
    anchorsReached: state.anchorsReached,
  };
}
