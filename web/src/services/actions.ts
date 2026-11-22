import { wsClient } from './websocket';
import { audioPlayer } from './audioPlayer';
import { useChat } from '../stores/chat';
import { useHistory } from '../stores/history';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import { useModels } from '../stores/models';
import type { ImagePayload } from '../protocol/types';

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
  if (!wsClient.ready || settings.switching) return;
  // 换角色会清空活动历史与 agent 记忆，先收尾正在进行的一轮
  if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
  settings.requestConfig(file);
  if (!wsClient.send({ type: 'switch-config', file })) settings.cancelConfigSwitch();
}

export function fetchModels() {
  wsClient.send({ type: 'fetch-models' });
}

// id 为 null 表示回到角色预设自带的模型。对话记忆不变，只换回答用的模型。
export function switchModel(id: string | null) {
  const models = useModels.getState();
  if (models.switching || id === models.current) return;
  // 服务端会先停掉正在生成的一轮再换模型，本地也同步收尾
  if (useConnection.getState().busy || audioPlayer.isActive()) interrupt();
  models.requestSwitch();
  wsClient.send({ type: 'switch-model', model: id });
}

// 当前模型的思考档位，从下一次请求起生效（正在生成的这一轮不受影响）。
// 先本地更新让按钮立即响应，服务端随后回一份 model-list 作为准信。
export function setThinking(level: string) {
  const models = useModels.getState();
  if (models.switching || level === models.thinking) return;
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
