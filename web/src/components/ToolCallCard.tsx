import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../stores/chat';

// 调用中展开结果预览，执行结束后自动收起；手动展开后保持用户选择
export function ToolCallCard({ entry }: { entry: ToolEntry }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(entry.status === 'running');
  const wasRunning = useRef(entry.status === 'running');

  useEffect(() => {
    const running = entry.status === 'running';
    if (wasRunning.current && !running) setOpen(false);
    wasRunning.current = running;
  }, [entry.status]);

  return (
    <div className={`tool-card status-${entry.status}`}>
      <button className="tool-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
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
}
