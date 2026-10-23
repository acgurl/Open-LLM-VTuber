import { useEffect, useRef } from 'react';
import { live2d } from '../live2d/controller';
import { loadCachedModel } from '../services/modelCache';

export function Live2DStage() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    live2d.mount(ref.current);
    // 先用上次模型占位；服务端配置到达后按 URL 复用，不会重复加载。
    const cached = loadCachedModel();
    if (cached) void live2d.load(cached);
  }, []);
  return <canvas ref={ref} className="live2d-canvas" />;
}
