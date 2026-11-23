import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDialog } from '../hooks/useDialog';
import { usePresence } from '../hooks/usePresence';
import { usePlaceView } from '../stores/placeView';
import { formatPoint, gaodePoint } from '../utils/places';
import { MapAppMenu } from './MapAppMenu';
import { PlaceMap } from './PlaceMap';
import { Segmented } from './Segmented';
import { CloseIcon, MapPinIcon } from './icons';

// 全屏地图：与抽屉同层的 mask + dialog（z 50/60），挂在 App 层而不是消息卡里——
// 消息卡的 backdrop-filter 会把 fixed 子元素困进它的包含块。
export function PlaceFullscreen() {
  const { t } = useTranslation();
  const open = usePlaceView((s) => s.open);
  const places = usePlaceView((s) => s.places);
  const index = usePlaceView((s) => s.index);
  const setIndex = usePlaceView((s) => s.setIndex);
  const close = usePlaceView((s) => s.close);
  const { mounted, closing } = usePresence(open, 240);
  const [satellite, setSatellite] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  useDialog(mounted, close, panelRef);

  if (!mounted || places.length === 0) return null;
  const place = places[Math.min(index, places.length - 1)];
  const sub = [place.category, place.campus].filter(Boolean).join(' · ');

  return (
    <>
      <button
        type="button"
        className={`drawer-mask${closing ? ' closing' : ''}`}
        aria-label={t('location.close')}
        tabIndex={-1}
        onClick={close}
      />
      <div
        ref={panelRef}
        className={`place-fullscreen${closing ? ' closing' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={place.name}
        tabIndex={-1}
      >
        <div className="place-full-head">
          <span className="place-glyph" aria-hidden="true">
            <MapPinIcon size={18} />
          </span>
          <div className="place-titles" key={index}>
            <strong className="place-name">{place.name}</strong>
            {sub && <span className="place-sub">{sub}</span>}
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={close}
            aria-label={t('location.close')}
            title={t('location.close')}
          >
            <CloseIcon />
          </button>
        </div>

        {places.length > 1 && (
          <div className="place-switch" role="group" aria-label={t('location.switchLabel')}>
            {places.map((p, i) => (
              <button
                key={`${p.name}-${p.campus ?? ''}-${i}`}
                type="button"
                className={`place-chip${i === index ? ' active' : ''}`}
                aria-pressed={i === index}
                onClick={() => setIndex(i)}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}

        <div className="place-full-map">
          <PlaceMap place={place} interactive satellite={satellite} />
        </div>

        <div className="place-full-bar">
          <Segmented
            value={satellite ? 'sat' : 'road'}
            options={[
              { value: 'road', label: t('location.standard') },
              { value: 'sat', label: t('location.satellite') },
            ]}
            label={t('location.mapStyle')}
            onChange={(v) => setSatellite(v === 'sat')}
          />
          <MapAppMenu place={place} />
        </div>

        <div className="place-full-info">
          {(place.detail || place.room) && (
            <p className="place-detail">
              {place.detail}
              {place.room && <span className="place-room">{place.room}</span>}
            </p>
          )}
          {place.note && <p className="place-note open">{place.note}</p>}
          <div className="place-coords">
            <span>
              GCJ-02 <code>{formatPoint(gaodePoint(place))}</code>
            </span>
            {place.wgs84 && (
              <span>
                WGS-84 <code>{formatPoint(place.wgs84)}</code>
              </span>
            )}
            <span className="place-meta">
              {[place.accuracy, place.source].filter(Boolean).join(' · ')}
            </span>
          </div>
        </div>
      </div>
    </>
  );
}
