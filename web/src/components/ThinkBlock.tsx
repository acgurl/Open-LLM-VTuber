import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

// 三种形态：
// - preview：正在思考时只露出几行的小窗，自动滚到最新一行（用户往上翻就不再跟随）
// - closed：思考结束自动收起成一行标题，历史消息默认也是这样
// - open：点标题展开全文；手动点过之后不再自动收起
type Mode = 'preview' | 'closed' | 'open';

export const ThinkBlock = memo(function ThinkBlock({
  text,
  active = false,
}: {
  text: string;
  active?: boolean;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>(active ? 'preview' : 'closed');
  const touched = useRef(false);
  const wasActive = useRef(active);
  const startedAt = useRef<number | null>(active ? Date.now() : null);
  const [seconds, setSeconds] = useState<number | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  useEffect(() => {
    if (active && !wasActive.current) {
      startedAt.current ??= Date.now();
      if (!touched.current) setMode('preview');
    }
    if (wasActive.current && !active) {
      if (startedAt.current !== null) {
        setSeconds(Math.max(1, Math.round((Date.now() - startedAt.current) / 1000)));
      }
      if (!touched.current) setMode('closed');
    }
    wasActive.current = active;
  }, [active]);

  // 预览小窗跟随最新内容
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (mode === 'preview' && el && follow.current) el.scrollTop = el.scrollHeight;
  }, [text, mode]);

  const onScroll = () => {
    const el = bodyRef.current;
    if (el && mode === 'preview') {
      follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 12;
    }
  };

  const label = active
    ? t('think.active')
    : seconds !== null
      ? t('think.done', { seconds })
      : t('think.label');
  const expanded = mode !== 'closed';

  return (
    <div className={`think-block ${mode}${active ? ' active' : ''}`}>
      <button
        className="think-toggle"
        aria-expanded={mode === 'open'}
        aria-busy={active}
        onClick={() => {
          touched.current = true;
          setMode((m) => (m === 'open' ? 'closed' : 'open'));
        }}
      >
        <span className="think-chevron">▸</span>
        {label}
        {active && (
          <span className="think-live" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        )}
      </button>
      <div className={`collapsible${expanded ? ' open' : ''}`} aria-hidden={!expanded}>
        <div className="collapsible-inner">
          <div ref={bodyRef} className="think-body" onScroll={onScroll}>
            {text.trim()}
          </div>
        </div>
      </div>
    </div>
  );
});
