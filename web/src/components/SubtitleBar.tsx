import { useSubtitle } from '../stores/subtitle';
import { useSettings } from '../stores/settings';

export function SubtitleBar() {
  const subtitlesOn = useSettings((s) => s.subtitlesOn);
  const active = useSubtitle((s) => s.active);
  const name = useSubtitle((s) => s.name);
  const fullText = useSubtitle((s) => s.fullText);
  const shownChars = useSubtitle((s) => s.shownChars);

  if (!subtitlesOn || !active) return null;
  return (
    <div className="subtitle-bar">
      {name && <span className="subtitle-name">{name}</span>}
      <span className="subtitle-text">{fullText.slice(0, shownChars)}</span>
    </div>
  );
}
