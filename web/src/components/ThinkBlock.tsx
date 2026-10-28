import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

// 思考中自动展开，思考结束（active 转 false）自动收起；手动展开后保持用户选择
export function ThinkBlock({ text, active = false }: { text: string; active?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(active);
  const wasActive = useRef(active);

  useEffect(() => {
    if (wasActive.current && !active) setOpen(false);
    wasActive.current = active;
  }, [active]);

  return (
    <div className={`think-block ${open ? 'open' : ''}${active ? ' active' : ''}`}>
      <button
        className="think-toggle"
        aria-expanded={open}
        aria-busy={active}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="think-chevron">▸</span>
        {t('think.label')}
        {active && (
          <span className="think-live" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        )}
      </button>
      <div className={`collapsible${open ? ' open' : ''}`} aria-hidden={!open}>
        <div className="collapsible-inner">
          <div className="think-body">{text}</div>
        </div>
      </div>
    </div>
  );
}
