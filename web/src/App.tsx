import { useEffect } from 'react';
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
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="app">
      {background && <div className="bg-layer" style={{ backgroundImage: `url(${background})` }} />}
      <Live2DStage />
      <div className="atmosphere" aria-hidden="true" />
      <TopBar />
      <CameraWindow />
      <ChatOverlay />
      <InputBar />
      <HistoryDrawer />
      <SettingsDrawer />
      <Toasts />
      {status === 'failed' && (
        <div className="boot-failure" role="status">
          {t('boot.unreachable')}
        </div>
      )}
    </div>
  );
}
