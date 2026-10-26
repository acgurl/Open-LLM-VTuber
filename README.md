![](./assets/banner.jpg)

<h1 align="center">Open-LLM-VTuber</h1>

<p align="center">
A self-hosted, multi-user Live2D voice companion with a rebuilt web client.
</p>

<p align="center">
English | <a href="./README.CN.md">简体中文</a> | <a href="./README.JP.md">日本語 (upstream)</a> | <a href="./README.KR.md">한국어 (upstream)</a>
</p>

<p align="center">
<a href="https://github.com/acgurl/Open-LLM-VTuber/actions/workflows/tests.yml"><img src="https://github.com/acgurl/Open-LLM-VTuber/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
<a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
</p>

**Reference deployment:** <https://vtuber.acgurl.cn/> (OIDC login required)

> This repository is the `acgurl/Open-LLM-VTuber` fork. The AI engine layer is inherited from
> upstream [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber), while the web
> client, authentication, storage, MCP management and deployment workflow are specific to this
> repository. Upstream documentation and screenshots may describe features that no longer exist
> here. The Japanese and Korean READMEs are upstream snapshots and are not maintained in this fork.

## What this project is

Open-LLM-VTuber is a browser-based AI companion with a Live2D avatar. You can talk to it by voice
or text, it replies with streaming text and synthesized speech, and its avatar reacts with
expressions and motions. It also supports visual input (camera, screen capture or uploaded images)
and MCP tools such as search, time or a private knowledge base.

Everything can be self-hosted. The LLM, ASR and TTS layers can run against local engines or cloud
APIs, and authentication, conversation history and generated audio stay on your server.

This fork is **web only**. The upstream Electron desktop client and transparent desktop-pet mode
are not part of this repository.

## What is different from upstream

| Area | This fork |
| --- | --- |
| Frontend | Rebuilt React 18 + Vite + TypeScript client in `web/`; served by the backend from `web/dist` |
| Authentication | Optional OIDC login (Casdoor-compatible) with signed session cookies, per-user connection limits and origin checks |
| History | SQLite repository scoped by internal user id, with one-time import of legacy `chat_history/*.json` |
| MCP | Deployment-level servers plus per-user remote/local MCP configuration and a browser-side bridge for `localhost` endpoints |
| Live2D | Model metadata comes from `model_dict.json`; expressions, motions, tap reactions, pinch/scroll zoom and silhouette-based framing |
| UI | Streaming chat, think blocks, tool cards, history drawer, character/background switching, light/dark/system themes, accent hue, zh/en UI |
| Deployment | Single Dockerfile that builds the frontend in a Node stage; secrets and runtime data stay outside the image |

## Features

- **Voice and text conversation** — browser VAD and microphone input, text input, voice interruption,
  streaming replies, TTS playback with an independent mute toggle, and a separate audio WebSocket so
  large audio frames do not block text deltas.
- **Live2D stage** — expression mapping, motion groups, tap reactions, automatic upper-body framing,
  pinch zoom, scroll-to-zoom and configurable pointer interaction.
- **Vision** — live camera window, camera photo, screen capture or image upload; up to four images
  per message (8 MiB each).
- **Conversation UI** — Markdown with external links, collapsible think blocks, tool-call cards,
  message copy, smart auto-scroll and a per-user history drawer. Text input is capped at 4000
  characters.
- **Characters and scenes** — switch character presets and backgrounds from the settings drawer.
  Character presets are scanned at runtime, so adding a YAML file does not require a restart.
- **Group chat** — invite another browser tab by its connection id; each connection keeps its own
  agent memory.
- **MCP tools** — deployment-managed stdio/HTTP servers, per-user HTTP/SSE servers configured from
  the UI, and browser-local servers for endpoints that the server cannot reach.
- **Multi-user isolation** — with OIDC enabled, history, user MCP servers, TTS cache files and
  browser localStorage keys are scoped per user. The default is a single-user, no-login mode.
- **Model coverage** — OpenAI-compatible APIs, Ollama, Gemini, Claude, DeepSeek, Zhipu, Groq,
  Mistral, LM Studio, llama.cpp; ASR via sherpa-onnx, FunASR, Faster-Whisper, Whisper, Groq and
  Azure; TTS via Azure, Edge, MeloTTS, GPT-SoVITS, CosyVoice, Fish Audio, Bark, pyttsx3 and
  sherpa-onnx.

## Architecture

```text
Browser (web/: React 18 + Vite + TypeScript)
  │  /client-ws   JSON control, streaming text, history, config, mic audio
  │  /audio-ws    TTS audio payloads
  │  /tts-ws      standalone text-to-speech
  ▼
FastAPI (src/open_llm_vtuber/server.py)
  ├─ Auth (single or OIDC) + static hosting (web/dist, models, backgrounds, avatars, cache)
  ├─ WebSocketHandler
  │    └─ one ServiceContext per connection
  │         └─ BasicMemoryAgent → LLM
  ├─ shared ASR / VAD / TTS engines
  ├─ MCP registry (deployment servers, per-user remote servers, browser-local tools)
  └─ HistoryRepository → SQLite
```

Important runtime properties:

- **One WebSocket connection is one session.** Each connection gets its own agent memory. Shared
  engines are reused, but conversation state is not shared between tabs.
- **History is restored into the agent** when a client opens an existing history, so a previous
  conversation can be continued after reconnecting.
- **The whole backend accepts JSON WebSocket frames only.** Microphone audio is sent as an array of
  floats, not as binary PCM. See [BACKEND_API.md](./BACKEND_API.md).
- **The frontend must be served same-origin.** OIDC session cookies are `HttpOnly` and
  credential-less CORS is disabled; the WebSocket origin check also compares the request host.
- **Configuration is loaded at startup.** At runtime you can switch character presets, backgrounds
  and per-user MCP; other configuration changes require a restart.

### Endpoints

| Endpoint | Purpose |
| --- | --- |
| `/client-ws` | Control messages, text deltas, history, character config, microphone audio |
| `/audio-ws?client_uid=...` | TTS audio payloads; falls back to `/client-ws` when absent |
| `/tts-ws` | Standalone text-to-speech synthesis |
| `/proxy-ws` | Optional multi-client fan-out; not mounted in OIDC mode |
| `/healthz` | Readiness: `200 {"status":"ok"}` or `503 {"status":"starting"}` |
| `/api/session` | Current session (`authenticated`, `mode`, `user_id`, `display_name`) |
| `/auth/login`, `/auth/callback`, `/auth/logout` | OIDC authorization-code flow |
| `/api/mcp/config` | Read/save/test the current user's MCP configuration |
| `POST /asr` | Standalone speech-to-text upload |
| `/live2d-models/info` | Scan for Live2D models (the authoritative list is `model_dict.json`) |

The complete message set, payload shapes, limits and close codes are documented in
[BACKEND_API.md](./BACKEND_API.md).

## Quick start (local)

### Prerequisites

- Python 3.10–3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- `ffmpeg` on `PATH`
- A `model_dict.json` describing the Live2D model you want to use
- A character preset in `characters/` (the default template refers to `mao_pro`)

### Run

```bash
uv sync

cd web
npm ci
npm run build
cd ..

uv run run_server.py
```

Open <http://localhost:12393>. Use `uv run run_server.py --verbose` for debug logging.

On first start:

- `conf.yaml` is created from `config_templates/conf.default.yaml` if it does not exist.
- `mcp_servers.json` is created from `config_templates/mcp_servers.default.json` if it does not exist.
- `model_dict.json` is **not** created automatically. It is deployment-specific and intentionally
  untracked, so place one in the project root before starting. A minimal entry looks like this:

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

The microphone requires a secure context. `localhost` is fine; any remote access must use HTTPS
through a reverse proxy.

## Configuration

| Path | Purpose | Tracked |
| --- | --- | --- |
| `conf.yaml` | Main runtime configuration: host/port, storage, auth, agent, LLM, ASR, TTS, VAD, default character | No |
| `characters/*.yaml` | Character presets (persona, model name, avatar, optional engine overrides) | Mostly no |
| `model_dict.json` | Live2D model metadata: URL, scale, lip-sync gain, emotion/motion maps | No |
| `mcp_servers.json` | Deployment-managed MCP servers; may contain tokens | No |
| `web/` | Frontend source; `npm run build` emits `web/dist` | Yes |
| `data/storage/` | SQLite history and legacy import/archive data | No |
| `avatars/`, `backgrounds/`, `live2d-models/`, `models/` | Runtime assets; only a subset is tracked | Partly |
| `cache/` | Generated TTS audio; cleared on process shutdown | No |

### Authentication

`system_config.auth.mode` accepts:

- `single` (default) — no login; every connection is the `default_user_id` user (`local` by default).
- `oidc` — standard authorization-code flow with OIDC discovery, nonce validation and signed session
  cookies. Refresh tokens are not implemented.

Example OIDC configuration:

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

Provide the cookie-signing secret through the environment instead of committing it:

```bash
export VTUBER_AUTH_SECRET="$(openssl rand -hex 32)"
```

Keep the secret stable: changing it invalidates every existing session. OIDC requires HTTPS and a
reverse proxy on the same origin as the app. On the first OIDC start, the legacy single-user history
can be exported to `data/storage/archive/`; the local account is no longer bound to new sessions.

### History

- Default backend: SQLite at `data/storage/open_llm_vtuber.db`.
- All reads and writes are scoped by the internal `user_id`; the UI never sees another user's
  history.
- Existing `chat_history/*.json` files are imported once and moved to
  `data/storage/legacy_history/` (`import_legacy_history: true`).
- Back up the database file together with `data/storage/` before upgrades.

### MCP

Two layers are available:

1. **Deployment-managed servers** from `mcp_servers.json` (stdio or HTTP). Enable tool calling in the
   agent configuration:

   ```yaml
   agent_config:
     agent_settings:
       basic_memory_agent:
         use_mcpp: true
         mcp_enabled_servers: ['time', 'ddg-search']
   ```

2. **Per-user servers** edited in the settings drawer (or via `/api/mcp/config`). This accepts a JSON
   document with `mcp_servers` / `mcpServers` entries using `url`, optional `headers`, `enabled` and
   `type` / `transport` (`sse` or `streamable-http`). stdio commands are rejected.

The backend classifies each URL:

- Public HTTPS endpoints are connected by the server (`remote`).
- `localhost`, loopback and private-network endpoints are connected by the browser (`local`); the
  browser opens the connection directly and registers tool schemas over `/client-ws`.

Per-user MCP changes apply after reconnecting (reload the page). Header values shown as `***` mean
"keep the stored secret". Browser-local HTTP endpoints may require Local Network Access permission
when the page itself is served over HTTPS.

## Docker

The image builds the frontend in a Node stage and serves `/app/web/dist`; runtime data and secrets
are excluded from the image by `.dockerignore`.

```bash
docker build -f dockerfile -t open-llm-vtuber:local .
```

Prepare a `conf/` directory containing at least `conf.yaml`. Optionally place `model_dict.json`,
`characters/`, `live2d-models/`, `avatars/` and `backgrounds/` under `conf/`; the startup script
links them into `/app`. Then run:

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

Notes:

- `conf/conf.yaml` is required; the container exits with an error when it is missing.
- `--network host` makes `127.0.0.1:12393` reachable on Linux. On Docker Desktop, publish the port
  with `-p 12393:12393` and set `system_config.host` to `0.0.0.0`.
- Recreate the container after changing `mcp_servers.json`; a restart does not necessarily re-read
  an atomically replaced bind mount.
- Keep `data/storage/` on a persistent volume. History and per-user MCP configuration live there.

## Deployment notes

- Terminate HTTPS and WebSocket upgrades in a reverse proxy (Caddy, nginx, etc.). The page, API and
  WebSockets must share one origin.
- Preserve the cache policy produced by the app: `/assets/` is immutable, HTML revalidates,
  `/api/`, `/auth/`, `/cache/`, `/web-tool/` and `/model_dict.json` are `no-store`.
- `GET /healthz` is public and is the readiness probe.
- DNS, Cloudflare and Caddy details for the reference deployment are outside this repository and
  recorded in [HANDOFF.md](./HANDOFF.md).

## Character presets

The working tree contains the following presets. Assets for some of them (models, avatars,
backgrounds) are intentionally not tracked, so a fresh clone will only have the subset that is in
Git.

| Preset | Character | Live2D model |
| --- | --- | --- |
| `zh_relu_airi.yaml` | ReLU / AIRI | `hiyori_pro` |
| `zh_haru.yaml` | Haru | `haru` |
| `zh_mao.yaml` | 虹色Mao | `mao` |
| `zh_nahida.yaml` | 纳西妲 | `nahida` |
| `zh_naiwa.yaml` | 奶娃 | `naiwa` |
| `zh_xiaozhi2.yaml` | 小智 | `xiaozhi2` |
| `zh_yifan.yaml` | 小智（弈帆） | `yifan` |
| `en_unhelpful_ai.yaml` | unhelpful_ai | `mao_pro` |

To add a character, copy a preset, change `character_name`, `conf_uid`, `live2d_model_name` and
`persona_prompt`, then drop the file into `characters/`. The frontend discovers it on the next
`fetch-configs`.

## Development

```bash
# backend tests (same command as CI)
uv run --frozen python -m unittest discover -s tests -v

# lint and formatting
ruff check .
ruff format --check .
pre-commit run --all-files
```

Frontend:

```bash
cd web
npm ci
npm run dev      # Vite dev server, proxies WebSocket/API to the backend
npm run build    # type-check and emit web/dist
```

### Project layout

```text
run_server.py                 entry point: config, logger, uvicorn
src/open_llm_vtuber/
  server.py                   FastAPI app, static mounts, health check
  routes.py                   /client-ws, /audio-ws, /tts-ws, /asr
  websocket_handler.py        message routing, sessions, MCP registration
  service_context.py          per-connection engine/session container
  auth/                       OIDC, signed cookies, HTTP guard
  storage/                    HistoryRepository, SQLite, legacy import
  mcpp/                       MCP client, registry, per-user servers, browser bridge
  agent/, asr/, tts/, vad/    engine implementations and factories
  config_manager/             typed YAML configuration
web/                          React + Vite frontend source
characters/                   character presets
config_templates/             default conf.yaml and mcp_servers.json
tests/                        unittest suite
```

## Documentation

| Document | Contents |
| --- | --- |
| [BACKEND_API.md](./BACKEND_API.md) | Complete WebSocket/HTTP contract, payloads, limits, timing, gotchas |
| [HANDOFF.md](./HANDOFF.md) | Production deployment topology, mounts, operations, change history |
| [CLAUDE.md](./CLAUDE.md) | Codebase guide for development agents |
| [config_templates/README.md](./config_templates/README.md) | How the default templates are used |

## Security notes

- In OIDC mode, session cookies are `HttpOnly`, `Secure` (configurable) and `SameSite=Lax`; WS
  connections without a valid session close with code `4401`, and cross-origin WS connections close
  with `1008`.
- Generated TTS files live under `/cache/<user_id>/`; a logged-in user cannot fetch another user's
  file.
- `conf.yaml`, `mcp_servers.json`, `model_dict.json`, `data/` and most model/character assets are
  ignored by Git and `.dockerignore`. Never put API keys or MCP tokens in tracked files.
- Cloud ASR/TTS providers receive audio or text. Use local engines when that is not acceptable.
- The default single-user mode has no authentication. Do not expose it publicly without a reverse
  proxy and access control or OIDC.

## Known limitations

- No desktop client or desktop-pet mode; this fork is browser-only.
- Agent working memory is per WebSocket connection. History can be reloaded from SQLite, but memory
  is not shared between concurrent tabs.
- OIDC has no refresh-token flow; after the session expires, users log in again.
- Most configuration changes require a restart; only character/background switching and per-user MCP
  apply at runtime.
- Browser-local MCP depends on browser permissions and cannot reach arbitrary private services.
- Live2D sample models have their own license terms (see below).

## Credits and license

This project is a fork of
[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) and keeps its modular engine
design. Thanks to the upstream authors and contributors.

The code is released under the [MIT License](./LICENSE).

### Live2D sample models notice

This project includes Live2D sample models provided by Live2D Inc. These assets are licensed
separately under the Live2D Free Material License Agreement and the Terms of Use for Live2D Cubism
Sample Data. They are not covered by the MIT license of this project.

This content uses sample data owned and copyrighted by Live2D Inc. The sample data are utilized in
accordance with the terms and conditions set by Live2D Inc. (See
[Live2D Free Material License Agreement](https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/)
and [Terms of Use](https://www.live2d.com/eula/live2d-sample-model-terms_en.html)).

For commercial use, especially by medium or large-scale enterprises, the use of these Live2D sample
models may be subject to additional licensing requirements. Ensure that you have the appropriate
permissions from Live2D Inc., or use a version of the project without these models.
