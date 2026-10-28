import { useEffect, useRef, useState } from 'react';
import { useConnection, type ConnectionStatus } from '../stores/connection';
import { live2d, STAGE_SETTLED_EVENT } from '../live2d/controller';

declare global {
  interface Window {
    __bootStartedAt?: number;
    bootScreen?: {
      finish: () => void;
    };
  }
}

// 秒开时也别让转圈一闪而过
const MIN_VISIBLE_MS = 600;
// 连接已在线但模型迟迟不就位时放行，不能把用户锁在幕布后面
const STAGE_WAIT_MS = 8000;
const FAILSAFE_MS = 15000;

function canReveal(status: ConnectionStatus, modelSettled: boolean) {
  if (status === 'boot' || status === 'connecting') return false;
  if (status !== 'online') return true;
  return modelSettled;
}

// 启动幕的视觉在 index.html 内联；这里只负责判断何时淡出。
export function BootScreen() {
  const status = useConnection((s) => s.status);
  const [modelSettled, setModelSettled] = useState(live2d.isStageSettled);
  const finished = useRef(false);

  useEffect(() => {
    const onSettled = () => setModelSettled(true);
    window.addEventListener(STAGE_SETTLED_EVENT, onSettled);
    return () => window.removeEventListener(STAGE_SETTLED_EVENT, onSettled);
  }, []);

  useEffect(() => {
    if (status !== 'online' || modelSettled) return;
    const timer = window.setTimeout(() => setModelSettled(true), STAGE_WAIT_MS);
    return () => window.clearTimeout(timer);
  }, [modelSettled, status]);

  useEffect(() => {
    const finish = () => {
      if (finished.current) return;
      finished.current = true;
      const started = window.__bootStartedAt ?? performance.now();
      const wait = Math.max(0, MIN_VISIBLE_MS - (performance.now() - started));
      window.setTimeout(() => {
        window.bootScreen?.finish();
        document.getElementById('root')?.removeAttribute('inert');
      }, wait);
    };
    if (canReveal(status, modelSettled)) {
      finish();
      return;
    }
    const timer = window.setTimeout(finish, FAILSAFE_MS);
    return () => window.clearTimeout(timer);
  }, [modelSettled, status]);

  return null;
}
