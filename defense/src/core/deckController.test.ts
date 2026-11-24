import { describe, expect, it } from 'vitest';
import { DECK_SOURCE } from '../data/deck.ts';
import { createDeckController, mapKeyToCommand, buildSpeakerSyncPayload } from './deckController.ts';

describe('DECK_SOURCE invariants', () => {
  it('defines 6 slides summing to 290s within the 300s safety limit', () => {
    expect(DECK_SOURCE.slides).toHaveLength(6);
    const total = DECK_SOURCE.slides.reduce((acc, s) => acc + s.durationSec, 0);
    expect(total).toBe(290);
    expect(total).toBeLessThanOrEqual(DECK_SOURCE.meta.safetyLimitSec);
  });

  it('orders the three hard time anchors (1:10, 2:25, 4:10) against valid slides', () => {
    expect(DECK_SOURCE.anchors.map((a) => [a.timeLabel, a.atSeconds, a.slideId])).toEqual([
      ['1:10', 70, 3],
      ['2:25', 145, 4],
      ['4:10', 250, 6],
    ]);
  });
});

describe('DeckController core navigation, remote mapping, and theme', () => {
  it('starts on slide 1 in light theme and clamps navigation within 1..6', () => {
    const controller = createDeckController(DECK_SOURCE);
    expect(controller.getState().slide).toBe(1);
    expect(controller.getState().theme).toBe('light');

    controller.dispatch({ type: 'PREV_SLIDE' });
    expect(controller.getState().slide).toBe(1);

    controller.dispatch({ type: 'GO_TO_SLIDE', slide: 99 });
    expect(controller.getState().slide).toBe(6);

    controller.dispatch({ type: 'NEXT_SLIDE' });
    expect(controller.getState().slide).toBe(6);

    controller.dispatch({ type: 'GO_TO_SLIDE', slide: -3 });
    expect(controller.getState().slide).toBe(1);
  });

  it('toggles between light and dark theme', () => {
    const controller = createDeckController(DECK_SOURCE, { initialTheme: 'dark' });
    expect(controller.getState().theme).toBe('dark');
    controller.dispatch({ type: 'TOGGLE_THEME' });
    expect(controller.getState().theme).toBe('light');
    controller.dispatch({ type: 'SET_THEME', theme: 'dark' });
    expect(controller.getState().theme).toBe('dark');
  });

  it('maps presenter remote keys and keyboard shortcuts while ignoring inputs and space on buttons', () => {
    expect(mapKeyToCommand({ key: 'ArrowRight', targetTag: 'DIV' })).toEqual({ type: 'NEXT_SLIDE' });
    expect(mapKeyToCommand({ key: 'PageDown', targetTag: 'BODY' })).toEqual({ type: 'NEXT_SLIDE' });
    expect(mapKeyToCommand({ key: 'ArrowLeft', targetTag: 'BODY' })).toEqual({ type: 'PREV_SLIDE' });
    expect(mapKeyToCommand({ key: 'PageUp', targetTag: 'BODY' })).toEqual({ type: 'PREV_SLIDE' });
    expect(mapKeyToCommand({ key: ' ', targetTag: 'BODY' })).toEqual({ type: 'NEXT_SLIDE' });
    expect(mapKeyToCommand({ key: '4', targetTag: 'BODY' })).toEqual({ type: 'GO_TO_SLIDE', slide: 4 });
    expect(mapKeyToCommand({ key: 't', targetTag: 'BODY' })).toEqual({ type: 'TOGGLE_THEME' });

    expect(mapKeyToCommand({ key: ' ', targetTag: 'BUTTON' })).toBeNull();
    expect(mapKeyToCommand({ key: ' ', insideButton: true, targetTag: 'SPAN' })).toBeNull();
    expect(mapKeyToCommand({ key: 'ArrowRight', targetTag: 'INPUT' })).toBeNull();
    expect(mapKeyToCommand({ key: 't', targetTag: 'TEXTAREA' })).toBeNull();
  });
});

describe('DeckController live demo switcher & prompt copy tracking', () => {
  it('switches liveUrl among configured endpoints and rejects unknown URLs', () => {
    const controller = createDeckController(DECK_SOURCE);
    expect(controller.getState().liveUrl).toBe('https://ai.acgurl.cn/');

    controller.dispatch({ type: 'SET_LIVE_URL', url: 'https://vtuber.acgurl.cn/' });
    expect(controller.getState().liveUrl).toBe('https://vtuber.acgurl.cn/');

    controller.dispatch({ type: 'SET_LIVE_URL', url: 'http://localhost:12393/' });
    expect(controller.getState().liveUrl).toBe('http://localhost:12393/');

    controller.dispatch({ type: 'SET_LIVE_URL', url: 'https://evil.example.com/' });
    expect(controller.getState().liveUrl).toBe('http://localhost:12393/');
  });

  it('increments iframeReloadNonce on RELOAD_LIVE_FRAME', () => {
    const controller = createDeckController(DECK_SOURCE);
    expect(controller.getState().iframeReloadNonce).toBe(0);

    controller.dispatch({ type: 'RELOAD_LIVE_FRAME' });
    controller.dispatch({ type: 'RELOAD_LIVE_FRAME' });
    expect(controller.getState().iframeReloadNonce).toBe(2);
  });

  it('tracks copied prompt flash and deduplicates usedPromptIds', () => {
    const controller = createDeckController(DECK_SOURCE);

    controller.dispatch({ type: 'MARK_PROMPT_COPIED', promptId: '1' });
    expect(controller.getState().copiedPromptId).toBe('1');
    expect(controller.getState().usedPromptIds).toEqual(['1']);

    controller.dispatch({ type: 'MARK_PROMPT_COPIED', promptId: '1' });
    expect(controller.getState().usedPromptIds).toEqual(['1']);

    controller.dispatch({ type: 'CLEAR_COPIED_FLASH', promptId: '3' });
    expect(controller.getState().copiedPromptId).toBe('1');

    controller.dispatch({ type: 'CLEAR_COPIED_FLASH', promptId: '1' });
    expect(controller.getState().copiedPromptId).toBeNull();
    expect(controller.getState().usedPromptIds).toEqual(['1']);

    controller.dispatch({ type: 'MARK_PROMPT_COPIED', promptId: 'nonexistent' });
    expect(controller.getState().copiedPromptId).toBeNull();
    expect(controller.getState().usedPromptIds).toEqual(['1']);
  });
});

describe('DeckController timer, anchors, overlays, and speaker console payload', () => {
  it('manages timer lifecycle, thresholds (260s warn, 290s over), and 70/145/250s anchor lights', () => {
    const controller = createDeckController(DECK_SOURCE);
    expect(controller.getState().timerSeconds).toBe(0);
    expect(controller.getState().timerTone).toBe('idle');
    expect(controller.getState().anchorsReached).toEqual({
      demo: false,
      design: false,
      closing: false,
    });

    // Does not tick when paused
    controller.dispatch({ type: 'TICK_TIMER' });
    expect(controller.getState().timerSeconds).toBe(0);

    controller.dispatch({ type: 'TOGGLE_TIMER' });
    expect(controller.getState().timerRunning).toBe(true);
    expect(controller.getState().timerTone).toBe('running');

    for (let i = 0; i < 70; i += 1) controller.dispatch({ type: 'TICK_TIMER' });
    expect(controller.getState().timerSeconds).toBe(70);
    expect(controller.getState().anchorsReached).toEqual({
      demo: true,
      design: false,
      closing: false,
    });

    for (let i = 0; i < 75; i += 1) controller.dispatch({ type: 'TICK_TIMER' });
    expect(controller.getState().timerSeconds).toBe(145);
    expect(controller.getState().anchorsReached).toEqual({
      demo: true,
      design: true,
      closing: false,
    });

    for (let i = 0; i < 105; i += 1) controller.dispatch({ type: 'TICK_TIMER' });
    expect(controller.getState().timerSeconds).toBe(250);
    expect(controller.getState().anchorsReached).toEqual({
      demo: true,
      design: true,
      closing: true,
    });

    for (let i = 0; i < 10; i += 1) controller.dispatch({ type: 'TICK_TIMER' });
    expect(controller.getState().timerSeconds).toBe(260);
    expect(controller.getState().timerTone).toBe('warn');

    for (let i = 0; i < 30; i += 1) controller.dispatch({ type: 'TICK_TIMER' });
    expect(controller.getState().timerSeconds).toBe(290);
    expect(controller.getState().timerTone).toBe('over');

    controller.dispatch({ type: 'RESET_TIMER' });
    expect(controller.getState().timerSeconds).toBe(0);
    expect(controller.getState().timerRunning).toBe(false);
    expect(controller.getState().timerTone).toBe('idle');
    expect(controller.getState().anchorsReached).toEqual({
      demo: false,
      design: false,
      closing: false,
    });
  });

  it('toggles teleprompter and Q&A modal and closes modal on CLOSE_OVERLAYS', () => {
    const controller = createDeckController(DECK_SOURCE);

    controller.dispatch({ type: 'TOGGLE_TELEPROMPTER' });
    expect(controller.getState().teleprompterOpen).toBe(true);

    controller.dispatch({ type: 'TOGGLE_QA_MODAL', force: true });
    expect(controller.getState().qaModalOpen).toBe(true);

    controller.dispatch({ type: 'CLOSE_OVERLAYS' });
    expect(controller.getState().qaModalOpen).toBe(false);
  });

  it('maps P, F, N, Q, R, and Escape shortcuts', () => {
    expect(mapKeyToCommand({ key: 'p', targetTag: 'BODY' })).toEqual({ type: 'OPEN_SPEAKER' });
    expect(mapKeyToCommand({ key: 'F', targetTag: 'BODY' })).toEqual({ type: 'TOGGLE_FULLSCREEN' });
    expect(mapKeyToCommand({ key: 'n', targetTag: 'BODY' })).toEqual({ type: 'TOGGLE_TELEPROMPTER' });
    expect(mapKeyToCommand({ key: 'q', targetTag: 'BODY' })).toEqual({ type: 'TOGGLE_QA_MODAL' });
    expect(mapKeyToCommand({ key: 'r', targetTag: 'BODY' })).toEqual({ type: 'RESET_TIMER' });
    expect(mapKeyToCommand({ key: 'Escape', targetTag: 'BODY' })).toEqual({ type: 'CLOSE_OVERLAYS' });
  });

  it('builds speaker sync payload with formatted timer, slide meta, next slide meta, and anchors', () => {
    const controller = createDeckController(DECK_SOURCE);
    controller.dispatch({ type: 'GO_TO_SLIDE', slide: 3 });
    controller.dispatch({ type: 'TOGGLE_TIMER' });
    for (let i = 0; i < 70; i += 1) controller.dispatch({ type: 'TICK_TIMER' });

    const payload = buildSpeakerSyncPayload(DECK_SOURCE, controller.getState());
    expect(payload.slide).toBe(3);
    expect(payload.totalSlides).toBe(6);
    expect(payload.sec).toBe(70);
    expect(payload.formattedTimer).toBe('01:10 / 05:00');
    expect(payload.timerTone).toBe('running');
    expect(payload.slideMeta.id).toBe(3);
    expect(payload.nextSlideMeta?.id).toBe(4);
    expect(payload.anchorsReached.demo).toBe(true);
    expect(payload.anchorsReached.design).toBe(false);
  });
});
