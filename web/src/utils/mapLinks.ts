// 跳转手机地图 App 的落地链接。全部走 HTTPS URI：装了 App 就拉起，没装落网页版，
// 不需要 scheme 白名单，也不依赖任何地图 SDK 的 key。
// 坐标系约定：高德/百度/苹果（中国区底图为高德）都用 gcj02；百度显式声明 coord_type。

import { formatPoint, gaodePoint, type Place } from './places';

const SRC = 'webapp.live-xiaozhi';

const enc = encodeURIComponent;

/** 高德：callnative=1 优先拉起 App，未安装时落到 uri.amap.com 网页标记页。 */
export const amapLink = (p: Place): string => {
  const { lat, lon } = gaodePoint(p);
  return (
    `https://uri.amap.com/marker?position=${lon.toFixed(6)},${lat.toFixed(6)}` +
    `&name=${enc(p.name)}&src=${enc(SRC)}&coordinate=gaode&callnative=1`
  );
};

/** 百度：coord_type=gcj02 让服务端自己换算，无需 bd09。 */
export const baiduLink = (p: Place): string => {
  const { lat, lon } = gaodePoint(p);
  return (
    `https://api.map.baidu.com/marker?location=${lat.toFixed(6)},${lon.toFixed(6)}` +
    `&title=${enc(p.name)}&content=${enc(p.detail ?? p.name)}&output=html` +
    `&coord_type=gcj02&src=${enc(SRC)}`
  );
};

/** 苹果地图：中国区底图与坐标系同为 GCJ-02，故与高德共用同一坐标。 */
export const appleLink = (p: Place): string => {
  const { lat, lon } = gaodePoint(p);
  return `https://maps.apple.com/?ll=${lat.toFixed(6)},${lon.toFixed(6)}&q=${enc(p.name)}`;
};

export const isIOS = (): boolean =>
  typeof navigator !== 'undefined' &&
  (/iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));

export const coordText = (p: Place): string => formatPoint(gaodePoint(p));
