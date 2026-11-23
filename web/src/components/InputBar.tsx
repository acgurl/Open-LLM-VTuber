import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePendingImages } from "../hooks/usePendingImages";
import { usePresence } from "../hooks/usePresence";
import { usePttGesture } from "../hooks/usePttGesture";
import { LIMITS } from "../protocol/types";
import { interrupt, sendText } from "../services/actions";
import { camera } from "../services/camera";
import { useConnection } from "../stores/connection";
import { useGroup } from "../stores/group";
import { toast } from "../stores/toast";
import { AddIcon, CloseIcon, SendIcon, StopIcon } from "./icons";
import { MediaSourceMenu } from "./MediaSourceMenu";
import { PttBar } from "./PttBar";
import { useThinking } from "./ThinkingControls";

export function InputBar() {
  const { t } = useTranslation();
  const busy = useConnection((s) => s.busy);
  const inGroup = useGroup((s) => s.members.length > 1);
  const [text, setText] = useState("");
  const [mediaMenuOpen, setMediaMenuOpen] = useState(false);

  const mediaMenuPresence = usePresence(mediaMenuOpen, 150);
  const thinking = useThinking();
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const {
    images,
    imagesRef,
    addImage,
    addUploadedFiles,
    removeImage,
    grabAndAdd,
    clearImages,
  } = usePendingImages();

  const hasTextRef = useRef(false);
  hasTextRef.current = text.trim().length > 0;
  const mediaMenuOpenRef = useRef(false);
  mediaMenuOpenRef.current = mediaMenuOpen;
  const sendDisabledRef = useRef(false);

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
    clearImages();
    setText("");
    return true;
  };

  const {
    pttPhase,
    pttHolding,
    pttCancelIntent,
    pttSeconds,
    pttBars,
    rowHandlers,
  } = usePttGesture({
    rowRef,
    textRef,
    hasTextRef,
    sendDisabledRef,
    onBeforeStartGesture: () => {
      if (mediaMenuOpenRef.current) setMediaMenuOpen(false);
    },
    onTranscriptReady: async (transcript) => {
      await sendMessage(transcript);
    },
    onTranscriptTooLong: (transcript) => {
      setText(transcript);
      toast(t("input.tooLong"), "error");
    },
  });

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

  // 来源菜单：点菜单外或按 Esc 收起
  useEffect(() => {
    if (!mediaMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (
        !anchorRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        setMediaMenuOpen(false);
      }
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

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void sendMessage(text);
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

  const thinkingName = thinking.active
    ? thinking.active.name ||
      t(`thinking.level.${thinking.active.id}`, {
        defaultValue: thinking.active.id,
      })
    : "";

  // 群聊中一轮未结束时禁发
  const sendDisabled = inGroup && busy;
  sendDisabledRef.current = sendDisabled;
  const hasText = text.trim().length > 0;
  const hasContent = hasText || images.length > 0;
  const pttReady = !hasText && pttPhase === "idle";
  const isTranscribing = pttPhase === "transcribing";

  return (
    <div className="input-bar" ref={barRef}>
      {/* 菜单挂在输入条外层：输入条自己有 backdrop-filter，嵌在里面的玻璃只能模糊到输入条本身 */}
      {mediaMenuPresence.mounted && (
        <MediaSourceMenu
          ref={menuRef}
          closing={mediaMenuPresence.closing}
          onUpload={() => {
            setMediaMenuOpen(false);
            fileRef.current?.click();
          }}
          onCapture={(source) => {
            setMediaMenuOpen(false);
            void grabAndAdd(source);
          }}
        />
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
        ref={rowRef}
        className={`input-row${hasContent ? " filled" : ""}${pttReady ? " ptt-ready" : ""}${pttHolding ? " ptt-holding" : ""}${pttPhase === "arming" ? " ptt-arming" : ""}${pttCancelIntent ? " ptt-cancel" : ""}${isTranscribing ? " ptt-transcribing" : ""}`}
        {...rowHandlers}
      >
        <div
          className={`media-anchor${pttHolding ? " ptt-hidden" : ""}`}
          ref={anchorRef}
        >
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
            addUploadedFiles(Array.from(e.target.files ?? []));
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
          <PttBar
            phase={pttPhase}
            cancelIntent={pttCancelIntent}
            seconds={pttSeconds}
            bars={pttBars}
          />
        )}
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
              title={isTranscribing ? t("input.pttTranscribing") : t("input.send")}
              aria-label={
                isTranscribing ? t("input.pttTranscribing") : t("input.send")
              }
              disabled={
                sendDisabled ||
                isTranscribing ||
                (!text.trim() && images.length === 0)
              }
              onClick={() => void sendMessage(text)}
            >
              {isTranscribing ? <span className="spinner" /> : <SendIcon />}
            </button>
          ))}
      </div>
    </div>
  );
}
