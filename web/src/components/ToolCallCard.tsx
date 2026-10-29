import { memo, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../stores/chat';

// 完成到收起之间留一拍，先让结果被看见，也让上面的收光单独播完
const HOLD_MS = 420;

// 调用中展开结果预览，执行结束后自动收起；手动点过之后就不再自动收起
export const ToolCallCard = memo(function ToolCallCard({ entry }: { entry: ToolEntry }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(entry.status === 'running');
  const wasRunning = useRef(entry.status === 'running');
  const touched = useRef(false);
  const holdTimer = useRef(0);

  useEffect(() => {
    const running = entry.status === 'running';
    if (wasRunning.current && !running && !touched.current) {
      holdTimer.current = window.setTimeout(() => setOpen(false), HOLD_MS);
    }
    wasRunning.current = running;
    return () => window.clearTimeout(holdTimer.current);
  }, [entry.status]);

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
        <span className="tool-status">{t(`tool.${entry.status}`)}</span>
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
