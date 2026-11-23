import { wsClient } from './websocket';
import { audioPlayer } from './audioPlayer';
import { useChat } from '../stores/chat';
import { useHistory } from '../stores/history';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import { useModels } from '../stores/models';
import { toast } from '../stores/toast';
import i18n from '../i18n';
import type { ImagePayload, ModelKind } from '../protocol/types';

const MODEL_SWITCH_TIMEOUT_MS = 10_000;

export function sendText(text: string, images?: ImagePayload[]) {
  const trimmed = text.trim();
  if (!trimmed && (!images || images.length === 0)) return;
  // 上一轮还在生成或播放时，新输入立即打断，旧语音不能压在新一轮前面
  if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
  useChat.getState().addUserMessage(trimmed);
  wsClient.send({ type: 'text-input', text: trimmed, ...(images?.length ? { images } : {}) });
}

export function interrupt() {
  const heard = audioPlayer.getHeardText();
  audioPlayer.stopAll();
  useChat.getState().finalizeStream();
  wsClient.send({ type: 'interrupt-signal', text: heard });
  // 单聊打断没有回执，本地直接收尾
  useConnection.getState().setBusy(false);
  useConnection.getState().setStatusText('');
}

export function proactiveSpeak() {
  wsClient.send({ type: 'ai-speak-signal' });
}

export function refreshHistories() {
  wsClient.send({ type: 'fetch-history-list' });
}

export function openHistory(uid: string) {
  if (uid === useHistory.getState().currentUid) return;
  // 旧一轮的语音不能串到新历史，先收尾再切换
  if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
  useHistory.getState().setCurrentUid(uid);
  wsClient.send({ type: 'fetch-and-set-history', history_uid: uid });
}

export function newHistory() {
  if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
  useChat.getState().clear();
  useHistory.getState().setCurrentUid(null);
  audioPlayer.stopAll();
  wsClient.send({ type: 'create-new-history' });
}

export function deleteHistory(uid: string) {
  wsClient.send({ type: 'delete-history', history_uid: uid });
  if (useHistory.getState().currentUid === uid) newHistory();
}

export function fetchConfigs() {
  return wsClient.send({ type: 'fetch-configs' });
}

export function switchConfig(file: string) {
  const settings = useSettings.getState();
  if (!wsClient.ready || settings.switching || useModels.getState().pending) return;
  // 换角色会清空活动历史与 agent 记忆，先收尾正在进行的一轮
  if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
  settings.requestConfig(file);
  if (!wsClient.send({ type: 'switch-config', file })) settings.cancelConfigSwitch();
}

export function fetchModels() {
  return wsClient.send({ type: 'fetch-models' });
}

// id 为 null 表示回到当前角色对应分类的预设。语音切换不打断正在进行的一轮。
export function switchModel(id: string | null, kind: ModelKind = 'llm') {
  const models = useModels.getState();
  if (!wsClient.ready || useSettings.getState().switching || models.pending || id === models.catalogs[kind].current) return;
  if (kind === 'llm' && (useConnection.getState().busy || audioPlayer.isActive())) interrupt();
  const request = { id, kind };
  models.requestSwitch(request);
  if (!wsClient.send({ type: 'switch-model', model: id, ...(kind === 'llm' ? {} : { kind }) })) {
    models.cancelSwitch(kind);
    return;
  }
  window.setTimeout(() => {
    // 到时只处理这一次请求，不影响期间已经发出的下一次切换。
    if (useModels.getState().pending !== request) return;
    models.cancelSwitch(kind);
    toast(i18n.t('model.timeout', { category: i18n.t(`model.category.${kind}`) }), 'error');
    fetchModels();
  }, MODEL_SWITCH_TIMEOUT_MS);
}

// 当前模型的思考档位，从下一次请求起生效（正在生成的这一轮不受影响）。
// 先本地更新让按钮立即响应，服务端随后回一份 model-list 作为准信。
export function setThinking(level: string) {
  const models = useModels.getState();
  if (models.pending?.kind === 'llm' || level === models.thinking) return;
  models.setThinking(level);
  wsClient.send({ type: 'set-thinking', level });
}

export function fetchBackgrounds() {
  wsClient.send({ type: 'fetch-backgrounds' });
}

export function inviteToGroup(uid: string) {
  wsClient.send({ type: 'add-client-to-group', invitee_uid: uid });
}

export function removeFromGroup(uid: string) {
  wsClient.send({ type: 'remove-client-from-group', target_uid: uid });
}

export function refreshGroup() {
  wsClient.send({ type: 'request-group-info' });
}
