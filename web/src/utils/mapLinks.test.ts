import { describe, expect, it } from 'vitest';
import { amapLink, appleLink, baiduLink, coordText } from './mapLinks';
import type { Place } from './places';

const samplePlace: Place = {
  name: '中蓝食堂 & 咖啡',
  detail: '1号楼二层',
  gcj02: { lat: 39.9123456, lon: 116.5512345 },
};

describe('mapLinks', () => {
  it('builds encoded Amap, Baidu, and Apple map links using GCJ-02 coordinates', () => {
    expect(amapLink(samplePlace)).toBe(
      'https://uri.amap.com/marker?position=116.551235,39.912346' +
        '&name=%E4%B8%AD%E8%93%9D%E9%A3%9F%E5%A0%82%20%26%20%E5%92%96%E5%95%A1' +
        '&src=webapp.live-xiaozhi&coordinate=gaode&callnative=1',
    );

    expect(baiduLink(samplePlace)).toBe(
      'https://api.map.baidu.com/marker?location=39.912346,116.551235' +
        '&title=%E4%B8%AD%E8%93%9D%E9%A3%9F%E5%A0%82%20%26%20%E5%92%96%E5%95%A1' +
        '&content=1%E5%8F%B7%E6%A5%BC%E4%BA%8C%E5%B1%82&output=html' +
        '&coord_type=gcj02&src=webapp.live-xiaozhi',
    );

    expect(appleLink(samplePlace)).toBe(
      'https://maps.apple.com/?ll=39.912346,116.551235' +
        '&q=%E4%B8%AD%E8%93%9D%E9%A3%9F%E5%A0%82%20%26%20%E5%92%96%E5%95%A1',
    );
  });

  it('formats coordinate summary text', () => {
    expect(coordText(samplePlace)).toBe('39.912346, 116.551235');
  });
});
