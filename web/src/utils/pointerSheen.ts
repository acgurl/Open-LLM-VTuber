// 玻璃面受光：指针经过消息卡、输入条、设置分区时，在指针处亮起一小团柔光。
// 全局只挂一个 pointermove 监听，按帧合并，只给当前命中的那一块写两个 CSS 变量；
// 触屏和 reduced-motion 下不安装。
const TARGETS = '.bubble, .tool-card, .input-row, .drawer-body section';

export function installPointerSheen() {
  if (typeof window === 'undefined' || !window.matchMedia) return;
  if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let current: HTMLElement | null = null;
  let frame = 0;
  let lastX = 0;
  let lastY = 0;
  let lastTarget: EventTarget | null = null;

  const release = () => {
    current?.classList.remove('sheen-on');
    current = null;
  };

  const apply = () => {
    frame = 0;
    const el =
      lastTarget instanceof Element ? (lastTarget.closest(TARGETS) as HTMLElement | null) : null;
    if (el !== current) {
      release();
      if (el) {
        el.classList.add('sheen-on');
        current = el;
      }
    }
    if (!current) return;
    const r = current.getBoundingClientRect();
    current.style.setProperty('--mx', `${lastX - r.left}px`);
    current.style.setProperty('--my', `${lastY - r.top}px`);
  };

  window.addEventListener(
    'pointermove',
    (e) => {
      if (e.pointerType !== 'mouse') return;
      lastX = e.clientX;
      lastY = e.clientY;
      lastTarget = e.target;
      if (!frame) frame = window.requestAnimationFrame(apply);
    },
    { passive: true },
  );
  document.documentElement.addEventListener('pointerleave', release);
  window.addEventListener('blur', release);
}
