import { create } from 'zustand';
import type { Place } from '../utils/places';

// 全屏地图挂在 App 层（消息卡有 backdrop-filter，fixed 子元素会被困在其包含块里），
// 由这个小 store 驱动：卡片只负责把「哪一组地点、第几个」交出去。
interface PlaceViewState {
  open: boolean;
  places: Place[];
  index: number;
  openWith: (places: Place[], index: number) => void;
  setIndex: (index: number) => void;
  close: () => void;
}

export const usePlaceView = create<PlaceViewState>((set) => ({
  open: false,
  places: [],
  index: 0,
  openWith: (places, index) =>
    set({ open: true, places, index: Math.max(0, Math.min(index, places.length - 1)) }),
  setIndex: (index) => set({ index }),
  // places 保留到退场动画结束，避免关闭瞬间地图先消失
  close: () => set({ open: false }),
}));
