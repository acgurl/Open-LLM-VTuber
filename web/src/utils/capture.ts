export async function captureCamera(): Promise<Blob | null> {
  const stream = await navigator.mediaDevices.getUserMedia({ video: true });
  try {
    return await grabFrame(stream, 500);
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

export async function captureScreen(): Promise<Blob | null> {
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
  try {
    return await grabFrame(stream, 700);
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

async function grabFrame(stream: MediaStream, warmupMs: number): Promise<Blob | null> {
  const video = document.createElement('video');
  video.srcObject = stream;
  video.muted = true;
  await video.play();
  await sleep(warmupMs);
  return drawToJpeg(video, Infinity, 0.85);
}

/** Draw the current video frame to a JPEG, downscaled to at most `maxWidth` px wide. */
export function drawToJpeg(
  video: HTMLVideoElement,
  maxWidth: number,
  quality: number,
): Promise<Blob | null> {
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return Promise.resolve(null);
  const scale = Math.min(1, maxWidth / w);
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.resolve(null);
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
