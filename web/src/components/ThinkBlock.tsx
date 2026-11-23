import {
  lazy,
  memo,
  Suspense,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

const MarkdownText = lazy(() => import("./MarkdownText"));

// 和工具卡一样：完成到收起之间留一拍
const HOLD_MS = 420;

// 思考卡与工具卡同构：独立一块消息面板，思考中展开并跟随最新内容，
// 思考结束自动收起；手动点过之后就不再自动开合。正文按 markdown 渲染。
export const ThinkBlock = memo(function ThinkBlock({
  text,
  active = false,
}: {
  text: string;
  active?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(active);
  const wasActive = useRef(active);
  const touched = useRef(false);
  const holdTimer = useRef(0);
  const startedAt = useRef<number | null>(active ? Date.now() : null);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [settled, setSettled] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  useEffect(() => {
    if (active && !wasActive.current) {
      startedAt.current ??= Date.now();
      setSettled(false);
      if (!touched.current) setOpen(true);
    }
    if (wasActive.current && !active) {
      setSettled(true);
      if (startedAt.current !== null) {
        setSeconds(
          Math.max(1, Math.round((Date.now() - startedAt.current) / 1000)),
        );
      }
      if (!touched.current) {
        holdTimer.current = window.setTimeout(() => setOpen(false), HOLD_MS);
      }
    }
    wasActive.current = active;
    return () => window.clearTimeout(holdTimer.current);
  }, [active]);

  // 思考中跟随最新内容；用户往上翻就不再跟随
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (active && el && follow.current) el.scrollTop = el.scrollHeight;
  }, [text, active]);

  const onScroll = () => {
    const el = bodyRef.current;
    if (el && active)
      follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 12;
  };

  const toggle = () => {
    touched.current = true;
    window.clearTimeout(holdTimer.current);
    setOpen((v) => !v);
  };

  const status = active
    ? t("think.active")
    : seconds !== null
      ? t("think.done", { seconds })
      : t("tool.completed");
  const body = text.trim();

  return (
    <div
      className={`tool-card think-card${active ? " status-running" : settled ? " status-completed" : ""}`}
    >
      <button
        className="tool-head"
        aria-expanded={open}
        aria-busy={active}
        onClick={toggle}
      >
        <span
          className={`think-mark${active ? " active" : settled ? " done" : ""}`}
          aria-hidden="true"
        />
        <span className="tool-name think-name">{t("think.title")}</span>
        <span className="tool-status">
          <span className="tool-status-text" key={status}>
            {status}
          </span>
          {active && (
            <span className="think-live" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          )}
        </span>
        <span className="think-chevron">▸</span>
      </button>
      <div className={`collapsible${open ? " open" : ""}`} aria-hidden={!open}>
        <div className="collapsible-inner">
          <div
            ref={bodyRef}
            className="think-body bubble-text"
            onScroll={onScroll}
          >
            <Suspense fallback={<span className="md-pending">{body}</span>}>
              <MarkdownText text={body} />
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  );
});
