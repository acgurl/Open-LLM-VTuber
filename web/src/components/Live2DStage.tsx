import { useEffect, useRef } from 'react';
import { live2d } from '../live2d/controller';
import { bindVoiceHalo } from '../live2d/stageFx';
import { loadCachedModel } from '../services/modelCache';

export function Live2DStage() {
  const ref = useRef<HTMLCanvasElement>(null);
  const haloRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    live2d.mount(ref.current);
    // 先用上次模型占位；服务端配置到达后按 URL 复用，不会重复加载。
    const cached = loadCachedModel();
    if (cached) void live2d.load(cached);
  }, []);
  useEffect(() => {
    bindVoiceHalo(haloRef.current);
    return () => bindVoiceHalo(null);
  }, []);
  return (
    <>
      {/* 人物背后的背光与地面光：说话时随口型音量轻轻涨落 */}
      <div ref={haloRef} className="stage-halo" aria-hidden="true" />
      <canvas ref={ref} className="live2d-canvas" />
    </>
  );
}
