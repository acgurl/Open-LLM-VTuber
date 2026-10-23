import { wsClient } from './websocket';
import { audioPlayer } from './audioPlayer';
import { useChat } from '../stores/chat';
import { useHistory } from '../stores/history';
import { useSettings } from '../stores/settings';
import { useConnection } from '../stores/connection';
import type { ImagePayload } from '../protocol/types';

export function sendText(text: string, images?: ImagePayload[]) {
  const trimmed = text.trim();
  if (!trimmed && (!images || images.length === 0)) return;
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
  useHistory.getState().setCurrentUid(uid);
  wsClient.send({ type: 'fetch-and-set-history', history_uid: uid });
}

export function newHistory() {
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
  wsClient.send({ type: 'fetch-configs' });
}

export function switchConfig(file: string) {
  const settings = useSettings.getState();
  if (settings.switching) return;
  settings.setSwitching(true);
  wsClient.send({ type: 'switch-config', file });
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
