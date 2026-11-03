// 舞台声光：把口型音量写成光晕节点上的一个 CSS 变量。
// 只改这一个节点的内联样式，不碰 .app，避免每帧整树样式重算；
// 量化到 1/20 再写，静音或音量平稳时不产生任何 DOM 写入。
let halo: HTMLElement | null = null;
let last = -1;

export function bindVoiceHalo(node: HTMLElement | null) {
  halo = node;
  last = -1;
  lastX = NaN;
}

// 背光跟着人物的取景中心走（聊天列让位、拖拽都会移动人物），按整像素写，不变不写
let lastX = NaN;

export function setStageCenter(x: number) {
  if (!halo) return;
  const px = Math.round(x);
  if (px === lastX) return;
  lastX = px;
  halo.style.setProperty('--stage-x', `${px}px`);
}

export function setVoiceLevel(v: number) {
  if (!halo) return;
  const q = Math.round(Math.max(0, Math.min(1, v)) * 20) / 20;
  if (q === last) return;
  last = q;
  halo.style.setProperty('--voice', String(q));
  halo.classList.toggle('speaking', q > 0);
}
