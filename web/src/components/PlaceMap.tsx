import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Map as LeafletMap, Marker, TileLayer } from 'leaflet';
import { gaodePoint, type Place } from '../utils/places';
import { ExpandIcon } from './icons';

// 高德免 key raster 瓦片：底图与坐标同为 GCJ-02，标记才能落在楼上是而不是偏几百米。
// style=8 路网注记 / style=6 卫星影像 + style=8 透明注记叠层。
const ROAD_URL = 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}';
const SAT_URL = 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}';
const SAT_LABEL_URL = 'https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}';
const SUBDOMAINS = '1234';
const MAX_ZOOM = 18;
const PREVIEW_ZOOM = 16;

interface Props {
  place: Place;
  /** 预览禁掉所有手势，避免聊天列滚动被地图劫持；全屏才开放平移缩放 */
  interactive?: boolean;
  satellite?: boolean;
  onExpand?: () => void;
}

export function PlaceMap({ place, interactive = false, satellite = false, onExpand }: Props) {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const tilesRef = useRef<TileLayer[]>([]);
  const leafletRef = useRef<typeof import('leaflet') | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const loadedRef = useRef(0);
  const errorsRef = useRef(0);
  // 异步加载 leaflet 期间 props 可能已经换过（切地点/切卫星），建图时读最新值
  const propsRef = useRef({ place, satellite });
  propsRef.current = { place, satellite };

  const applyTiles = (sat: boolean) => {
    const L = leafletRef.current;
    const map = mapRef.current;
    if (!L || !map) return;
    tilesRef.current.forEach((layer) => map.removeLayer(layer));
    const urls = sat ? [SAT_URL, SAT_LABEL_URL] : [ROAD_URL];
    tilesRef.current = urls.map((url) => {
      const layer = L.tileLayer(url, {
        subdomains: SUBDOMAINS,
        maxZoom: MAX_ZOOM,
        attribution: '&copy; 高德地图',
      }).addTo(map);
      // tileload/tileerror 是 GridLayer 事件，不会冒泡到 map，必须挂在层上
      layer.on('tileload', () => {
        loadedRef.current += 1;
        if (loadedRef.current === 1) setState('ready');
      });
      layer.on('tileerror', () => {
        errorsRef.current += 1;
        // 个别瓦片 404 不算失败；一张都拉不到才降级成坐标面板
        if (loadedRef.current === 0 && errorsRef.current >= 2) setState('failed');
      });
      return layer;
    });
  };

  useEffect(() => {
    let cancelled = false;
    let map: LeafletMap | null = null;
    let ro: ResizeObserver | null = null;
    void (async () => {
      const L = await import('leaflet');
      await import('leaflet/dist/leaflet.css');
      if (cancelled || !hostRef.current) return;
      leafletRef.current = L;
      const current = propsRef.current;
      const point = gaodePoint(current.place);
      map = L.map(hostRef.current, {
        center: [point.lat, point.lon],
        zoom: interactive ? 17 : PREVIEW_ZOOM,
        minZoom: 3,
        maxZoom: MAX_ZOOM,
        zoomSnap: 0.5,
        zoomControl: interactive,
        dragging: interactive,
        scrollWheelZoom: interactive,
        doubleClickZoom: interactive,
        touchZoom: interactive,
        boxZoom: interactive,
        keyboard: interactive,
      });
      map.attributionControl.setPrefix(false);
      mapRef.current = map;
      applyTiles(current.satellite);
      markerRef.current = L.marker([point.lat, point.lon], {
        icon: L.divIcon({
          className: 'place-pin',
          html: '<span class="place-pin-ring"></span><span class="place-pin-dot"></span>',
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        interactive: false,
        keyboard: false,
      }).addTo(map);

      ro = new ResizeObserver(() => map?.invalidateSize());
      ro.observe(hostRef.current);
    })();
    return () => {
      cancelled = true;
      ro?.disconnect();
      map?.remove();
      mapRef.current = null;
      markerRef.current = null;
      tilesRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive]);

  useEffect(() => {
    const map = mapRef.current;
    const marker = markerRef.current;
    if (!map || !marker) return;
    const point = gaodePoint(place);
    marker.setLatLng([point.lat, point.lon]);
    map.setView([point.lat, point.lon], interactive ? Math.max(map.getZoom(), 16) : PREVIEW_ZOOM, {
      animate: interactive,
    });
  }, [place, interactive]);

  useEffect(() => {
    applyTiles(satellite);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [satellite]);

  return (
    <div
      className={`place-map${interactive ? ' interactive' : ''}${state === 'failed' ? ' failed' : ''}`}
      onClick={interactive ? undefined : onExpand}
    >
      <div ref={hostRef} className="place-map-host" />
      {state === 'loading' && (
        <div className="place-map-veil" aria-hidden="true">
          <span className="spinner" />
        </div>
      )}
      {state === 'failed' && (
        <div className="place-map-veil error" role="status">
          <strong>{t('location.mapFailed')}</strong>
          <span>{t('location.mapFailedHint')}</span>
        </div>
      )}
      {!interactive && onExpand && state !== 'failed' && (
        <button
          type="button"
          className="place-map-expand"
          onClick={(e) => {
            e.stopPropagation();
            onExpand();
          }}
        >
          <ExpandIcon />
          <span>{t('location.fullscreen')}</span>
        </button>
      )}
    </div>
  );
}
