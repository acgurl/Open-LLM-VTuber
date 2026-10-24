import { useState } from 'react';
import { useTranslation } from 'react-i18next';

export function ThinkBlock({ text }: { text: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className={`think-block ${open ? 'open' : ''}`}>
      <button className="think-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="think-chevron">▸</span>
        {t('think.label')}
      </button>
      <div className={`collapsible${open ? ' open' : ''}`} aria-hidden={!open}>
        <div className="collapsible-inner">
          <div className="think-body">{text}</div>
        </div>
      </div>
    </div>
  );
}
