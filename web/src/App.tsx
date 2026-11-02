import { useEffect, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { useConnection } from './stores/connection';
import { useSettings } from './stores/settings';
import { fetchSession, redirectToLogin } from './services/session';
import { wsClient } from './services/websocket';
import { Live2DStage } from './components/Live2DStage';
import { ChatOverlay } from './components/ChatOverlay';
import { InputBar } from './components/InputBar';
import { TopBar } from './components/TopBar';
import { CameraWindow } from './components/CameraWindow';
import { HistoryDrawer } from './components/HistoryDrawer';
import { SettingsDrawer } from './components/SettingsDrawer';
import { Toasts } from './components/Toasts';
import { BootScreen } from './components/BootScreen';

// 舞台里缓慢上浮的光尘：位置、大小、周期错开，避免看出循环节拍
const MOTES = [
  { x: 8, s: 5, d: 26, t: -3, c: 'var(--accent)' },
  { x: 19, s: 3, d: 21, t: -14, c: 'var(--secondary)' },
  { x: 31, s: 4, d: 30, t: -8, c: 'var(--accent)' },
  { x: 44, s: 2, d: 19, t: -2, c: 'var(--tertiary)' },
  { x: 57, s: 6, d: 34, t: -20, c: 'var(--accent)' },
  { x: 68, s: 3, d: 24, t: -11, c: 'var(--secondary)' },
  { x: 79, s: 4, d: 28, t: -17, c: 'var(--tertiary)' },
  { x: 91, s: 3, d: 22, t: -6, c: 'var(--accent)' },
].map(
  (m) =>
    ({
      '--x': `${m.x}%`,
      '--s': `${m.s}px`,
      '--d': `${m.d}s`,
      '--t': `${m.t}s`,
      '--c': m.c,
    }) as CSSProperties,
);

export default function App() {
  const { t } = useTranslation();
  const status = useConnection((s) => s.status);
  const background = useSettings((s) => s.background);

  useEffect(() => {
    let cancelled = false;
    // WS 与 session 并行：握手走 cookie 鉴权，不必先等 session 往返。
    wsClient.connect();
    void (async () => {
      const session = await fetchSession();
      if (cancelled) return;
      if (!session) {
        // WS 可能已连上（session 只是辅助信息），别把在线状态改回失败。
        if (useConnection.getState().status !== 'online') {
          useConnection.getState().setStatus('failed');
        }
        return;
      }
      if (!session.authenticated && session.mode === 'oidc') {
        redirectToLogin();
        return;
      }
      if (session.display_name) useConnection.getState().setDisplayName(session.display_name);
      if (session.user_id) useConnection.getState().setUserId(session.user_id);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="app">
      {background && (
        <div
          key={background}
          className="bg-layer"
          style={{ backgroundImage: `url(${background})` }}
        />
      )}
      <Live2DStage />
      <div className="atmosphere" aria-hidden="true">
        <div className="stage-fog" />
        {MOTES.map((m, i) => (
          <i key={i} className="mote" style={m} />
        ))}
      </div>
      <TopBar />
      <CameraWindow />
      <ChatOverlay />
      <InputBar />
      <HistoryDrawer />
      <SettingsDrawer />
      <Toasts />
      <BootScreen />
      {status === 'failed' && (
        <div className="boot-failure" role="status">
          {t('boot.unreachable')}
        </div>
      )}
    </div>
  );
}
