import { useTranslation } from "react-i18next";
import type { PttPhase } from "../hooks/usePttGesture";

function formatDuration(totalSeconds: number): string {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

interface PttBarProps {
  phase: PttPhase;
  cancelIntent: boolean;
  seconds: number;
  bars: number[];
}

export function PttBar({ phase, cancelIntent, seconds, bars }: PttBarProps) {
  const { t } = useTranslation();

  return (
    <div className="ptt-bar" aria-live="polite">
      <div className="ptt-timer">
        {phase === "arming" ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <>
            <span className="ptt-dot" aria-hidden="true" />
            <span>{formatDuration(seconds)}</span>
          </>
        )}
      </div>
      <div className="ptt-waves" aria-hidden="true">
        {bars.map((level, idx) => (
          <i
            key={idx}
            style={{
              transform: `scaleY(${cancelIntent ? 0.16 : level})`,
            }}
          />
        ))}
      </div>
      <span
        key={cancelIntent ? "cancel" : phase}
        className="ptt-hint"
      >
        {cancelIntent
          ? t("input.pttReleaseToCancel")
          : phase === "arming"
            ? t("input.pttArming")
            : t("input.pttReleaseToSend")}
      </span>
    </div>
  );
}
