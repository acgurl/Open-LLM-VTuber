import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useModels } from "../stores/models";
import { setThinking } from "../services/actions";
import type { ThinkingLevel } from "../protocol/types";
import { BulbIcon } from "./icons";

// 这些档位 id 表示“不思考”
const OFF_IDS = new Set(["off", "none"]);
export const isOffLevel = (id: string | null) => id === null || OFF_IDS.has(id);

// 当前模型的思考档位信息。adjustable 为 false 时按钮仍显示，但锁定不可点：
// 只有一档（始终思考 / 不支持思考），或模型没声明档位（角色预设的 LLM 也算这种）。
export function useThinking() {
  const { options: models, current } = useModels((s) => s.catalogs.llm);
  const level = useModels((s) => s.thinking);
  const switching = useModels((s) => s.pending?.kind === 'llm');
  const lastOn = useModels((s) => s.lastThinkingOn);
  const info = models.find((m) => m.id === current)?.thinking;
  const levels = info?.levels ?? [];
  const active =
    levels.find((l) => l.id === level) ??
    levels.find((l) => l.id === info?.default) ??
    levels[0] ??
    null;
  const offLevel = levels.find((l) => isOffLevel(l.id)) ?? null;
  const onLevels = levels.filter((l) => !isOffLevel(l.id));
  return {
    adjustable: levels.length > 1,
    known: levels.length > 0,
    modelId: current,
    active,
    on: active !== null && !isOffLevel(active.id),
    offLevel,
    onLevels,
    lastOn: current ? lastOn[current] : undefined,
    switching,
  };
}

// 强度分段：选中块在档位之间弹性滑动（同设置里的分段控件），宽度跟随文字
function LevelPicker({
  levels,
  activeId,
  open,
  disabled,
  label,
  name,
}: {
  levels: ThinkingLevel[];
  activeId: string;
  open: boolean;
  disabled: boolean;
  label: string;
  name: (l: ThinkingLevel) => string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null);
  const index = levels.findIndex((l) => l.id === activeId);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const measure = () => {
      const btn = root.querySelectorAll<HTMLElement>(".thinking-level")[index];
      setThumb(btn ? { x: btn.offsetLeft, w: btn.offsetWidth } : null);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => ro.disconnect();
  }, [index, levels]);

  const pick = (i: number) => {
    const l = levels[(i + levels.length) % levels.length];
    if (l) setThinking(l.id);
    return l;
  };

  return (
    // 收起时用 grid 0fr→1fr 过渡高度，菜单整体跟着平滑长高/变矮
    <div
      className={`thinking-levels-wrap${open ? " open" : ""}`}
      aria-hidden={!open || undefined}
    >
      <div className="thinking-levels-clip">
        <div
          ref={rootRef}
          className="thinking-levels"
          role="radiogroup"
          aria-label={label}
          onKeyDown={(e) => {
            let next = index;
            if (e.key === "ArrowRight") next = index + 1;
            else if (e.key === "ArrowLeft") next = index - 1;
            else return;
            e.preventDefault();
            if (!disabled) pick(next);
            const btns =
              rootRef.current?.querySelectorAll<HTMLElement>(".thinking-level");
            btns?.[(next + levels.length) % levels.length]?.focus();
          }}
        >
          {thumb && index >= 0 && (
            <span
              className="thinking-level-thumb"
              aria-hidden="true"
              style={{ transform: `translateX(${thumb.x}px)`, width: thumb.w }}
            />
          )}
          {levels.map((l, i) => {
            const selected = i === index;
            return (
              <button
                key={l.id}
                type="button"
                role="radio"
                aria-checked={selected}
                tabIndex={selected && open ? 0 : -1}
                className={`thinking-level${selected ? " selected" : ""}`}
                disabled={disabled || !open}
                onClick={() => pick(i)}
              >
                {name(l)}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// 加号菜单里的思考区：一行开关 + 开启后展开的强度分段。
// 不可调整的模型也显示这一行，开关置灰并上锁，说明为什么不能改。
export function ThinkingControls() {
  const { t } = useTranslation();
  const {
    adjustable,
    known,
    active,
    on,
    offLevel,
    onLevels,
    lastOn,
    switching,
  } = useThinking();

  const name = (l: ThinkingLevel) =>
    l.name || t(`thinking.level.${l.id}`, { defaultValue: l.id });
  // 有“不思考”档才能开关；只有几档强度时开关恒亮且锁定，只调强度
  const canToggle = adjustable && offLevel !== null && onLevels.length > 0;
  const locked = !canToggle;

  const toggle = () => {
    if (locked) return;
    if (on) {
      if (offLevel) setThinking(offLevel.id);
      return;
    }
    // 打开时回到上次用过的强度，没有就用最轻的一档
    const target = onLevels.find((l) => l.id === lastOn) ?? onLevels[0];
    if (target) setThinking(target.id);
  };

  let desc: string;
  if (!known) desc = t("thinking.descUnknown");
  else if (!adjustable)
    desc = on ? t("thinking.descAlways") : t("thinking.descUnsupported");
  else if (!canToggle) desc = t("thinking.descAlwaysPick");
  else desc = on ? t("thinking.descOn") : t("thinking.descOff");

  const showLevels = adjustable && onLevels.length > 1;

  return (
    <div
      className={`thinking-section${on ? " on" : ""}${locked ? " locked" : ""}`}
    >
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-disabled={locked || undefined}
        className="thinking-row"
        disabled={switching}
        title={locked ? desc : undefined}
        onClick={toggle}
      >
        <span className="thinking-row-icon">
          <BulbIcon lit={on} />
        </span>
        <span className="thinking-row-text">
          <span className="thinking-row-title">
            {t("thinking.label")}
            {active && on && !showLevels && (
              <em className="thinking-row-level">{name(active)}</em>
            )}
          </span>
          <span className="thinking-row-desc">{desc}</span>
        </span>
        <span className="thinking-switch" aria-hidden="true">
          <i>
            {locked && (
              <svg viewBox="0 0 12 12" width="9" height="9">
                <path
                  d="M3.6 5.4V4a2.4 2.4 0 0 1 4.8 0v1.4M3 5.4h6v4.2H3z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.3"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </i>
        </span>
      </button>
      {showLevels && active && (
        <LevelPicker
          levels={onLevels}
          activeId={active.id}
          open={on}
          disabled={switching}
          label={t("thinking.title")}
          name={name}
        />
      )}
    </div>
  );
}
