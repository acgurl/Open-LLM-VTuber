import { describe, expect, it } from 'vitest';
import {
  formatPoint,
  gaodePoint,
  parsePlaces,
  placeKey,
  wgs84ToGcj02,
} from './places';

describe('parsePlaces', () => {
  it('extracts valid places, trims strings, drops invalid coordinates, and caps at 6', () => {
    const payload = JSON.stringify({
      places: [
        {
          name: '  Library ',
          campus: 'Main',
          gcj02: { lat: 39.91, lon: 116.55 },
          room: '  201  ',
        },
        { name: 'NoCoords' },
        { name: 'OutOfRange', wgs84: { lat: 95, lon: 116 } },
        { name: 'P2', wgs84: { lat: 39.9, lon: 116.5 } },
        { name: 'P3', wgs84: { lat: 39.9, lon: 116.5 } },
        { name: 'P4', wgs84: { lat: 39.9, lon: 116.5 } },
        { name: 'P5', wgs84: { lat: 39.9, lon: 116.5 } },
        { name: 'P6', wgs84: { lat: 39.9, lon: 116.5 } },
        { name: 'P7-Dropped', wgs84: { lat: 39.9, lon: 116.5 } },
      ],
    });

    const parsed = parsePlaces(payload);
    expect(parsed).toHaveLength(6);
    expect(parsed[0]).toMatchObject({
      name: 'Library',
      campus: 'Main',
      room: '201',
      gcj02: { lat: 39.91, lon: 116.55 },
    });
    expect(parsed.some((p) => p.name === 'P7-Dropped')).toBe(false);
  });

  it('returns empty array on malformed JSON or missing places', () => {
    expect(parsePlaces('not json')).toEqual([]);
    expect(parsePlaces('{"places":"bad"}')).toEqual([]);
  });
});

describe('coordinates and deduplication', () => {
  it('converts WGS-84 inside China to offset GCJ-02 and leaves outside points unchanged', () => {
    const beijingWgs = { lat: 39.911013, lon: 116.5567 };
    const gcj = wgs84ToGcj02(beijingWgs);
    expect(gcj.lat).not.toBe(beijingWgs.lat);
    expect(gcj.lon).not.toBe(beijingWgs.lon);

    const london = { lat: 51.5074, lon: -0.1278 };
    expect(wgs84ToGcj02(london)).toEqual(london);
  });

  it('prefers existing gcj02 in gaodePoint and builds deterministic placeKey/formatPoint', () => {
    const place = {
      name: 'Canteen',
      campus: 'East',
      gcj02: { lat: 39.9123456, lon: 116.5512345 },
      wgs84: { lat: 39.9, lon: 116.5 },
    };
    expect(gaodePoint(place)).toEqual(place.gcj02);
    expect(formatPoint(place.gcj02)).toBe('39.912346, 116.551235');
    expect(placeKey(place)).toBe('Canteen|East|39.912346|116.551235');
  });
});
