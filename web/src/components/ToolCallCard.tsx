import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ToolEntry } from '../stores/chat';

export function ToolCallCard({ entry }: { entry: ToolEntry }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(entry.status === 'running');
  return (
    <div className={`tool-card status-${entry.status}`}>
      <button className="tool-head" onClick={() => setOpen((v) => !v)}>
        <span className={`tool-dot ${entry.status}`} />
        <span className="tool-name">{entry.tool_name}</span>
        <span className="tool-status">{t(`tool.${entry.status}`)}</span>
        <span className="think-chevron">▸</span>
      </button>
      {open && <pre className="tool-body">{entry.content}</pre>}
    </div>
  );
}
