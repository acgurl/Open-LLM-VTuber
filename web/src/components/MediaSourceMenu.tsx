import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { CamIcon, ImageIcon, ScreenShareIcon } from "./icons";
import { ThinkingControls } from "./ThinkingControls";

interface MediaSourceMenuProps {
  closing: boolean;
  onUpload: () => void;
  onCapture: (source: "camera" | "screen") => void;
}

export const MediaSourceMenu = forwardRef<HTMLDivElement, MediaSourceMenuProps>(
  function MediaSourceMenu({ closing, onUpload, onCapture }, ref) {
    const { t } = useTranslation();

    return (
      <div
        ref={ref}
        className={`media-menu composer-menu${closing ? " closing" : ""}`}
        role="menu"
      >
        <div className="composer-menu-group">
          <button role="menuitem" onClick={onUpload}>
            <ImageIcon />
            <span>{t("input.sourceUpload")}</span>
          </button>
          <button role="menuitem" onClick={() => onCapture("camera")}>
            <CamIcon />
            <span>{t("input.sourceCamera")}</span>
          </button>
          <button role="menuitem" onClick={() => onCapture("screen")}>
            <ScreenShareIcon />
            <span>{t("input.sourceScreen")}</span>
          </button>
        </div>
        <ThinkingControls />
      </div>
    );
  },
);
