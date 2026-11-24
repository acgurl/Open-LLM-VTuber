import type { DeckSource, ThemeMode } from '../data/deck.ts';

export type DeckCommand =
  | { readonly type: 'NEXT_SLIDE' }
  | { readonly type: 'PREV_SLIDE' }
  | { readonly type: 'GO_TO_SLIDE'; readonly slide: number }
  | { readonly type: 'TOGGLE_THEME' }
  | { readonly type: 'SET_THEME'; readonly theme: ThemeMode }
  | { readonly type: 'SET_LIVE_URL'; readonly url: string }
  | { readonly type: 'RELOAD_LIVE_FRAME' }
  | { readonly type: 'MARK_PROMPT_COPIED'; readonly promptId: string }
  | { readonly type: 'CLEAR_COPIED_FLASH'; readonly promptId: string };

export interface DeckState {
  readonly slide: number;
  readonly theme: ThemeMode;
  readonly liveUrl: string;
  readonly iframeReloadNonce: number;
  readonly copiedPromptId: string | null;
  readonly usedPromptIds: readonly string[];
}

export interface KeyInputEvent {
  readonly key: string;
  readonly targetTag?: string;
  readonly isContentEditable?: boolean;
  readonly insideButton?: boolean;
}

export interface DeckController {
  getState: () => DeckState;
  dispatch: (command: DeckCommand) => DeckState;
}

function clampSlide(slide: number, total: number): number {
  if (!Number.isFinite(slide)) return 1;
  return Math.max(1, Math.min(total, Math.trunc(slide)));
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
  };

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
      }
    },
  };
}

export function mapKeyToCommand(input: KeyInputEvent): DeckCommand | null {
  const tag = (input.targetTag || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || input.isContentEditable) {
    return null;
  }

  const key = input.key;
  if (key === 'ArrowRight' || key === 'ArrowDown' || key === 'PageDown') {
    return { type: 'NEXT_SLIDE' };
  }
  if (key === 'ArrowLeft' || key === 'ArrowUp' || key === 'PageUp') {
    return { type: 'PREV_SLIDE' };
  }
  if (key === ' ') {
    if (tag === 'BUTTON' || tag === 'LABEL' || input.insideButton) {
      return null;
    }
    return { type: 'NEXT_SLIDE' };
  }
  if (key >= '1' && key <= '6') {
    return { type: 'GO_TO_SLIDE', slide: parseInt(key, 10) };
  }
  if (key === 't' || key === 'T') {
    return { type: 'TOGGLE_THEME' };
  }
  return null;
}
