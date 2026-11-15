// 玻璃面受光：指针经过任一块玻璃面（消息卡、输入条与其弹出菜单、顶栏小岛与模型菜单、
// 图标按钮、摄像头窗、提示条、推荐问题、历史条目、设置分区）时，在指针处亮起一小团柔光。
// 全局只挂一个 pointermove 监听，按帧合并，只给当前命中的最内层那一块写两个 CSS 变量；
// 触屏和 reduced-motion 下不安装。新加玻璃面时：这里登记选择器，CSS 背景最上层叠
// radial-gradient(... at var(--mx) var(--my), var(--sheen-spot), ...) 并给 --sheen-spot 加过渡。
// 输入条里的透明图标按钮、抽屉头的关闭钮不算独立玻璃面，排除掉，让光斑留在外层。
const TARGETS = [
  '.bubble',
  '.tool-card',
  '.composer-menu',
  '.input-row',
  '.drawer-body section',
  '.history-item',
  '.topbar-center',
  '.model-pill',
  '.model-menu',
  '.icon-btn:not(.input-row .icon-btn, .drawer-head .icon-btn)',
  '.cam-window',
  '.toast',
  '.starter-chip',
  '.scroll-jump',
].join(', ');

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
