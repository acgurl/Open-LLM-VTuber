import { memo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { PlaceEntry } from '../stores/chat';
import { usePlaceView } from '../stores/placeView';
import { MapAppMenu } from './MapAppMenu';
import { PlaceMap } from './PlaceMap';
import { ExpandIcon, MapPinIcon } from './icons';

const NOTE_CLAMP_CHARS = 42;

// 地点卡：与工具卡同一套玻璃几何，整行拉伸。地图预览禁手势，点任意处进全屏。
export const PlaceCard = memo(function PlaceCard({ entry }: { entry: PlaceEntry }) {
  const { t } = useTranslation();
  const [index, setIndex] = useState(0);
  const [noteOpen, setNoteOpen] = useState(false);
  const place = entry.places[Math.min(index, entry.places.length - 1)];
  const openFullscreen = () => usePlaceView.getState().openWith(entry.places, index);
  const sub = [place.category, place.campus].filter(Boolean).join(' · ');
  const longNote = (place.note?.length ?? 0) > NOTE_CLAMP_CHARS;

  return (
    <div className="tool-card place-card">
      <div className="place-head">
        <span className="place-glyph" aria-hidden="true">
          <MapPinIcon />
        </span>
        <div className="place-titles" key={index}>
          <strong className="place-name">{place.name}</strong>
          {sub && <span className="place-sub">{sub}</span>}
        </div>
        <button
          type="button"
          className="icon-btn place-expand"
          onClick={openFullscreen}
          aria-label={t('location.fullscreen')}
          title={t('location.fullscreen')}
        >
          <ExpandIcon />
        </button>
      </div>

      {entry.places.length > 1 && (
        <div className="place-switch" role="group" aria-label={t('location.switchLabel')}>
          {entry.places.map((p, i) => (
            <button
              key={`${p.name}-${p.campus ?? ''}-${i}`}
              type="button"
              className={`place-chip${i === index ? ' active' : ''}`}
              aria-pressed={i === index}
              onClick={() => {
                setIndex(i);
                setNoteOpen(false);
              }}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}

      <PlaceMap place={place} onExpand={openFullscreen} />

      {(place.detail || place.room) && (
        <p className="place-detail">
          {place.detail}
          {place.room && <span className="place-room">{place.room}</span>}
        </p>
      )}
      {place.note && (
        <div className="place-note-block">
          <p className={`place-note${noteOpen || !longNote ? ' open' : ''}`}>{place.note}</p>
          {/* 开关放在 clamp 容器外：line-clamp 会把行内按钮一起裁掉，窄屏就点不到了 */}
          {longNote && (
            <button type="button" className="place-note-toggle" onClick={() => setNoteOpen((v) => !v)}>
              {noteOpen ? t('location.noteLess') : t('location.noteMore')}
            </button>
          )}
        </div>
      )}

      <div className="place-foot">
        <MapAppMenu place={place} />
        <span className="place-meta">
          {[place.accuracy, place.source].filter(Boolean).join(' · ')}
        </span>
      </div>
    </div>
  );
});
