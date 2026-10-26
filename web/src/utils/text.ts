import type { ModelInfo } from '../protocol/types';

export function buildTagSet(model: ModelInfo | null | undefined): Set<string> {
  const set = new Set<string>();
  if (!model) return set;
  for (const k of Object.keys(model.emotionMap ?? {})) set.add(k.toLowerCase());
  for (const k of Object.keys(model.motionMap ?? {})) set.add(k.toLowerCase());
  return set;
}

export interface TextToken {
  kind: 'text' | 'tag';
  value: string;
}

// 把 display/流式文本中的 [joy] 这类 Live2D 标签拆出来（大小写不敏感）。
// 未知方括号内容保留为普通文本。
export function splitByTags(text: string, tagSet: Set<string>): TextToken[] {
  if (!text) return [];
  if (tagSet.size === 0) return [{ kind: 'text', value: text }];
  const out: TextToken[] = [];
  const re = /\[([^\[\]]{1,32})\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const key = m[1].trim().toLowerCase();
    if (!tagSet.has(key)) continue;
    if (m.index > last) out.push({ kind: 'text', value: text.slice(last, m.index) });
    out.push({ kind: 'tag', value: key });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'text', value: text.slice(last) });
  return out;
}

export function stripTags(text: string, tagSet: Set<string>): string {
  return splitByTags(text, tagSet)
    .filter((t) => t.kind === 'text')
    .map((t) => t.value)
    .join('')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

export interface ThinkBlock {
  kind: 'normal' | 'think';
  text: string;
  // think 块是否已遇到 </think>；流式期间未闭合的块仍在生成
  closed?: boolean;
}

export function splitThink(text: string): ThinkBlock[] {
  const out: ThinkBlock[] = [];
  const re = /<\/?think>/gi;
  let last = 0;
  let inThink = false;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const seg = text.slice(last, m.index);
    if (seg) {
      out.push(inThink ? { kind: 'think', text: seg, closed: true } : { kind: 'normal', text: seg });
    }
    inThink = m[0].toLowerCase() === '<think>';
    last = m.index + m[0].length;
  }
  const tail = text.slice(last);
  if (tail) {
    out.push(inThink ? { kind: 'think', text: tail, closed: false } : { kind: 'normal', text: tail });
  }
  return out;
}

export function backgroundUrl(file: string): string {
  return `/bg/${file}`;
}

export function cacheUrl(audioPath: string): string {
  const base = audioPath.split(/[\\/]/).pop() ?? audioPath;
  return `/cache/${base}`;
}
