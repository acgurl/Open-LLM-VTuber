import { useEffect, useRef } from 'react';
import { live2d } from '../live2d/controller';

export function Live2DStage() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (ref.current) live2d.mount(ref.current);
  }, []);
  return <canvas ref={ref} className="live2d-canvas" />;
}
