import { useEffect, useState } from 'react';

export function usePresence(open: boolean, duration: number) {
  const [mounted, setMounted] = useState(open);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    if (!mounted) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const timer = window.setTimeout(() => setMounted(false), reducedMotion ? 0 : duration);
    return () => window.clearTimeout(timer);
  }, [open, mounted, duration]);

  return { mounted, closing: mounted && !open };
}
