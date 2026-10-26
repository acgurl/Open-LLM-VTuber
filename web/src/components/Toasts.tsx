import { useToasts } from '../stores/toast';

export function Toasts() {
  const toasts = useToasts((s) => s.toasts);
  const dismiss = useToasts((s) => s.dismiss);
  return (
    <div className="toasts" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`toast ${t.level}${t.leaving ? ' leaving' : ''}`}
          onClick={() => dismiss(t.id)}
        >
          <span className="toast-dot" aria-hidden="true" />
          {t.text}
        </button>
      ))}
    </div>
  );
}
