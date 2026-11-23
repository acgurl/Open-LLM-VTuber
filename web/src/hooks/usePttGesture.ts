import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LIMITS } from "../protocol/types";
import { interrupt } from "../services/actions";
import { audioPlayer } from "../services/audioPlayer";
import { ptt, transcribeWav } from "../services/ptt";
import { useConnection } from "../stores/connection";
import { toast } from "../stores/toast";

export type PttPhase = "idle" | "arming" | "recording" | "transcribing";

const HOLD_DELAY_MS = 140;
const CANCEL_SLIDE_PX = 48;
const WAVE_BAR_COUNT = 14;
const INITIAL_WAVE_BARS = Array<number>(WAVE_BAR_COUNT).fill(0.14);

interface UsePttGestureOptions {
  rowRef: React.RefObject<HTMLDivElement>;
  textRef: React.RefObject<HTMLTextAreaElement>;
  hasTextRef: React.MutableRefObject<boolean>;
  sendDisabledRef: React.MutableRefObject<boolean>;
  onBeforeStartGesture: () => void;
  onTranscriptReady: (transcript: string) => Promise<void>;
  onTranscriptTooLong: (transcript: string) => void;
}

export function usePttGesture({
  rowRef,
  textRef,
  hasTextRef,
  sendDisabledRef,
  onBeforeStartGesture,
  onTranscriptReady,
  onTranscriptTooLong,
}: UsePttGestureOptions) {
  const { t } = useTranslation();
  const [pttPhase, setPttPhase] = useState<PttPhase>("idle");
  const [pttCancelIntent, setPttCancelIntent] = useState(false);
  const [pttSeconds, setPttSeconds] = useState(0);
  const [pttBars, setPttBars] = useState<number[]>(INITIAL_WAVE_BARS);

  const pttPhaseRef = useRef<PttPhase>("idle");
  pttPhaseRef.current = pttPhase;

  const beforeStartRef = useRef(onBeforeStartGesture);
  beforeStartRef.current = onBeforeStartGesture;
  const submitTranscriptRef = useRef(onTranscriptReady);
  submitTranscriptRef.current = onTranscriptReady;
  const tooLongTranscriptRef = useRef(onTranscriptTooLong);
  tooLongTranscriptRef.current = onTranscriptTooLong;

  const gestureRef = useRef({
    mode: null as "mouse" | "touch" | null,
    pointerId: null as number | null,
    startX: 0,
    startY: 0,
    movedOut: false,
    holdTimer: null as number | null,
    holdTriggered: false,
    cancelIntent: false,
    submitting: false,
  });
  const detachWinRef = useRef<(() => void) | null>(null);
  const suppressNextClickRef = useRef(false);
  const pttStartAtRef = useRef(0);
  const lastWaveAtRef = useRef(0);
  const asrAbortRef = useRef<AbortController | null>(null);

  const pttHolding = pttPhase === "arming" || pttPhase === "recording";

  // 录音计时器
  useEffect(() => {
    if (pttPhase !== "recording") return;
    const id = window.setInterval(() => {
      setPttSeconds(Math.floor((Date.now() - pttStartAtRef.current) / 1000));
    }, 250);
    return () => window.clearInterval(id);
  }, [pttPhase]);

  const releaseCaptureIfHeld = (pid: number | null) => {
    if (pid === null) return;
    try {
      if (rowRef.current?.hasPointerCapture(pid)) {
        rowRef.current.releasePointerCapture(pid);
      }
    } catch {
      /* ignore */
    }
  };

  const resetGestureState = () => {
    const g = gestureRef.current;
    if (g.holdTimer !== null) {
      window.clearTimeout(g.holdTimer);
      g.holdTimer = null;
    }
    detachWinRef.current?.();
    const pid = g.mode === "mouse" ? g.pointerId : null;
    g.mode = null;
    g.pointerId = null;
    g.movedOut = false;
    g.holdTriggered = false;
    g.cancelIntent = false;
    releaseCaptureIfHeld(pid);
  };

  const cancelHoldRecording = () => {
    resetGestureState();
    gestureRef.current.submitting = false;
    ptt.cancel();
    setPttPhase("idle");
    setPttCancelIntent(false);
    setPttSeconds(0);
    setPttBars(INITIAL_WAVE_BARS);
  };

  // 按住录音期间：按 Esc、窗口失焦时安全取消，并屏蔽长按菜单/选词事件
  useEffect(() => {
    if (!pttHolding) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelHoldRecording();
      }
    };
    const onBlur = () => cancelHoldRecording();
    const onBlock = (e: Event) => e.preventDefault();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("blur", onBlur);
    window.addEventListener("contextmenu", onBlock);
    window.addEventListener("selectstart", onBlock);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("contextmenu", onBlock);
      window.removeEventListener("selectstart", onBlock);
    };
  }, [pttHolding]);

  // 组件卸载清理
  useEffect(() => {
    return () => {
      if (gestureRef.current.holdTimer !== null) {
        window.clearTimeout(gestureRef.current.holdTimer);
      }
      detachWinRef.current?.();
      ptt.cancel();
      asrAbortRef.current?.abort();
    };
  }, []);

  const finishHoldRecording = async () => {
    const g = gestureRef.current;
    if (g.submitting) return;
    g.submitting = true;
    resetGestureState();

    const result = ptt.stopAndEncode();
    setPttCancelIntent(false);
    setPttSeconds(0);
    setPttBars(INITIAL_WAVE_BARS);

    if (result.status === "empty") {
      g.submitting = false;
      setPttPhase("idle");
      return;
    }
    if (result.status === "too-short") {
      g.submitting = false;
      setPttPhase("idle");
      toast(t("input.pttTooShort"));
      return;
    }

    if (sendDisabledRef.current) {
      g.submitting = false;
      setPttPhase("idle");
      toast(t("error.serverBusy"), "error");
      return;
    }

    setPttPhase("transcribing");
    const controller = new AbortController();
    asrAbortRef.current = controller;

    try {
      const transcript = await transcribeWav(result.wav, controller.signal);
      if (!transcript) {
        toast(t("input.pttEmpty"));
        return;
      }
      if (transcript.length > LIMITS.textInputChars) {
        tooLongTranscriptRef.current(transcript);
        return;
      }
      await submitTranscriptRef.current(transcript);
    } catch (err) {
      if ((err as DOMException | null)?.name === "AbortError") return;
      toast(err instanceof Error ? err.message : t("error.generic"), "error");
    } finally {
      if (asrAbortRef.current === controller) asrAbortRef.current = null;
      g.submitting = false;
      setPttPhase("idle");
    }
  };

  const handleGestureMove = (clientX: number, clientY: number) => {
    const g = gestureRef.current;
    if (g.pointerId === null) return;
    if (!g.holdTriggered) {
      // 尚未进入录音前大幅滑动，视为滑动误触而非长按，取消计时
      if (Math.hypot(clientX - g.startX, clientY - g.startY) > 24) {
        if (g.holdTimer !== null) {
          window.clearTimeout(g.holdTimer);
          g.holdTimer = null;
        }
        g.movedOut = true;
        if (g.mode === "mouse") {
          detachWinRef.current?.();
          g.mode = null;
          g.pointerId = null;
        }
      }
      return;
    }
    const wantCancel = clientY - g.startY < -CANCEL_SLIDE_PX;
    if (wantCancel !== g.cancelIntent) {
      g.cancelIntent = wantCancel;
      setPttCancelIntent(wantCancel);
    }
  };

  const finishActiveGesture = (
    mode: "mouse" | "touch",
    id: number,
    forceCancel: boolean,
    focusOnTap = false,
  ) => {
    const g = gestureRef.current;
    if (g.mode !== mode || g.pointerId !== id) return;
    const wasTriggered = g.holdTriggered;
    const wasCancelIntent = g.cancelIntent;
    const wasMovedOut = g.movedOut;
    resetGestureState();

    if (!wasTriggered) {
      if (focusOnTap && !forceCancel && !wasMovedOut) {
        textRef.current?.focus();
      }
      return;
    }

    window.setTimeout(() => {
      suppressNextClickRef.current = false;
    }, 0);

    if (forceCancel || wasCancelIntent) {
      cancelHoldRecording();
      return;
    }
    void finishHoldRecording();
  };

  const startHoldRecording = async () => {
    const g = gestureRef.current;
    if (g.pointerId === null || g.movedOut) return;
    g.holdTriggered = true;
    g.holdTimer = null;
    suppressNextClickRef.current = true;

    // 真正触发长按后再失焦并接管指针，避免影响短按聚焦输入
    textRef.current?.blur();
    window.getSelection()?.removeAllRanges();
    if (g.mode === "mouse") {
      try {
        rowRef.current?.setPointerCapture(g.pointerId);
      } catch {
        /* ignore */
      }
    }

    setPttPhase("arming");
    setPttCancelIntent(false);
    setPttSeconds(0);
    setPttBars(INITIAL_WAVE_BARS);

    // 进入按住说话即打断当前 AI 播报/生成，避免外放回声被录进麦克风
    if (useConnection.getState().busy || audioPlayer.isActive()) {
      interrupt();
    }

    const ok = await ptt.start({
      onReady: () => {
        if (
          gestureRef.current.pointerId === null ||
          !gestureRef.current.holdTriggered ||
          gestureRef.current.submitting
        ) {
          return;
        }
        pttStartAtRef.current = Date.now();
        setPttPhase("recording");
        try {
          navigator.vibrate?.(15);
        } catch {
          /* ignore */
        }
      },
      onLevel: (level) => {
        const now = performance.now();
        if (now - lastWaveAtRef.current < 55) return;
        lastWaveAtRef.current = now;
        const barHeight = Math.max(0.14, level);
        setPttBars((prev) => [...prev.slice(1), barHeight]);
      },
      onAutoStop: () => {
        void finishHoldRecording();
      },
    });

    if (
      !ok &&
      gestureRef.current.holdTriggered &&
      !gestureRef.current.submitting
    ) {
      cancelHoldRecording();
    }
  };

  const startHoldRef = useRef(startHoldRecording);
  startHoldRef.current = startHoldRecording;
  const moveRef = useRef(handleGestureMove);
  moveRef.current = handleGestureMove;
  const finishRef = useRef(finishActiveGesture);
  finishRef.current = finishActiveGesture;

  // 触屏端使用非 passive 的原生 touchstart/touchmove 监听：
  // 在输入栏无文字时于 touchstart 立即 preventDefault()，彻底阻止 Android/iOS 弹出原生文本/粘贴菜单并打断录音；
  // 短按 (<180ms) 在 touchend 中同步 focus() 输入框唤起键盘。桌面鼠标完全不触发 touch 事件，保留右键粘贴。
  useEffect(() => {
    const row = rowRef.current;
    if (!row) return;

    const findTouch = (list: TouchList, id: number): Touch | null => {
      for (let i = 0; i < list.length; i += 1) {
        if (list[i].identifier === id) return list[i];
      }
      return null;
    };

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      if (pttPhaseRef.current !== "idle") return;
      if (hasTextRef.current) return;
      if ((e.target as Element | null)?.closest("button, .media-anchor")) return;

      // 关键：必须在原生非 passive 的 touchstart 阻止默认行为，否则移动浏览器约 450ms 后会弹出文本菜单并触发 pointercancel
      e.preventDefault();
      beforeStartRef.current();

      const touch = e.changedTouches[0] ?? e.touches[0];
      if (!touch) return;

      const g = gestureRef.current;
      resetGestureState();
      suppressNextClickRef.current = false;

      const tid = touch.identifier;
      g.mode = "touch";
      g.pointerId = tid;
      g.startX = touch.clientX;
      g.startY = touch.clientY;
      g.movedOut = false;
      g.holdTriggered = false;
      g.cancelIntent = false;
      g.submitting = false;

      const onTouchMove = (ev: TouchEvent) => {
        if (
          gestureRef.current.mode !== "touch" ||
          gestureRef.current.pointerId !== tid
        )
          return;
        const tItem =
          findTouch(ev.touches, tid) ?? findTouch(ev.changedTouches, tid);
        if (!tItem) return;
        ev.preventDefault();
        moveRef.current(tItem.clientX, tItem.clientY);
      };
      const onTouchEnd = (ev: TouchEvent) => {
        if (
          gestureRef.current.mode !== "touch" ||
          gestureRef.current.pointerId !== tid
        )
          return;
        const tItem = findTouch(ev.changedTouches, tid);
        if (!tItem && findTouch(ev.touches, tid)) return;
        finishRef.current("touch", tid, false, true);
      };
      const onTouchCancel = (ev: TouchEvent) => {
        if (
          gestureRef.current.mode !== "touch" ||
          gestureRef.current.pointerId !== tid
        )
          return;
        const tItem = findTouch(ev.changedTouches, tid);
        if (!tItem && findTouch(ev.touches, tid)) return;
        finishRef.current("touch", tid, true, false);
      };

      window.addEventListener("touchmove", onTouchMove, { passive: false });
      window.addEventListener("touchend", onTouchEnd);
      window.addEventListener("touchcancel", onTouchCancel);
      detachWinRef.current = () => {
        window.removeEventListener("touchmove", onTouchMove);
        window.removeEventListener("touchend", onTouchEnd);
        window.removeEventListener("touchcancel", onTouchCancel);
        detachWinRef.current = null;
      };

      g.holdTimer = window.setTimeout(() => {
        void startHoldRef.current();
      }, HOLD_DELAY_MS);
    };

    row.addEventListener("touchstart", onTouchStart, { passive: false });
    return () => {
      row.removeEventListener("touchstart", onTouchStart);
    };
  }, []);

  const onRowPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "touch") return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (pttPhase !== "idle") return;
    // 输入栏有文字时保留长按选词/移动光标能力，不抢占为语音
    if (hasTextRef.current) return;
    if ((e.target as Element | null)?.closest("button, .media-anchor")) return;
    beforeStartRef.current();

    const g = gestureRef.current;
    resetGestureState();
    suppressNextClickRef.current = false;

    const pid = e.pointerId;
    g.mode = "mouse";
    g.pointerId = pid;
    g.startX = e.clientX;
    g.startY = e.clientY;
    g.movedOut = false;
    g.holdTriggered = false;
    g.cancelIntent = false;
    g.submitting = false;

    const onMove = (ev: PointerEvent) => {
      if (
        gestureRef.current.mode !== "mouse" ||
        ev.pointerId !== gestureRef.current.pointerId
      )
        return;
      moveRef.current(ev.clientX, ev.clientY);
    };
    const onUp = (ev: PointerEvent) => {
      if (
        gestureRef.current.mode !== "mouse" ||
        ev.pointerId !== gestureRef.current.pointerId
      )
        return;
      finishRef.current("mouse", ev.pointerId, false);
    };
    const onCancel = (ev: PointerEvent) => {
      if (
        gestureRef.current.mode !== "mouse" ||
        ev.pointerId !== gestureRef.current.pointerId
      )
        return;
      finishRef.current("mouse", ev.pointerId, true);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    detachWinRef.current = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      detachWinRef.current = null;
    };

    g.holdTimer = window.setTimeout(() => {
      void startHoldRef.current();
    }, HOLD_DELAY_MS);
  };

  const onRowPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (
      gestureRef.current.mode === "mouse" &&
      e.pointerId === gestureRef.current.pointerId
    ) {
      handleGestureMove(e.clientX, e.clientY);
    }
  };

  const onRowPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    finishActiveGesture("mouse", e.pointerId, false);
  };

  const onRowPointerCancel = (e: React.PointerEvent<HTMLDivElement>) => {
    finishActiveGesture("mouse", e.pointerId, true);
  };

  const onRowLostPointerCapture = (e: React.PointerEvent<HTMLDivElement>) => {
    finishActiveGesture("mouse", e.pointerId, true);
  };

  const onRowClickCapture = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!suppressNextClickRef.current) return;
    suppressNextClickRef.current = false;
    e.preventDefault();
    e.stopPropagation();
    textRef.current?.blur();
  };

  const onRowContextMenu = (e: React.MouseEvent<HTMLDivElement>) => {
    if (
      pttHolding ||
      gestureRef.current.holdTriggered ||
      gestureRef.current.pointerId !== null
    ) {
      e.preventDefault();
    }
  };

  return {
    pttPhase,
    pttHolding,
    pttCancelIntent,
    pttSeconds,
    pttBars,
    rowHandlers: {
      onPointerDown: onRowPointerDown,
      onPointerMove: onRowPointerMove,
      onPointerUp: onRowPointerUp,
      onPointerCancel: onRowPointerCancel,
      onLostPointerCapture: onRowLostPointerCapture,
      onClickCapture: onRowClickCapture,
      onContextMenu: onRowContextMenu,
    },
  };
}
