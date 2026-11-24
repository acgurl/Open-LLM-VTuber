import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DECK_SOURCE, type ThemeMode } from './data/deck.ts';
import {
  createDeckController,
  mapKeyToCommand,
  type DeckCommand,
  type DeckState,
} from './core/deckController.ts';
import { LiveDemoSlide } from './ui/LiveDemoSlide.tsx';
import { SlideSpread } from './ui/SlideSpread.tsx';
import './ui/EditorialDeck.css';

const THEME_STORAGE_KEY = 'defense.editorial.theme';

function loadSavedTheme(): ThemeMode {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    return saved === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
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

  const flashDock = useCallback(() => {
    setDockVisible(true);
    if (dockTimerRef.current !== null) {
      window.clearTimeout(dockTimerRef.current);
    }
    dockTimerRef.current = window.setTimeout(() => {
      setDockVisible(false);
    }, 2200);
  }, []);

  const dispatch = useCallback(
    (command: DeckCommand) => {
      const next = controller.dispatch(command);
      setState(next);
      flashDock();
      return next;
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
      const command = mapKeyToCommand({
        key: e.key,
        targetTag: target?.tagName,
        isContentEditable: Boolean(target?.isContentEditable),
        insideButton: Boolean(target?.closest('button')),
      });
      if (!command) return;
      e.preventDefault();
      dispatch(command);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [dispatch]);

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
              <span className="ed-folio-num">0{currentSlide.id} / 0{DECK_SOURCE.slides.length}</span>
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
            <LiveDemoSlide deck={DECK_SOURCE} state={state} onDispatch={dispatch} />
          ) : (
            <SlideSpread deck={DECK_SOURCE} slide={currentSlide} />
          )}
        </div>
      </main>

      <div className="ed-hover-zone">
        <nav className={`ed-dock ${dockVisible ? 'is-visible' : ''}`} aria-label="演示控制台">
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => dispatch({ type: 'PREV_SLIDE' })}
            title="上一页 (←)"
          >
            ←
          </button>
          <span className="ed-dock-num">
            0{state.slide} / 0{DECK_SOURCE.slides.length}
          </span>
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => dispatch({ type: 'NEXT_SLIDE' })}
            title="下一页 (→)"
          >
            →
          </button>
          <span className="ed-dock-sep" />
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => dispatch({ type: 'TOGGLE_THEME' })}
            title="切换亮/暗投影模式 (T)"
          >
            亮/暗(T)
          </button>
        </nav>
      </div>
    </>
  );
};
