![](./assets/banner.cn.jpg)

<h1 align="center">Open-LLM-VTuber</h1>

<p align="center">
一个可自托管、支持多用户的 Live2D 语音 AI 伴侣，前端已完整重写。
</p>

<p align="center">
<a href="../README.md">English</a> | 简体中文
</p>

<p align="center">
<a href="https://github.com/acgurl/Open-LLM-VTuber/actions/workflows/tests.yml"><img src="https://github.com/acgurl/Open-LLM-VTuber/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
<a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
</p>

**参考部署：** <https://vtuber.acgurl.cn/>（需要 OIDC 登录）

> 本仓库是 `acgurl/Open-LLM-VTuber` fork。AI 引擎层继承自上游
> [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)，但网页客户端、认证、
> 历史存储、MCP 管理与部署方式均以本仓库为准。上游文档和截图可能描述了本 fork 已不存在的功能。
> 日文、韩文 README 为上游快照，本 fork 不维护。

## 项目简介

Open-LLM-VTuber 是一个运行在浏览器里的 Live2D AI 伴侣。你可以用语音或文字与它对话，它会以流式
文本和合成语音回复，Live2D 形象会配合表情与动作作出反应。它还支持视觉输入（摄像头、屏幕截图或
上传图片）以及搜索、时间、私有知识库等 MCP 工具。

项目可以自托管：LLM 可接 Ollama/LM Studio 或云 API，ASR 走云 API，TTS 可接云 API 或自建服务；认证、对话历史和生成的音频
都留在自己的服务器上。

本 fork **只提供网页端**。上游的 Electron 桌面客户端和透明桌宠模式不在本仓库范围内。

## 与上游的主要区别

| 方面 | 本 fork |
| --- | --- |
| 前端 | `web/` 下重写的 React 18 + Vite + TypeScript 客户端，构建到 `web/dist` 后由后端托管 |
| 认证 | 可选 OIDC 登录（兼容 Casdoor），签名会话 Cookie、每用户连接数限制、Origin 校验 |
| 历史 | 按内部 user id 隔离的 SQLite 存储，并支持一次性导入旧版 `chat_history/*.json` |
| MCP | 部署级服务器 + 用户级远程/本地 MCP 配置 + 浏览器本地 MCP 桥接 |
| Live2D | 由 `model_dict.json` 驱动的表情、动作、点击反馈、双指/滚轮缩放和按轮廓自动构图 |
| 界面 | 流式对话、think 折叠块、工具卡、历史抽屉、角色/背景切换、昼夜主题、强调色、中英文界面 |
| 部署 | 单个 Dockerfile 在 Node 阶段构建前端；密钥和运行时数据不打进镜像 |

## 功能

- **语音与文字对话** —— 浏览器 VAD 与麦克风输入、文字输入、语音打断、流式回复、独立 TTS 静音开关；
  文本和音频分走两条 WebSocket，避免大音频帧阻塞文字增量。
- **Live2D 舞台** —— 表情映射、动作组、点击反馈、默认上半身构图、双指缩放、滚轮缩放与指针交互。
- **视觉输入** —— 实时摄像头窗口、拍照、屏幕截图或上传图片；每条消息最多 4 张，单张上限 8 MiB。
- **对话界面** —— Markdown 外链、可折叠 think 块、工具调用卡片、复制消息、智能吸底和按用户隔离的
  历史抽屉；文字输入上限 4000 字。
- **角色与场景** —— 在设置抽屉里切换角色预设和背景。角色目录在运行时扫描，新增 YAML 不需要重启。
- **群聊** —— 通过连接 ID 邀请另一个浏览器标签页加入，每个连接仍保留独立的 agent 记忆。
- **MCP 工具** —— 部署级 stdio/HTTP 服务器、用户级 HTTP/SSE 服务器，以及服务器无法访问时由浏览器
  直连的本地 MCP 服务器。
- **多用户隔离** —— 启用 OIDC 后，历史、用户 MCP、TTS 缓存文件和浏览器 localStorage 键都按用户隔离；
  默认是单用户免登录模式。
- **模型支持** —— 兼容 OpenAI 的 API、Ollama、Gemini、Claude、DeepSeek、智谱、Groq、Mistral、
  LM Studio；ASR 支持 Groq Whisper、Azure；TTS 支持 Azure、Edge、OpenAI 兼容接口、ElevenLabs、
  Cartesia、Fish Audio、MiniMax、SiliconFlow、pyttsx3，以及自建的 GPT-SoVITS、CosyVoice、XTTS、
  Spark 服务。后端不再在进程内运行 ASR/TTS/VAD 模型。

## 架构

```text
浏览器（web/：React 18 + Vite + TypeScript）
  │  /client-ws   JSON 控制、流式文本、历史、配置、麦克风音频
  │  /audio-ws    TTS 音频载荷
  │  /tts-ws      独立文字转语音
  ▼
FastAPI（src/open_llm_vtuber/server.py）
  ├─ 认证（single 或 OIDC）+ 静态托管（web/dist、模型、背景、头像、缓存）
  ├─ WebSocketHandler
  │    └─ 每个连接一个 ServiceContext
  │         └─ BasicMemoryAgent → LLM
  ├─ 共享的 ASR / VAD / TTS 引擎
  ├─ MCP 注册表（部署级、用户级远程、浏览器本地工具）
  └─ HistoryRepository → SQLite
```

几个关键事实：

- **一条 WebSocket 连接就是一个会话。** 每个连接有独立的 agent 记忆；引擎共享，但会话状态不在
  标签页之间共享。
- **打开已有历史时会把消息重新载入 agent**，所以断线重连后可以从上次的对话继续。
- **后端只接受 JSON WebSocket 帧。** 麦克风音频是浮点数组，不是二进制 PCM。详见
  [BACKEND_API.md](./BACKEND_API.md)。
- **前端必须与后端同源部署。** OIDC 会话 Cookie 是 `HttpOnly`，且 CORS 不携带凭证；WebSocket
  还会校验请求的 Origin 与 Host 一致。
- **配置在启动时加载。** 运行时可以切换角色预设、背景和用户级 MCP；其他配置改动需要重启。

### 接口

| 接口 | 用途 |
| --- | --- |
| `/client-ws` | 控制消息、文本增量、历史、角色配置、麦克风音频 |
| `/audio-ws?client_uid=...` | TTS 音频载荷；未连接时回落到 `/client-ws` |
| `/tts-ws` | 独立的文字转语音 |
| `/proxy-ws` | 可选的多客户端扇出；OIDC 模式下不挂载 |
| `/healthz` | 就绪检查：`200 {"status":"ok"}` 或 `503 {"status":"starting"}` |
| `/api/session` | 当前会话（`authenticated`、`mode`、`user_id`、`display_name`） |
| `/auth/login`、`/auth/callback`、`/auth/logout` | OIDC 授权码流程 |
| `/api/mcp/config` | 读取、保存、测试当前用户的 MCP 配置 |
| `POST /asr` | 独立的语音转文字上传接口 |
| `/live2d-models/info` | 扫描 Live2D 模型（权威列表仍是 `model_dict.json`） |

完整的消息集、载荷结构、限额和关闭码见 [BACKEND_API.md](./BACKEND_API.md)。

## 本地快速开始

### 环境要求

- Python 3.10–3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ 与 npm
- `ffmpeg` 在 `PATH` 中
- 描述所用 Live2D 模型的 `model_dict.json`；默认角色引用其中的 `mao_pro` 条目。
- 使用默认模型清单时：可访问的 Ollama 服务（`ollama pull qwen2.5:latest`）、可访问 Edge TTS 的网络，以及用于语音识别的 Groq API Key。

### 启动

全新安装请在启动前复制三份最小模型清单，并为服务进程设置 `GROQ_API_KEY`，或在 `asr_models.yaml` 中填写密钥。
如需换用其他提供商，先配置模型条目，再修改角色引用，详见[模型清单](#模型清单)。

```bash
cp config_templates/llm_models.default.yaml llm_models.yaml
cp config_templates/tts_models.default.yaml tts_models.yaml
cp config_templates/asr_models.default.yaml asr_models.yaml
uv sync

cd web
npm ci
npm run build
cd ..

uv run run_server.py
```

打开 <http://localhost:12393>。需要调试日志时使用 `uv run run_server.py --verbose`。

首次启动时：

- 如果不存在 `conf.yaml`，会从 `config_templates/conf.default.yaml` 复制一份。
- 如果不存在 `mcp_servers.json`，会从 `config_templates/mcp_servers.default.json` 复制一份。
- **必须手动准备 LLM、TTS、ASR 三份清单**：服务不会自动创建，请按上面的步骤复制模板。
- **不会自动创建 `model_dict.json`。** 它是每个部署自己的模型清单，按设计不纳入版本管理，请在启动
  前放到项目根目录。一个最小条目如下：

```json
[
  {
    "name": "mao_pro",
    "url": "/live2d-models/mao_pro/runtime/mao_pro.webp.model3.json",
    "kScale": 0.5,
    "lipSyncGain": 1.2,
    "initialXshift": 0,
    "initialYshift": 0,
    "kXOffset": 0,
    "idleMotionGroupName": "Idle",
    "emotionMap": { "neutral": 0, "joy": 3 },
    "motionMap": {}
  }
]
```

麦克风需要安全上下文：`localhost` 可以直接使用，其他设备访问必须通过反向代理配置 HTTPS。

## 配置

| 路径 | 用途 | 是否纳入 Git |
| --- | --- | --- |
| `conf.yaml` | 主配置：host/port、存储、认证、Agent 行为、默认角色及其模型引用 | 否 |
| `characters/*.yaml` | 角色预设（人设、Live2D 模型名、头像、必填的模型引用、可选的 `allowed_users`） | 大部分否 |
| `model_dict.json` | Live2D 模型元数据：URL、缩放、口型增益、表情/动作映射 | 否 |
| `mcp_servers.json` | 部署级 MCP 服务器，可能含 token | 否 |
| `llm_models.yaml` | 必需的语言模型清单，供角色和选择器使用；可能含 API Key | 否 |
| `tts_models.yaml` | 必需的语音合成清单；可能含 API Key | 否 |
| `asr_models.yaml` | 必需的语音识别清单；可能含 API Key | 否 |
| `web/` | 前端源码；`npm run build` 输出到 `web/dist` | 是 |
| `data/storage/` | SQLite 历史与旧版导入/归档数据 | 否 |
| `avatars/`、`backgrounds/`、`live2d-models/`、`models/` | 运行时资源，只有一部分纳入版本管理 | 部分 |
| `cache/` | 生成的 TTS 音频；进程关闭时清空 | 否 |

### 认证

`system_config.auth.mode` 有两个取值：

- `single`（默认）—— 不登录，所有连接都使用 `default_user_id`（默认 `local`）。
- `oidc` —— 标准授权码流程，包含 OIDC discovery、nonce 校验和签名会话 Cookie；未实现 refresh token。

OIDC 配置示例：

```yaml
system_config:
  host: '127.0.0.1'
  port: 12393
  storage:
    backend: 'sqlite'
    sqlite_path: 'data/storage/open_llm_vtuber.db'
    default_user_id: 'local'
    import_legacy_history: true
  auth:
    mode: 'oidc'
    cookie_secure: true
    archive_local_history: true
    oidc:
      issuer: 'https://sso.example.com'
      client_id: 'open-llm-vtuber'
      client_secret: '...'
      redirect_uri: 'https://vtuber.example.com/auth/callback'
      post_logout_redirect_uri: 'https://vtuber.example.com/'
```

会话签名密钥建议通过环境变量提供，不要提交到仓库：

```bash
export VTUBER_AUTH_SECRET="$(openssl rand -hex 32)"
```

密钥必须保持稳定，修改后所有已登录会话都会失效。OIDC 需要 HTTPS，并由反向代理保证应用与页面同源。
首次以 OIDC 启动时，旧的单用户历史可以导出到 `data/storage/archive/`，本地账号不再绑定新会话。

### 历史记录

- 默认后端是 SQLite，路径 `data/storage/open_llm_vtuber.db`。
- 所有读写都按内部 `user_id` 作用域隔离，界面不会看到其他用户的历史。
- 已有的 `chat_history/*.json` 会在首次启动时导入一次，并移动到 `data/storage/legacy_history/`
  （`import_legacy_history: true`）。
- 升级前请把数据库文件和整个 `data/storage/` 一起备份。

### MCP

MCP 分为两层：

1. **部署级服务器**，来自 `mcp_servers.json`（stdio 或 HTTP）。需要在 agent 配置里启用工具调用：

   ```yaml
   agent_config:
     agent_settings:
       basic_memory_agent:
         use_mcpp: true
         mcp_enabled_servers: ['time', 'ddg-search']
   ```

2. **用户级服务器**，在设置抽屉里编辑（或调用 `/api/mcp/config`）。接受 `mcp_servers` /
   `mcpServers` 形式的 JSON，条目支持 `url`、可选 `headers`、`enabled` 以及 `type` / `transport`
   （`sse` 或 `streamable-http`）。stdio 命令会被拒绝。

后端会按 URL 分类：

- 公网 HTTPS 端点由服务器连接（`remote`）。
- `localhost`、回环地址和内网地址由浏览器连接（`local`）；浏览器直接建立连接，并通过
  `/client-ws` 注册工具 schema。

用户级 MCP 修改后需要重新连接（刷新页面）才会生效。请求头显示为 `***` 表示保留已保存的密钥。
当页面本身通过 HTTPS 提供时，浏览器访问本地 HTTP MCP 可能需要在浏览器中授予本地网络访问权限。

## Docker

镜像会在 Node 阶段构建前端并托管 `/app/web/dist`；运行时数据和密钥由 `.dockerignore` 排除，不会
打进镜像。

```bash
docker build -f dockerfile -t open-llm-vtuber:local .
```

准备一个包含 `conf.yaml` 和三份模型清单的 `conf/` 目录。首次部署可执行：

```bash
mkdir -p conf
cp config_templates/conf.ZH.default.yaml conf/conf.yaml
cp config_templates/llm_models.default.yaml conf/llm_models.yaml
cp config_templates/tts_models.default.yaml conf/tts_models.yaml
cp config_templates/asr_models.default.yaml conf/asr_models.yaml
```

然后配置提供商。如果 Ollama 在容器外运行，请确保容器能访问 LLM 清单中的 `base_url`。将 `GROQ_API_KEY`
传入容器（例如先在宿主机导出，再给 `docker run` 加上 `-e GROQ_API_KEY`），或在挂载的
`conf/asr_models.yaml` 中配置密钥。也可以把 `model_dict.json`、`characters/`、`live2d-models/`、
`avatars/`、`backgrounds/` 放进 `conf/`，启动脚本会把它们链接到 `/app`。然后运行：

```bash
docker run -d --name open-llm-vtuber --restart unless-stopped --network host \
  -v "$PWD/conf:/app/conf" \
  -v "$PWD/characters:/app/characters" \
  -v "$PWD/live2d-models:/app/live2d-models" \
  -v "$PWD/avatars:/app/avatars" \
  -v "$PWD/backgrounds:/app/backgrounds" \
  -v "$PWD/models:/app/models" \
  -v "$PWD/data/storage:/app/data/storage" \
  -v "$PWD/data/logs:/app/logs" \
  -v "$PWD/data/cache:/app/cache" \
  -v "$PWD/mcp_servers.json:/app/mcp_servers.json:ro" \
  open-llm-vtuber:local
```

说明：

- `conf/conf.yaml` 是必需项；缺失时容器会报错退出。
- `--network host` 让 Linux 上的 `127.0.0.1:12393` 可直接访问。Docker Desktop 用户请改用
  `-p 12393:12393`，并把 `system_config.host` 设为 `0.0.0.0`。
- 修改 `mcp_servers.json` 后要重建容器；`docker restart` 不一定能重新读取被原子替换的 bind mount。
- 把 `data/storage/` 放在持久卷上，历史和用户级 MCP 配置都在这里。

## 部署要点

- 在反向代理（Caddy、nginx 等）终止 HTTPS，并转发 WebSocket 升级；页面、API 和 WebSocket 必须同源。
- 保留应用产生的缓存策略：`/assets/` 长期 immutable，HTML 需要重新验证，`/api/`、`/auth/`、
  `/cache/`、`/web-tool/` 和 `/model_dict.json` 为 `no-store`。
- `GET /healthz` 是公开接口，可用作就绪探针。
- 参考部署的 DNS、Cloudflare 与 Caddy 细节不在本仓库内，记录在 [HANDOFF.md](./HANDOFF.md)。

## 角色预设

当前工作区包含以下预设。部分模型、头像和背景按设计未纳入版本管理，因此全新 clone 只会得到
Git 中实际跟踪的那一部分资源。

| 预设 | 角色 | Live2D 模型 |
| --- | --- | --- |
| `zh_relu_airi.yaml` | ReLU / AIRI | `hiyori_pro` |
| `zh_haru.yaml` | Haru | `haru` |
| `zh_mao.yaml` | 虹色Mao | `mao` |
| `zh_nahida.yaml` | 纳西妲 | `nahida` |
| `zh_naiwa.yaml` | 奶娃 | `naiwa` |
| `zh_xiaozhi2.yaml` | 小智 | `xiaozhi2` |
| `zh_yifan.yaml` | 小智（弈帆） | `yifan` |
| `en_unhelpful_ai.yaml` | unhelpful_ai | `mao_pro` |

新增角色时复制一份预设，修改 `character_name`、`conf_uid`、`live2d_model_name` 和
`persona_prompt`，并明确填写三个 `model_refs`，再保存到 `characters/`。可参考[角色配置示例](../characters/README.md)。

### 模型清单

三份清单均必需，可在 `conf.yaml` 中分别设置路径。相对路径以服务进程的工作目录为准。

| `system_config` 配置项 | 默认文件 | 顶层键 | 模板 |
| --- | --- | --- | --- |
| `llm_models_file` | `llm_models.yaml` | `models` | [默认](../config_templates/llm_models.default.yaml) · [示例](../config_templates/llm_models.example.yaml) |
| `tts_models_file` | `tts_models.yaml` | `tts_models` | [默认](../config_templates/tts_models.default.yaml) · [示例](../config_templates/tts_models.example.yaml) |
| `asr_models_file` | `asr_models.yaml` | `asr_models` | [默认](../config_templates/asr_models.default.yaml) · [示例](../config_templates/asr_models.example.yaml) |

`conf.yaml` 的默认角色和 `characters/*.yaml` 中的**每个**角色都必须明确填写三个模型 ID，即使与默认角色相同。
必需引用缺失或无效时，角色加载失败，不会回退到内联配置或旧的合并清单。

```yaml
character_config:
  model_refs:
    llm: local-qwen
    tts: edge-default
    asr: groq-whisper
```

连接器的 `system_config.connectors.instances[].character` 是对默认角色的部分覆盖：不写 `model_refs` 则全部继承，
只写部分项目则仅覆盖对应的模型 ID。

- LLM 参数直接写在 `models` 的条目下；语音条目的 `settings` 要填写提供商所需的参数。`pyttsx3_tts` 无需参数，写 `settings: {}`。
- 运行时按需独立检查各清单是否变动。某个文件格式错误时，保留该文件上一次成功加载的版本，不影响其他清单更新。
- 网页端可按账号覆盖角色的默认模型。选回“角色默认”时，使用该角色对应的模型引用。
- 模型可以用 `allowed_users` 限制为指定的内部用户 ID 或已验证的登录邮箱。公开角色（包括默认角色）只能引用公开模型；
  受限角色引用受限模型时，角色允许名单的每一项都必须也出现在模型允许名单中（忽略大小写和首尾空白）。
- 运行时清单可能包含服务地址和密钥，请勿提交到 Git。`${ENV_VAR}` 从服务进程的环境变量取值。
- 使用模型清单的角色应配置 `basic_memory_agent`；`hume_ai_agent` 无法使用清单引用的 LLM，因此不支持用作此配置下的角色 Agent。

#### 从合并模型清单升级

**启动新版前**，先备份 `conf.yaml`、`characters/` 和现有的合并清单，不要用默认模板覆盖已有条目。

1. 将 `models:` 及其条目留在 `llm_models.yaml`（或原 `llm_models_file` 指向的文件）。
2. 将完整的 `tts_models:` 小节复制到 `tts_models.yaml`，将完整的 `asr_models:` 小节复制到 `asr_models.yaml`，
   各自保留为顶层键，再从 LLM 文件删除这两个小节。Docker 部署时，将默认文件名的三份清单放在 `conf/`。
3. 不要改动任何条目的 `id`，以保留角色引用和账号已保存的选择。只有在使用非默认路径时，才需要设置
   `system_config.tts_models_file` 和 `system_config.asr_models_file`。

服务不会自动拆分旧清单，也不会从 LLM 文件中回读语音预设。

#### 从旧版内联模型配置升级

备份 `conf.yaml`、`characters/` 和已有清单，在**启动新版前**手动迁移，不要用最小模板覆盖已有条目。

1. 将每个角色原先实际使用的提供商参数迁入对应的清单条目。把旧的 `llm_provider` 在 `agent_config.llm_configs`
   中对应的参数直接写到 LLM 条目下；将 `tts_config` / `asr_config` 中选中的提供商参数放进语音条目的 `settings`。
   已有清单中依赖继承的语音条目也要补齐 `settings`。
2. 给默认角色及每个独立角色填写 `model_refs.llm`、`model_refs.tts`、`model_refs.asr`，删除旧的内联模型配置。
   保留 Agent 行为设置和 `tts_preprocessor_config`。如果连接器原来内联覆盖了模型，改为在 `character.model_refs` 中引用对应的清单条目。

服务不会自动将旧的内联提供商参数转换为清单条目；仅复制最小模板并不能迁移已有部署。

## 开发

```bash
# 后端测试（与 CI 相同的命令）
uv run --frozen python -m unittest discover -s tests -v

# 代码检查与格式化（ruff/pre-commit 在 `dev` 依赖组，直接 `uv sync` 即会安装）
ruff check .
ruff format --check .
pre-commit run --all-files
```

前端：

```bash
cd web
npm ci
npm run dev      # Vite 开发服务器，把 WebSocket/API 代理到后端
npm run build    # 类型检查并输出 web/dist
```

### 目录结构

```text
run_server.py                 入口：配置、日志、uvicorn
src/open_llm_vtuber/
  server.py                   FastAPI 应用、静态挂载、健康检查
  routes.py                   /client-ws、/audio-ws、/tts-ws、/asr
  websocket_handler.py        消息路由、会话、MCP 注册
  service_context.py          每连接的引擎/会话容器
  auth/                       OIDC、签名 Cookie、HTTP 访问控制
  storage/                    HistoryRepository、SQLite、旧版导入
  mcpp/                       MCP 客户端、注册表、用户级服务器、浏览器桥
  agent/、asr/、tts/、vad/    各引擎实现与工厂
  config_manager/             带类型校验的 YAML 配置
web/                          React + Vite 前端源码
characters/                   角色预设
config_templates/             主配置、模型清单和 MCP 服务器模板
tests/                        unittest 测试集
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [BACKEND_API.md](./BACKEND_API.md) | 完整的 WebSocket/HTTP 契约、载荷、限额、时序与已知坑 |
| [HANDOFF.md](./HANDOFF.md) | 生产部署拓扑、挂载、运维操作与变更记录 |
| [CLAUDE.md](../CLAUDE.md) | 面向开发 agent 的代码库说明 |
| [config_templates/README.md](../config_templates/README.md) | 默认模板的使用方式 |

## 安全说明

- OIDC 模式下，会话 Cookie 为 `HttpOnly`、`Secure`（可配置）、`SameSite=Lax`；没有有效会话的
  WebSocket 会以 `4401` 关闭，跨域 WebSocket 以 `1008` 关闭。
- 生成的 TTS 文件位于 `/cache/<user_id>/`，已登录用户无法获取其他用户的文件。
- `conf.yaml`、`llm_models.yaml`、`tts_models.yaml`、`asr_models.yaml`、`mcp_servers.json`、`model_dict.json`、
  `data/` 以及大部分模型/角色资源都被 Git 和 `.dockerignore` 排除。不要把 API key 或 MCP token 写进受版本管理的文件。
- 云 ASR/TTS 会把音频或文本发送给第三方。ASR 只有云端选项；TTS 无法接受时请改用自建服务（GPT-SoVITS、CosyVoice、XTTS、Spark）。
- 默认的 single 模式没有认证。不要在没有任何反向代理或访问控制的情况下直接暴露到公网；需要公开
  访问时请启用 OIDC。

## 已知限制

- 没有桌面客户端和桌宠模式，本 fork 只提供网页端。
- agent 工作记忆按 WebSocket 连接隔离；可以从 SQLite 重新载入历史，但并发标签页之间不共享记忆。
- OIDC 没有 refresh token；会话过期后需要重新登录。
- 大部分配置修改需要重启。清单内容在运行时独立刷新；修改清单路径仍需要重启。
- 浏览器本地 MCP 受浏览器权限限制，无法访问任意内网服务。
- B 站直播（`scripts/run_bilibili_live.py`）依赖 `blivedm`，本仓库不内置也不作为依赖发布：需手动将 <https://github.com/xfgryujk/blivedm> 克隆到仓库根目录的 `blivedm/`，并安装 `bilibili` extra（`uv sync --extra bilibili`）。Docker 镜像不包含它。
- Live2D 示例模型有独立的许可条款（见下）。

## 致谢与许可

本项目 fork 自 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)，并保留其模块化
引擎设计。感谢上游作者与贡献者。

代码以 [MIT License](../LICENSE) 发布。

### Live2D 样本模型声明

本项目包含由 Live2D Inc. 提供的 Live2D 样本模型。这些资产根据 Live2D 免费素材许可协议和 Live2D
Cubism 样本数据使用条款单独授权，不受本项目 MIT 许可证的约束。

本内容使用由 Live2D Inc. 拥有并享有版权的样本数据。样本数据的使用符合 Live2D Inc. 制定的条款和
条件。（参见 [Live2D 免费素材许可协议](https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/)
和 [使用条款](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)）。

对于商业用途，特别是中型或大型企业，使用这些 Live2D 样本模型可能需要额外的许可要求。如果你计划
将本项目用于商业目的，请确保已获得 Live2D Inc. 的适当许可，或使用不包含这些模型的项目版本。
