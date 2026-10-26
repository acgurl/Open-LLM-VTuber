import type { CSSProperties } from 'react';
import { useSubtitle } from '../stores/subtitle';
import { useSettings } from '../stores/settings';
import { usePresence } from '../hooks/usePresence';

export function SubtitleBar() {
  const subtitlesOn = useSettings((s) => s.subtitlesOn);
  const active = useSubtitle((s) => s.active);
  const name = useSubtitle((s) => s.name);
  const fullText = useSubtitle((s) => s.fullText);
  const shownChars = useSubtitle((s) => s.shownChars);
  const presence = usePresence(subtitlesOn && active, 160);

  if (!presence.mounted) return null;
  const progress = fullText.length > 0 ? Math.min(1, shownChars / fullText.length) : 0;
  return (
    <div
      className={`subtitle-bar${presence.closing ? ' closing' : ''}`}
      style={{ '--p': progress } as CSSProperties}
    >
      {name && <span className="subtitle-name">{name}</span>}
      <span className="subtitle-text">{fullText.slice(0, shownChars)}</span>
      <span className="subtitle-progress" aria-hidden="true" />
    </div>
  );
}
