import type { DeckSource, ThemeMode } from '../data/deck.ts';

export type DeckCommand =
  | { readonly type: 'NEXT_SLIDE' }
  | { readonly type: 'PREV_SLIDE' }
  | { readonly type: 'GO_TO_SLIDE'; readonly slide: number }
  | { readonly type: 'TOGGLE_THEME' }
  | { readonly type: 'SET_THEME'; readonly theme: ThemeMode };

export interface DeckState {
  readonly slide: number;
  readonly theme: ThemeMode;
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
  let state: DeckState = {
    slide: 1,
    theme: options?.initialTheme === 'dark' ? 'dark' : 'light',
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
