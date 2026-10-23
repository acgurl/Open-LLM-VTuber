import type { ModelInfo } from '../protocol/types';

const KEY = 'ollmvt.model';

// 上次的模型配置仅用于首屏秒开，服务端 set-model-and-conf 仍是最终来源。
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
