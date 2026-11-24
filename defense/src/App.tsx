import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DECK_SOURCE, type ThemeMode } from './data/deck.ts';
import {
  buildSpeakerSyncPayload,
  createDeckController,
  mapKeyToCommand,
  type DeckKeyAction,
  type DeckState,
  type SpeakerSyncPayload,
} from './core/deckController.ts';
import { DeckChrome } from './ui/DeckChrome.tsx';
import { LiveDemoSlide } from './ui/LiveDemoSlide.tsx';
import { SlideSpread } from './ui/SlideSpread.tsx';
import {
  openOrFocusSpeakerConsole,
  syncSpeakerWindow,
  type SpeakerWindowHandle,
} from './ui/speakerConsole.ts';
import './ui/EditorialDeck.css';

const THEME_STORAGE_KEY = 'defense.editorial.theme';

declare global {
  interface Window {
    __defenseDeck?: {
      goTo: (n: number) => void;
      next: () => void;
      prev: () => void;
      toggleTimer: () => void;
      resetTimer: () => void;
      toggleTheme: () => void;
      getState: () => {
        slide: number;
        sec: number;
        running: boolean;
        theme: ThemeMode;
      };
      getPayload: () => SpeakerSyncPayload;
    };
  }
}

function loadSavedTheme(): ThemeMode {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    return saved === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function toggleFullscreen(): void {
  if (!document.fullscreenElement) {
    void document.documentElement.requestFullscreen?.();
  } else {
    void document.exitFullscreen?.();
  }
}

export const App: React.FC = () => {
  const controller = useMemo(
    () => createDeckController(DECK_SOURCE, { initialTheme: loadSavedTheme() }),
    [],
  );
  const [state, setState] = useState<DeckState>(() => controller.getState());
  const [scale, setScale] = useState(1);
  const [dockVisible, setDockVisible] = useState(true);
  const dockTimerRef = useRef<number | null>(null);
  const speakerWinRef = useRef<SpeakerWindowHandle | null>(null);

  const flashDock = useCallback(() => {
    setDockVisible(true);
    if (dockTimerRef.current !== null) {
      window.clearTimeout(dockTimerRef.current);
    }
    dockTimerRef.current = window.setTimeout(() => {
      setDockVisible(false);
    }, 2200);
  }, []);

  const dispatchAction = useCallback(
    (action: DeckKeyAction) => {
      if (action.type === 'OPEN_SPEAKER') {
        const payload = buildSpeakerSyncPayload(DECK_SOURCE, controller.getState());
        speakerWinRef.current = openOrFocusSpeakerConsole(
          speakerWinRef.current,
          DECK_SOURCE,
          payload,
        );
        return;
      }
      if (action.type === 'TOGGLE_FULLSCREEN') {
        toggleFullscreen();
        return;
      }
      const next = controller.dispatch(action);
      setState(next);
      if (action.type !== 'TICK_TIMER') {
        flashDock();
      }
    },
    [controller, flashDock],
  );

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', state.theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, state.theme);
    } catch {
      // ignore storage errors in restricted contexts
    }
  }, [state.theme]);

  useEffect(() => {
    syncSpeakerWindow(speakerWinRef.current, buildSpeakerSyncPayload(DECK_SOURCE, state));
  }, [state]);

  useEffect(() => {
    if (!state.timerRunning) return undefined;
    const id = window.setInterval(() => {
      dispatchAction({ type: 'TICK_TIMER' });
    }, 1000);
    return () => window.clearInterval(id);
  }, [state.timerRunning, dispatchAction]);

  useEffect(() => {
    window.__defenseDeck = {
      goTo: (n) => dispatchAction({ type: 'GO_TO_SLIDE', slide: n }),
      next: () => dispatchAction({ type: 'NEXT_SLIDE' }),
      prev: () => dispatchAction({ type: 'PREV_SLIDE' }),
      toggleTimer: () => dispatchAction({ type: 'TOGGLE_TIMER' }),
      resetTimer: () => dispatchAction({ type: 'RESET_TIMER' }),
      toggleTheme: () => dispatchAction({ type: 'TOGGLE_THEME' }),
      getState: () => {
        const cur = controller.getState();
        return {
          slide: cur.slide,
          sec: cur.timerSeconds,
          running: cur.timerRunning,
          theme: cur.theme,
        };
      },
      getPayload: () => buildSpeakerSyncPayload(DECK_SOURCE, controller.getState()),
    };
    return () => {
      delete window.__defenseDeck;
    };
  }, [controller, dispatchAction]);

  useEffect(() => {
    const updateScale = () => {
      const next = Math.min(window.innerWidth / 1600, window.innerHeight / 900);
      setScale(Number(next.toFixed(5)));
    };
    updateScale();
    flashDock();
    window.addEventListener('resize', updateScale);
    return () => {
      window.removeEventListener('resize', updateScale);
      if (dockTimerRef.current !== null) {
        window.clearTimeout(dockTimerRef.current);
      }
    };
  }, [flashDock]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target instanceof HTMLElement ? e.target : null;
      const action = mapKeyToCommand({
        key: e.key,
        targetTag: target?.tagName,
        isContentEditable: Boolean(target?.isContentEditable),
        insideButton: Boolean(target?.closest('button')),
        hasModifier: e.ctrlKey || e.metaKey || e.altKey,
      });
      if (!action) return;
      e.preventDefault();
      dispatchAction(action);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [dispatchAction]);

  const currentSlide = DECK_SOURCE.slides[state.slide - 1] ?? DECK_SOURCE.slides[0];
  const progressPct = ((state.slide / DECK_SOURCE.slides.length) * 100).toFixed(2);

  return (
    <>
      <div className="ed-progress-track">
        <div className="ed-progress-fill" style={{ width: `${progressPct}%` }} />
      </div>

      <main className="ed-viewport">
        <div
          className="ed-stage"
          style={{ '--ed-scale': String(scale) } as React.CSSProperties}
        >
          <header className="ed-folio">
            <div className="ed-folio-left">
              <span className="ed-folio-num">
                0{currentSlide.id} / 0{DECK_SOURCE.slides.length}
              </span>
              <span className="ed-folio-kicker">
                {currentSlide.kicker} · {DECK_SOURCE.meta.competitionTag}
              </span>
            </div>
            <div className="ed-folio-right">
              <span className="ed-folio-tag">{currentSlide.anchorTag}</span>
              <span className="ed-folio-time">{currentSlide.window}</span>
            </div>
          </header>

          {currentSlide.id === 3 ? (
            <LiveDemoSlide deck={DECK_SOURCE} state={state} onDispatch={dispatchAction} />
          ) : (
            <SlideSpread
              deck={DECK_SOURCE}
              slide={currentSlide}
              onOpenQa={() => dispatchAction({ type: 'TOGGLE_QA_MODAL', force: true })}
            />
          )}
        </div>
      </main>

      <DeckChrome
        deck={DECK_SOURCE}
        state={state}
        currentSlide={currentSlide}
        dockVisible={dockVisible}
        onAction={dispatchAction}
      />
    </>
  );
};
