import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LIMITS, type ImagePayload, type ImageSource } from "../protocol/types";
import { camera } from "../services/camera";
import { toast } from "../stores/toast";
import { fileToBase64 } from "../utils/base64";
import { captureCamera, captureScreen } from "../utils/capture";

export interface PendingImage {
  id: number;
  payload: ImagePayload;
  preview: string;
}

let imageSeq = 0;

export function usePendingImages() {
  const { t } = useTranslation();
  const [images, setImages] = useState<PendingImage[]>([]);
  // 已占用的附图名额：多张图并发编码时 images 状态还没更新，靠它同步计数才能守住上限
  const imageSlots = useRef(0);
  const imagesRef = useRef<PendingImage[]>([]);
  imagesRef.current = images;

  useEffect(() => {
    return () => {
      imagesRef.current.forEach((img) => URL.revokeObjectURL(img.preview));
    };
  }, []);

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

  const addUploadedFiles = (files: File[]) => {
    // 超出的部分整批丢弃并只提示一次，不要每张多余的图各弹一条
    const room = Math.max(0, LIMITS.maxImages - imageSlots.current);
    if (files.length > room) toast(t("input.imageTooMany"), "error");
    for (const file of files.slice(0, room)) {
      void addImage(file, "upload", file.type || "image/png");
    }
  };

  const removeImage = (id: number) => {
    imageSlots.current = Math.max(0, imageSlots.current - 1);
    setImages((prev) => {
      const target = prev.find((img) => img.id === id);
      if (target) URL.revokeObjectURL(target.preview);
      return prev.filter((img) => img.id !== id);
    });
  };

  const grabAndAdd = async (source: "camera" | "screen") => {
    try {
      // 实况窗口开着就直接从常驻流抓帧，免得二次开摄像头
      const blob =
        source === "camera"
          ? camera.isLive
            ? await camera.grabBlob()
            : await captureCamera()
          : await captureScreen();
      if (blob) await addImage(blob, source, "image/jpeg");
    } catch {
      toast(t("error.generic"), "error");
    }
  };

  const clearImages = () => {
    imagesRef.current.forEach((img) => URL.revokeObjectURL(img.preview));
    imageSlots.current = 0;
    setImages([]);
  };

  return {
    images,
    imagesRef,
    addImage,
    addUploadedFiles,
    removeImage,
    grabAndAdd,
    clearImages,
  };
}
