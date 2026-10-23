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
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return null;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
