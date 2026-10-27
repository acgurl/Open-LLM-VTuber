import { useConnection } from '../stores/connection';
import { useChat } from '../stores/chat';
import { useHistory } from '../stores/history';
import { useSettings } from '../stores/settings';
import { useGroup } from '../stores/group';
import { toast } from '../stores/toast';
import { audioPlayer } from './audioPlayer';
import { audioChannel } from './audioChannel';
import { wsClient } from './websocket';
import { live2d } from '../live2d/controller';
import { groupBridge } from './groupBridge';
import { saveCachedModel } from './modelCache';
import {
  configureLocalMcpServers,
  handleLocalToolCall,
  onLocalMcpError,
  onLocalMcpRegistered,
  onLocalMcpUnregistered,
} from './localMcp';
import i18n from '../i18n';
import type { ServerMessage } from '../protocol/types';

export function onConnected() {
  // 坑 3：连接建立时 history_uid 为空，不落库；必须显式建历史
  wsClient.send({ type: 'create-new-history' });
}

export function handleServerMessage(msg: ServerMessage) {
  const conn = useConnection.getState();
  const chat = useChat.getState();
  const t = i18n.t.bind(i18n);

  switch (msg.type) {
    case 'set-model-and-conf': {
      // 坑 2：switch-config 后的这条不带 client_uid，只在有值时更新
      if (msg.client_uid) {
        conn.setClientUid(msg.client_uid);
        audioChannel.connect(msg.client_uid);
        groupBridge.setUid(msg.client_uid);
      }
      conn.setModelConf(msg.model_info ?? {}, msg.conf_name ?? '', msg.conf_uid ?? '');
      conn.setWelcomeMessage(msg.welcome_message ?? '');
      saveCachedModel(msg.model_info ?? null);
      void live2d.load(msg.model_info ?? null);
      break;
    }

    case 'full-text': {
      const map: Record<string, string> = {
        'Connection established': t('status.connectionEstablished'),
        'Thinking...': t('status.thinking'),
        'AI wants to speak something...': t('status.proactive'),
      };
      conn.setStatusText(map[msg.text] ?? msg.text);
      break;
    }

    case 'control': {
      if (msg.text === 'conversation-chain-start') {
        // 新一轮开始：上一轮若还有声音在播或排队（客户端漏发打断时会出现），
        // 先停掉再接收新音频，否则旧 TTS 会排在新语音前面继续读完
        if (audioPlayer.isActive()) audioPlayer.stopAll();
        chat.finalizeStream();
        conn.setBusy(true);
        audioPlayer.resetChain();
      } else if (msg.text === 'conversation-chain-end') {
        conn.setBusy(false);
        conn.setStatusText('');
      } else if (msg.text === 'interrupt') {
        audioPlayer.stopAll();
      }
      // mic-audio-end 是服务端 VAD 路径的提示，本前端用前端 VAD，忽略
      break;
    }

    case 'text-delta':
      chat.appendAiDelta(msg.text, msg.name, msg.avatar);
      break;

    case 'tool_call_status':
      chat.upsertTool({
        tool_id: msg.tool_id,
        tool_name: msg.tool_name,
        status: msg.status,
        content: msg.content,
        timestamp: msg.timestamp,
        name: msg.name,
      });
      break;

    case 'audio':
      audioPlayer.enqueue(msg);
      break;

    case 'backend-synth-complete':
      audioPlayer.notifySynthComplete();
      break;

    case 'force-new-message':
      chat.finalizeStream();
      break;

    case 'user-input-transcription':
      chat.addUserMessage(msg.text);
      break;

    case 'history-list':
      useHistory.getState().setHistories(msg.histories ?? []);
      break;

    case 'history-data':
      chat.loadHistory(msg.messages ?? []);
      break;

    case 'new-history-created': {
      useHistory.getState().setCurrentUid(msg.history_uid);
      // 欢迎语只进入当前这轮新会话，纯文本不触发 TTS，也不落库
      const welcome = useConnection.getState().welcomeMessage.trim();
      if (welcome && useChat.getState().entries.length === 0) {
        useChat.getState().addAiMessage(welcome);
      }
      break;
    }

    case 'history-deleted':
      useHistory.getState().removeHistory(msg.history_uid);
      break;

    case 'config-files':
      useSettings.getState().setConfigs(msg.configs ?? []);
      break;

    case 'config-switched': {
      const settings = useSettings.getState();
      settings.setSwitching(false);
      chat.clear();
      audioPlayer.stopAll();
      toast(translateServer(msg.message), 'success');
      // 切换后 history_uid 被清空，重建
      wsClient.send({ type: 'create-new-history' });
      break;
    }

    case 'background-files':
      useSettings.getState().setBackgroundFiles(msg.files ?? []);
      break;

    case 'group-update':
      useGroup.getState().setGroup(msg.members ?? [], msg.is_owner ?? false);
      break;

    case 'group-operation-result':
      toast(translateServer(msg.message), msg.success ? 'success' : 'error');
      break;

    case 'interrupt-signal':
      // 群聊打断广播；单聊打断无回执
      audioPlayer.stopAll();
      chat.finalizeStream();
      conn.setBusy(false);
      break;

    case 'heartbeat-ack':
      wsClient.markAlive();
      break;

    case 'local-mcp-config':
      void configureLocalMcpServers(msg.servers ?? []);
      break;

    case 'local-tool-call':
      void handleLocalToolCall(msg);
      break;

    case 'local-mcp-registered':
      onLocalMcpRegistered(msg);
      break;

    case 'local-mcp-unregistered':
      onLocalMcpUnregistered(msg);
      break;

    case 'local-mcp-error':
      onLocalMcpError(msg);
      break;

    case 'error':
      useSettings.getState().setSwitching(false);
      toast(translateServer(msg.message), 'error');
      break;
  }
}

function translateServer(message: string): string {
  const key = `server.${message}`;
  return i18n.exists(key) ? i18n.t(key) : message;
}
