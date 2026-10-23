import { useState } from 'react';
import { useTranslation } from 'react-i18next';

export function ThinkBlock({ text }: { text: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className={`think-block ${open ? 'open' : ''}`}>
      <button className="think-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="think-chevron">▸</span>
        {t('think.label')}
      </button>
      {open && <div className="think-body">{text}</div>}
    </div>
  );
}
