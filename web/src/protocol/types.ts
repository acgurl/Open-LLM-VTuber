// WebSocket 协议类型，与 BACKEND_API.md 附录 B 逐条对应。

export type ImageSource = 'camera' | 'screen' | 'shared' | 'clipboard' | 'upload';

export interface ImagePayload {
  source: ImageSource;
  mime_type: string; // 必须以 image/ 开头
  data: string; // base64，不含 data: 前缀
}

export interface MotionRef {
  group: string;
  index?: number;
}

export interface ModelInfo {
  name?: string;
  description?: string;
  url?: string;
  kScale?: number;
  lipSyncGain?: number;
  initialXshift?: number;
  initialYshift?: number;
  kXOffset?: number;
  idleMotionGroupName?: string;
  frameHeightRatio?: number;
  frameTopRatio?: number;
  defaultEmotion?: number | string;
  pointerInteractive?: boolean;
  scrollToResize?: boolean;
  emotionMap?: Record<string, number>;
  motionMap?: Record<string, MotionRef>;
  tapMotions?: Record<string, Record<string, number>>;
}

export interface DisplayText {
  text: string;
  name?: string;
  avatar?: string;
}

export interface Actions {
  expressions?: number[];
  motions?: MotionRef[];
  pictures?: unknown;
  sounds?: unknown;
}

export interface AudioPayload {
  type: 'audio';
  audio: string | null; // base64 或 null（静音载荷）
  audio_mime: string | null;
  volumes: number[];
  slice_length: number; // 毫秒，默认 20
  display_text: DisplayText | null;
  actions: Actions | null;
  forwarded: boolean;
  streamed: boolean;
}

export interface LocalMcpToolPayload {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface LocalMcpServerConfig {
  server_id: string;
  name: string;
  url: string;
  headers: Record<string, string>;
  transport: 'http' | 'sse';
}

export interface ToolCallStatus {
  type: 'tool_call_status';
  tool_id: string;
  tool_name: string;
  status: 'running' | 'completed' | 'error';
  content: string;
  timestamp: string;
  name?: string;
  browser_view?: unknown;
  scoped?: boolean; // 用户/本地 MCP 工具，群聊时只发给工具所有者
}

export interface HistoryMessage {
  role: 'human' | 'ai' | 'system';
  timestamp: string;
  content: string;
  name?: string;
  avatar?: string;
}

export interface HistorySummary {
  uid: string;
  latest_message?: HistoryMessage;
  timestamp?: string;
}

export interface ConfigFileEntry {
  filename: string;
  name: string;
}

export type ControlText =
  | 'conversation-chain-start'
  | 'conversation-chain-end'
  | 'interrupt'
  | 'mic-audio-end';

export type ServerMessage =
  | { type: 'full-text'; text: string }
  | {
      type: 'set-model-and-conf';
      model_info: ModelInfo;
      conf_name: string;
      conf_uid: string;
      client_uid?: string;
    }
  | { type: 'config-switched'; message: string }
  | { type: 'config-files'; configs: ConfigFileEntry[] }
  | { type: 'background-files'; files: string[] }
  | { type: 'control'; text: ControlText | string }
  | {
      type: 'text-delta';
      text: string;
      full_text?: string;
      name?: string;
      avatar?: string;
    }
  | AudioPayload
  | { type: 'backend-synth-complete' }
  | ToolCallStatus
  | { type: 'user-input-transcription'; text: string }
  | { type: 'force-new-message' }
  | { type: 'interrupt-signal'; text: string }
  | { type: 'group-update'; members: string[]; is_owner: boolean }
  | { type: 'group-operation-result'; success: boolean; message: string }
  | { type: 'history-list'; histories: HistorySummary[] }
  | { type: 'history-data'; messages: HistoryMessage[] }
  | { type: 'new-history-created'; history_uid: string }
  | { type: 'history-deleted'; success: boolean; history_uid: string }
  | { type: 'heartbeat-ack' }
  | {
      type: 'local-tool-call';
      request_id: string;
      server_id: string;
      tool_name: string;
      arguments?: Record<string, unknown>;
    }
  | {
      type: 'local-mcp-registered';
      server_id: string;
      server_name: string;
      tools: string[];
    }
  | { type: 'local-mcp-unregistered'; server_id: string; success: boolean }
  | { type: 'local-mcp-error'; server_id: string; message: string }
  | { type: 'local-mcp-config'; servers: LocalMcpServerConfig[] }
  | { type: 'error'; message: string };

export type ClientMessage =
  | { type: 'text-input'; text: string; images?: ImagePayload[] }
  | { type: 'mic-audio-end'; images?: ImagePayload[] }
  | { type: 'mic-audio-data'; audio: number[] }
  | { type: 'raw-audio-data'; audio: number[] }
  | { type: 'ai-speak-signal' }
  | { type: 'interrupt-signal'; text: string }
  | { type: 'frontend-playback-complete' }
  | { type: 'fetch-history-list' }
  | { type: 'fetch-and-set-history'; history_uid: string }
  | { type: 'create-new-history' }
  | { type: 'delete-history'; history_uid: string }
  | { type: 'fetch-configs' }
  | { type: 'switch-config'; file: string }
  | { type: 'request-init-config' }
  | { type: 'fetch-backgrounds' }
  | { type: 'heartbeat' }
  | { type: 'add-client-to-group'; invitee_uid: string }
  | { type: 'remove-client-from-group'; target_uid: string }
  | { type: 'request-group-info' }
  | { type: 'audio-play-start'; display_text: DisplayText }
  | {
      type: 'register-local-mcp';
      server_id: string;
      name: string;
      tools: LocalMcpToolPayload[];
    }
  | { type: 'unregister-local-mcp'; server_id: string }
  | {
      type: 'local-tool-result';
      request_id: string;
      server_id: string;
      is_error: boolean;
      content_items: Array<Record<string, unknown>>;
    };

export interface SessionInfo {
  authenticated: boolean;
  mode: string;
  user_id?: string;
  display_name?: string;
}

export const LIMITS = {
  textInputChars: 4000,
  maxImages: 4,
  maxImageDataChars: 8 * 1024 * 1024,
  sampleRate: 16000,
  maxAudioSeconds: 120,
  heartbeatIntervalMs: 25_000,
  heartbeatTimeoutMs: 10_000,
} as const;
