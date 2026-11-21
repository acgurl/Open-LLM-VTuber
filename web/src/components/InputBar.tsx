import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useConnection } from "../stores/connection";
import { useSettings } from "../stores/settings";
import { useGroup } from "../stores/group";
import { toast } from "../stores/toast";
import { sendText, interrupt } from "../services/actions";
import { audioPlayer } from "../services/audioPlayer";
import { mic } from "../services/mic";
import { ptt, transcribeWav } from "../services/ptt";
import { camera } from "../services/camera";
import { fileToBase64 } from "../utils/base64";
import { captureCamera, captureScreen } from "../utils/capture";
import { LIMITS, type ImagePayload, type ImageSource } from "../protocol/types";
import { usePresence } from "../hooks/usePresence";
import {
  AddIcon,
  CamIcon,
  CloseIcon,
  ImageIcon,
  MicIcon,
  ScreenShareIcon,
  StopIcon,
  SendIcon,
} from "./icons";
import { ThinkingControls, useThinking } from "./ThinkingControls";

interface PendingImage {
  id: number;
  payload: ImagePayload;
  preview: string;
}

type PttPhase = "idle" | "arming" | "recording" | "transcribing";

const HOLD_DELAY_MS = 180;
const CANCEL_SLIDE_PX = 48;
const WAVE_BAR_COUNT = 14;
const INITIAL_WAVE_BARS = Array<number>(WAVE_BAR_COUNT).fill(0.14);

let imageSeq = 0;

function formatDuration(totalSeconds: number): string {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function InputBar() {
  const { t } = useTranslation();
  const busy = useConnection((s) => s.busy);
  const inGroup = useGroup((s) => s.members.length > 1);
  const micOn = useSettings((s) => s.micOn);
  const [text, setText] = useState("");
  const [images, setImages] = useState<PendingImage[]>([]);
  const [micStarting, setMicStarting] = useState(false);
  const [mediaMenuOpen, setMediaMenuOpen] = useState(false);
  const [pttPhase, setPttPhase] = useState<PttPhase>("idle");
  const [pttCancelIntent, setPttCancelIntent] = useState(false);
  const [pttSeconds, setPttSeconds] = useState(0);
  const [pttBars, setPttBars] = useState<number[]>(INITIAL_WAVE_BARS);

  const mediaMenuPresence = usePresence(mediaMenuOpen, 140);
  const thinking = useThinking();
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // 已占用的附图名额：多张图并发编码时 images 状态还没更新，靠它同步计数才能守住上限
  const imageSlots = useRef(0);

  // 最新值同步到 ref，供异步转写结束后的提交闭包读取，避免拿到过期状态
  const imagesRef = useRef<PendingImage[]>([]);
  imagesRef.current = images;
  const textStateRef = useRef("");
  textStateRef.current = text;
  const sendDisabledRef = useRef(false);

  const gestureRef = useRef({
    pointerId: null as number | null,
    startY: 0,
    holdTimer: null as number | null,
    holdTriggered: false,
    cancelIntent: false,
    submitting: false,
  });
  const suppressNextClickRef = useRef(false);
  const pttStartAtRef = useRef(0);
  const lastWaveAtRef = useRef(0);
  const asrAbortRef = useRef<AbortController | null>(null);

  const pttHolding = pttPhase === "arming" || pttPhase === "recording";

  // 窄屏聊天区贴输入框上沿，输入条自身会长高（换行、附图条），高度得上报给 CSS
  useEffect(() => {
    const el = barRef.current;
    if (!el) return;
    const apply = () => {
      document.documentElement.style.setProperty(
        "--input-bar-h",
        `${el.offsetHeight}px`,
      );
    };
    apply();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = textRef.current;
    if (!el || pttHolding) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [text, pttHolding]);

  // 录音计时器
  useEffect(() => {
    if (pttPhase !== "recording") return;
    const id = window.setInterval(() => {
      setPttSeconds(Math.floor((Date.now() - pttStartAtRef.current) / 1000));
    }, 250);
    return () => window.clearInterval(id);
  }, [pttPhase]);

  const cancelHoldRecording = () => {
    const g = gestureRef.current;
    if (g.holdTimer !== null) {
      window.clearTimeout(g.holdTimer);
      g.holdTimer = null;
    }
    g.pointerId = null;
    g.holdTriggered = false;
    g.cancelIntent = false;
    g.submitting = false;
    ptt.cancel();
    setPttPhase("idle");
    setPttCancelIntent(false);
    setPttSeconds(0);
    setPttBars(INITIAL_WAVE_BARS);
  };

  // 按住录音期间：按 Esc 或窗口失焦时安全取消，防止状态卡死
  useEffect(() => {
    if (!pttHolding) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelHoldRecording();
      }
    };
    const onBlur = () => cancelHoldRecording();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("blur", onBlur);
    };
  }, [pttHolding]);

  // 组件卸载清理
  useEffect(() => {
    return () => {
      if (gestureRef.current.holdTimer !== null) {
        window.clearTimeout(gestureRef.current.holdTimer);
      }
      ptt.cancel();
      asrAbortRef.current?.abort();
    };
  }, []);

  const grabAndAdd = async (source: "camera" | "screen") => {
    setMediaMenuOpen(false);
    try {
      let blob: Blob | null;
      // 实况窗口开着就直接从常驻流抓帧，免得二次开摄像头
      if (source === "camera")
        blob = camera.isLive ? await camera.grabBlob() : await captureCamera();
      else blob = await captureScreen();
      if (blob) await addImage(blob, source, "image/jpeg");
    } catch {
      toast(t("error.generic"), "error");
    }
  };

  const addImage = async (
    file: File | Blob,
    source: ImageSource,
    mime: string,
  ) => {
    if (imageSlots.current >= LIMITS.maxImages) {
      toast(t("input.imageTooMany"), "error");
      return;
    }
    imageSlots.current += 1;
    const data = await fileToBase64(file).catch(() => null);
    if (data === null || data.length > LIMITS.maxImageDataChars) {
      imageSlots.current -= 1;
      toast(
        t(data === null ? "error.generic" : "input.imageTooLarge"),
        "error",
      );
      return;
    }
    setImages((prev) => [
      ...prev,
      {
        id: ++imageSeq,
        payload: { source, mime_type: mime, data },
        preview: URL.createObjectURL(file),
      },
    ]);
  };

  const removeImage = (id: number) => {
    imageSlots.current = Math.max(0, imageSlots.current - 1);
    setImages((prev) => {
      const target = prev.find((img) => img.id === id);
      if (target) URL.revokeObjectURL(target.preview);
      return prev.filter((img) => img.id !== id);
    });
  };

  // 来源菜单：点菜单外或按 Esc 收起
  useEffect(() => {
    if (!mediaMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (
        !anchorRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      )
        setMediaMenuOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setMediaMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mediaMenuOpen]);

  const sendMessage = async (rawText: string) => {
    const value = rawText.trim();
    const currentImages = imagesRef.current;
    if (!value && currentImages.length === 0) return false;
    if (value.length > LIMITS.textInputChars) {
      toast(t("input.tooLong"), "error");
      return false;
    }
    let payload = currentImages.map((i) => i.payload);
    // 实况开着且没手动附图时，文字轮次也带一帧（对齐老前端）
    if (payload.length === 0 && camera.isLive) {
      const frame = await camera.grabImage().catch(() => null);
      if (frame) payload = [frame];
    }
    sendText(value, payload);
    currentImages.forEach((i) => URL.revokeObjectURL(i.preview));
    imageSlots.current = 0;
    setImages([]);
    setText("");
    return true;
  };

  const submit = async () => {
    await sendMessage(text);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  const onPaste = (e: React.ClipboardEvent) => {
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          void addImage(file, "clipboard", item.type);
        }
        return;
      }
    }
  };

  const onMicClick = async () => {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false;
      return;
    }
    if (pttPhase !== "idle") return;
    if (micOn) {
      mic.stop();
      return;
    }
    setMicStarting(true);
    await mic.start();
    setMicStarting(false);
  };

  const finishHoldRecording = async () => {
    const g = gestureRef.current;
    if (g.submitting) return;
    g.submitting = true;
    g.pointerId = null;
    g.holdTriggered = false;
    g.cancelIntent = false;

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
      const draft = textStateRef.current.trim();
      const combined = draft ? `${draft} ${transcript}` : transcript;
      if (combined.length > LIMITS.textInputChars) {
        setText(combined);
        toast(t("input.tooLong"), "error");
        return;
      }
      await sendMessage(combined);
    } catch (err) {
      if ((err as DOMException | null)?.name === "AbortError") return;
      toast(err instanceof Error ? err.message : t("error.generic"), "error");
    } finally {
      if (asrAbortRef.current === controller) asrAbortRef.current = null;
      g.submitting = false;
      setPttPhase("idle");
    }
  };

  const startHoldRecording = async () => {
    const g = gestureRef.current;
    if (g.pointerId === null) return;
    g.holdTriggered = true;
    g.holdTimer = null;
    suppressNextClickRef.current = true;

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

    if (!ok && gestureRef.current.holdTriggered && !gestureRef.current.submitting) {
      cancelHoldRecording();
    }
  };

  const onMicPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (micOn || micStarting || pttPhase !== "idle") return;
    if (mediaMenuOpen) setMediaMenuOpen(false);

    const g = gestureRef.current;
    if (g.holdTimer !== null) window.clearTimeout(g.holdTimer);
    suppressNextClickRef.current = false;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    g.pointerId = e.pointerId;
    g.startY = e.clientY;
    g.holdTriggered = false;
    g.cancelIntent = false;
    g.submitting = false;
    g.holdTimer = window.setTimeout(() => {
      void startHoldRecording();
    }, HOLD_DELAY_MS);
  };

  const onMicPointerMove = (e: React.PointerEvent<HTMLButtonElement>) => {
    const g = gestureRef.current;
    if (!g.holdTriggered || g.pointerId !== e.pointerId) return;
    const wantCancel = e.clientY - g.startY < -CANCEL_SLIDE_PX;
    if (wantCancel !== g.cancelIntent) {
      g.cancelIntent = wantCancel;
      setPttCancelIntent(wantCancel);
    }
  };

  const finishPointerGesture = (
    e: React.PointerEvent<HTMLButtonElement>,
    forceCancel: boolean,
  ) => {
    const g = gestureRef.current;
    if (g.pointerId !== e.pointerId) return;
    if (g.holdTimer !== null) {
      window.clearTimeout(g.holdTimer);
      g.holdTimer = null;
    }
    try {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    } catch {
      /* ignore */
    }

    if (!g.holdTriggered) {
      g.pointerId = null;
      return;
    }

    window.setTimeout(() => {
      suppressNextClickRef.current = false;
    }, 0);

    if (forceCancel || g.cancelIntent) {
      cancelHoldRecording();
      return;
    }
    void finishHoldRecording();
  };

  const thinkingName = thinking.active
    ? thinking.active.name ||
      t(`thinking.level.${thinking.active.id}`, {
        defaultValue: thinking.active.id,
      })
    : "";

  // 群聊中一轮未结束时禁发
  const sendDisabled = inGroup && busy;
  sendDisabledRef.current = sendDisabled;
  const hasContent = text.trim().length > 0 || images.length > 0;
  const isTranscribing = pttPhase === "transcribing";
  const micActiveVisual = micOn || pttHolding;

  return (
    <div className="input-bar" ref={barRef}>
      {/* 菜单挂在输入条外层：输入条自己有 backdrop-filter，嵌在里面的玻璃只能模糊到输入条本身 */}
      {mediaMenuPresence.mounted && (
        <div
          ref={menuRef}
          className={`media-menu composer-menu${mediaMenuPresence.closing ? " closing" : ""}`}
          role="menu"
        >
          <div className="composer-menu-group">
            <button
              role="menuitem"
              onClick={() => {
                setMediaMenuOpen(false);
                fileRef.current?.click();
              }}
            >
              <ImageIcon />
              <span>{t("input.sourceUpload")}</span>
            </button>
            <button role="menuitem" onClick={() => void grabAndAdd("camera")}>
              <CamIcon />
              <span>{t("input.sourceCamera")}</span>
            </button>
            <button role="menuitem" onClick={() => void grabAndAdd("screen")}>
              <ScreenShareIcon />
              <span>{t("input.sourceScreen")}</span>
            </button>
          </div>
          <ThinkingControls />
        </div>
      )}
      {images.length > 0 && (
        <div className="image-strip">
          {images.map((img) => (
            <div key={img.id} className="image-thumb">
              <img src={img.preview} alt="" width={60} height={60} />
              <button
                type="button"
                className="image-remove"
                aria-label={t("input.removeImage")}
                title={t("input.removeImage")}
                onClick={() => removeImage(img.id)}
              >
                <CloseIcon size={11} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div
        className={`input-row${hasContent ? " filled" : ""}${pttHolding ? " ptt-holding" : ""}${pttCancelIntent ? " ptt-cancel" : ""}${isTranscribing ? " ptt-transcribing" : ""}`}
      >
        <div className={`media-anchor${pttHolding ? " ptt-hidden" : ""}`} ref={anchorRef}>
          <button
            className={`icon-btn plus-btn${mediaMenuOpen ? " open" : ""}${thinking.on ? " thinking-on" : ""}`}
            title={
              thinking.on
                ? t("input.moreThinking", { name: thinkingName })
                : t("input.more")
            }
            aria-label={
              thinking.on
                ? t("input.moreThinking", { name: thinkingName })
                : t("input.more")
            }
            aria-haspopup="menu"
            aria-expanded={mediaMenuOpen}
            disabled={isTranscribing}
            onClick={() => setMediaMenuOpen((v) => !v)}
          >
            <AddIcon />
            {thinking.on && <span className="plus-badge" aria-hidden="true" />}
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          aria-label={t("input.uploadImage")}
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            // 超出的部分整批丢弃并只提示一次，不要每张多余的图各弹一条
            const room = Math.max(0, LIMITS.maxImages - imageSlots.current);
            if (files.length > room) toast(t("input.imageTooMany"), "error");
            for (const f of files.slice(0, room))
              void addImage(f, "upload", f.type || "image/png");
            e.target.value = "";
          }}
        />
        <textarea
          ref={textRef}
          className={`input-text${pttHolding ? " ptt-hidden" : ""}`}
          name="message"
          rows={1}
          value={text}
          disabled={isTranscribing}
          placeholder={
            isTranscribing ? t("input.pttTranscribing") : t("input.placeholder")
          }
          aria-label={t("input.message")}
          autoComplete="off"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
        />
        {pttHolding && (
          <div className="ptt-bar" aria-live="polite">
            <div className="ptt-timer">
              <span className="ptt-dot" aria-hidden="true" />
              <span>{formatDuration(pttSeconds)}</span>
            </div>
            <div className="ptt-waves" aria-hidden="true">
              {pttBars.map((level, idx) => (
                <i
                  key={idx}
                  style={{
                    transform: `scaleY(${pttCancelIntent ? 0.16 : level})`,
                  }}
                />
              ))}
            </div>
            <span className="ptt-hint">
              {pttPhase === "arming"
                ? t("input.pttArming")
                : pttCancelIntent
                  ? t("input.pttReleaseToCancel")
                  : t("input.pttReleaseToSend")}
            </span>
          </div>
        )}
        <button
          className={`icon-btn mic-btn${micActiveVisual ? " active" : ""}${pttHolding ? " ptt-live" : ""}${pttCancelIntent ? " ptt-cancel" : ""}`}
          title={micOn ? t("input.micOn") : t("input.micOff")}
          aria-label={micOn ? t("input.micOn") : t("input.micOff")}
          disabled={micStarting || isTranscribing}
          onClick={() => void onMicClick()}
          onPointerDown={onMicPointerDown}
          onPointerMove={onMicPointerMove}
          onPointerUp={(e) => finishPointerGesture(e, false)}
          onPointerCancel={(e) => finishPointerGesture(e, true)}
          onLostPointerCapture={(e) => finishPointerGesture(e, true)}
          onContextMenu={(e) => e.preventDefault()}
        >
          {micStarting || isTranscribing ? (
            <span className="spinner" />
          ) : (
            <MicIcon on={micActiveVisual} />
          )}
        </button>
        {!pttHolding &&
          (busy ? (
            <button
              className="icon-btn stop-btn"
              title={t("input.stop")}
              aria-label={t("input.stop")}
              onClick={interrupt}
            >
              <StopIcon />
            </button>
          ) : (
            <button
              className="icon-btn send-btn"
              title={t("input.send")}
              aria-label={t("input.send")}
              disabled={
                sendDisabled ||
                isTranscribing ||
                (!text.trim() && images.length === 0)
              }
              onClick={() => void submit()}
            >
              <SendIcon />
            </button>
          ))}
      </div>
    </div>
  );
}
