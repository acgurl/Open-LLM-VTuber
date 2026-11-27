import { memo, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../stores/chat';
import { useSettings } from '../stores/settings';

// 完成到收起之间留一拍，先让结果被看见，也让上面的收光单独播完
const HOLD_MS = 420;

// 调用中展开结果预览；默认不自动收起，开启「自动折叠工具调用卡片」后才在结束时收起；手动点过之后不再自动开合
export const ToolCallCard = memo(function ToolCallCard({ entry }: { entry: ToolEntry }) {
  const { t } = useTranslation();
  const autoCollapse = useSettings((s) => s.autoCollapseToolCards);
  const [open, setOpen] = useState(() => entry.status === 'running' || !autoCollapse);
  const wasRunning = useRef(entry.status === 'running');
  const prevAutoCollapse = useRef(autoCollapse);
  const touched = useRef(false);
  const holdTimer = useRef(0);

  useEffect(() => {
    window.clearTimeout(holdTimer.current);
    const running = entry.status === 'running';
    if (!touched.current) {
      if (running) {
        setOpen(true);
      } else if (wasRunning.current) {
        if (autoCollapse) {
          holdTimer.current = window.setTimeout(() => setOpen(false), HOLD_MS);
        } else {
          setOpen(true);
        }
      } else if (prevAutoCollapse.current !== autoCollapse) {
        setOpen(!autoCollapse);
      }
    }
    wasRunning.current = running;
    prevAutoCollapse.current = autoCollapse;
    return () => window.clearTimeout(holdTimer.current);
  }, [entry.status, autoCollapse]);

  const toggle = () => {
    touched.current = true;
    window.clearTimeout(holdTimer.current);
    setOpen((v) => !v);
  };

  return (
    <div className={`tool-card status-${entry.status}`}>
      <button className="tool-head" aria-expanded={open} onClick={toggle}>
        <span className={`tool-dot ${entry.status}`} />
        <span className="tool-name">{entry.tool_name}</span>
        <span className="tool-status">
          <span className="tool-status-text" key={entry.status}>
            {t(`tool.${entry.status}`)}
          </span>
        </span>
        <span className="think-chevron">▸</span>
      </button>
      <div className={`collapsible${open ? ' open' : ''}`} aria-hidden={!open}>
        <div className="collapsible-inner">
          <pre className="tool-body">{entry.content}</pre>
        </div>
      </div>
    </div>
  );
});
