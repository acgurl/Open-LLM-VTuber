import { useToasts } from '../stores/toast';

export function Toasts() {
  const toasts = useToasts((s) => s.toasts);
  const dismiss = useToasts((s) => s.dismiss);
  const hold = useToasts((s) => s.hold);
  const release = useToasts((s) => s.release);
  return (
    <div className="toasts" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`toast ${t.level}${t.leaving ? ' leaving' : ''}`}
          onClick={() => dismiss(t.id)}
          onPointerEnter={() => hold(t.id)}
          onPointerLeave={() => release(t.id)}
        >
          <span className="toast-dot" aria-hidden="true" />
          {t.text}
        </button>
      ))}
    </div>
  );
}
