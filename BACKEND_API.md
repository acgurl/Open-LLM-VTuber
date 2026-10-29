# Open-LLM-VTuber 后端接口文档（面向新前端实现）

基线：本仓库 `main` 分支，2026-10-23 代码状态（父仓库提交 `32840ac`），**含 2026-10-23 的服务端 VAD 采样归一化修复**（`websocket_handler.py:679-685`）；**2026-10-25 增加按用户 MCP 与浏览器本地 MCP**（见[第 22 节](#22-用户-mcp-与浏览器本地-mcp2026-10-25)）。
读者：要从零写一个 Web/桌面前端的人。本文只描述**后端对外契约**，不描述现有 React 前端的实现。
所有字段名、常量、路径均与源码逐条核对，引用格式为 `文件:行号`。**2026-10-25 的用户/本地 MCP 改动在部分文件顶部新增了 import、常量和 schema，旧章节的行号可能整体偏移；字段与常量语义未变，行号以当前源码为准。**

---

## 目录

1. [系统概览](#1-系统概览)
2. [连接模型与三条 WebSocket 通道](#2-连接模型与三条-websocket-通道)
3. [认证与会话](#3-认证与会话)
4. [HTTP 接口与静态资源](#4-http-接口与静态资源)
5. [`/client-ws`：客户端 → 服务端 消息全集](#5-client-ws客户端--服务端-消息全集)
6. [`/client-ws`：服务端 → 客户端 消息全集](#6-client-ws服务端--客户端-消息全集)
7. [一轮对话的完整时序](#7-一轮对话的完整时序)
8. [语音输入契约（麦克风）](#8-语音输入契约麦克风)
9. [语音输出契约（TTS 播放、口型）](#9-语音输出契约tts-播放口型)
10. [文本渲染契约（流式、标签、think、工具调用）](#10-文本渲染契约流式标签think工具调用)
11. [Live2D 模型元数据](#11-live2d-模型元数据)
12. [历史记录](#12-历史记录)
13. [角色预设与运行时配置切换](#13-角色预设与运行时配置切换)
14. [群聊](#14-群聊)
15. [`/tts-ws` 独立合成接口](#15-tts-ws-独立合成接口)
16. [`POST /asr` 独立转写接口](#16-post-asr-独立转写接口)
17. [限额、超时、关闭码总表](#17-限额超时关闭码总表)
18. [错误与降级行为](#18-错误与降级行为)
19. [已知坑（实现前必读）](#19-已知坑实现前必读)
20. [新前端实现清单](#20-新前端实现清单)
21. [最小可用客户端伪代码](#21-最小可用客户端伪代码)
22. [用户 MCP 与浏览器本地 MCP（2026-10-25）](#22-用户-mcp-与浏览器本地-mcp2026-10-25)
- [附录 A：常量索引](#附录-a常量索引)
- [附录 B：消息类型总索引](#附录-b消息类型总索引)

---

## 1. 系统概览

后端是一个 FastAPI 应用（`src/open_llm_vtuber/server.py:66`，类 `WebSocketServer`），同时承担三件事：

| 职责 | 说明 |
| --- | --- |
| WebSocket 服务 | `/client-ws`（控制+文本）、`/audio-ws`（音频下行）、`/tts-ws`（独立合成）、`/proxy-ws`（可选） |
| HTTP 接口 | 健康检查、OIDC 认证、`POST /asr`、`GET /live2d-models/info` |
| 静态托管 | 前端产物、Live2D 模型、背景、头像、TTS 缓存、web-tool |

启动入口 `run_server.py`，读取根目录 `conf.yaml`，监听 `system_config.host:port`（生产为 `127.0.0.1:12393`，由 Caddy 反代）。

**每个 WebSocket 连接 = 一个独立会话。** 连接建立时后端克隆一份 `ServiceContext`（`websocket_handler.py:284-321`）：配置、角色、Live2D、ASR/TTS/VAD 引擎引用共享，但 **agent 会话状态（记忆）每连接独立**（`init_session_agent`）。因此：

- 同一浏览器开两个标签页 = 两个互不相干的 AI 记忆。
- 断开连接即丢失未落库的 agent 记忆；只有写进 history 的消息能恢复（见[第 12 节](#12-历史记录)）。

**没有 HTTP 配置读写接口。** 本 fork 不包含上游的 `/web-tool/api/config*` 路由。配置在启动时加载一次，运行时唯一的"改配置"手段是 WS 上的角色预设切换（`switch-config`）。

**后端不提供 i18n 文案。** `config_manager/i18n.py` 里的双语 `DESCRIPTIONS` 仅供 Python 侧使用，无任何路由暴露；线上前端的翻译串打包在 JS bundle 内（i18next）。新前端必须自带全部文案。

---

## 2. 连接模型与三条 WebSocket 通道

| 通道 | 方向 | 帧类型 | 用途 |
| --- | --- | --- | --- |
| `/client-ws` | 双向 | **JSON 文本帧（无二进制）** | 全部控制消息、流式文本、历史记录、群聊、麦克风音频 |
| `/audio-ws?client_uid=<uid>` | 仅下行有意义 | JSON 文本帧 | TTS 音频载荷专用通道，避免大 base64 阻塞文本增量 |
| `/tts-ws` | 双向 | JSON 文本帧 | 独立"文字转语音"接口，与对话无关（web-tool 用） |
| `/proxy-ws` | 双向 | JSON | 多客户端扇出代理；**OIDC 模式下不挂载**（`server.py:138-146`） |

关键事实：

1. **整个后端不接受任何二进制 WebSocket 帧。** `/client-ws` 用 `receive_json()` 读取（`websocket_handler.py:336`）；`/audio-ws` 的入站帧被直接丢弃（`websocket_handler.py:228-229`）。麦克风音频是 **JSON 数组里的浮点数**，不是 PCM 字节。
2. **`client_uid` 由服务端生成**，`uuid4()`，每连接一个（`routes.py:198`）。前端不能自己编，只能从 `set-model-and-conf` 消息里读取，然后作为 `/audio-ws` 的查询参数回传。
3. **`/audio-ws` 是可选的。** 未连接时，音频载荷自动回落到 `/client-ws`（`websocket_handler.py:176-188`）；发送失败也会回落并摘除该音频通道。推荐连接它，否则大音频帧会和 `text-delta` 抢同一条 socket。
4. 同一 `client_uid` 重复连接 `/audio-ws` 时，旧的那条会被服务端 `close(1000)`（`websocket_handler.py:218-224`）。
5. `/client-ws` 上所有发送经过一把串行锁（`websocket_handler.py:137-147`），因此**同一通道内消息顺序即发送顺序**，可以依赖顺序做状态机。
6. 心跳由**客户端主动发起**：发 `{"type":"heartbeat"}`，服务端回 `{"type":"heartbeat-ack"}`。服务端没有主动 ping，也不会因为没心跳而断开。

连接生命周期（服务端视角，`routes.py:182-223`）：

```
Origin 校验 → 会话 Cookie 解析 → 预留连接名额 → accept()
  → 初始化 ServiceContext（可能启动 MCP 子进程，耗时）
  → 发送 full-text / set-model-and-conf / group-update
  → 进入消息循环
  → 断开时：中断进行中的对话、移出群聊、关闭音频通道、释放 agent/MCP 资源
```

---

## 3. 认证与会话

由 `system_config.auth.mode` 决定，取值 `single`（默认，单用户无认证）或 `oidc`。

### 3.1 `single` 模式

- 所有接口无认证；身份固定为 `Identity(default_user_id, "Local User")`，`default_user_id` 默认 `"local"`（`routes.py:131-133`）。
- `AuthRedirectMiddleware` 直接放行（`auth/middleware.py:35`）。

### 3.2 `oidc` 模式（生产环境）

标准 authorization code + OIDC discovery + JWKS/ID Token nonce 校验，**不实现 refresh token**。

| 端点 | 方法 | 行为 |
| --- | --- | --- |
| `/auth/login?next=<path>` | GET | 302 到身份提供商；下发 state cookie。已登录或认证关闭时直接 302 到 `next`（经 `safe_next_path` 净化）。Provider 不可用返回 503 `{"error":"Authentication provider unavailable"}`（`auth/routes.py:14-42`） |
| `/auth/callback?code=&state=` | GET | 校验 state → 换 token → 下发会话 cookie → 302 回 `next`。失败 400/401 JSON `{"error": ...}`（`auth/routes.py:44-85`） |
| `/auth/logout` | GET | 删除会话 cookie；配置了 `post_logout_redirect_uri` 时 302 到 provider 的 end-session，否则 302 到 `/`（`auth/routes.py:87-106`） |
| `/api/session` | GET | 200 `{"authenticated":true,"mode":"oidc","user_id":"<内部hex>","display_name":"..."}`；未登录 401 `{"authenticated":false,"mode":"oidc"}`（`auth/routes.py:108-121`） |

**前端唯一需要关心的认证接口是 `GET /api/session`**：用它判断是否已登录、拿显示名；未登录时把用户导航到 `/auth/login?next=<当前路径>`（整页跳转，不是 fetch）。

Cookie（`auth/manager.py`）：

| Cookie | 用途 | 属性 |
| --- | --- | --- |
| `vtuber_session` | 会话，HMAC-SHA256 签名的 `{v,uid,name,iat,exp}` | `HttpOnly`、`Secure`（`cookie_secure`，默认 true）、`SameSite=Lax`、`Path=/`、默认 7 天 |
| `vtuber_oauth_state` | OAuth state/nonce/next | 短时效（默认 600s） |

因为 `HttpOnly`，**JS 读不到会话 cookie**，只能靠 `/api/session` 探测。

### 3.3 HTTP 访问控制

`AuthRedirectMiddleware`（`auth/middleware.py:16-26`）在 oidc 模式下拦截所有非公开路径：

- 公开精确路径：`/healthz`、`/api/session`、`/favicon.ico`
- 公开前缀：`/auth/`、`/assets/`、`/libs/`、`/live2d-models/`、`/bg/`、`/avatars/`
- **`/cache/` 受保护**（TTS 生成的音频文件）
- 其余未登录请求：`Accept` 含 `text/html` → 302 到 `/auth/login?next=...`；否则 401 JSON `{"error":"Authentication required"}`
- `OPTIONS` 永远放行

### 3.4 WebSocket 认证

在每个 WS 路由内部完成，不走中间件：

- 会话 cookie 解析失败 → `accept()` 后立刻 `close(4401, "Authentication required")`（`/client-ws`、`/tts-ws`）
- Origin 校验（`routes.py:136-154`）：**仅在 oidc 模式生效**。若请求带 `Origin` 头，其 host 必须等于请求的 `Host`（忽略默认端口）。不匹配 → `close(1008, "Origin not allowed")`；不带 `Origin`（非浏览器客户端）→ 放行
- `/audio-ws` 额外要求 `?client_uid=` 指向一个属于同一 user 的已建立 `/client-ws` 连接，否则 `close(1008, "Unknown client")`

> **结论：新前端必须与后端同源部署**（构建到 `web/dist` 由后端托管，或反代到同一域名）。CORS 虽然配了 `allow_origins=["*"]`，但同时 `allow_credentials=False`（`server.py:101-107`），跨域请求**不会携带 cookie**，oidc 模式下必然 401。静态资源另有 `Access-Control-Allow-Origin: *`（`server.py:39-50`），所以只有"读静态文件"能跨域，"用会话"不能。

---

## 4. HTTP 接口与静态资源

### 4.1 路由表

| 方法 | 路径 | 认证 | 响应 | 源码 |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | 公开 | 角色配置就绪：200 `{"status":"ok"}`；启动中：503 `{"status":"starting"}` | `server.py:111-117` |
| GET | `/api/session` | 公开 | 见 3.2 | `auth/routes.py:108` |
| GET | `/auth/login`、`/auth/callback`、`/auth/logout` | 公开 | 302 / JSON 错误 | `auth/routes.py` |
| POST | `/asr` | oidc 下需会话 | multipart `file` → `{"text":"..."}`；错误见第 16 节 | `routes.py:344-382` |
| GET | `/live2d-models/info` | 公开前缀 | `{"type":"live2d-models/info","count":N,"characters":[{"name","avatar","model_path"}]}` | `routes.py:299-342` |
| GET | `/api/mcp/config` | oidc 下需会话 | 当前用户的统一 MCP 配置：`{"config":{"mcp_servers":{...}},"servers":[{id,name,url,headers,mode,enabled}]}`；headers 脱敏 | `mcp_routes.py` |
| PUT | `/api/mcp/config` | oidc 下需会话 | 全量保存 `{"config":{"mcp_servers":{...}}}`；后端按 URL 分类 local/remote；见 22.2 | `mcp_routes.py` |
| POST | `/api/mcp/config/test` | oidc 下需会话 | `{server_id}`；remote 返回 `{"mode":"remote","tools":[...]}`，local 返回 `{"mode":"local","tools":[]}` | `mcp_routes.py` |
| GET | `/web-tool`、`/web_tool` | 公开 | 302 → `/web-tool/index.html` | `routes.py:289-297` |
| WS | `/client-ws` | 见 3.4 | — | `routes.py:182` |
| WS | `/audio-ws?client_uid=` | 见 3.4 | — | `routes.py:225` |
| WS | `/tts-ws` | 见 3.4 | — | `routes.py:384` |
| WS | `/proxy-ws` | 仅 `enable_proxy` 且非 oidc | — | `routes.py:259` |

`GET /live2d-models/info` 扫描 `live2d-models/` 下形如 `<folder>/<folder>.model3.json` 的目录。注意：**本仓库自带模型用的是 `runtime/` 子目录**（例如 `live2d-models/nahida/runtime/Nahida_v2.model3.json`），所以这个接口对自带模型返回空或不一致。**权威来源是 `model_dict.json`**，见[第 11 节](#11-live2d-模型元数据)。

### 4.2 静态挂载

| URL 前缀 | 磁盘目录 | 认证 | 备注 |
| --- | --- | --- | --- |
| `/cache` | `cache/` | **oidc 下受保护** | TTS 生成的音频；进程关闭时清空 |
| `/live2d-models` | `live2d-models/` | 公开 | 模型文件（`.model3.json`、贴图、motion） |
| `/bg` | `backgrounds/` | 公开 | 背景图 |
| `/avatars` | `avatars/` | 公开 | 头像，**仅允许 `.jpg/.jpeg/.png/.gif/.svg`，其它扩展名 403**（`server.py:53-63`） |
| `/web-tool` | `web_tool/` | 公开 | ASR/TTS 测试页 |
| `/` | `web/dist/` | 受中间件保护 | 前端产物（`html=True`，兜底挂载，必须最后注册） |

所有静态响应都带 `Access-Control-Allow-Origin: *`，`.js` 强制 `Content-Type: application/javascript`。

### 4.3 与前端相关的 URL 拼接规则

| 数据 | 字段值示例 | 前端应请求 |
| --- | --- | --- |
| 头像 | `character_config.avatar = "relu.png"` | `/avatars/relu.png`（空值时用角色名首字母占位） |
| 背景 | `background-files` 返回 `"bg1.png"` | `/bg/bg1.png` |
| Live2D 模型 | `model_info.url = "/live2d-models/nahida/runtime/Nahida_v2.model3.json"` | 原样使用（已是 URL 路径，服务端不再补全，见 `live2d_model.py:146`） |
| `/tts-ws` 音频 | `audioPath = "cache/20261023_101500_ab12cd34.mp3"` | `/cache/20261023_101500_ab12cd34.mp3`（取 basename 拼 `/cache/`） |

> `scan_bg_directory()`（`config_manager/utils.py:195-202`）用 `os.walk` 递归但**只返回文件 basename**，不含子目录路径。背景图请平铺放在 `backgrounds/` 根下，否则 URL 拼不出来。

---

## 5. `/client-ws`：客户端 → 服务端 消息全集

所有消息都是 JSON 对象，**必须带 `type` 字段**；缺失则被丢弃并记警告（`websocket_handler.py:369-372`）。未知 `type` 只记警告、不断连（`websocket_handler.py:374-379`）。JSON 解析失败被忽略（`websocket_handler.py:341-343`）；处理器抛异常时回 `{"type":"error","message":"Invalid request"}`（`websocket_handler.py:344-348`）。

分发表在 `websocket_handler.py:79-101`。

### 5.1 对话触发

| type | 字段 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text-input` | `text`: string | 是 | 非空、strip 后非空、≤ **4000** 字符（`websocket_handler.py:31,691-696`） |
| | `images`: array | 否 | 见下 |
| `mic-audio-end` | `images`: array | 否 | 触发对累积的音频缓冲做 ASR，然后开始一轮对话；**缓冲随即清空**（`conversation_handler.py:117-119`） |
| `ai-speak-signal` | — | — | 主动说话：用 `proactive_speak_prompt` 作为输入，先回 `full-text` "AI wants to speak something..."，且 `skip_history=true`（**这轮不写入历史**）（`conversation_handler.py:82-94,113-114`） |
| `interrupt-signal` | `text`: string | 否，默认 `""` | 打断。`text` = 用户**实际听到**的那部分 AI 回复。若回复已生成完毕（已落库），打断只停止播放、不再写历史；否则把听到的部分写入**该轮开始时**的历史并告知 agent（`websocket_handler.py:490-513`、`conversation_handler.py:175-213`） |
| `frontend-playback-complete` | 无 | — | **必须实现**。回放完成回执，见 5.2 |

`images` 数组元素结构（`websocket_handler.py:698-715`，枚举 `agent/input_types.py`）：

```json
{ "source": "camera", "mime_type": "image/jpeg", "data": "<base64，不含 data: 前缀>" }
```

- `source` ∈ `camera` / `screen` / `shared` / `clipboard` / `upload`
- `mime_type` 必须以 `image/` 开头
- 最多 **4** 张；单张 base64 字符串 ≤ **8 MiB 字符**
- 校验失败回 `{"type":"error","message":"<原因>"}`，原因文案见 `websocket_handler.py:694-715`

对话并发限制：全局同时最多 **16** 个进行中的对话任务，超出回 `{"type":"error","message":"Server is busy, please try again shortly"}`（`conversation_handler.py:19,26-41`）。
单聊模式下，**新触发会取消上一条未完成的任务**（`conversation_handler.py:155`）——前端可以不等回复完就发下一条，但要注意 UI 上旧流会被截断。群聊模式下若已有群任务在跑，新触发被**静默忽略**（`conversation_handler.py:128-131`）。

### 5.2 `frontend-playback-complete`（最容易漏的一条）

一轮对话如果产生了任何 TTS 音频，服务端发完 `backend-synth-complete` 后会**阻塞等待**客户端回 `{"type":"frontend-playback-complete"}`，超时 **120 秒**（`conversation_utils.py:19,336-346`）。等待结束后才发 `force-new-message` 和 `conversation-chain-end`。

- 走 `/client-ws`，不走路由分发表，由 `MessageHandler` 的请求-响应关联层截获（`message_handler.py:56-76`）。
- 服务端用 `request_id=None` 等待，所以**客户端不要带 `request_id` 字段**（带了就匹配不上，等于没发）。
- 不发也不会报错，但每轮对话会白等 120s，群聊会卡住所有成员。
- 应在**本轮所有音频实际播放完毕后**发送（不是收到就发），否则群聊口型同步和轮次节奏会错。
- 这个回执只决定 `force-new-message` / `conversation-chain-end` 的时机，**不影响历史落库**：AI 回复在文本生成完毕时已经写入（见 12.3），所以播放期间切历史/断线不会丢回复。

### 5.3 麦克风音频

| type | 字段 | 说明 |
| --- | --- | --- |
| `mic-audio-data` | `audio`: number[] | 追加到该连接的录音缓冲。非数组或空数组被静默忽略（`websocket_handler.py:617-639`） |
| `raw-audio-data` | `audio`: number[] | 交给**服务端 VAD**（Silero）处理；VAD 未启用时静默丢弃（`websocket_handler.py:655-686`） |

音频格式（两条路径相同）：**16000 Hz、单声道、float32 语义、取值 [-1.0, 1.0]**，以 JSON 数字数组传输（无 base64、无字节流）。采样率常量 `ASR_SAMPLE_RATE = 16000`（`utils/audio.py:16`）。

缓冲上限 `MAX_AUDIO_SAMPLES = 16000 * 120 = 1,920,000` 个样本（120 秒）。单条消息超限**或累积后超限**都会：清空整个缓冲 + 回 `{"type":"error","message":"Audio input is too long; the recording was discarded"}`（`websocket_handler.py:625-653`）。注意是**整段丢弃**，不是丢弃超限那一段。

两条路径写入**同一个录音缓冲**，样本统一为 [-1,1] 归一化 float32：`mic-audio-data` 直接存前端给的浮点数；`raw-audio-data` 由 Silero 转成 int16 PCM 字节（`vad/silero.py:127-129`），后端再除以 32768 归一化（`websocket_handler.py:679-685`）。因此两种模式产出的音频对 ASR 是等价的，但**同一次录音里不要混用两条路径**。

选择建议：前端自己做 VAD（例如 `@ricky0123/vad-web`）走 `mic-audio-data` + `mic-audio-end`，起止判定和延迟由前端掌控；服务端 VAD 走 `raw-audio-data`，前端只需持续推流，由后端判定并回 `control` 提示。

`raw-audio-data` 路径下服务端会回两种 `control` 消息：

- `{"type":"control","text":"interrupt"}` — 检测到用户开口，前端应立即停止播放并（可选）发 `interrupt-signal`
- `{"type":"control","text":"mic-audio-end"}` — 检测到一段完整语音已入缓冲，**前端需要自己再发一条 `mic-audio-end` 才会真正触发对话**（服务端只是把语音塞进缓冲，不自动开轮次）

### 5.4 历史记录

| type | 字段 | 服务端响应 |
| --- | --- | --- |
| `fetch-history-list` | 无 | `history-list` |
| `fetch-and-set-history` | `history_uid`: string（必填，缺失则静默无响应） | `history-data`；历史不存在或不属于当前角色时，服务端会新建一个历史并在 `history-data` 后补发 `new-history-created` |
| `create-new-history` | 无 | `new-history-created` |
| `delete-history` | `history_uid`: string（必填，缺失则静默无响应） | `history-deleted` |

详见[第 12 节](#12-历史记录)。

### 5.5 配置与资源

| type | 字段 | 服务端响应 |
| --- | --- | --- |
| `fetch-configs` | 无 | `config-files`（已按当前用户的角色权限过滤） |
| `switch-config` | `file`: string（**键名是 `file`**，不是 `config`/`name`；缺失则静默无响应） | `set-model-and-conf` + `config-switched`，或 `error`（无权限时为 `Character not available`） |
| `request-init-config` | 无 | `set-model-and-conf`（含 `client_uid`） |
| `fetch-backgrounds` | 无 | `background-files` |
| `heartbeat` | 无 | `heartbeat-ack` |

### 5.6 群聊

| type | 字段 | 说明 |
| --- | --- | --- |
| `add-client-to-group` | `invitee_uid`: string | 邀请。**键名是 `invitee_uid`** |
| `remove-client-from-group` | `target_uid`: string | 退出或踢人（同一条消息）。**键名是 `target_uid`** |
| `request-group-info` | 无 | 回 `group-update` |
| `audio-play-start` | `display_text`: object | 仅群聊有效：告知服务端"我开始播放这句了"，服务端把一条静音载荷转发给其他成员用于口型同步 |

详见[第 14 节](#14-群聊)。

### 5.7 浏览器本地 MCP

用户配置页只有**一份 JSON**（与 `mcp_servers.json` 同形状）。后端解析后判定每个条目是 `remote`（后端连接）还是 `local`（浏览器连接）；本地条目会通过服务端的 `local-mcp-config` 消息下发，浏览器再连自己的地址并注册工具。后端不会反向访问用户 localhost。完整流程见[第 22 节](#22-用户-mcp-与浏览器本地-mcp2026-10-25)。

| type | 字段 | 说明 |
| --- | --- | --- |
| `register-local-mcp` | `server_id`: string（`[A-Za-z0-9_-]{1,64}`，**必须来自 `local-mcp-config` 的 `server_id`**）、`name`: string（≤64，仅展示）、`tools`: array | 注册/替换一个浏览器侧 MCP 的工具列表。每次 WS 连接/重连后都要重发。响应 `local-mcp-registered` 或 `local-mcp-error` |
| `unregister-local-mcp` | `server_id`: string | 注销；响应 `local-mcp-unregistered` |
| `local-tool-result` | `request_id`: string、`server_id`: string、`is_error`: bool、`content_items`: array | 对 `local-tool-call` 的回执。由 `MessageHandler` 按 `(type, request_id)` 关联，不进入普通路由；不要带错误 `request_id` |

`tools` 元素：`{"name":"...","description":"...","inputSchema":{...}}`；单个 `inputSchema` ≤ 64 KiB，单次注册消息 ≤ 256 KiB。

`content_items` 元素建议使用 `{"type":"text","text":"..."}` 或 `{"type":"image","data":"<base64>","mimeType":"image/png"}`；后端只保留 `text/data/mimeType/url/altText` 字段，最多 64 项，总文本/数据 ≤ 512 KiB。

---

## 6. `/client-ws`：服务端 → 客户端 消息全集

除标注外均为 JSON 文本帧，发往**该连接自身**；标注"群播"的会发给群内所有成员。
`audio` 与 `backend-synth-complete` 走**音频通道**（`/audio-ws`，未连接时回落 `/client-ws`）。

### 6.1 连接与配置

**`full-text`** — 遗留的状态文本，字段 `text`: string。取值：
- `"Connection established"`（连接建立，`websocket_handler.py:273-275`）
- `"Thinking..."`（每轮开始 / 群聊每个发言者开始，`conversation_utils.py:300`、`group_conversation.py:308-311` 群播）
- `"AI wants to speak something..."`（主动说话，`conversation_handler.py:86-88`）

建议当作"状态提示"渲染，不要当对话内容追加进气泡。

**`set-model-and-conf`** — 当前角色与 Live2D 模型（`service_context.py:562-572`）：

```json
{
  "type": "set-model-and-conf",
  "model_info": { "name": "nahida", "url": "/live2d-models/...", "lipSyncGain": 1.2, "emotionMap": {}, "motionMap": {}, "...": "..." },
  "conf_name": "纳西妲",
  "conf_uid": "zh_nahida_01",
  "welcome_message": "你好呀，我是 AIRI～...",
  "client_uid": "6f1c...-uuid"
}
```

- `model_info` 是 `model_dict.json` 里的**整个条目原样**；未配置 Live2D 时为 `{}`
- `welcome_message` 是角色配置里的可选纯文本欢迎语（默认空串）。前端应在**新会话建立**（`new-history-created`）且聊天为空时把非空值渲染成一条 AI 气泡；它不经过 TTS，也不写入对话历史
- **`client_uid` 只在"连接建立"和"响应 `request-init-config`"时存在**；`switch-config` 之后推送的那条**不带 `client_uid`**（`service_context.py:686`）。前端必须缓存首次拿到的 `client_uid`，切换角色时不要覆盖成 undefined。

**`config-switched`** — `{ "type":"config-switched", "message":"Switched to config: <file>" }`（`service_context.py:688-695`），紧跟在 `set-model-and-conf` 之后。

**`config-files`** — `{ "type":"config-files", "configs":[{"filename":"conf.yaml","name":"ReLU / AIRI (Hiyori)"}, ...] }`（`websocket_handler.py:748-750`，扫描逻辑 `config_manager/utils.py:142-192`）。
`configs[0]` 永远是 `conf.yaml`（基础配置），其后按 `filename` 排序；`name` 取自各文件的 `character_config.conf_name`，读不到则回落为相对路径。
角色预设可用 `character_config.allowed_users` 限定用户（内部 user_id 或显示名，大小写不敏感，空表示公开），列表会按当前会话身份过滤；`conf.yaml` 对应的默认角色不受限制。

**`background-files`** — `{ "type":"background-files", "files":["bg1.png", ...] }`（`websocket_handler.py:766-768`）。只有 basename，需自己拼 `/bg/`。

**`heartbeat-ack`** — `{ "type":"heartbeat-ack" }`，无其它字段。

**`error`** — `{ "type":"error", "message":"<英文文案>" }`。来源：非法请求、音频超限、输入校验失败、服务繁忙、对话异常、配置切换失败、无权使用该角色（`Character not available`）；群聊中的错误是**群播**（`group_conversation.py:314-326`）。字段名是 `message`，不是 `text`。

### 6.2 轮次控制

**`control`** — `{ "type":"control", "text":"<值>" }`，取值：

| text | 含义 | 来源 |
| --- | --- | --- |
| `conversation-chain-start` | 一轮开始 | `conversation_utils.py:292-299` |
| `conversation-chain-end` | 一轮结束（所有音频已交付且回放回执已收到/超时） | `conversation_utils.py:360-378` |
| `interrupt` | 服务端 VAD 检测到用户开口，应停止播放 | `websocket_handler.py:667-669` |
| `mic-audio-end` | 服务端 VAD 收完一段语音，提示前端可以提交 | `websocket_handler.py:684-686` |

**`force-new-message`** — `{ "type":"force-new-message" }`，无其它字段。语义："上一条 AI 回复已完整结束，请把后续内容当作新气泡"。群聊中同时群播给其他成员（`conversation_utils.py:348-355`）。

**`user-input-transcription`** — `{ "type":"user-input-transcription", "text":"<ASR 结果>" }`。仅语音输入时发送。单聊发给本人；群聊**群播给除发言者外的所有成员**（`conversation_utils.py:303-316`、`group_conversation.py:198-212`）。

**`interrupt-signal`** — `{ "type":"interrupt-signal", "text":"conversation-interrupted" }`，**仅群聊打断时群播**（`conversation_handler.py:262-269`）。单聊打断**没有任何回执**，任务被直接取消。

### 6.3 流式文本

**`text-delta`**（`conversation_utils.py:83-103`）：

```json
{
  "type": "text-delta",
  "text": "增量片段",
  "full_text": "从头累积到目前为止的完整文本",
  "name": "纳西妲",
  "avatar": "relu.png"
}
```

- 增量在 `TextDeltaBuffer` 里合并，**每 ~50ms 最多 flush 一次**（`interval=0.05`），所以一个 `text` 可能含多个 token
- `full_text` 是累积全量，可用来在丢帧/重连后校准
- 这是 **LLM 原始文本**，包含 `[joy]` 之类的 Live2D 标签和 `<think>` 标记；清洗过的版本在 `audio` 载荷的 `display_text` 里
- 群聊中 `text-delta` 是**群播**给所有成员（`group_conversation.py:339-341`）
- 服务端在转发 `tool_call_status` 或任何音频载荷**之前会先 flush**（`conversation_utils.py:162,166`），所以同通道内文本不会越过工具/音频消息

### 6.4 音频载荷

**`audio`**（构造于 `utils/stream_audio.py:62-108`），**一个句子一条**：

```json
{
  "type": "audio",
  "audio": "<base64 或 null>",
  "audio_mime": "audio/mpeg",
  "volumes": [0.0, 0.31, 1.0, 0.42],
  "slice_length": 20,
  "display_text": { "text": "要显示的句子", "name": "纳西妲", "avatar": "relu.png" },
  "actions": { "expressions": [5], "motions": [{"group":"Nod","index":1}] },
  "forwarded": false,
  "streamed": true
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `audio` | string \| null | base64 音频字节。`.mp3/.wav/.ogg/.m4a/.aac` **原编码直传**，其它格式转成 WAV（`stream_audio.py:10-40`）。`null` = 静音载荷 |
| `audio_mime` | string \| null | `audio/mpeg`、`audio/wav`、`audio/ogg`、`audio/mp4`、`audio/aac`；`audio` 为 null 时也是 null |
| `volumes` | number[] | 归一化 RMS（0..1，按峰值归一），用于口型/波形；静音载荷为 `[]` |
| `slice_length` | int | `volumes` 每格对应的毫秒数，默认 **20** |
| `display_text` | object \| null | `{text, name, avatar}`（`output_types.py:29-39`）；`name`/`avatar` 由角色配置填充 |
| `actions` | object \| null | `{expressions?, motions?, pictures?, sounds?}`，值为 `None` 的键会被剔除（`output_types.py:6-17`） |
| `forwarded` | bool | `true` 仅出现在群聊转发：别人播放的句子同步给你，**没有音频**，只渲染文本 |
| `streamed` | bool | `true` = 这句话的文本已经通过 `text-delta` 流给过你了，**不要再把 `display_text.text` 当新气泡追加**；`false` = 未流式，需要自己上屏 |

顺序保证：TTS 并行生成，但通过内部序列号**严格按句子顺序投递**（`tts_manager.py:84-128`）；序列号不出现在载荷里。合成超时（**30s**）或异常时，用一条**静音载荷**（`audio: null`）占位，保证句子数量和顺序不变（`tts_manager.py:180-193`）。

**`backend-synth-complete`** — `{ "type":"backend-synth-complete" }`，无其它字段，走**音频通道**（`conversation_utils.py:333`）。含义："本轮所有音频载荷已写出"。收到后应把队列播完，然后回 `frontend-playback-complete`。**只有本轮产生过 TTS 载荷时才会发**（`conversation_utils.py:326`）。

### 6.5 工具调用（MCP）

**`tool_call_status`**（构造于 `mcpp/tool_executor.py:155-172`）：

```json
{
  "type": "tool_call_status",
  "tool_id": "call_abc123",
  "tool_name": "search_kb",
  "status": "running",
  "content": "Input: {\"query\": \"...\"}",
  "timestamp": "2026-10-23T10:15:00.123456Z",
  "name": "纳西妲",
  "browser_view": { "...": "仅 stagehand_navigate 成功时存在" }
}
```

| 字段 | 说明 |
| --- | --- |
| `tool_id` | 关联同一次调用的 running / completed / error |
| `status` | `running` → `completed` 或 `error` |
| `content` | running: `Input: <json 参数>`；completed: 结果文本（返回图片时追加 `[Tool returned N image(s)]`）；error: `Error: <文本>` |
| `timestamp` | UTC ISO-8601，尾部带 `Z` |
| `name` | 角色名，转发前注入（`conversation_utils.py:163`） |
| `browser_view` | **可选**，仅 `stagehand_navigate` 成功时携带（`tool_executor.py:282`） |
| `scoped` | **可选**，`true` 表示用户 HTTP / 浏览器本地 MCP 工具；群聊中该状态只发给工具所有者，不群播 |

内部的 `final_tool_results` 事件只给 LLM，**不会发给客户端**（`tool_executor.py:302`）。群聊中该消息群播。

**用户/浏览器 MCP 的消息**（详见[第 22 节](#22-用户-mcp-与浏览器本地-mcp2026-10-25)）：

| type | 字段 | 说明 |
| --- | --- | --- |
| `local-tool-call` | `request_id`、`server_id`、`tool_name`、`arguments` | 后端要求**这台浏览器**执行一次本地 MCP 工具调用。`tool_name` 是 MCP 原始工具名（不是 `l_...` 暴露名）；前端必须在 **30 s** 内回 `local-tool-result` |
| `local-mcp-registered` | `server_id`、`server_name`、`tools`: string[] | 注册成功；`tools` 是后端实际暴露给 LLM 的前缀名（`l_<hash>_<name>`） |
| `local-mcp-unregistered` | `server_id`、`success` | 注销结果 |
| `local-mcp-error` | `server_id`、`message` | 注册失败（schema 非法、超限、会话无浏览器通道、server_id 不在配置中等） |
| `local-mcp-config` | `servers`: array | 连接/重连后下发当前用户配置中 `mode=local` 的服务器：`[{server_id,name,url,headers}]`；`headers` 明文，仅发给该用户的已认证连接。没有本地服务器时也发空数组 |

配置中 `mode=remote` 的用户 MCP 不产生额外 WS 消息；它的工具与全局工具一样通过 `tool_call_status` 展示。`mode=local` 的条目由 `local-mcp-config` 下发，并额外使用上面的本地消息。

### 6.6 历史记录

**`history-list`**（`websocket_handler.py:529-531`，SQL 见 `storage/sqlite.py:336-356`）：

```json
{
  "type": "history-list",
  "histories": [
    {
      "uid": "2e6f...-uuid",
      "latest_message": { "role": "ai", "timestamp": "2026-10-23 10:15:00", "content": "...", "name": "纳西妲", "avatar": "relu.png" },
      "timestamp": "2026-10-23 10:15:00"
    }
  ]
}
```

- 只含**非空**历史，按最新消息时间**倒序**（新→旧）
- 作用域是 **(当前用户, 当前角色的 `conf_uid`)**，换角色后列表会变
- `latest_message.name` / `avatar` 可能不存在（`storage/sqlite.py:93-103`）
- 存储异常时降级为 `histories: []`，不报错

**`history-data`**（`websocket_handler.py:554-561`）：`{ "type":"history-data", "messages":[HistoryMessage...] }`，**`role == "system"` 的消息被过滤掉**。`HistoryMessage` 结构见 `storage/base.py:18-24`：`{role: "human"|"ai"|"system", timestamp: str, content: str, name?: str, avatar?: str}`。历史不存在或不属于该用户 → 先回空数组，再新建一个历史并补发 `new-history-created`（客户端应更新当前 UID，不要继续使用旧值）。

**`new-history-created`** — `{ "type":"new-history-created", "history_uid":"<服务端生成的 uuid>" }`。

**`history-deleted`** — `{ "type":"history-deleted", "success": true, "history_uid":"..." }`。

### 6.7 群聊

**`group-update`** — `{ "type":"group-update", "members":["<client_uid>", ...], "is_owner": true }`（`websocket_handler.py:465-488`）。未入群时 `members: []`、`is_owner: false`。连接时自动推送，成员变动时推给每个受影响成员。

**`group-operation-result`** — `{ "type":"group-operation-result", "success": bool, "message": "..." }`（`chat_group.py:161-172`）。`message` 是英文文案，例如：
- `"You have been invited to the group by <uid>"`（`chat_group.py:219`）
- `"You have been removed from the group"`（`chat_group.py:237`）
- `"Member <uid> was added to the group"` / `"Member <uid> was removed from the group"` / `"Member <uid> disconnected"`（`chat_group.py:278`）
- `"Cannot group clients belonging to different users"`（`chat_group.py:38`）
- `"Only group owner or self can remove members"`（`chat_group.py:84`）

---

## 7. 一轮对话的完整时序

### 7.1 文本输入（单聊）

```
客户端                                     服务端
  │ {"type":"text-input","text":"你好"}      │
  ├──────────────────────────────────────────>│
  │                                          │ 取消该连接上一轮未完成的任务
  │ {"type":"control","text":"conversation-chain-start"}
  │<──────────────────────────────────────────┤
  │ {"type":"full-text","text":"Thinking..."} │
  │<──────────────────────────────────────────┤
  │ {"type":"text-delta", ...}  ×N（每~50ms） │  ← 文本通道
  │<──────────────────────────────────────────┤
  │ {"type":"tool_call_status","status":"running"}   （若有工具调用）
  │<──────────────────────────────────────────┤
  │ {"type":"audio", ...}  ×M（每句一条，严格顺序）  ← 音频通道
  │<──────────────────────────────────────────┤
  │ {"type":"tool_call_status","status":"completed"}
  │<──────────────────────────────────────────┤
  │ {"type":"backend-synth-complete"}         │  ← 音频通道（仅当产生过音频）
  │<──────────────────────────────────────────┤
  │ {"type":"frontend-playback-complete"}     │  ← 必须回！否则等 120s
  ├──────────────────────────────────────────>│
  │ {"type":"force-new-message"}              │
  │<──────────────────────────────────────────┤
  │ {"type":"control","text":"conversation-chain-end"}
  │<──────────────────────────────────────────┤
```

若本轮没有任何 TTS 音频（例如全是 think 段），则不发 `backend-synth-complete`，也**不需要**回 `frontend-playback-complete`，服务端直接发 `force-new-message` + `conversation-chain-end`（`conversation_utils.py:326-348`）。

### 7.2 语音输入（单聊，前端 VAD）

```
{"type":"mic-audio-data","audio":[0.01,-0.03,...]}   ×N（录音期间持续发）
{"type":"mic-audio-end"}
  → 服务端 ASR
  → {"type":"user-input-transcription","text":"识别结果"}
  → 之后与 7.1 的 conversation-chain-start 之后完全一致
```

注意 `conversation-chain-start` 和 `Thinking...` 在 ASR **之前**就已发出（`single_conversation.py:50-56`），所以顺序是：chain-start → Thinking → transcription → deltas。

### 7.3 打断

```
{"type":"interrupt-signal","text":"我已经听到的那部分文本"}
```

- 单聊：取消当前任务、通知 agent、把听到的部分以 `role:"ai"` 落库并追加一条 `role:"system"` 的 `[Interrupted by user]`（`conversation_handler.py:175-202`）。**没有回执消息**，前端需自己停止播放、收尾气泡。
- 群聊：取消群任务、给每个成员落库，然后群播 `{"type":"interrupt-signal","text":"conversation-interrupted"}`（`conversation_handler.py:205-269`）。

### 7.4 连接建立时的初始消息

顺序固定（`websocket_handler.py:266-282`）：

1. `{"type":"full-text","text":"Connection established"}`
2. `{"type":"set-model-and-conf", ..., "client_uid":"<uid>"}`
3. `{"type":"group-update", ...}`
4. `{"type":"group-update", ...}`（重复一次，来自 `_store_client_data` 与 `_send_initial_messages` 各调一次；无害，前端做幂等处理即可）

拿到第 2 条后就可以用 `client_uid` 去连 `/audio-ws`。

---

## 8. 语音输入契约（麦克风）

| 项 | 值 |
| --- | --- |
| 采样率 | 16000 Hz（`utils/audio.py:16`） |
| 声道 | 单声道 |
| 样本格式 | JSON 数字数组，float，范围 [-1.0, 1.0]（服务端 `np.array(..., dtype=np.float32)`，`websocket_handler.py:636-639`） |
| 传输 | `/client-ws` 上的 JSON 文本帧，`{"type":"mic-audio-data","audio":[...]}` |
| 时长上限 | 累积 120 秒（1,920,000 样本），超限整段丢弃 |
| 提交 | `{"type":"mic-audio-end"}` |

浏览器实现要点：`getUserMedia` → `AudioContext`（若设备采样率不是 16k，需重采样到 16000）→ `ScriptProcessor`/`AudioWorklet` 取 Float32 → 分块（建议 20~100ms 一块）`Array.from(chunk)` 塞进 JSON。

> JSON 传浮点数的开销约为二进制的 6~8 倍。120 秒上限内这是可接受的，但**不要发超过几秒才发一次的大数组**，会阻塞同通道的其它消息。

`POST /asr` 是另一条独立路径，接受**真正的 WAV 字节**（见第 16 节），适合"按住说话、松手整段上传"的交互，比 WS 分块更简单，但不支持流式。

---

## 9. 语音输出契约（TTS 播放、口型）

### 9.1 播放

1. 收到 `audio` 载荷 → `audio` 字段 base64 解码 → `new Blob([bytes], {type: audio_mime})` → `URL.createObjectURL` → 排队播放。
2. `audio_mime` 必须用，不要硬编码 `audio/wav`：Edge TTS 出 MP3，Azure 出 WAV，其它引擎可能是别的（`stream_audio.py:10-16`）。
3. `audio === null` 时**不要跳过这条消息**：它是有效的"只显示不发声"载荷（think 段、TTS 超时/失败），仍然要渲染 `display_text`、执行 `actions`、并计入句子顺序。
4. 按到达顺序串行播放（服务端已保证顺序）。
5. 收到 `backend-synth-complete` 且队列播完 → 发 `frontend-playback-complete`。

### 9.2 口型同步

- `volumes` 是归一化 RMS 序列，`slice_length` 是每格毫秒数（默认 20）。播放进度 `t` 毫秒对应 `volumes[floor(t / slice_length)]`。
- 最终嘴部开合幅度 = `volume * model_info.lipSyncGain`。**增益只来自 `model_dict.json`**，不要再乘额外系数。
- 口型参数**不能写死 `ParamMouthOpenY`**：应读取模型 `model3.json` 的 `Groups[Name=LipSync].Ids`（pixi 里是 `internalModel.motionManager.lipSyncIds`）。例如 `mao_pro` 用的是 `ParamA`。
- 写入时机要在模型 update 的 `beforeModelUpdate` 阶段（或等效的绘制前钩子），否则会被动作参数回滚覆盖。
- `volumes` 为空数组时（静音载荷）不做口型。

### 9.3 文本上屏

- `streamed === true`：文本已通过 `text-delta` 上屏，不要再追加新气泡。
- `streamed === false`：这句没走过流式，需要把 `display_text.text` 作为新内容上屏。
- `forwarded === true`（群聊）：别人正在播的句子，只有文本没有音频，按普通文本渲染即可。

---

## 10. 文本渲染契约（流式、标签、think、工具调用）

### 10.1 两套文本

| 来源 | 内容 | 用途 |
| --- | --- | --- |
| `text-delta.text` / `full_text` | **LLM 原始输出**，含 `[joy]`、`[nod]` 等 Live2D 标签、含 `<think>` 标记 | 打字机式流式上屏 |
| `audio.display_text.text` | 经过分句/装饰管线处理的**单句**显示文本 | 文本上屏、TTS 对齐、动作触发 |

装饰管线（`agent/transformers.py`）：`sentence_divider` → `actions_extractor` → `display_processor` → `tts_filter`。

### 10.2 Live2D 标签

LLM 被提示在句子里插入方括号关键字（提示词 `prompts/utils/live2d_expression_prompt.txt`），例如：

```
你好呀！[joy] 今天想聊点什么？[nod]
```

- 关键字来自 `model_info.emotionMap`（表情）和 `model_info.motionMap`（动作）的**键**，大小写不敏感（匹配时统一转小写，`live2d_model.py:164,192`）。
- 后端把它们**抽取到 `actions`** 里：`expressions` 是 `emotionMap` 的**值**（表情索引，number[]）；`motions` 是 `motionMap` 的**值**（形如 `{"group":"Nod","index":1}` 的对象数组，`index` 可能不存在）。
- **`display_text.text` 里方括号标签不会被删除。** 前端渲染时需要自己把 `[xxx]` 剥掉，或者按现有前端的做法把动作标签渲染成折叠/动作块。
- 只有"不含 think 起止标记"的句子才会抽取动作（`transformers.py:82-91`）。

### 10.3 think 段（内心活动）

启用 `think_tag_prompt` 后，LLM 会输出 `<think>...</think>`。后端处理（`transformers.py:106-157,192-193`）：

- 标记所在句子的 `display_text.text` 被**整体替换成字面量** `"<think>"` 或 `"</think>"`
- think 段内的句子：`display_text.text` 是正常内容，但 **TTS 文本为空** → 产生 `audio: null` 的静音载荷
- `text-delta` 流里则是**原始带标记的文本**

前端渲染建议：以 `<think>` / `</think>` 标记为界，把中间内容放进可折叠的"思考"块（默认折叠、弱化样式），并跳过其音频。

### 10.4 TTS 文本清洗

`tts_filter` 会按 `character_config.tts_preprocessor_config` 剥离特殊字符（`remove_special_char`、`ignore_brackets`、`ignore_parentheses`、`ignore_asterisks`、`ignore_angle_brackets`）。**这只影响语音，不影响 `display_text`**。所以"显示的"和"念出来的"可以不同，这是预期行为。

若 `display_text.text` 清洗后为空（`is_silent_text`，`utils/text.py:6-8`），直接走静音载荷路径（`tts_manager.py:59-64`）。

### 10.5 翻译

启用 `translator_config.translate_audio` 时，TTS 文本会被翻译（`conversation_utils.py:252-255`），`display_text` 保持原文 → 实现"看中文、听日文"。前端无需处理。

---

## 11. Live2D 模型元数据

### 11.1 获取方式

**只能通过 WebSocket**：`set-model-and-conf.model_info`（连接时自动推送，或主动发 `request-init-config`）。
**没有 `GET /model_dict.json` 这样的 HTTP 接口**，`model_dict.json` 不是静态挂载目录里的文件。

### 11.2 `model_dict.json` / `model_info` 结构

根目录 `model_dict.json` 是一个**数组**，`character_config.live2d_model_name` 与条目的 `name` 精确匹配（`live2d_model.py:136-144`；匹配失败启动即崩）。单个条目：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | string | 查找键，对应 `live2d_model_name` |
| `description` | string | 自由文本 |
| `url` | string | `.model3.json` 的 URL 路径，已以 `/live2d-models/` 开头，**原样使用** |
| `kScale` | number | 模型缩放（旧前端遗留，当前前端按模型可见轮廓自动构图，不使用） |
| `lipSyncGain` | number | 口型增益（唯一的增益来源） |
| `initialXshift` / `initialYshift` | number | 画布偏移（同上，当前前端不使用） |
| `kXOffset` | number | 水平偏移（同上，当前前端不使用） |
| `idleMotionGroupName` | string | 待机动作组名，如 `"Idle"` |
| `frameHeightRatio` | number（可选） | 构图覆盖：可见轮廓高度 = 视口高度 × 该值，默认 `1.39`。半身像等轮廓较矮的模型调小（如 `0.86`）即可拉远 |
| `frameTopRatio` | number（可选） | 构图覆盖：轮廓顶部在视口中的位置比例，默认 `0.12` |
| `defaultEmotion` | number / string（可选） | 一轮对话结束后回落的表情；缺省使用第 0 个表情 |
| `emotionMap` | object | 情绪关键字 → **表情索引（int）**。可为 `{}` |
| `motionMap` | object | 动作关键字 → `{"group": string, "index"?: int}`。可为 `{}` |
| `tapMotions` | object（可选） | 点击区域 → {动作组名 → **权重**}，如 `{"HitAreaBody": {"Tap@Body": 1}}`。区域键可匹配 model3.json 的 HitArea `Id` 或 `Name`；权重用于加权随机选组，`1` 不是动作索引。没有命中已配置区域时，应合并所有区域的动作组按权重兜底 |

真实样例（`model_dict.json` 的 `nahida` 条目）：

```json
{
  "name": "nahida",
  "description": "纳西妲 (Genshin Impact)",
  "url": "/live2d-models/nahida/runtime/Nahida_v2.model3.json",
  "kScale": 0.5,
  "lipSyncGain": 1.2,
  "initialXshift": 0,
  "initialYshift": 0,
  "kXOffset": 0,
  "idleMotionGroupName": "Idle",
  "emotionMap": { "joy": 5, "sadness": 2, "anger": 4, "surprise": 5, "fear": 2, "disgust": 4, "smirk": 3 },
  "motionMap": {},
  "tapMotions": {}
}
```

### 11.3 提示词注入

后端把 `emotionMap` / `motionMap` 的**键列表**渲染成 `"[neutral], [anger], ..."` 形式，替换进 `live2d_expression_prompt` 的 `[<insert_emomap_keys>]` / `[<insert_motionmap_keys>]` 占位符（`service_context.py:601-607`），追加到系统提示词末尾。所以**模型有哪些标签可用，完全由 `model_dict.json` 决定**，前端不需要也无法干预。未配置 Live2D 时该提示词被跳过。

---

## 12. 历史记录

### 12.1 存储与作用域

- 后端 SQLite：`data/storage/open_llm_vtuber.db`（`storage.backend` 目前只支持 `"sqlite"`）
- 每条历史归属 **(user_id, conf_uid, history_uid)** 三元组
  - `user_id`：oidc 模式是内部随机 hex；single 模式是 `local`
  - `conf_uid`：**角色的唯一标识**，来自 `character_config.conf_uid`
  - `history_uid`：服务端生成的 uuid
- 含义：**历史按角色分区**。切换到另一个角色后 `fetch-history-list` 返回的是那个角色的历史。
- `user_id` 只来自会话 cookie，**客户端无法指定或伪造**；不存在跨用户读取。

### 12.2 当前活动历史（`history_uid`）

服务端每个连接维护一个"当前活动历史" `context.history_uid`：

- **连接刚建立时为空字符串 `""`**（`service_context.py:79`）→ 此时对话**不会落库**！必须显式调用 `create-new-history` 或 `fetch-and-set-history` 才开始记录。
- 客户端应在同一标签页内持久化当前 `history_uid`，连接建立/重连/刷新时优先用 `fetch-and-set-history` 恢复；只有新标签页或用户显式“新建会话”时才调用 `create-new-history`。后端在历史不存在时会自动新建并补发 `new-history-created`。
- `switch-config` 成功后被重置为 `None`（`service_context.py:680`）→ 换角色后同样需要重新选择/新建历史。
- `delete-history` 删掉当前活动历史后也被置 `None`（`websocket_handler.py:614-615`）。
- 两种空值（`""` / `None`）对落库判断等效，`store_history_message` 都会直接返回（`service_context.py:269-270`）。
- `fetch-and-set-history` 除了返回消息，还会把该历史的消息灌进 agent 记忆（`agent_engine.set_memory`）并设为活动历史（`service_context.py:243-260`）。
- **一轮对话的写入绑定到该轮开始时的 `history_uid`**（`single_conversation.py:49-112`）。播放期间切到别的历史不会把这条回复写到新历史；但新历史的 `set_memory` 会替换 agent 工作记忆，所以客户端切历史前应先打断进行中的一轮（见 12.3）。

### 12.3 消息写入时机

| 场景 | 写入内容 |
| --- | --- |
| 正常一轮 | `role:"human"`（用户输入文本，含 ASR 结果）在轮次开始时写入；`role:"ai"`（完整回复）在**文本生成完毕时立即写入**，早于 TTS 播放结束与 `frontend-playback-complete` |
| 主动说话 `ai-speak-signal` | **都不写**（`skip_history`） |
| 打断（回复尚未生成完） | `role:"ai"` = 用户听到的部分 + `role:"system"` = `[Interrupted by user]`，写入该轮开始时的历史 |
| 打断（回复已生成完、只是播放没结束） | **不写**：完整回复已在生成完毕时落库，打断只停播放 |
| 切历史 / 新建历史 / 换角色前 | 客户端应先发 `interrupt-signal` 收尾进行中的一轮；否则旧一轮的音画会串到新会话，且 agent 记忆被换掉 |
| 群聊 | 人类输入写给发起者；AI 回复写给**所有成员**各自的历史 |

`role:"system"` 的消息在 `history-data` 返回时被过滤，但会进 agent 记忆。

### 12.4 消息结构

```ts
type HistoryMessage = {
  role: "human" | "ai" | "system";
  timestamp: string;      // "YYYY-MM-DD HH:MM:SS"
  content: string;
  name?: string;          // 可能缺失
  avatar?: string;        // 可能缺失，是 avatars/ 下的文件名
}
```

`content` 是**原始文本**（可能含 `[joy]` 标签、Markdown）。渲染历史时需要走与实时消息相同的标签/Markdown 处理。

### 12.5 不支持的操作

- **没有重命名接口。** `rename_history` / `modify_latest_message` 只存在于存储层（`storage/base.py:189-209`），未通过 WS 暴露。
- 没有分页：`fetch-history-list` 一次返回全部非空历史。
- 没有"修改/删除单条消息"。

---

## 13. 角色预设与运行时配置切换

### 13.1 预设文件格式

目录由 `system_config.config_alts_dir` 指定（本仓库为 `characters/`）。每个 `.yaml` 文件只有一个顶层键 `character_config:`，内容是 `CharacterConfig` 的**部分字段**；切换时与根 `conf.yaml` 的 `character_config` **深度合并**（`service_context.py:655-665`，`deep_merge` 在 `service_context.py:727-737`），所以只需写要覆盖的字段。

```yaml
character_config:
  conf_name: "纳西妲"          # 列表里显示的名字
  conf_uid: "zh_nahida_01"     # 唯一标识，决定历史分区
  character_name: "纳西妲"      # 消息里的 name 字段
  live2d_model_name: "nahida"  # 必须能在 model_dict.json 里找到
  avatar: "xxx.png"            # 可选，avatars/ 下的文件名
  human_name: "Human"          # 可选
  welcome_message: |           # 可选，新会话里的纯文本欢迎语（不朗读）
    ...
  persona_prompt: |
    ...
  # 可选覆盖：agent_config / asr_config / tts_config / vad_config / tts_preprocessor_config
```

### 13.2 切换流程

```
客户端: {"type":"fetch-configs"}
服务端: {"type":"config-files","configs":[{"filename":"conf.yaml","name":"..."},{"filename":"zh_nahida.yaml","name":"纳西妲"},...]}

客户端: {"type":"switch-config","file":"zh_nahida.yaml"}
服务端: {"type":"set-model-and-conf", ...}   ← 注意：不带 client_uid
服务端: {"type":"config-switched","message":"Switched to config: zh_nahida.yaml"}
```

- 回到基础配置用 `{"type":"switch-config","file":"conf.yaml"}`（特例，读根文件，`service_context.py:641-642`）
- 其它值必须在 `config_alts_dir` 内、`.yaml` 后缀；路径穿越被 `resolve_existing_file_within` 拦截（`service_context.py:647-653`）
- 失败回 `{"type":"error","message":"Failed to switch configuration"}`（文案固定，不含细节，避免泄露配置内容，`service_context.py:712-724`）
- 切换会按需重建 Live2D / ASR / TTS / VAD / agent / 翻译引擎（子配置相同则复用），**可能耗时数秒**，UI 要有 loading 态
- **切换后 `history_uid` 被清空**，必须重新 `create-new-history` 或 `fetch-and-set-history`，否则对话不落库

### 13.3 背景图

`{"type":"fetch-backgrounds"}` → `{"type":"background-files","files":["a.png","b.jpg"]}`，自己拼 `/bg/<file>`。背景**不在配置里**，纯目录扫描（`config_manager/utils.py:195-202`）。

---

## 14. 群聊

群聊 = 多个 `/client-ws` 连接（每个连接一个 AI 角色）被编成一组，用户的一句话广播给组内所有 AI，它们轮流发言。

### 14.1 组建

```
A: {"type":"add-client-to-group","invitee_uid":"<B 的 client_uid>"}
A ← {"type":"group-operation-result","success":true,"message":"..."}
B ← {"type":"group-update","members":["A","B"],"is_owner":false}
B ← {"type":"group-operation-result","success":true,"message":"You have been invited to the group by A"}
A ← {"type":"group-update","members":["A","B"],"is_owner":true}
```

- 群 ID = `f"group_{邀请者 client_uid}"`（`chat_group.py:51`）
- **被邀请者无需确认**，收到即入群
- 限制：目标必须在线、必须还没在别的群里、**必须与邀请者属于同一个 user_id**（oidc 下即同一登录账号，`chat_group.py:33-38`）
- 退出/踢人：`{"type":"remove-client-from-group","target_uid":"<uid>"}`；只有**群主或本人**能移除（`chat_group.py:82-84`）；剩 ≤1 人时群自动解散
- 断线自动移出，其余成员收到 `group-update` + `"Member <uid> disconnected"`

前端需要知道其它连接的 `client_uid` 才能邀请——服务端不提供"列出同用户所有连接"的接口，需要前端自己在多个标签页间协调（例如 BroadcastChannel）。

### 14.2 群聊中的消息差异

| 消息 | 单聊 | 群聊 |
| --- | --- | --- |
| `control:conversation-chain-start`、`full-text:Thinking...` | 发给发言者 | **群播给所有成员**，每个发言者各来一次（`group_conversation.py:300-311`） |
| `text-delta`、`tool_call_status` | 发给发言者 | **群播给所有成员** |
| `audio`、`backend-synth-complete` | 发给发言者 | **只发给发言者**（走各自的音频通道） |
| `user-input-transcription` | 发给本人 | 群播给**除发言者外**的成员 |
| `force-new-message`、`conversation-chain-end` | 发给发言者 | 发给发言者 **+ 群播给其他成员** |
| `error` | 发给本人 | **群播** |
| `interrupt-signal` | 无回执 | 群播 `text:"conversation-interrupted"` |

因此非发言者要靠 `audio-play-start` 拿到同步文本：

```
发言者开始播放某句 → {"type":"audio-play-start","display_text":{...}}
其他成员 ← {"type":"audio","audio":null,"display_text":{...},"actions":null,"forwarded":true,"streamed":false,...}
```

（`websocket_handler.py:770-788`）——即一条 `forwarded:true` 的静音载荷，用于对齐口型。只在群成员 > 1 时生效。

### 14.3 群聊轮次

每个成员轮流发言；某成员发言期间群任务占用 `group_id` 这个 task key，此时**任何成员的新触发都会被静默忽略**（`conversation_handler.py:128-131`）。前端应在一轮完全结束（收到 `conversation-chain-end`）前禁用发送按钮。

---

## 15. `/tts-ws` 独立合成接口

与对话无关的"文本转语音"通道，`web_tool/` 测试页在用。**协议与 `/client-ws` 完全不同：没有 `type` 字段，用 `status`。**

请求（每帧一条，可连续发多条）：

```json
{ "text": "要合成的文本" }
```

- `text` 必须是 strip 后非空的字符串，否则该帧被静默忽略（`routes.py:113-118`）
- ≤ **2000** 字符；按 `[.!?。！？]` 切句后 ≤ **30** 句；每句缺终止标点时自动补 `.`（`routes.py:24-51`）

响应：

```json
{ "status": "partial", "audioPath": "cache/20261023_101500_ab12cd34.mp3", "text": "第一句" }
{ "status": "partial", "audioPath": "cache/20261023_101501_ef56gh78.mp3", "text": "第二句" }
{ "status": "complete" }
```

出错（终止本次请求）：

```json
{ "status": "error", "message": "Text exceeds the 2000-character limit" }
```

其它 `message`：`"Text exceeds the 30-sentence limit"`、`"Failed to generate audio"`。

音频**不在 socket 上传输**，`audioPath` 是服务端相对路径，用 `GET /cache/<basename>` 取（oidc 模式下该路径受会话保护）。
并发上限 **16** 条连接，超出 `close(1013, "Server is at capacity")`。认证与 Origin 规则同 `/client-ws`。

---

## 16. `POST /asr` 独立转写接口

`multipart/form-data`，字段名 `file`（`routes.py:344-382`）。

要求（`utils/audio.py:21-50`）：**WAV 容器、单声道、16-bit PCM、恰好 16000 Hz、≤120 秒、≤10 MiB**。解码为小端 int16 后除以 32768 归一化。

响应：

| 状态码 | Body |
| --- | --- |
| 200 | `{"text": "转写结果"}` |
| 400 | `{"error": "Audio must be mono"}` / `"Audio must be 16-bit PCM"` / `"Audio must be 16000 Hz"` / `"Audio exceeds the 120-second limit"` / `"Invalid WAV file: ..."` / `"Empty audio file"` / `"Empty audio data"` |
| 401 | `{"error": "Authentication required"}`（仅 oidc） |
| 413 | `{"error": "Audio file is too large"}` |
| 429 | `{"error": "Too many concurrent transcription requests"}`（并发上限 **2**） |
| 500 | `{"error": "Internal server error during transcription"}` |

用的是**默认上下文的 ASR 引擎**，不随角色切换而变（`default_context_cache.asr_engine`，`routes.py:371`）。

---

## 17. 限额、超时、关闭码总表

### 17.1 限额

| 项 | 值 | 源码 |
| --- | --- | --- |
| `text-input.text` 长度 | 4000 字符 | `websocket_handler.py:31` |
| 单条消息图片数 | 4 | `websocket_handler.py:32` |
| 单张图片 base64 | 8 MiB 字符 | `websocket_handler.py:33` |
| 图片 `source` 白名单 | camera/screen/shared/clipboard/upload | `websocket_handler.py:34` |
| 麦克风累积样本 | 1,920,000（120s @16k） | `utils/audio.py:16-18` |
| `/client-ws` 总连接数 | 64 | `websocket_handler.py:30` |
| 每用户连接数 | 4（`auth.max_connections_per_user`，仅 oidc 生效） | `routes.py:173-175,199-206` |
| 并发对话任务 | 16 | `conversation_handler.py:19` |
| 并发 `/asr` | 2 | `routes.py:27` |
| `/asr` 上传大小 | 10 MiB | `routes.py:23` |
| `/tts-ws` 并发连接 | 16 | `routes.py:26` |
| `/tts-ws` 文本 | 2000 字符 / 30 句 | `routes.py:24-25` |
| 每用户 MCP 条目（remote + local） | 8 个 | `mcpp/user_servers.py` |
| 单条目请求头 | 16 个 / 单值 4096 字符 | `mcpp/user_servers.py` |
| 用户 MCP URL 长度 | 2048 字符 | `mcpp/user_servers.py` |
| 单个远程 MCP 工具数 | 64 个 | `mcpp/user_servers.py` |
| 单个本地 MCP 工具数 | 64 个 | `mcpp/user_servers.py` |
| 单个工具 `inputSchema` | 64 KiB | `mcpp/user_servers.py` |
| 单次本地注册消息 | 256 KiB | `websocket_handler.py` |
| 工具结果（remote/local） | 512 KiB | `mcpp/user_servers.py` |

### 17.2 超时

| 项 | 值 | 源码 |
| --- | --- | --- |
| `text-delta` 合并间隔 | 50 ms | `conversation_utils.py:30` |
| TTS 单句合成 | 30 s（超时改发静音载荷） | `tts_manager.py:16` |
| TTS 载荷投递等待 | 10 s | `tts_manager.py:17,208-218` |
| 等待 `frontend-playback-complete` | 120 s | `conversation_utils.py:19` |
| 远程 MCP 建连/工具发现 | 10 s（各服务器并发，失败跳过） | `mcpp/user_servers.py` |
| 远程 MCP 单次工具调用 | 15 s | `mcpp/user_servers.py` |
| 浏览器本地 MCP 工具调用 | 30 s（等待 `local-tool-result`） | `mcpp/local_bridge.py` |
| OAuth state cookie | 600 s（默认） | `config_manager/auth.py` |
| 会话 cookie | 7 天（默认） | `config_manager/auth.py` |

### 17.3 WebSocket 关闭码

| Code | Reason | 触发条件 |
| --- | --- | --- |
| 4401 | `Authentication required` | oidc 下无有效会话（`/client-ws`、`/tts-ws`） |
| 1008 | `Origin not allowed` | oidc 下跨站 Origin |
| 1008 | `Unknown client` | `/audio-ws` 的 `client_uid` 缺失/无效/不属于该用户 |
| 1013 | `Too many connections for this user` | 超过每用户或全局连接上限 |
| 1013 | `Server is at capacity` | `/tts-ws` 并发满 |
| 1000 | — | 音频通道被新连接替换、或连接正常清理 |

前端应对 4401 → 跳登录；1013 → 退避重连并提示；1008 → 检查部署是否同源。

---

## 18. 错误与降级行为

| 情况 | 后端行为 | 前端应对 |
| --- | --- | --- |
| JSON 无法解析 | 记日志，忽略该帧 | 保证发送合法 JSON |
| 缺 `type` | 记警告，忽略 | — |
| 未知 `type` | 记警告，忽略，**不断连** | 可安全地前向兼容新消息类型 |
| 处理器抛异常 | 回 `{"type":"error","message":"Invalid request"}`，继续服务 | 提示用户，不必重连 |
| 输入校验失败 | 回 `error`，文案为具体原因 | 直接展示 |
| 音频超限 | 清空**整段**缓冲 + 回 `error` | 提示重录 |
| ASR/TTS/LLM 异常 | 回 `error`，文案含异常信息 | 展示；对话可能已中断 |
| TTS 单句超时/失败 | 用 `audio:null` 静音载荷占位，**顺序不乱** | 正常渲染文本，跳过播放 |
| 历史存储不可用 | `history-list` 返回 `[]`；`create-new-history` 静默无响应 | 显示"历史不可用"而非报错 |
| `history_uid` 未设置 | 对话正常但**不落库** | 连接后立即新建/选择历史 |
| 配置切换失败 | 回 `error`，`"Failed to switch configuration"`（无细节） | 提示重试；细节看服务端日志 |
| 客户端 120s 内不回 `frontend-playback-complete` | 记警告后继续发 `force-new-message` / `chain-end` | 别依赖这个兜底 |
| 客户端断开 | 中断进行中的对话、移出群聊、关闭音频通道、释放 agent/MCP | — |

---

## 19. 已知坑（实现前必读）

1. **麦克风音频是 JSON 浮点数组，不是二进制帧。** 整个后端没有任何二进制 WS 帧。想用 PCM 字节流的话只有 `POST /asr`（整段 WAV 上传）。
2. **`set-model-and-conf` 在 `switch-config` 后不带 `client_uid`。** 首次连接和 `request-init-config` 才带。若前端无条件用该消息覆盖 `client_uid`，切角色后 `/audio-ws` 会连不上（1008 Unknown client）。
3. **连接建立时 `history_uid` 为空，对话不落库。** 必须在开始聊天前发 `create-new-history` 或 `fetch-and-set-history`。`switch-config` 之后同样要重做。
4. **必须回 `frontend-playback-complete`**（不带 `request_id`），否则每轮白等 120s，群聊会卡住全员。
5. **服务端 VAD 不会自动开启对话轮次。** `raw-audio-data` 路径下，后端把检测到的语音塞进录音缓冲后，只回一条 `{"type":"control","text":"mic-audio-end"}` 作为**提示**；前端必须自己再发一条真正的 `mic-audio-end` 消息，才会触发 ASR 和新一轮对话。另外该路径要求 `vad_config.vad_model` 已启用，否则消息被静默丢弃。
6. **`display_text.text` 不剥离 `[joy]` 这类方括号标签。** 前端必须自己处理（剥离或渲染成动作块），否则文本里会出现方括号关键字。
7. **`audio:null` 的静音载荷是正常消息**，不是错误。think 段、TTS 超时都会产生它，必须照常渲染文本并计入句子序号。
8. **`streamed:true` 的载荷不能把 `display_text.text` 再追加一次**，否则文本重复。
9. **群聊键名不对称**：邀请用 `invitee_uid`，移除用 `target_uid`，切配置用 `file`。写错不会报错，只会静默无响应。
10. **单聊打断没有回执。** 别等 `interrupt-signal`（那是群聊专用），发完就自己停播放、收气泡。
11. **`/live2d-models/info` 与 `model_dict.json` 不一致**：前者要求 `<folder>/<folder>.model3.json`，自带模型在 `runtime/` 子目录下。以 `model_dict.json`（经 WS 下发的 `model_info`）为准。
12. **`background-files` 只有 basename**，子目录里的背景图无法正确拼 URL。
13. **oidc 模式下必须同源。** CORS 是 `*` 但 `allow_credentials=False`，跨域拿不到会话；且 WS 的 Origin host 必须等于请求 Host。
14. **`/cache` 受会话保护**，oidc 模式下 `/tts-ws` 返回的 `audioPath` 需要带 cookie 才能取到（同源 + `credentials: "include"`）。
15. **后端不提供任何 i18n 文案**，全部 UI 字符串（包括后端回传的英文 `error.message`、`group-operation-result.message`）都需要前端自己映射/翻译。
16. **没有 HTTP 配置接口**，不要照搬上游文档里的 `/web-tool/api/config` 之类路由，本 fork 没有。
17. 连接建立时会收到**两条 `group-update`**，做幂等处理。
18. `full-text` 是遗留的状态提示（"Thinking..." 等），**不是对话内容**，别追加进气泡。
19. `mic-audio-end` 在缓冲为空时仍会跑一次 ASR（无空判护），可能产生一条空转写。前端应保证有音频才发。
20. 没有历史重命名/分页/单条删除接口。
21. **配置页只有一份 JSON，类型由后端判定。** 不要在前端让用户先选 remote/local；`mode` 来自 `GET /api/mcp/config` 的 `servers[]`。保存后当前会话不热更新，必须重连。
22. **`local-mcp-config` 是本地服务器的唯一来源。** 它给出的 `server_id` 是数据库行 id，不是 JSON 里的名称；`register-local-mcp` / `local-tool-call` / `local-tool-result` 都用这个 id。每次 WS 连接/重连后都要重新连接并重发 `register-local-mcp`，以后端的 `local-mcp-registered` 为准。
23. **浏览器本地 MCP 只在页面打开时可用。** 页面关闭/刷新时正在执行的 `local-tool-call` 会超时（30 s）并作为工具错误返回给 LLM；本地服务必须允许本站 Origin（含 CORS/PNA/`Mcp-Session-Id` 暴露），且页面保持打开。
24. **`local-tool-call.tool_name` 是 MCP 原始工具名。** LLM 看到的是 `l_<hash>_<name>` 这样的暴露名，但服务端回传/调用时已经还原；前端不要再做前缀处理。
25. **不要把 local 当成"服务器侧也能连"的捷径。** local 条目只下发给浏览器，后端不拨号；remote 条目强制公网 HTTPS（保存时和每次连接前重新解析 DNS），用户 `command/args` 一律拒绝。全局 `cuc-kb` 仍由部署方在 `mcp_servers.json` 管理，不受用户配置影响。

---

## 20. 新前端实现清单

**必做（不做就跑不起来）**

- [ ] `GET /api/session` 判断登录态；未登录整页跳 `/auth/login?next=...`
- [ ] 连 `/client-ws`，处理初始三/四条消息，缓存 `client_uid`
- [ ] 连 `/audio-ws?client_uid=<uid>`（强烈建议）
- [ ] 实现 `text-input` 发送 + `text-delta` 流式渲染
- [ ] 实现 `audio` 载荷解码播放（用 `audio_mime`）
- [ ] 收到 `backend-synth-complete` 且播完后回 `frontend-playback-complete`（不带 `request_id`）
- [ ] 连接后 `create-new-history`（或让用户选一条 `fetch-and-set-history`），否则不落库
- [ ] 处理 `control` 的 `conversation-chain-start` / `conversation-chain-end` 做输入框禁用/启用
- [ ] 处理 `error` 消息
- [ ] 心跳：定时发 `{"type":"heartbeat"}`（建议 20~30s），并据此检测断线
- [ ] 断线重连（重连后 `client_uid` 会变，需重新走初始化流程）

**语音输入**

- [ ] `getUserMedia` → 重采样到 16000 Hz 单声道 → Float32 [-1,1]
- [ ] 前端 VAD（推荐 `@ricky0123/vad-web`），分块发 `mic-audio-data`，静音结束发 `mic-audio-end`
- [ ] 渲染 `user-input-transcription`
- [ ] 打断按钮：停播放 + 发 `interrupt-signal`（`text` = 已听到的文本）

**图片输入（可选）**

- [ ] `text-input` 与 `mic-audio-end` 都可带 `images`（≤4 张、单张 base64 ≤8 MiB 字符、`source` ∈ camera/screen/shared/clipboard/upload）
- [ ] 实况摄像头窗口：常驻预览流，每轮语音结束时抓一帧随 `mic-audio-end` 发出；窗口关闭时不带 `images` 字段

**Live2D / 表现层**

- [ ] 用 `model_info.url` 加载模型，按渲染出的可见轮廓自动构图（默认轮廓高 = 视口高度 × `frameHeightRatio`（1.39）、顶部留白 `frameTopRatio`（12%）；两个字段均可按模型覆盖）；缩放/拖拽/移动端双指缩放自行实现
- [ ] `volumes` + `slice_length` + `lipSyncGain` 驱动口型
- [ ] `actions.expressions`（索引数组）/ `actions.motions`（`{group,index?}` 数组）驱动表情动作
- [ ] `idleMotionGroupName` 待机动作、`tapMotions` 点击区域
- [ ] 剥离/渲染 `display_text.text` 里的 `[tag]`
- [ ] `<think>` / `</think>` 折叠块

**历史与设置**

- [ ] 历史抽屉：`fetch-history-list` → 渲染 `uid` / `latest_message.content` / `timestamp`
- [ ] 打开历史：`fetch-and-set-history`，用 `history-data.messages` 重建气泡
- [ ] 切换 / 新建历史或角色前，若本轮仍在生成或播放，先发 `interrupt-signal` 并停止本地音频、口型，避免旧轮串台
- [ ] 新建 / 删除历史
- [ ] 角色切换：`fetch-configs` → `switch-config`，切换后重新选/建历史，并**保留旧的 `client_uid`**
- [ ] 背景：`fetch-backgrounds` → `/bg/<file>`
- [ ] 头像：`/avatars/<avatar>`

**群聊（可选）**

- [ ] 跨标签页协调拿到彼此 `client_uid`（如 BroadcastChannel）
- [ ] `add-client-to-group` / `remove-client-from-group` / `request-group-info`
- [ ] 渲染 `group-update`、`group-operation-result`
- [ ] 播放句子时发 `audio-play-start`；渲染 `forwarded:true` 的静音载荷
- [ ] 一轮结束前禁用发送

**工具调用（可选）**

- [ ] 按 `tool_id` 聚合 `running` → `completed`/`error`，渲染成可折叠状态块，展示 `tool_name`、`content`、`timestamp`

**不需要做**

- 二进制音频帧、`/proxy-ws`、历史重命名、配置写回 HTTP 接口、后端 i18n 拉取

---

## 21. 最小可用客户端伪代码

```ts
const session = await fetch("/api/session").then(r => r.json());
if (!session.authenticated) { location.href = "/auth/login?next=" + encodeURIComponent(location.pathname); return; }

const ws = new WebSocket(`${location.origin.replace(/^http/, "ws")}/client-ws`);
let clientUid: string | null = null;
let audioWs: WebSocket | null = null;
let playbackQueue: Promise<void> = Promise.resolve();
let pendingPlaybackAck = false;

const handle = (msg: any) => {
  switch (msg.type) {
    case "set-model-and-conf":
      if (msg.client_uid) {                       // 坑 2：switch-config 后不带
        clientUid = msg.client_uid;
        audioWs = new WebSocket(`${wsUrl("/audio-ws")}?client_uid=${clientUid}`);
        audioWs.onmessage = (e) => handle(JSON.parse(e.data));
      }
      loadLive2D(msg.model_info);                 // {} 表示无模型
      setActiveCharacter(msg.conf_name, msg.conf_uid);
      break;

    case "full-text":
      setStatus(msg.text);                        // 坑 18：状态提示，不是气泡
      break;

    case "control":
      if (msg.text === "conversation-chain-start") setInputEnabled(false);
      if (msg.text === "conversation-chain-end")   setInputEnabled(true);
      if (msg.text === "interrupt")                stopPlayback();
      break;

    case "text-delta":
      appendStreaming(msg.text, msg.full_text, msg.name, msg.avatar);
      break;

    case "tool_call_status":
      upsertToolCard(msg.tool_id, msg);
      break;

    case "audio":
      enqueueAudio(msg);                          // 见下
      break;

    case "backend-synth-complete":
      pendingPlaybackAck = true;
      playbackQueue.then(() => {
        if (pendingPlaybackAck) { pendingPlaybackAck = false; wsSend({ type: "frontend-playback-complete" }); }
      });
      break;

    case "force-new-message":
      finalizeCurrentBubble();
      break;

    case "user-input-transcription":
      addUserBubble(msg.text);
      break;

    case "history-list":   renderHistoryDrawer(msg.histories); break;
    case "history-data":   rebuildTranscript(msg.messages);   break;
    case "new-history-created": setCurrentHistory(msg.history_uid); break;
    case "history-deleted":     removeHistory(msg.history_uid, msg.success); break;
    case "config-files":        renderCharacterPicker(msg.configs); break;
    case "config-switched":     toast(msg.message); break;
    case "background-files":    renderBackgrounds(msg.files.map(f => `/bg/${f}`)); break;
    case "group-update":        renderGroup(msg.members, msg.is_owner); break;
    case "group-operation-result": toast(msg.message, msg.success); break;
    case "interrupt-signal":    stopPlayback(); break;
    case "heartbeat-ack":       markAlive(); break;
    case "error":               toast(msg.message, false); break;
  }
};

function enqueueAudio(msg: any) {
  // 坑 6/7/8：先剥标签，再决定要不要上屏，静音载荷也要处理
  const text = stripLive2dTags(msg.display_text?.text ?? "");
  if (!msg.streamed && !msg.forwarded && text) appendText(text);
  if (text === "<think>")  { openThinkBlock();  return; }
  if (text === "</think>") { closeThinkBlock(); return; }
  applyActions(msg.actions);                       // expressions / motions

  if (!msg.audio) return;                          // 静音载荷：只显示不播
  const blob = new Blob([base64ToBytes(msg.audio)], { type: msg.audio_mime });
  playbackQueue = playbackQueue.then(() => playWithLipSync(blob, msg.volumes, msg.slice_length));
}

const wsSend = (o: object) => ws.readyState === 1 && ws.send(JSON.stringify(o));

ws.onmessage = (e) => handle(JSON.parse(e.data));
ws.onopen = () => {
  setInterval(() => wsSend({ type: "heartbeat" }), 25000);
  // 坑 3：不建历史就不落库
  setTimeout(() => wsSend({ type: "create-new-history" }), 0);
};

function sendText(text: string, images?: ImagePayload[]) {
  wsSend({ type: "text-input", text, ...(images ? { images } : {}) });
}
```

麦克风（前端 VAD）：

```ts
// AudioWorklet 输出 Float32，重采样到 16000Hz、单声道、[-1,1]
onVadSpeechChunk((chunk: Float32Array) => wsSend({ type: "mic-audio-data", audio: Array.from(chunk) }));
onVadSpeechEnd(() => wsSend({ type: "mic-audio-end" }));
onUserBargeIn(() => { stopPlayback(); wsSend({ type: "interrupt-signal", text: heardSoFar }); });
```

---

## 22. 用户 MCP 与浏览器本地 MCP（2026-10-25）

### 22.1 边界与不可变约定

- **全局 MCP 不动。** `mcp_servers.json` 里的服务器（例如 `cuc-kb`）仍是部署方配置，用户不可见、不可改、不可删；用户配置永远不能覆盖同名全局服务器（`ServerRegistry.merged_with` 会忽略冲突）。
- **配置页只有一份 JSON。** 用户编辑与 `mcp_servers.json` 同形状的 `mcp_servers` 文档，后端逐条判定 `remote`（后端连接）或 `local`（浏览器连接），不要求用户先选类型。
- **按用户隔离。** 配置存在 SQLite 的 `user_mcp_servers` 表里，每条都带 `user_id`；只有该用户的会话会加载。
- **不接受 stdio。** 用户条目只能是 HTTP(S) `url`；`command/args/env/cwd` 会被拒绝（否则等于服务器 RCE）。
- **remote 只允许公网 HTTPS。** 后端会真正建连，因此拒绝 localhost / 私网 / 链路本地 / 元数据地址（否则等于 SSRF）。本机、内网、`.local`、单标签主机名等由浏览器连接，后端不拨号。
- **工具名命名空间。** 全局工具名保持不变；remote 工具暴露为 `u_<hash>_<name>`，local 工具为 `l_<hash>_<name>`。LLM 看到的是暴露名，后端调用 MCP 时用 `FormattedTool.remote_name` 还原成原始工具名。

### 22.2 统一配置：存储、API 与分类

配置 JSON（与部署方 `mcp_servers.json` 同形状）：

```json
{
  "mcp_servers": {
    "my-remote": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ..." },
      "enabled": true
    },
    "my-pc": {
      "url": "http://127.0.0.1:3001/mcp"
    }
  }
}
```

- 顶层只允许 `mcp_servers`；每个条目只允许 `url` / `headers` / `enabled`。
- `enabled` 缺省为 `true`；`headers` 缺省为 `{}`。
- 每用户最多 **8** 个条目（local + remote 合计），其中 local 最多 **4** 个；名称 ≤64 字符且禁止控制字符。

分类规则（`mcpp/user_servers.classify_mcp_url`）：

| URL 情况 | mode | 谁连接 |
| --- | --- | --- |
| `localhost`、`127.0.0.1`、`::1`、私网/链路本地 IP、`.local` / `.lan` / `.internal` / `.home.arpa` / `.corp` / `.home`、无点单标签主机名 | `local` | 浏览器 |
| 主机名解析后任一地址为私网/保留地址 | `local` | 浏览器 |
| 公网 IP 或解析后全部为公网地址，且 scheme = `https` | `remote` | 后端 |
| 公网地址但 scheme = `http` | 拒绝 | — |
| 含 userinfo / fragment / 非法端口 / 解析失败 | 拒绝 | — |

存储（`storage/sqlite.py`，schema version 4；v3 表会自动补 `mode` 列）：

```sql
CREATE TABLE user_mcp_servers (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  headers_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  mode TEXT NOT NULL DEFAULT 'remote',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, name)
);
```

接口（`mcp_routes.py`）：

| 方法 | 路径 | 请求/响应 |
| --- | --- | --- |
| GET | `/api/mcp/config` | `{"config":{"mcp_servers":{...}},"servers":[{id,name,url,headers,enabled,mode}]}`；headers 值一律 `"***"` |
| PUT | `/api/mcp/config` | body `{"config":{"mcp_servers":{...}}}`；全量替换，返回与 GET 相同结构 |
| POST | `/api/mcp/config/test` | body `{"server_id":"..."}`；remote 返回 `{"mode":"remote","tools":[{name,description}]}`；local 返回 `{"mode":"local","tools":[]}`，不做服务端拨号 |

- **PUT 是整份配置的原子替换**：未出现的名称会被删除；同名条目保留原 `id`（local 工具命名空间稳定），改名等于删除+新增。
- `headers` 里的 `"***"` 表示保留同名条目已存的值；新名称/新键使用 `"***"` 会 400。省略某个 header 键等于删除它。
- 错误码：400（JSON/字段/URL/headers/mode/数量校验失败，或 `***` 无法解析）、401（oidc 无会话）、404（`/test` 的 server_id 不存在）、502（remote `/test` 连不上）、503（存储未就绪）。

校验与限额（`mcpp/user_servers.py`）：

- URL：非空、≤2048 字符、`http`/`https`、无 userinfo、无 fragment、端口合法；remote 必须为公网 HTTPS，保存时和**每次建连前**都会重新解析 DNS，所有结果都必须是公网地址（`is_global` 且非 private/loopback/link-local/multicast/reserved/unspecified/site-local）。
- headers：≤16 个；键 `[A-Za-z0-9-]{1,64}`；值 ≤4096 字符、禁止 CR/LF/NUL；禁止 hop-by-hop 头（`Host`、`Cookie`、`Content-Length`、`Transfer-Encoding`、`Connection`、`Upgrade` 等）。
- local 工具：单服务器 ≤64 个、单个 `inputSchema` ≤64 KiB、单次注册消息 ≤256 KiB、结果 ≤512 KiB；remote 工具单服务器同样 ≤64 个、单 schema ≤64 KiB、总 schema ≤256 KiB、结果 ≤512 KiB。
- remote 工具发现并发执行，每个 10s 超时；失败只跳过该服务器，不阻断会话。remote 单次工具调用 15s。
- DNS 校验是 best-effort：保存时和每次建连前各解析一次，仍存在解析与连接之间的 TOCTOU 窗口（DNS rebinding）。更强保证需要网络层出站限制或固定解析结果。

> 说明：`headers` 目前在 SQLite 中明文存储（数据库文件权限 600），API 只返回 `"***"`；local 条目的明文 headers 会通过已认证的 `/client-ws` 下发给同一用户的浏览器。后续如需静态加密，不要复用 `auth.signing_secret`（轮换会导致历史 token 不可解密）。

### 22.3 会话加载与工具命名

连接建立时（`WebSocketHandler._init_service_context`）按 `identity.user_id` 读取全部条目，`split_user_mcp_servers` 按**存储的 mode** 拆成两份：

- `remote` → `ServiceContext.load_cache(user_mcp_servers=...)`，进入服务端 registry；
- `local` → `load_cache(local_mcp_servers=...)`，连接后通过 `local-mcp-config` 下发给浏览器。

`_init_mcp_components`：

1. 只取 `enabled=true` 的 remote 条目，生成内部 key `user:<id>`；
2. 与全局 `enabled_servers` 合并（全局在前，用户在后）；
3. 若角色配置 `use_mcpp: false`，**全局工具仍不启用**，但只要该用户启用了 remote 或注册了 local 工具，会话仍会启用原生工具调用（用户显式 opt-in）；
4. 全局服务器按原顺序串行发现（保持 stdio 行为不变），`user:` remote 服务器并发发现；
5. remote 工具按 `u_<sha1("user:<id>")[:6]>_<sanitized>` 暴露，local 工具按 `l_<sha1("local:<id>")[:6]>_<sanitized>` 暴露，最长 64 字符；同一服务器内重名加 `_2`、`_3`……；全局工具名和 prompt 顺序保持不变。

remote 服务器失败（DNS、TLS、超时、401）只影响该服务器：会话照常启动，只是少了这些工具。

**保存配置不会热更新当前会话。** 保存/启用/删除/改名后需要重连（刷新页面）；local 条目在每次连接/重连后由 `local-mcp-config` 重新下发，浏览器必须重新注册。

### 22.4 浏览器本地 MCP：完整流程

1. 连接建立后，后端发送（在 `set-model-and-conf` 之后）：
   ```json
   {"type":"local-mcp-config","servers":[
     {"server_id":"<db row id>","name":"my-pc",
      "url":"http://127.0.0.1:3001/mcp","headers":{}}
   ]}
   ```
   `server_id` 是数据库行 id，**不是** JSON 里的名称；`headers` 是该条目保存的明文值（仅发给该用户的已认证连接）。没有 local 条目时也发空数组。
2. 页面为每个条目作为 MCP client 用 **Streamable HTTP** 连接：
   - `POST initialize`，`Accept: application/json, text/event-stream`，请求体 `protocolVersion` / `capabilities` / `clientInfo`；
   - 记录响应头 `Mcp-Session-Id`（如果服务端分配），之后每个请求都带上；初始化后带上 `MCP-Protocol-Version`；
   - `POST notifications/initialized`（无 id，202 即可）；
   - 自定义 headers 直接用于请求（`Content-Type` / `Accept` / `MCP-*` 由客户端保留）。
3. `POST tools/list` 拿工具 schema，然后发：
   ```json
   {"type":"register-local-mcp","server_id":"<db row id>","name":"my-pc",
    "tools":[{"name":"read_file","description":"...","inputSchema":{...}}]}
   ```
   `server_id` 必须来自 `local-mcp-config`；后端会拒绝未配置的 id。`name` 仅用于展示，后端以配置中的名称为准。
4. 后端回 `local-mcp-registered`，`tools` 是 `l_...` 暴露名。**以这条 ack 为准**。
5. LLM 要调用时，后端发：
   ```json
   {"type":"local-tool-call","request_id":"...","server_id":"<db row id>",
    "tool_name":"read_file","arguments":{...}}
   ```
   `tool_name` 是原始 MCP 名。页面执行 `POST tools/call`，然后回：
   ```json
   {"type":"local-tool-result","request_id":"...","server_id":"<db row id>",
    "is_error":false,"content_items":[{"type":"text","text":"..."}]}
   ```
6. 页面关闭/刷新 → 本地工具随会话消失；正在执行的调用在 30s 后变成工具错误返回给 LLM。重连后后端会再次下发 `local-mcp-config`，前端应重新连接并重发 `register-local-mcp`（新前端实现已自动处理）。

本地服务要求：

- 必须允许页面 Origin 的 CORS（包括 `POST`/`DELETE`、`Content-Type`、`Mcp-Session-Id`、`MCP-Protocol-Version` 预检），并 `Access-Control-Expose-Headers: Mcp-Session-Id`，否则浏览器读不到会话 id；
- 多数 stdio MCP 需要用户先跑一个 HTTP 包装（例如 `npx supergateway --stdio "..."`），这属于"运行一个命令"，不是安装常驻软件；
- HTTPS 页面访问 `http://127.0.0.1` 时，浏览器可能要求 Local Network Access 权限或受混合内容策略限制，上线前需在目标浏览器实测；
- 本地工具结果总大小 ≤512 KiB，超过会作为工具错误返回。

参考实现：`web/src/components/McpPanel.tsx`（统一 JSON 编辑器 + 解析结果列表）、`web/src/services/mcp.ts`（配置 API）、`web/src/services/localMcpClient.ts`（最小 Streamable HTTP client）、`web/src/services/localMcp.ts`（按 `local-mcp-config` 连接/注册/回传/重连）、`web/src/stores/mcp.ts`（本地状态）。这些是前端实现，不是后端契约。

### 22.5 可观测与日志

- 用户 MCP 配置：日志只记录 `user_id`、条目数、服务器名称/ID、工具数量、失败类型；**不记录 headers**。用户/本地工具的参数不写入服务器日志（`ToolExecutor` 对 `user:`/`local:` 只记录工具名）。
- 本地 MCP：后端记录注册/注销/超时；`local-mcp-config` 的 headers 只发给该用户的已认证连接，`local-tool-call` 的参数只发给该会话的浏览器，均不落库。
- `tool_call_status` 仍照常发给客户端，`tool_name` 为暴露名（`u_...`/`l_...`）；前端按现有工具块渲染即可。群聊中，带 `scoped: true` 的工具状态**只发给工具所有者**，避免把个人工具参数/结果广播给其他成员。

### 22.6 验收清单

- [ ] 全局 `cuc-kb` 的工具名、prompt、调用行为与改造前一致；
- [ ] 用户 A 的服务器/工具不出现在用户 B 的会话；
- [ ] 一份 JSON 同时包含 remote/local 时，GET 的 `servers[].mode` 正确；localhost/私网 → local，公网 HTTPS → remote，公网 HTTP 与 `command/args` → 400；
- [ ] GET `/api/mcp/config` 不回明文 headers；PUT 中 `"***"` 保留旧值；
- [ ] 连接/重连后收到 `local-mcp-config`，`server_id` 与 DB id 一致，浏览器重新注册；`local-mcp-registered` 的 `tools` 与 LLM 看到的名称一致；
- [ ] 本地工具调用能完成 `local-tool-call → tools/call → local-tool-result → tool_call_status → 最终文本`；
- [ ] 页面关闭后调用在 30s 内以工具错误结束，不挂起会话；
- [ ] 用户服务器离线时只丢该服务器的工具，会话仍可正常聊天。

---

## 附录 A：常量索引

| 常量 | 值 | 位置 |
| --- | --- | --- |
| `MAX_WS_CONNECTIONS` | 64 | `websocket_handler.py:30` |
| `MAX_TEXT_INPUT_CHARS` | 4000 | `websocket_handler.py:31` |
| `MAX_IMAGES_PER_MESSAGE` | 4 | `websocket_handler.py:32` |
| `MAX_IMAGE_DATA_CHARS` | 8 MiB 字符 | `websocket_handler.py:33` |
| `IMAGE_SOURCES` | camera/screen/shared/clipboard/upload | `websocket_handler.py:34` |
| `ASR_SAMPLE_RATE` | 16000 | `utils/audio.py:16` |
| `MAX_AUDIO_SECONDS` | 120 | `utils/audio.py:17` |
| `MAX_AUDIO_SAMPLES` | 1,920,000 | `utils/audio.py:18` |
| `MAX_CONCURRENT_CONVERSATIONS` | 16 | `conversation_handler.py:19` |
| `MAX_ASR_UPLOAD_BYTES` | 10 MiB | `routes.py:23` |
| `MAX_TTS_TEXT_CHARS` | 2000 | `routes.py:24` |
| `MAX_TTS_SENTENCES` | 30 | `routes.py:25` |
| `MAX_TTS_CONNECTIONS` | 16 | `routes.py:26` |
| `MAX_CONCURRENT_ASR` | 2 | `routes.py:27` |
| `TTS_SYNTHESIS_TIMEOUT_SECONDS` | 30.0 | `tts_manager.py:16` |
| `TTS_DELIVERY_TIMEOUT_SECONDS` | 10.0 | `tts_manager.py:17` |
| `PLAYBACK_COMPLETE_TIMEOUT_SECONDS` | 120.0 | `conversation_utils.py:19` |
| `TextDeltaBuffer.interval` | 0.05 s | `conversation_utils.py:30` |
| `prepare_audio_payload.chunk_length_ms` | 20 | `utils/stream_audio.py:64` |
| `_PASSTHROUGH_AUDIO_MIME` | mp3/wav/ogg/m4a/aac | `utils/stream_audio.py:10-16` |
| 音频缓存目录 | `cache/` | `tts/tts_interface.py:78` |

配置侧默认值见 `src/open_llm_vtuber/config_manager/*.py`；运行时配置在根目录 `conf.yaml`。

## 附录 B：消息类型总索引

**客户端 → 服务端（`/client-ws`）**

`text-input`、`mic-audio-data`、`mic-audio-end`、`raw-audio-data`、`interrupt-signal`、`frontend-playback-complete`、`ai-speak-signal`、`audio-play-start`、`fetch-configs`、`switch-config`、`request-init-config`、`fetch-backgrounds`、`fetch-history-list`、`fetch-and-set-history`、`create-new-history`、`delete-history`、`add-client-to-group`、`remove-client-from-group`、`request-group-info`、`heartbeat`、`register-local-mcp`、`unregister-local-mcp`、`local-tool-result`

**服务端 → 客户端（`/client-ws` 文本通道）**

`full-text`、`set-model-and-conf`、`config-switched`、`config-files`、`background-files`、`control`、`text-delta`、`tool_call_status`、`local-mcp-config`、`local-tool-call`、`local-mcp-registered`、`local-mcp-unregistered`、`local-mcp-error`、`user-input-transcription`、`force-new-message`、`interrupt-signal`、`group-update`、`group-operation-result`、`history-list`、`history-data`、`new-history-created`、`history-deleted`、`heartbeat-ack`、`error`

**服务端 → 客户端（音频通道：`/audio-ws`，未连接时回落 `/client-ws`）**

`audio`、`backend-synth-complete`

**`/tts-ws`（独立协议，用 `status` 而非 `type`）**

入站 `{"text": ...}`；出站 `{"status":"partial","audioPath","text"}`、`{"status":"complete"}`、`{"status":"error","message"}`

---

*本文档由源码逐条核对生成。若后端改动，请同步更新本文件；相关部署与历史决策见 `HANDOFF.md`。*
