// 地点卡的数据层：从工具结果原文里解析知识库的 places 结构。
// 后端不新增 WS 字段——kb_search 完成态的 content 就是知识库 JSON 原文，
// 历史 tool_calls.content 同样原文落库，所以直播与回放走同一条解析路径。

export interface PlacePoint {
  lat: number;
  lon: number;
}

export interface Place {
  name: string;
  alias?: string;
  category?: string;
  campus?: string;
  detail?: string;
  room?: string;
  note?: string;
  source?: string;
  accuracy?: string;
  wgs84?: PlacePoint;
  gcj02?: PlacePoint;
  bd09?: PlacePoint;
}

// 一次查询最多渲染这么多地点：同名多校区/多门口时够用，也挡住异常大的 payload
const MAX_PLACES = 6;

const isPoint = (v: unknown): v is PlacePoint => {
  if (!v || typeof v !== 'object') return false;
  const p = v as Record<string, unknown>;
  return (
    typeof p.lat === 'number' &&
    typeof p.lon === 'number' &&
    Number.isFinite(p.lat) &&
    Number.isFinite(p.lon) &&
    Math.abs(p.lat) <= 90 &&
    Math.abs(p.lon) <= 180
  );
};

const str = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined;

/** 解析工具结果里的 places；不是地点结果（或坐标不合法）时返回空数组。 */
export function parsePlaces(content: string): Place[] {
  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return [];
  }
  if (!data || typeof data !== 'object') return [];
  const raw = (data as Record<string, unknown>).places;
  if (!Array.isArray(raw)) return [];

  const places: Place[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const name = str(row.name);
    const gcj02 = isPoint(row.gcj02) ? row.gcj02 : undefined;
    const wgs84 = isPoint(row.wgs84) ? row.wgs84 : undefined;
    // 没有任何可用坐标的条目画不出地图，直接丢弃
    if (!name || (!gcj02 && !wgs84)) continue;
    places.push({
      name,
      alias: str(row.alias),
      category: str(row.category),
      campus: str(row.campus),
      detail: str(row.detail),
      room: str(row.room),
      note: str(row.note),
      source: str(row.source),
      accuracy: str(row.accuracy),
      wgs84,
      gcj02,
      bd09: isPoint(row.bd09) ? row.bd09 : undefined,
    });
    if (places.length >= MAX_PLACES) break;
  }
  return places;
}

/** 去重键：同名同校区同坐标视为同一地点（并行工具调用可能重复返回）。 */
export const placeKey = (p: Place): string => {
  const point = p.gcj02 ?? p.wgs84;
  return `${p.name}|${p.campus ?? ''}|${point?.lat.toFixed(6)}|${point?.lon.toFixed(6)}`;
};

/* ---------- GCJ-02 偏移：知识库只给 wgs84 时，高德瓦片仍需 gcj02 才对齐 ---------- */

const A = 6378245.0;
const EE = 0.00669342162296594323;

const outOfChina = (lat: number, lon: number) =>
  lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271;

const transformLat = (x: number, y: number) => {
  let r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  r += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  r += ((20 * Math.sin(y * Math.PI) + 40 * Math.sin((y / 3) * Math.PI)) * 2) / 3;
  r += ((160 * Math.sin((y / 12) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30)) * 2) / 3;
  return r;
};

const transformLon = (x: number, y: number) => {
  let r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  r += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  r += ((20 * Math.sin(x * Math.PI) + 40 * Math.sin((x / 3) * Math.PI)) * 2) / 3;
  r += ((150 * Math.sin((x / 12) * Math.PI) + 300 * Math.sin((x / 30) * Math.PI)) * 2) / 3;
  return r;
};

export function wgs84ToGcj02(point: PlacePoint): PlacePoint {
  const { lat, lon } = point;
  if (outOfChina(lat, lon)) return { lat, lon };
  let dLat = transformLat(lon - 105, lat - 35);
  let dLon = transformLon(lon - 105, lat - 35);
  const radLat = (lat / 180) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - EE * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180) / (((A * (1 - EE)) / (magic * sqrtMagic)) * Math.PI);
  dLon = (dLon * 180) / ((A / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return { lat: lat + dLat, lon: lon + dLon };
}

/** 高德瓦片/高德与百度跳转统一使用的坐标（gcj02 缺失时由 wgs84 换算）。 */
export const gaodePoint = (p: Place): PlacePoint => p.gcj02 ?? wgs84ToGcj02(p.wgs84 as PlacePoint);

export const formatPoint = (p: PlacePoint): string => `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`;
