import type { ModelInfo } from '../protocol/types';
import { storageKey } from '../utils/storage';

// 上次的模型配置仅用于首屏秒开，服务端 set-model-and-conf 仍是最终来源。
// Key is per-account so a shared browser does not warm-start another user's model.
const KEY = storageKey('model');
// 解析后的贴图地址，供 index.html 的内联脚本提前 preload（与主包并行下载）。
const ASSET_KEY = storageKey('model.assets');

export function loadCachedModel(): ModelInfo | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ModelInfo;
    return typeof parsed?.url === 'string' && parsed.url ? parsed : null;
  } catch {
    return null;
  }
}

export function saveCachedModel(info: ModelInfo | null | undefined) {
  try {
    if (info?.url) localStorage.setItem(KEY, JSON.stringify(info));
    else localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

// model3.json 的 Textures 只在首次加载后解析一次；地址是相对 model3 的。
export async function cacheModelAssets(modelUrl: string): Promise<void> {
  try {
    const settingsUrl = new URL(modelUrl, location.href);
    const res = await fetch(settingsUrl.href, { cache: 'force-cache' });
    if (!res.ok) return;
    const json = (await res.json()) as { FileReferences?: { Textures?: unknown } };
    const textures = json?.FileReferences?.Textures;
    if (!Array.isArray(textures)) return;
    const images = textures
      .filter((t): t is string => typeof t === 'string' && t.length > 0)
      .map((t) => {
        const url = new URL(t, settingsUrl);
        return url.pathname + url.search;
      })
      .slice(0, 8);
    if (images.length === 0) return;
    localStorage.setItem(ASSET_KEY, JSON.stringify({ url: modelUrl, images }));
  } catch {
    /* 预加载是锦上添花，失败不影响正常加载 */
  }
}
