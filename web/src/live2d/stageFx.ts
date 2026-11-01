// 舞台声光：把口型音量写成光晕节点上的一个 CSS 变量。
// 只改这一个节点的内联样式，不碰 .app，避免每帧整树样式重算；
// 量化到 1/20 再写，静音或音量平稳时不产生任何 DOM 写入。
let halo: HTMLElement | null = null;
let last = -1;

export function bindVoiceHalo(node: HTMLElement | null) {
  halo = node;
  last = -1;
}

export function setVoiceLevel(v: number) {
  if (!halo) return;
  const q = Math.round(Math.max(0, Math.min(1, v)) * 20) / 20;
  if (q === last) return;
  last = q;
  halo.style.setProperty('--voice', String(q));
  halo.classList.toggle('speaking', q > 0);
}
