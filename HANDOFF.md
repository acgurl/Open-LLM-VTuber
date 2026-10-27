# Open-LLM-VTuber 部署交接

更新日期：2026-10-23（OAuth 入口切换、历史列表刷新部署）

## 1. 现状概览

| 项 | 值 |
| --- | --- |
| 访问地址 | https://vtuber.acgurl.cn/ （未登录 302 → Casdoor 登录） |
| 服务器 | 甲骨文凤凰城，Ubuntu 24.04 ARM64，SSH 别名 `oracle` |
| 部署目录 | `/home/ubuntu/open-llm-vtuber` |
| 容器 | `open-llm-vtuber`，镜像 `open-llm-vtuber:1.2.1-history-refresh-20261023`，`--network host`，`--restart unless-stopped` |
| 应用监听 | `127.0.0.1:12393`（FastAPI + WebSocket `/client-ws`，前端由后端静态托管） |
| 登录 | OIDC / Casdoor，应用 `app-acgurl`（组织 `acgurl`，client_id `9f4231ba6649ec33bdd7`），issuer `https://sso.acgurl.cn`，回调 `https://vtuber.acgurl.cn/auth/callback`；`auth.mode: oidc`；旧 `built-in/open-llm-vtuber` 保留用于回滚 |
| 健康检查 | `https://vtuber.acgurl.cn/healthz` → 200 `{"status":"ok"}`（公开） |
| 反向代理 | Caddy，`/etc/caddy/Caddyfile` 第 129-140 行，站点 `vtuber.acgurl.cn, vtuber.acgurl.qzz.io`，`flush_interval -1` 支持 WebSocket |
| DNS / 优选 | DNSPod 按线路解析到 Cloudflare 优选 IP；Cloudflare SaaS custom hostname 经 `origin.acgurl.qzz.io` 回源；`/opt/cf2dns-sync/sync_cf_bestip.py` + `/etc/cron.d/cf2dns_sync` 每 2 小时同步 |
| ASR / TTS | Groq `whisper-large-v3-turbo` + Azure Speech（`azure_tts`，japaneast F0，`zh-CN-XiaoyiNeural`） |
| 历史存储 | SQLite `data/storage/open_llm_vtuber.db`，按内部 `user_id` 隔离；旧 `local` 历史已归档、不再绑定会话 |
| 本地历史归档 | `data/storage/archive/local-history-archive.json`（104 条非空历史 / 349 条消息，ubuntu:ubuntu 600） |

## 2. 模型与角色

- 默认 LLM 已是 DeepSeek：服务器 `conf/conf.yaml` 中 `basic_memory_agent.llm_provider: 'deepseek_llm'`，模型 `deepseek-flash`，temperature 0.7，`base_url` 使用原生默认 `https://api.deepseek.com/v1`。
- ASR 仍为 Groq `whisper-large-v3-turbo`；TTS 于 2026-10-22 切换为 Azure Speech（`azure_tts`，资源 `speech-phx-tts-jp-1022`，`japaneast`，音色 `zh-CN-XiaoyiNeural`）。Key 只放在服务器 `conf/conf.yaml` 和 `~/.config/azure-speech.env`，本地配置是占位符。Edge TTS 配置仍保留但不再启用；此前为缩短句间停顿做的 ffmpeg 裁剪已全部移除。
- DeepSeek / Groq API key 只存在于服务器 `conf/conf.yaml`，**不要写进仓库或角色卡**。本地 `conf/conf.yaml` 中 Groq key 是占位符。
- 默认角色已改为 AIRI（`conf_name: 'ReLU / AIRI (Hiyori)'`，Live2D `hiyori_pro`），刷新页面即为 AIRI + DeepSeek；本地根目录 `conf.yaml` 与 `conf/conf.yaml` 已同步该改动。
- 本地 `conf/conf.yaml` 的 DeepSeek key 是占位符，**不要用本地 conf 覆盖服务器 conf**。
- `llm_configs.openai_compatible_llm`（本机 Sub2API，`127.0.0.1:8080`，`gemini-3.8-flash`）仍保留但已不再被默认使用。
- 角色切换按连接生效，刷新后回到 `conf.yaml` 的默认角色（现在是 AIRI + DeepSeek）。

当前角色预设：

- `zh_relu_airi.yaml` — ReLU / AIRI (Hiyori)，Hiyori Pro 模型、头像 `avatars/relu.png`；显式覆盖 `deepseek_llm` 的 model `deepseek-flash` / temperature 0.7。
- `en_nuke_debate.yaml`、`en_unhelpful_ai.yaml`、`zh_米粒.yaml`、`zh_翻译腔.yaml` — 均不写 `agent_config`，继承默认 DeepSeek。
- `zh_mao_deepseek.yaml` 已删除（默认已是 DeepSeek，属重复预设）。

## 3. 文件与挂载

服务器 `run-container.sh` 挂载：

```
conf -> /app/conf
characters -> /app/characters
live2d-models -> /app/live2d-models
avatars -> /app/avatars
models -> /app/models
data/logs -> /app/logs
data/cache -> /app/cache
data/chat_history -> /app/chat_history
data/storage -> /app/data/storage
mcp_servers.json -> /app/mcp_servers.json (ro)
```

要点：

- `cuc-kb` 已从 stdio 子进程改为 Streamable HTTP：`http://127.0.0.1:8765/mcp`，Bearer token 在服务器 `mcp_servers.json` 中。容器是 `--network host`，所以直接走回环；不再挂载 `/home/ubuntu/cuc-kb/mcp_server.py` 和 `.env`。
- `mcp_servers.json` 含 token，权限 `600`；`.dockerignore` 已排除 `/mcp_servers.json`，不会打进镜像。修改该文件（尤其是轮换 token）后需用 `run-container.sh` 重建容器，`docker restart` 不会重新解析被原子替换的 bind mount。
- HTTP MCP 的传输层会创建 AnyIO task group，因此客户端在每次工具调用内建立并关闭会话，避免在 WebSocket 任务里关闭对话任务创建的会话。
- 回滚到 stdio 方案：恢复 `data/backups/mcp-http-20261022-033458/run-container.sh` 与 `mcp_servers.json`，镜像改回 `open-llm-vtuber:1.2.1-tts-gap-20261021`，再执行 `bash run-container.sh`。

- 实际生效的模型字典是 `conf/model_dict.json`。容器启动脚本会把 `/app/conf/model_dict.json` 软链到 `/app/model_dict.json`，**不要直接 bind mount `/app/model_dict.json`**，否则软链失败、容器重启循环。
- Hiyori 模型：`live2d-models/hiyori_pro/runtime/hiyori_pro_t11.model3.json`，约 4.8 MB；`model_dict.json` 中 `kScale` 为 0.65（前端会把该值乘 2）。
- 前端是 `frontend` 子模块，构建产物里已把 WS/base URL 改为同源：`(location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/client-ws"`。修改文件为 `frontend/assets/main-nu7uwxNJ.js`。
- 当前镜像 `open-llm-vtuber:1.2.1-history-refresh-20261023`（2026-10-23 历史列表刷新；`1.2.1-refactor-20261023`、`1.2.1-oidc-20261023-r2`、`1.2.1-storage-20261023-r2`、`1.2.1-frontend-refactor-20261023`、`1.2.1-deploy-20261023-47bf2c7`、`1.2.1-deploy-20261023` 仍保留可回滚）。只有改源码/前端/依赖时才需要重建：

```bash
ssh oracle
cd /home/ubuntu/open-llm-vtuber
docker build -f dockerfile -t open-llm-vtuber:1.2.1-<change>-20261023 .
bash run-container.sh
```

- Azure Speech 资源：`speech-phx-tts-jp-1022`（`rg-tts-japaneast`，japaneast，F0，50 万神经字符/月、20 次请求/60 秒）。Key 来源 `/home/ubuntu/.config/azure-speech.env`（600），服务器 `conf/conf.yaml` 的 `azure_tts.api_key` 已写入真实值（文件已 chmod 600）；不要把 key 提交到仓库或贴到聊天。
- 通用 TTS 连接池：`src/open_llm_vtuber/tts/pooled_tts.py` 的 `PooledTTSEngine` 管理最多 `max_clients`（默认 3）个可复用客户端，线程安全、LIFO 复用、失败自动丢弃并重建。新接入的 SDK/HTTP TTS 只需实现 `_create_client()`、`_synthesize(client, text, output_path)` 和可选 `_close_client()`。Azure 已接入；`TTSInterface.close()` 在配置切换时由 `ServiceContext.init_tts()` 调用，释放旧池。
- Azure 引擎 `src/open_llm_vtuber/tts/azure_tts.py`：使用 Speech SDK，输出 `Audio24Khz48KBitRateMonoMp3`，SSML 里加 `<mstts:silence type="Tailing" value="{tailing_silence_ms}ms"/>`（当前 0）。不再做任何音频后处理；旧的 Edge `_trim_boundary_silence()`、`trim_silence` / `leading_silence_ms` / `trailing_silence_ms` 配置和测试已删除。
- Azure 原生输出的句尾仍不固定：短句可能被服务端补到约 1.9 s（句尾 0.4–1.0 s），较长句通常约 0.17 s；`Tailing=0` 只能部分压缩，无法完全消除。这是切换到 Azure 后的已知取舍。

- 服务器源码目录**不是 git 仓库**。更新时从本地同步变更文件（例如 `tar -cf - <files> | ssh oracle "cd /home/ubuntu/open-llm-vtuber && tar -xf -"`），覆盖前先备份。
- 上一版镜像 `open-llm-vtuber:1.2.1-audit-20261021` 仍保留；部署脚本备份为 `run-container.sh.bak.refactor.20261021`，源码备份为 `backup-src-refactor-20261021.tar.gz`。回滚时恢复脚本并执行 `bash run-container.sh`。
- 更早镜像 `open-llm-vtuber:1.2.1-groq-edge`、`open-llm-vtuber:1.2.1-deepseek` 等仍保留可回滚。
- 依赖变更记录：`uv.lock` 中 edge-tts 7.2.7 → 7.3.1（7.2.7 在 Oracle 上 WSS 握手 403，7.3.1 正常）。

## 4. 常用操作

```bash
# 改配置后重启（配置在启动时加载）
ssh oracle "docker restart open-llm-vtuber"

# 改挂载/镜像后重建容器（不要手写 docker run）
ssh oracle "bash /home/ubuntu/open-llm-vtuber/run-container.sh"

# 看日志
ssh oracle "docker logs -f --tail 200 open-llm-vtuber"

# 站点检查
curl -sI https://vtuber.acgurl.cn/
```

新增角色只需把 YAML 放进服务器 `characters/`，无需重启；前端 `fetch-configs` 会实时扫描目录。

调 Azure 音色/语速只需改服务器 `conf/conf.yaml` 的 `azure_tts.voice` / `pitch` / `rate` / `tailing_silence_ms`，然后 `docker restart open-llm-vtuber`，不需要重建镜像。Key 轮换见 `~/.config/azure-speech.env` 与 Azure 文档。

## 5. WebSocket 验证方法

健康检查：

```bash
curl -s https://vtuber.acgurl.cn/healthz
# {"status":"ok"}
```

`/tts-ws` 可直接用 Node 验证：发送 `{"text":"你好。测试。"}`，应依次收到 `status=partial`（含 `audioPath`）与 `status=complete`。

消息格式（公网 `wss://vtuber.acgurl.cn/client-ws`）：

- 取角色列表：`{"type":"fetch-configs"}` → 回 `config-files`
- 切角色：`{"type":"switch-config","file":"zh_米粒.yaml"}`
- 发消息：`{"type":"text-input","text":"你好"}`
- AI 回复文本在 `audio` 消息的 `display_text.text`（不是独立 `full-text`）

Node 24 可直接用全局 WebSocket，无需装依赖：

```bash
node --input-type=module -e '
const ws = new WebSocket("wss://vtuber.acgurl.cn/client-ws");
ws.onmessage = e => { const m = JSON.parse(e.data);
  if (m.type === "config-files") { console.log(JSON.stringify(m.configs)); process.exit(0); } };
ws.onopen = () => ws.send(JSON.stringify({ type: "fetch-configs" }));
setTimeout(() => process.exit(1), 10000);'
```

服务端成功的标志：日志出现 `Initializing ASR: groq_whisper_asr`、`Initializing TTS: azure_tts`、`Initializing LLM: deepseek_llm`。

ASR 可用 `/asr` 接口单独验证（16kHz、16-bit 单声道 WAV）：

```bash
docker exec open-llm-vtuber curl -s -F "file=@/tmp/test16.wav" http://127.0.0.1:12393/asr
```

## 6. 已验证

- 2026-10-21 把默认角色由 Mao 切换为 AIRI（Hiyori Pro）后复测：页面加载即渲染 Hiyori，WS `set-model-and-conf` 返回 `conf_name=ReLU / AIRI (Hiyori)`、`model_info.name=hiyori_pro`；Hiyori 模型/纹理资源均 200，容器日志为 `Initializing Live2D: hiyori_pro`、`Initializing LLM: deepseek_llm`。
- 2026-10-21 13:15 部署 `open-llm-vtuber:1.2.1-refactor-20261021` 后复测：站点 HTTP 200、`/healthz` 200、7 个角色预设、切换 `zh_米粒.yaml` 成功、文本对话有回复、`/tts-ws` 两句合成正常、`/asr` 非法文件返回 400 JSON 错误；日志无 ERROR/CRITICAL/Traceback。
- 2026-10-22 切换 `cuc-kb` 到 HTTP MCP 后复测：容器内 `127.0.0.1:8765` 可达，4 个工具正常；WebSocket 提问“学校宿舍的床尺寸是多少？”触发 `kb_search` 并返回 2000×900×2200 mm；断连后日志无 MCP cancel-scope 错误、无 ERROR/Traceback，站点与 `/healthz` 均 200。
- 2026-10-22 部署 `open-llm-vtuber:1.2.1-azure-pool-20261022` 后复测：日志 `Initializing TTS: azure_tts`，工厂读到 `voice=zh-CN-XiaoyiNeural / pitch=0 / rate=1 / tailing=0`，连接池 `max_clients=3`；冷启动首轮 6 句 `TTS ready` 0.76–1.31 s（3 个连接同时冷建），第二轮热池 0.44 s / 1.16 s（含 payload 准备）；音频 MP3 正常，句尾表现与此前一致；`/healthz` 200，无 ERROR/Traceback。全套 47 个测试通过。
- 2026-10-22 Azure vs Edge 合成延迟基准（Oracle ARM，同音色 `zh-CN-XiaoyiNeural`，各 4 次中位数，只计 `generate_audio`）：Azure 复用连接池后 12/36 字为 **0.218/0.282 s**，Edge 为 **0.530/0.712 s**，Azure 快约 0.31/0.43 s；4 路并发的 36 字请求总墙钟 0.876 s（池大小 3）。冷启动每个新客户端首调约 0.97 s，稳定后约 0.2–0.3 s。对比未复用版本（0.83/1.01 s），单句省约 0.6–0.7 s。
- 2026-10-22 ASR 池化评估：Groq ASR 在 `__init__` 只创建一次 `Groq` client，HTTP 连接由 SDK 复用；4.25 s 音频实测首调 0.450 s、后续 0.256–0.451 s，差异主要是服务抖动，池化无收益。本地 ASR（sherpa/faster-whisper/funASR/whisper）已在实例内共享模型，池化会重复加载模型、增加内存。Azure ASR 每次新建 `SpeechRecognizer` 且绑定 `AudioConfig`，复用需要改推流/PCM 输入，暂不改造。结论：当前 ASR 不接入连接池。
- 站点 HTTP 200，前端正常加载；Hiyori 渲染高度约 560 px，比例合适。
- 默认 Mao 与「米粒」均能通过 DeepSeek 正常回复并完成 TTS。
- 逐一切换全部角色卡，日志均初始化 `deepseek_llm`（`zh_mao_deepseek` 因与当前配置完全一致被 `init_agent` 跳过重建，属正常优化；该文件已删除）。

## 7. 已知问题与注意事项

- `en_nuke_debate.yaml` 使用 `shizuku-local`，但 `model_dict.json` 中没有该模型，切换时会打一条 `Error initializing Live2D ... shizuku-local not found`；不影响 LLM/文本对话，如需修复可改用它存在的模型或补模型条目。
- `src/open_llm_vtuber/websocket_handler.py` 的发送串行化补丁已提交到 `acgurl/Open-LLM-VTuber` main；升级上游时注意保留。
- Groq ASR 实测中文准确、3.5s 语音约 0.3-0.5s，但静音/噪声会幻觉出 `Thank you.`；浏览器 VAD 可过滤大部分，必要时在 ASR 结果进 LLM 前加最短时长/语气词过滤。Groq 会把音频发往第三方，隐私敏感时切回本地 SenseVoice。
- Edge TTS 已停用但配置保留；原 `_trim_boundary_silence()` 静音裁剪及三个 Edge 配置项已删除。切换到 Azure 后不再做任何音频后处理。Azure 短句仍可能被服务端补出 0.4–1.0 s 尾音（`mstts:silence Tailing=0` 只能部分压缩），这是当前已知问题；若需严格一致的句间停顿，需要前端无缝调度或重新引入裁剪。
- 历史已改为 SQLite，数据库在宿主机 `data/storage/open_llm_vtuber.db`；`data/chat_history` 仅保留为旧 JSON 迁移入口，首次启动后应清空。重建容器不会丢失历史。
- `.dockerignore` 已排除 `/conf/`、`/data/`、`/mcp_servers.json`、`/model_dict.json` 等运行时文件，密钥不会打进镜像；服务器 `conf/conf.yaml` 是唯一真实密钥来源。
- 服务器保留备份 `conf/conf.yaml.bak.deepseek.20261021005452`；换音色前备份为 `conf/conf.yaml.bak.hsiaoyu.20261022060303`、`conf/conf.yaml.bak.xiaoyi.20261022060926`；切 Azure 前备份为 `conf/conf.yaml.bak.azure.20261022064712`；连接池改造前源码备份为 `*.bak.pool.20261022065834`。Azure 源码/部署脚本备份见 `*.bak.azure.20261022*`、`run-container.sh.bak.azure-pool.20261022*`。
- 2026-10-23 工作区已干净，`main` 与 `origin/main` 同步于 `e5555e1`；`HANDOFF.md` 本身仍未跟踪（按惯例保留在服务器/本地交接文档中）。
- 站点公网可访问并消耗 DeepSeek / 本地服务额度，必要时加访问保护。

## 8. 可选后续

- 如需把默认角色改回 Mao：把 `conf/conf.yaml` 中 `character_config` 的 conf_name / conf_uid / live2d_model_name / character_name / avatar / persona_prompt 改回 Mao 的值并重启容器；服务器改动前备份在 `conf/conf.yaml.bak.airi.20261021`。
- 若彻底停用本机 Sub2API，可删除 `conf.yaml` 中 `openai_compatible_llm` 配置块。
- 若要让句间停顿严格一致：可在前端把逐段播放改为 Web Audio 无缝调度，或在 Azure 输出后重新加一层静音裁剪；当前按要求未做后处理。
- 新增角色资源（`characters/zh_relu_airi.yaml`、`live2d-models/hiyori_pro/`、`avatars/relu.png`）仍未纳入版本管理；可整理提交或在服务器单独备份。

## 9. 2026-10-22 前端加载优化（缓存 + 拆包 + WebP）

- 缓存头由服务器 Caddy 的 vtuber 站点块统一设置：`/assets/*` 1 年 immutable、`/libs/*` 30 天、`/live2d-models|bg|avatars` 7 天 + SWR、HTML `no-cache`、`/cache/*` no-store；`.webp` 强制 `Content-Type: image/webp`。Caddyfile 备份 `/etc/caddy/Caddyfile.bak.cache.*`。
- Cloudflare（zone `acgurl.qzz.io`）：关闭 Rocket Loader（此前会把入口 `<script type="module">` 改写成带 hash 的 type 并延后下载）；在原有 `/v1/*` bypass 后追加 Cache Rule「Cache frontend static assets at edge」，覆盖 `/assets/ /libs/ /live2d-models/ /bg/ /avatars/ /web-tool/ /favicon.ico`，Edge TTL 30 天；浏览器 TTL 继续由源站 Cache-Control 决定。实测 `.wasm/.json/.moc3/.webp` 均 MISS→HIT，HTML 已恢复原生 module。
- Hiyori 贴图改为 WebP q95 + exact alpha：`texture_00/01` 4.32MB → 0.87MB；`hiyori_pro_t11.model3.json` 已指向 `.webp`，原 PNG 保留。备份 `hiyori_pro_t11.model3.json.bak.webp.20261022`。
- 前端把 `@ricky0123/vad-web` 改为动态 import：主包 2.09MB → 1.31MB（Brotli 约 553KB → 381KB），VAD/ONNX 拆成 578KB 按需 chunk。`frontend-streaming.patch` 已追加该 diff。新构建产物：`main-e_nUTYBA.js`、`index-CAZTsS-s.js`，CSS 未变。
- 部署：`run-container.sh` 镜像标签改为 `open-llm-vtuber:1.2.1-cache-webp-20261022`（备份 `run-container.sh.bak.cachewebp.20261022`）；旧镜像保留回滚。前端旧文件备份在服务器 `data/backups/frontend-20261022-lazyvad/`。
- 验证：`/healthz` 200；页面 WS 已连接、Hiyori 正常渲染、无声卡权限时不崩溃；首包与模型资源缓存命中正常。
- 注意：CF API Token 曾在聊天中明文出现，使用后应删除/轮换；Token 仅存于本机 `~/.cloudflare-token`（不应提交）。
- 注意：2026-10-22 起后端不再在连接时发送 `start-mic`，VAD chunk 只在用户手动开启麦克风时按需拉取。
- 模型或贴图更新后，CF 边缘会保留旧文件最多 30 天；当前 Token 已验证有 Cache Purge 权限，可 purge `/live2d-models/*` 对应 URL（或在 Dashboard 清理缓存）。

## 10. 2026-10-22 麦克风默认关闭

- 后端 `_send_initial_messages` 不再下发 `{"type":"control","text":"start-mic"}`；前端 `micOn` 由 localStorage 持久化改为运行时 `useState(false)`，避免刷新后按钮显示开启但 VAD 未启动。
- 前端产物更新为 `main-dpQl0Hum.js` + `index-DZ-Ietiz.js`（CSS 仍 `main-QEkl09-0.css`），`frontend-streaming.patch` 已同步。
- 部署镜像 `open-llm-vtuber:1.2.1-micoff-20261022`，`run-container.sh` 已更新；备份 `run-container.sh.bak.micoff.20261022`、`data/backups/micoff-20261022-074616/`。
- 验证：`/healthz` 200；WS 初始化 4 条消息中无 `start-mic`；页面引用新主包，产物中不再读取 `micOn` localStorage。

## 11. 2026-10-22 文本/音频双 WebSocket

- 后端新增 `/audio-ws`（query `client_uid`）：音频 payload 与 `backend-synth-complete` 走这条连接；`/client-ws` 只保留文字 `text-delta`、控制/配置/历史消息。两条连接各有独立发送锁，音频大帧不再阻塞文字。
- 前端在主连接收到 `set-model-and-conf.client_uid` 后自动连接 `/audio-ws`；断线 2 秒重连；音频连接未就绪时后端自动回退主连接。`backend-synth-complete` 必须发在音频通道、排在最后一段 `audio` 之后，否则主通道的完成信号会超过仍在传输的大音频帧，前端提前收尾。
- 前端构建产物：`main-zChVrlgt.js` + `index-zTFGkP5B.js`（VAD chunk），CSS 仍 `main-QEkl09-0.css`；`frontend-streaming.patch` 已重新生成。
- 部署镜像 `open-llm-vtuber:1.2.1-split-ws-20261022`；`run-container.sh` 已更新，备份 `run-container.sh.bak.splitws.20261022-161611`、`run-container.sh.bak.splitws.deploy`；源码/前端备份 `data/backups/split-ws-20261022-161611/`。
- 验证：`/healthz` 200；双连接探针收到 4 段音频全部经 `/audio-ws`，`backend-synth-complete` 在同通道最后到达；`text-delta` 间隔约 10–50ms，最大 359ms（模型侧停顿）；浏览器端主连接与音频连接均建立；日志无 ERROR/Traceback。
- 回滚：恢复 `data/backups/split-ws-20261022-161611/` 下的源码/前端，把 `run-container.sh` 改回 `open-llm-vtuber:1.2.1-micoff-20261022`，执行 `bash run-container.sh`；旧镜像仍保留。
- 注意：Cloudflare 不缓存 WebSocket（`/client-ws` 返回 `cf-cache-status: DYNAMIC`；50ms heartbeat 帧全部按 50ms 到达），无需加 Cache Bypass 规则；文字卡顿的根因是大音频帧与文字共用发送队列，不是 CF 缓存。

## 12. 2026-10-22 小智模型 v0.1.1

- 资源：`live2d-models/xiaozhi2/runtime_v011/xiaozhi2.model3.json`（新版本化路径，避开浏览器/CF 旧缓存）；`conf/model_dict.json` 的入口改为 `/live2d-models/xiaozhi2/runtime_v011/xiaozhi2.model3.json`，描述 `小智 v0.1.1 (PSD2Live)`，模型名仍为 `xiaozhi2`。
- 变化：`moc3/physics3/cdi3` 与旧版一致；idle/nod/shake 动作幅度放大（idle 约 2 倍，nod/shake 约 1.6–1.8 倍）；新增 2.6s 嘴型动作组 `动作 2`（保留在 model3，未映射到 motionMap）。贴图与旧版相同，转 WebP q95：1.28MB → 181KB，alpha 无损，可见区 PSNR 44.3dB。
- 源文件在 `source_v011/`（cmo3/can3/psd2live/原 PNG/model3）；旧 `runtime_v2/` 保留回滚。备份 `data/backups/xiaozhi-v011-20261022-121759/model_dict.json`。
- 部署：镜像不变（`1.2.1-split-ws-20261022`），容器仅重启；后端 `Live2dModel("xiaozhi2")` 已读取新 URL。
- 验证：新目录 10 个资源全部公网 200；model3/贴图 CF 首次 MISS 后 HIT；全部 JSON 引用完整；`/healthz` 200；日志无 ERROR/Traceback。默认角色仍为 AIRI/Hiyori，小智在角色预设中可选。
- 回滚：把 `conf/model_dict.json` 的 xiaozhi2 URL 改回 `/live2d-models/xiaozhi2/runtime_v2/xiaozhi2.model3.json`（或恢复上述备份），重启容器。

## 13. 2026-10-23 SQLite 历史存储

### 范围

本次只改存储层，不包含登录/鉴权。运行时仍使用 `system_config.storage.default_user_id: local`，所以所有连接共享 `local` 用户的数据；但仓库、表结构和调用链已经按 `user_id` 作用域设计，下一步接入登录时只需把真实用户 ID 传入 `ServiceContext`。

### 代码结构

- `src/open_llm_vtuber/storage/base.py`：`HistoryRepository` 抽象接口；所有历史读写方法都显式接收 `user_id`，新增数据库实现该接口即可。
- `src/open_llm_vtuber/storage/sqlite.py`：SQLite 实现，标准库 `sqlite3` + `asyncio.to_thread`，WAL、外键级联、单连接串行化；新增 `users` / `histories` / `messages` / `schema_migrations` 表。
- `src/open_llm_vtuber/storage/user_store.py`：`UserHistoryStore` 绑定 `user_id`，运行时代码只能通过它读写当前用户的数据。
- `src/open_llm_vtuber/storage/legacy.py`：旧 `chat_history/<conf_uid>/*.json` 一次性导入，保留原 `history_uid`、时间戳、name/avatar、metadata；导入后移动源文件。
- `src/open_llm_vtuber/storage/factory.py`：目前只注册 `sqlite`；接入 PostgreSQL/MySQL 时实现 `HistoryRepository` 并在此增加分支。
- `ServiceContext` 持有 `history_repository`、`history`、`user_id`；新增 `load_history` / `store_history_message` / `update_history_metadata`。
- `BasicMemoryAgent` 不再直接读文件：`ServiceContext` 取到已授权消息后调用 `set_memory(messages, metadata)`；Hume 的 `resume_id` 通过 `history_metadata_writer` 回调写回当前历史。
- WebSocket 消息类型和前端字段不变；`fetch-history-list` / `fetch-and-set-history` / `create-new-history` / `delete-history` 改为走用户作用域仓库。

### 配置与路径

```yaml
system_config:
  storage:
    backend: sqlite
    sqlite_path: data/storage/open_llm_vtuber.db
    default_user_id: local
    import_legacy_history: true
    legacy_history_dir: chat_history
    legacy_backup_dir: data/storage/legacy_history
```

- `data/storage` 已作为独立卷挂载到容器 `/app/data/storage`，数据库和旧历史备份不会随容器重建丢失。
- 首次启动迁移结果：生产 `data/chat_history` 共 141 个 JSON，103 个导入、38 个空历史跳过、0 失败；迁移后 `data/chat_history` 为 0 个 JSON，`data/storage/legacy_history` 保留全部 141 个源文件。
- 迁移后 DB 基线：103 条历史、347 条消息；浏览器页面自动新建一个空历史后为 104 条（空历史不会出现在 `history-list`）。
- 迁移前的完整备份：`data/backups/storage-sqlite-20261023-085205/`，含 `chat_history.tar.gz`、`conf.yaml`、`conf_model_dict.json`、`mcp_servers.json`、`source.tar.gz`、`run-container.sh`，以及迁移后的 `open_llm_vtuber.db.after-migration`（103 历史/347 消息，已验证可独立打开）。

### 部署

- 生产镜像：`open-llm-vtuber:1.2.1-storage-20261023-r2`；`run-container.sh` 已切到该镜像并增加 `data/storage:/app/data/storage` 挂载。
- 相关提交：`01e9608` 存储重构、`8100ad5` CI 使用 uv、`02ed3d9` Docker 构建上下文排除 conf/data、`e5555e1` 进一步排除 MCP 密钥和根 model_dict；`origin/main` HEAD 为 `e5555e1`。
- `.dockerignore` 现在排除 `/conf/`、`/data/`、`/mcp_servers.json`、`/mcp_servers.json.*`、`/model_dict.json`、`/backup-*.tar.gz`。r2 镜像内已确认不存在这些路径；含旧 MCP 密钥的中间镜像 tag `1.2.1-storage-20261023` 已删除。
- 服务器源码目录仍不是 git 仓库；本次通过 `git archive HEAD` + tar 解包同步，解包时排除了 `conf`、`characters`、`avatars`、`backgrounds`、`live2d-models`、`models`、`data`、`cache`、`logs`、`chat_history`、`mcp_servers.json`、`model_dict.json`、`frontend`。同步前后 `conf/conf.yaml`、`conf/model_dict.json`、`mcp_servers.json`、根 `model_dict.json`、`run-container.sh` 的 sha256 完全一致。

### 验证

- 本地：`uv run --frozen python -m unittest discover -s tests -v`，175 个用例通过；`ruff check .` 通过。
- 隔离容器（端口 12394，临时 conf/DB/历史）：41 条 AIRI 历史迁移、列表读取、加载、新建、用户+AI 落库、删除全部通过；文本流正常；Azure TTS 音频走 `/audio-ws`，`backend-synth-complete` 在音频后到达。
- 生产（12393）：同样完成历史列表/加载/新建/落库/删除和端到端文本/音频测试，测试历史已删除；公网 `wss://vtuber.acgurl.cn/client-ws` 默认 AIRI，`history-list` 返回 41 条；浏览器页面成功连接并自动新建历史；`/healthz`、首页、`assets/main-DS8X0Aex.js` 均 200；日志无 ERROR/WARNING。
- 容器重启后 DB 仍为 104 条历史/347 条消息，确认 `data/storage` 持久化有效。

### 回滚

1. 恢复 `data/backups/storage-sqlite-20261023-085205/run-container.sh`（或手动把镜像改回 `open-llm-vtuber:1.2.1-frontend-refactor-20261023`，并删除 `data/storage` 挂载行）。
2. 旧镜像只读 `data/chat_history`；把 `data/backups/storage-sqlite-20261023-085205/chat_history.tar.gz` 解压回 `data/chat_history`。
3. 执行 `bash run-container.sh`。新 DB 保留在 `data/storage`，不删除；回滚后再升级可继续使用。
4. 旧镜像 `open-llm-vtuber:1.2.1-frontend-refactor-20261023`、`...-deploy-20261023-47bf2c7`、`...-deploy-20261023` 仍保留。

### 已知限制

- 截至第 13 节部署时尚未接入登录，所有连接仍属于 `local` 用户；该限制已在第 14 节 OIDC 上线中解决。
- SQLite 当前按单进程设计；多 uvicorn worker 需要把 session/群组状态迁到 Redis，存储本身可继续 WAL。
- 备份 SQLite 时不要只复制主文件：至少一起复制 `-wal`/`-shm`，或使用 `sqlite3.Connection.backup()`（本次部署备份就是用该方式）。
- 空历史会保留在 DB 中但不会出现在列表；如果长期积累，可后续加定期清理。

## 14. 2026-10-23 OIDC 多用户上线

### 结果

- 生产镜像 `open-llm-vtuber:1.2.1-oidc-20261023-r2`；`run-container.sh` 已指向该镜像。
- Casdoor 应用 `open-llm-vtuber`：client_id `ce78b62865acce526bc5`，redirect_uri `https://vtuber.acgurl.cn/auth/callback`，issuer `https://sso.acgurl.cn`，grant_types 仅 `authorization_code`，`enable_signin_session=true`，scopes `openid profile email`。client_secret 和 `auth.signing_secret` 只在服务器 `conf/conf.yaml`（600），不在仓库/文档/聊天中记录。
- `local` 历史已归档到 `data/storage/archive/local-history-archive.json`：104 条非空历史 / 349 条消息（DB local 共 105 条，含 1 条空历史不归档）。`local` 行保留在 DB 中，但 OIDC 模式下 `default_context_cache` 不绑定 local，任何会话都不能读写它。

### 行为

- 登录：`/auth/login` → Casdoor authorization code + nonce/state → `/auth/callback`（校验 state/nonce/ID Token 签名、iss/aud/exp）→ 设置 HMAC 签名 `vtuber_session` Cookie（HttpOnly/Secure/SameSite=Lax，默认 7 天）。
- 身份：`user_identities(provider, subject)` 映射 Casdoor issuer+sub 到内部随机 user_id；所有历史读写仍经 `UserHistoryStore(user_id)`。
- 访问控制：`/`、`/web-tool`、`/model_dict.json`、`/cache` 需要登录；`/healthz`、`/auth/*`、`/api/session`、`/assets/`、`/libs/`、`/live2d-models/`、`/bg/`、`/avatars/` 公开。`/client-ws`、`/tts-ws` 无会话关闭 4401，`/audio-ws` 关闭 1008，OIDC 模式校验 Origin。
- 每用户主 WS 连接上限 4（`auth.max_connections_per_user`）；群组只允许同一 user_id 互邀；角色预设默认对所有已登录用户开放，可用 `characters/*.yaml` 里的 `allowed_users`（内部 user_id 或显示名）限定用户，见 `characters/README.md`。
- `ServiceContext._owns_tts_engine` 修复共享 TTS 被某个会话切预设关闭的问题。

### 代码入口

- `src/open_llm_vtuber/auth/`：`manager.py`（AuthManager/会话/state）、`oidc.py`（discovery/token/JWKS/ID Token）、`routes.py`、`middleware.py`、`cookies.py`。
- `src/open_llm_vtuber/config_manager/auth.py` + `system.py`；`storage/sqlite.py` 的 `user_identities` 与 `resolve_user_identity`；`storage/archive.py`；`server.py` 初始化/归档；`routes.py`/`websocket_handler.py` 的 WS 身份；`chat_group.py` 同用户限制。
- 依赖：`PyJWT[crypto]`（mcp 已传递依赖，本次显式加入 `pyproject.toml`，`uv.lock` 最小改动）。

### 部署与踩坑

1. 在 Casdoor 创建应用并设置 redirect/grant/scope；`enable_signin_session=true`，否则授权页每次要求密码。
2. 把 Casdoor 应用凭据直接从 `casdoor-db` 读取并写入服务器 `conf/conf.yaml`（不经过聊天/文档），生成独立 `signing_secret`。
3. 同步源码时只覆盖 `src/`、`pyproject.toml`、`uv.lock`、`requirements.txt`，排除 `conf/`、`data/`、`mcp_servers.json`、`model_dict.json`；备份 `data/backups/oidc-20261023-101635/`。
4. 首次 r1 镜像登录在 ID Token 校验阶段失败：Casdoor/Cloudflare 对默认 Python-urllib UA 的 `/.well-known/jwks` 返回 403。修复为给 `jwt.PyJWKClient` 传浏览器兼容 User-Agent（`auth/oidc.py` 顶部 `_JWKS_USER_AGENT`），重建 r2。
5. r2 上线重启时归档 local；再次重启会检测到归档文件并跳过（幂等）。

### 验证

- `/healthz` 200；未登录 `/` 302 到 `/auth/login?next=%2F`；`/api/session`、`/cache`、`/model_dict.json` 401；`/assets`、`/live2d-models/info` 200。
- 浏览器用 Casdoor admin 实际完成登录，`/api/session` 返回 `authenticated: true`；`/client-ws`、`/audio-ws` 建立；AIRI 回复、Live2D 动作、Azure TTS、MCP cuc-kb 4 工具正常。
- DB：新 OIDC 用户 1 条历史（测试对话后 2 条消息），local 保持 105 条历史/349 条消息且不显示给新用户；`user_identities` 1 行；schema versions `[1,2]`。
- 自动化后台标签页不发送播放完成回执，日志会出现 120s playback timeout WARNING；AI 消息在超时后正常落库，前台正常播放不受影响。

### 常用操作

```bash
# 查看登录/WS/归档日志
ssh oracle "docker logs --tail 200 open-llm-vtuber | grep -E 'OIDC|Connection established|Archived|ERROR|WARNING'"

# 查看本地历史归档（宿主机）
ssh oracle "python3 -c \"import json; d=json.load(open('/home/ubuntu/open-llm-vtuber/data/storage/archive/local-history-archive.json')); print(d['history_count'], d['message_count'])\""

# 改 auth 配置后重启（无需重建镜像）
ssh oracle "docker restart open-llm-vtuber"
```

### 回滚

1. 恢复上线前 conf/run-container：`cp data/backups/oidc-20261023-101635/conf.yaml conf/conf.yaml`、`cp data/backups/oidc-20261023-101635/run-container.sh run-container.sh`，`chmod 600 conf/conf.yaml`，执行 `bash run-container.sh`。
2. 该回滚回到 `1.2.1-storage-20261023-r2`，local 历史仍在 DB 中；OIDC 期间新建的用户/历史保留但不被旧镜像使用。若需要完全回到上线前数据，再恢复备份 DB（会丢失上线后新用户消息）。
3. 若只想回退 JWKS 修复，恢复 `run-container.sh.bak.oidc-r1.20261023` 会回到有 403 bug 的 r1，不建议。

### 已知问题/待办

- `app-acgurl` 当前 `enable_sign_up=true`（邮箱验证码、无手机号），任何人都能注册并使用（会消耗 DeepSeek/Azure 额度）；如需限制，在 Casdoor 应用/组织关闭注册或限制用户。`built-in/admin` 不能登录 `app-acgurl`，旧会话过期后需注册 acgurl 账号。
- `/auth/logout` 只清本地 `vtuber_session`，未配置 Casdoor `post_logout_redirect_uri`；Casdoor 会话保留，已建立 WS 不会立即断开；会话默认 7 天。
- 尚无每用户消息/TTS/ASR 速率限制；主 WS 仅限制 4 个连接。公开注册场景建议后续补。
- SQLite 单进程单 worker 设计不变；多 worker 需 Redis/Postgres。

## 15. 2026-10-23 重构与缺陷修复部署

### 结果

- 生产镜像 `open-llm-vtuber:1.2.1-refactor-20261023`，`run-container.sh` 已切换；旧镜像 `1.2.1-oidc-20261023-r2` 保留回滚。
- 本次覆盖 `3ff00d9..0469c6e` 共 13 个提交：OIDC 入库、全仓库坏味道扫描后的低风险重构、5 个缺陷修复。
- 重构：BasicMemoryAgent 工具执行块提取、SQLite 行映射统一、auth Cookie 参数收敛、TTS 冗余 path/cache 清理、translate traceback 保留、死代码移除。
- 缺陷修复：Fish TTS 日志不再输出 API key；Hume `AudioOutput` 的 actions 不再二次 `.to_dict()`；`pyttsx3_tts` 重新可选（仅新增 Literal 值，无 YAML 改名）；群组消失时中断不再空引用；chain-end 不再向当前发言人重复发送。
- 未改动 WS 消息字段、YAML 键、路径守卫和 `frontend/`；无需前端重建。

### 备份与同步

- 备份 `data/backups/refactor-20261023-105231/`：`source.tar.gz`、`conf.yaml`、`conf_model_dict.json`、`mcp_servers.json`、`run-container.sh`、SQLite `open_llm_vtuber.db`（使用 backup API）、`sha256-before`。
- 同步方式：本地 `git archive HEAD` 经 tar 覆盖服务器源码，排除 `conf`、`characters`、`avatars`、`backgrounds`、`live2d-models`、`models`、`data`、`cache`、`logs`、`chat_history`、`frontend`、`mcp_servers.json`、`model_dict.json`；同步后关键源码 sha256 与本地一致，4 个运行时文件 sha256 未变。
- 镜像由服务器 `docker build -f dockerfile -t open-llm-vtuber:1.2.1-refactor-20261023 .` 构建；`run-container.sh` 仅镜像标签一行变化。

### 验证

- 镜像内 210 个单测全部通过。
- 隔离容器（12394，临时 conf 改为 single、临时 logs/cache/storage/chat_history）：健康 200；默认 AIRI/hiyori_pro；MCP cuc-kb 4+4 工具；文本流 2 个 `text-delta`；音频仅走 `/audio-ws`（`audio/mpeg`）；`backend-synth-complete` 在最后一段音频之后；历史 human+ai 落库并可删除；`config-files` 10 项；日志无 ERROR/WARNING。
- 生产（12393）：启动日志 AIRI、Groq ASR、Azure TTS、MCP 4+4；`/healthz` 200（公网同）；带 `Accept: text/html` 的 `/` 302 到 `/auth/login`；`/api/session`、`/model_dict.json` 401；`/assets/main-DS8X0Aex.js` 200；`/live2d-models/info` 200；未登录 WS 关闭码 `/client-ws` 4401、`/audio-ws` 1008、`/tts-ws` 4401。
- OIDC 后链路：用服务器本地签名的临时会话（用户 `deploy_smoke_20261023`）连接生产 WS，完成文本流、Azure MP3、完成信号顺序、历史 human+ai 写入与删除；测试后删除临时用户，DB 恢复 **110 历史 / 362 消息 / 2 用户**，与部署前一致。
- 日志唯一 WARNING 是验证 `/auth/callback` 非法 state 时的预期告警；无 ERROR/Traceback。

### 回滚

1. 恢复 `data/backups/refactor-20261023-105231/run-container.sh` 到部署目录，执行 `bash run-container.sh`。
2. 旧镜像 `open-llm-vtuber:1.2.1-oidc-20261023-r2` 仍在；数据库未改动，可直接回退。
3. 如需恢复源码，解包备份中的 `source.tar.gz`。

### 已知限制

- 本次未改动数据库 schema；OIDC、历史隔离、MCP、TTS 行为与 r2 一致。
- 全仓库扫描中的结构提取/高风险长函数批次（OpenAI/Claude `chat_completion`、Sherpa、TTS payload 统一、sentence_divider/live2d 去重）仍未执行。
- TTS 发送失败时 `wait_for_delivery` 仍可能等到 10s 超时，未在本次修复范围。

## 16. 2026-10-23 OAuth 入口切换到 acgurl 组织

- VTuber 的 OIDC 客户端从 `built-in/open-llm-vtuber` 切到 `acgurl/app-acgurl`：`app-acgurl.redirect_uris` 新增 `https://vtuber.acgurl.cn/auth/callback`；服务器 `conf/conf.yaml` 的 `client_id/client_secret` 已更换（备份 `conf/conf.yaml.bak.oauth-entry.20261023-113559`）。
- 登录入口现在落在 `acgurl` 组织的登录页；未注册用户可从登录页进入邮箱验证码注册（无手机号）。管理员内置账号不能登录该组织。
- 验证：临时 acgurl 用户完成 authorize → callback → `/api/session` 全链路，随后删除 Casdoor 用户及内部 `users/user_identities` 行；VTuber DB 备份 `data/storage/backup-before-oauth-test-cleanup-20261023-113735.db`。
- 影响：`built-in/admin` 的旧签名会话仍有效到 7 天过期；之后需用新增的 acgurl 账号登录，内部 user_id/历史不会继承。旧 `built-in/open-llm-vtuber` 应用未删除。
- 回滚：恢复 conf 备份并重启容器；`app-acgurl` 的回调地址可保留，无副作用。

## 17. 2026-10-23 历史列表刷新部署

- 问题：前端只在 WebSocket 建连（及切换角色）时发送 `fetch-history-list`，连接保持期间打开历史抽屉不会刷新；后端其实逐轮写入 SQLite（human 即时、AI 在播放完成后），所以表现为“断开/刷新后才看到当前会话”。
- 改动（父仓库 `47411df`，前端 submodule `afcea88`）：抽屉每次打开且 WS 为 OPEN 时拉取列表；收到 `history-list` 不再把 `currentHistoryUid` 改成第一条；刷新时保留尚未产生消息的当前会话；新建会话时清理遗留的空历史壳。
- 前端产物 `main-qaAmbYPB.js` + `index-zpmUla8b.js`（CSS 未变），`frontend-streaming.patch` 已更新（新增 `use-history-drawer.ts` diff）。
- 部署镜像 `open-llm-vtuber:1.2.1-history-refresh-20261023`，`run-container.sh` 已切换；备份 `data/backups/frontend-history-refresh-20261023-121516/`（frontend + run-container.sh）。旧镜像 `1.2.1-refactor-20261023` 保留回滚。
- 验证：本地 mock WS + 浏览器连续打开抽屉 4 次均触发 `fetch-history-list`，模拟其他设备新增的会话即时出现，当前会话不被切走，手动切换历史正常；生产 `/healthz` 200、`assets/main-qaAmbYPB.js` 200 且 sha256 与本地一致（公网经 CF 命中缓存，哈希一致）、旧 `main-DS8X0Aex.js` 源站 404、镜像内 `/app/frontend` 含新包，启动日志无 ERROR/WARNING。
- 回滚：把 `run-container.sh` 镜像改回 `open-llm-vtuber:1.2.1-refactor-20261023` 并执行 `bash run-container.sh`；前端文件可从未部署前的备份目录恢复。
- 注意：Cloudflare 边缘仍可能对旧 hash 资源返回缓存的 200，但新 index 不再引用，无影响；已打开页面的用户需刷新一次。

## 18. 2026-10-25 用户 MCP 与浏览器本地 MCP（已部署）

### 能力

- **配置页只有一份 JSON**：与 `mcp_servers.json` 同形状的 `mcp_servers` 文档；后端逐条判定 `remote`（公网 HTTPS，后端连接）或 `local`（本机/内网，浏览器连接），用户不需要先选类型。
- **remote**：存 SQLite `user_mcp_servers`，只对本人会话生效；保存时与每次建连前做公网 HTTPS/SSRF 校验。
- **local**：后端在连接/重连后通过 `local-mcp-config` 把条目下发给该用户的浏览器；网页连自己的地址、注册工具，LLM 调用时经 `/client-ws` 转发。后端不访问用户 localhost。
- **不接收 stdio**：用户条目的 `command/args/env/cwd` 一律 400（避免服务器 RCE）。
- **全局 MCP 不动**：`mcp_servers.json` / cuc-kb 的配置、部署和行为完全不变；用户条目不能覆盖同名全局服务器。

### 关键实现

- 存储：`user_mcp_servers`（schema v4 增加 `mode`，v3 表启动时自动 `ALTER`）；`replace_user_mcp_servers` 原子替换整份配置，同名条目保留 id（local 工具命名空间稳定），删除缺失项。
- API：`GET/PUT /api/mcp/config`、`POST /api/mcp/config/test`；PUT 全量替换，headers `***` 保留旧值；GET 返回 `config` + `servers[]`（含 `mode`）。
- 分类：`mcpp/user_servers.classify_mcp_url`——localhost/私网/链路本地/`.local`/`.lan`/`.internal`/单标签主机名 → local；主机名解析到私网 → local；公网 HTTPS → remote；公网 HTTP、stdio、URL 内凭证/fragment → 400。
- 会话：`split_user_mcp_servers` 按 mode 拆分；remote 进 `ServiceContext` registry，local 进 `local-mcp-config`；`register_local_mcp_server` 只接受配置里存在的 `server_id`。
- 本地转发：`mcpp/local_bridge.py` + `message_handler.response_waiter`（先注册 waiter 再发送）；30s 超时、按会话 socket 返回；群聊 `scoped` 状态只发给所有者。
- WebSocket：客户端 `register-local-mcp` / `unregister-local-mcp` / `local-tool-result`；服务端 `local-mcp-config` / `local-tool-call` / `local-mcp-registered` / `local-mcp-unregistered` / `local-mcp-error`。
- 前端：`McpPanel.tsx` 统一 JSON 编辑器 + 解析结果列表（模式/状态/远程测试）；`localMcp.ts` 按 `local-mcp-config` 多服务器连接、注册、重连；不再用 localStorage 存本地 URL。

### 验证

- `uv run --frozen python -m unittest discover -s tests`：**259 个测试通过**。新增/更新 `tests/test_user_mcp.py`（分类、统一 JSON、拆分、存储隔离、本地桥、工具路由、命名空间、上限）与 `tests/test_user_mcp_routes.py`（config GET/PUT、脱敏、`***` 回填、删除、限额、local test 不拨号、401/503）。
- 真实浏览器冒烟：JSON 里只放 `"my-pc": {"url": "http://127.0.0.1:8766/mcp"}` → 保存 → 重连 → 列表显示 `本地` + `已连接 · 2 个工具`（`l_b97892_echo` / `l_b97892_add`）；假 OpenAI 兼容 LLM 触发调用，后端日志与 UI 均显示 `echo: hello from unified config`。
- `npx vite build` 成功；`tsc` 在改动文件上无新增错误。
- 测试产生的本地历史与 `my-pc` 配置已从 `data/storage/open_llm_vtuber.db` 删除，原有 2026-10-21 历史未动；未写 `mcp_servers.json`。

### 部署注意

- 需重建镜像（schema v4 在启动时自动建表/补列）；前端按现有流程构建 `web/dist` 并同步 `frontend/`；本次未部署。
- 反向代理需放行 `/api/mcp/*`（已受 OIDC 中间件保护）。
- **必须在目标浏览器实测**：HTTPS 页面访问 `http://127.0.0.1` 的混合内容 / Local Network Access 权限；本地 MCP 必须允许站点 Origin 的 CORS 并 `Access-Control-Expose-Headers: Mcp-Session-Id`。
- 配置修改只在下次连接生效；本地 MCP 只在页面打开时可用；`local-mcp-config` 的 headers 会经已认证 WS 下发给同一用户。
- headers 目前明文存 SQLite（600）；后续加密不要复用 `auth.signing_secret`（轮换会使历史 token 无法解密）。

### 部署结果（2026-10-24，服务器本地时间）

- 代码已提交并推送：源码 `a7a209a`、父仓库 bundle 指针 `36440d3`（origin/main）、前端子模块 `383ddff`（origin/build-motion）。
- 生产镜像 `open-llm-vtuber:1.2.1-user-mcp-20261024`，`run-container.sh` 已切换；旧镜像 `1.2.1-history-refresh-20261023` 保留回滚。`run-container.sh.bak.usermcp.20261024` 在部署目录。
- 备份 `data/backups/user-mcp-20261024-170303/`：`run-container.sh.bak`、`conf.yaml.bak`、`model_dict.json.bak`、`mcp_servers.json.bak`、`frontend.tar.gz`、`source-before.tar.gz`、SQLite 备份、`counts-before.txt`、`sha256-before.txt`。
- 同步：`git archive HEAD` 排除 `conf/characters/avatars/backgrounds/live2d-models/models/data/cache/logs/chat_history/mcp_servers.json/model_dict.json/frontend` 后解包；前端 tar 覆盖 `frontend/`（保留旧 hash 资源）。`mcp_servers.json` 保持 `fdcc0fce…`，`conf/conf.yaml` 保持 `7918b34b…`。
- 镜像内 `uv run --frozen python -m unittest discover -s tests`：**259 个测试通过**（注意要用 `uv run`，镜像的系统 Python 没有项目依赖）。
- 启动：`/healthz` 200（本机与公网）、未登录 `/api/mcp/config` 与 `/api/session` 均 401；cuc-kb 成功连接，MCP prompt 长度 1829；schema `[1,2,3,4]`，`user_mcp_servers` 已有 `mode` 列；users 3 / messages 417 未变，histories 206→208（重启期间活跃客户端新增 2 条空历史，0 消息）。
- 生产签名会话冒烟（用户 `deploy_mcp_smoke_20261024`，测试后已删除）：`GET /api/mcp/config` 200、`PUT` 本地条目 200 且 `mode=local`、WS 收到 `local-mcp-config`（1 个 `http://127.0.0.1:8766/mcp`）、临时配置清空 200；带会话访问 `/` 200 且引用新入口 `assets/index-CUMe6bnS.js`。
- 公网新资源 `/assets/index-CUMe6bnS.js`、`/assets/index-C8VRA23Y.css` 均 200；容器日志无 ERROR/Traceback。新前端产物：入口 `index-CUMe6bnS.js`、VAD chunk `index-BYcNb3V_.js`、CSS `index-C8VRA23Y.css`。
- 未做：浏览器端在 HTTPS 生产域下访问 `http://127.0.0.1` 的 Local Network Access / CORS 实测（本地开发域已通过），需要真实用户环境授权后验证；CF HTML 入口缓存未手动 purge（匿名入口仍 401/BYPASS）。

### SSE 兼容修复部署（2026-10-24）

- 问题：标准 MCP 配置使用 `mcpServers`，并用 `type: "sse"` 表示 legacy HTTP+SSE；原实现只接受 `mcp_servers` 且只支持 Streamable HTTP。用户本机 `127.0.0.1:8788` 的 `cuc-sse` 因此无法保存/连接。
- 代码：源码 `46f7c21`、父仓 bundle 指针 `bfccc3d`、前端子模块 `23f8be7`。
  - 配置接受 `mcp_servers` / `mcpServers`，条目接受 `type` / `transport`（`sse`、`http`、`streamable-http`，拒绝 `stdio`）。
  - 新增浏览器端 SSE client（`localSseMcpClient.ts`）：GET SSE 流、解析 `endpoint` 事件、把原 URL 的查询参数（如 `?key=...`）追加到 `/messages` 端点，再走 POST/SSE JSON-RPC。
  - 后端 `MCPClient` 增加 `sse_client` 分支；`MCPServer.transport` 持久化到 schema v5 的 `transport` 列；`local-mcp-config` 下发 `transport`。
  - 设置页显示 `SSE` 徽标，继续保留本地/远程分类。
- 生产镜像 `open-llm-vtuber:1.2.1-user-mcp-sse-20261024`，`run-container.sh` 已切换，旧 `1.2.1-user-mcp-20261024` 保留回滚；备份 `data/backups/user-mcp-sse-20261024-172827/` 与 `run-container.sh.bak.usermcpsse.20261024`。
- 验证：
  - 264 个单测通过（镜像内 `uv run --frozen python -m unittest discover -s tests`）；schema `[1..5]`，`user_mcp_servers` 已有 `transport`。
  - 本机真实 SSE 服务（用户 Windows，`127.0.0.1:8788`）：页面注册 7 个工具（`cuc_status`/`cuc_timetable`/`cuc_card`/`cuc_activity`/`cuc_message`/`cuc_visitor`/`cuc_request`），假 LLM 调用 `cuc_status` 成功返回 643 字符状态 JSON。
  - 生产签名会话冒烟：PUT `mcpServers` + `type: sse` → `mode=local`、`transport=sse`；WS `local-mcp-config` 同样带 `transport: sse`；临时用户/配置已清理。
  - 公网 `/healthz` 200，未登录 `/api/mcp/config` 401；新资源 `assets/index-CqRZKQEN.js`、`assets/index-CU-Yp-c1.css` 200；容器日志无 ERROR/Traceback；`mcp_servers.json`/`conf.yaml` 哈希未变。
  - 本机 SSE 服务的 CORS：`Access-Control-Allow-Origin: *`，允许 `Content-Type` 等预检头；生产域 `https://vtuber.acgurl.cn` 可访问。HTTPS 页面访问 `http://127.0.0.1` 仍可能需要浏览器 Local Network Access 授权。
- 使用方式：在生产设置页把 `mcpServers` JSON 保存；刷新/重连后浏览器会连接本机 SSE 服务。每用户独立配置。

### 回滚

- 恢复 `run-container.sh.bak.usermcpsse.20261024`（或把镜像改回 `1.2.1-user-mcp-20261024`）并 `bash run-container.sh`，可回退 SSE 兼容修复。
- 再往前回退到 `run-container.sh.bak.usermcp.20261024` / `1.2.1-history-refresh-20261023`，可撤销整个用户 MCP 功能。
- `user_mcp_servers` 表及 `mode`/`transport` 列均为新增，旧镜像不会读写/依赖，无需删表；如需完全恢复数据库，用对应备份目录的 `open_llm_vtuber.db`。
- 前端可回退到备份 `frontend.tar.gz`；旧 hash 资源仍在服务器，打开中的页面不受影响。

## 19. 2026-10-25 OIDC 缓存适配（已部署）

### 变更

- **HTTP 缓存**：`AuthRedirectMiddleware` 对 `/auth/*`、`/api/*`、`/cache/*`、`/web-tool/*`、`/model_dict.json` 统一补 `Cache-Control: no-store`，覆盖 401/302 与正常响应。Caddy vtuber 站点用 `header @session_scoped >Cache-Control "no-store"` 强制覆盖（不加 `>` 会出现两个同名头）。入口 HTML 仍由后端给 `public, max-age=0, must-revalidate, s-maxage=60`，静态资源策略不变；`/web-tool/*` 从 `public, max-age=3600` 改为 `no-store`（它本身需要登录）。
- **TTS 缓存**：`new_audio_file_stem(scope)` 生成 `cache/<user_id>/<stem>`（scope 只保留 `[A-Za-z0-9_-]`）；`TTSInterface.generate_cache_file_name` 递归建目录；`TTSTaskManager(cache_scope=...)` 由 `ServiceContext.user_id` 注入（单聊/群聊都传）。`/cache` 挂载改为 `UserCacheStaticFiles`：只允许访问 `cache/<自己 user_id>/...`，他人目录与根目录旧文件返回 404，single 模式（无身份）不限制。
- **前端 localStorage**：新增 `web/src/utils/storage.ts`，按 `vtuber_uid` cookie 命名空间化，键形如 `ollmvt.u<uid>.model`；`settings.ts`、`services/modelCache.ts`、`i18n`、`CameraWindow` 全部改走 `readSetting/writeSetting`。服务端在 `/auth/callback` 设置 `vtuber_uid`（非 HttpOnly，只含内部 user_id，Secure/SameSite=Lax，与 session 同寿命），`/auth/logout` 删除，`/api/session` 给老会话补种。
- **不做迁移**：升级后旧的无前缀键（`ollmvt.model`、`ollmvt.lang`、`ollmvt.bg` 等）不再读取，避免共享浏览器把上一个用户的设置带给新账号；需要的话手动删除即可。

### 验证

- 本地 `uv run --frozen python -m unittest discover -s tests`：**275 个测试通过**。新增 `tests/test_cache_isolation.py`（stem 作用域/清洗、嵌套目录、`/cache` 归属、TTS manager 传参）；`tests/test_auth_routes.py` 增加 no-store 与 `vtuber_uid` 断言。
- 线上（经 Cloudflare）：
  - `/auth/login`、`/api/session`、`/model_dict.json`、`/cache/*`、`/web-tool/*` 均为单个 `Cache-Control: no-store`，`cf-cache-status` 为 `DYNAMIC`/`BYPASS`；匿名 `/` 仍 302 到登录页；`/assets/*` 仍 immutable。
  - 浏览器登录后 `document.cookie` 含 `vtuber_uid=<32 位 uid>`；刷新后 localStorage 写入 `ollmvt.u<uid>.model`，旧 `ollmvt.model` 不再更新。
  - `/cache/<uid>/probe.mp3` 本人 200，他人目录与 `cache/` 根目录均 404；真实对话中 TTS 文件在 `data/cache/<uid>/` 生成并在投递后清理，页面语音/Live2D 正常。

### 部署

- 镜像 `open-llm-vtuber:1.2.1-oidc-cache-20261025`，`run-container.sh` 已切换；旧镜像 `1.2.1-refactor-20261025` 保留回滚。
- 备份 `data/backups/oidc-cache-20261025-064723/`：9 个后端源文件、`frontend/index.html`、`run-container.sh`；Caddyfile 备份 `/etc/caddy/Caddyfile.bak.oidccache.20261025`、`/etc/caddy/Caddyfile.bak.oidccache2.20261025`。
- 前端产物 `index-BiqjDyMf.js`、`index-BJiath1D.js`、`index-BT7NIenF.css`（旧 hash 资源保留）；`frontend/` 子模块提交 `eba3249`。源码父仓 `49640e2`、子模块 `eba3249` 均已推送 `origin`（main / build-motion）。
- 回滚：把 `run-container.sh` 镜像改回 `1.2.1-refactor-20261025` 并 `bash run-container.sh`；前端可在备份目录恢复 `index.html`。恢复 Caddy 用 `.bak.oidccache*.20261025`。
- 未做：Cloudflare HTML 入口（`/`、`/index.html`，`respect_origin`）未手动 purge，最多 60s 后自然刷新；旧 hash 资源仍在，不影响打开中的页面。

## 20. 2026-10-25 Live2D 加载加速（A+B+C，已热部署）

### 变更

- **B 贴图无损 WebP**：`mao_pro.4096/texture_00.png` 8.21MB → 4.52MB，`shizuku.1024/texture_0{0..4}.png` 4.45MB → 2.48MB，合计 12.66MB → 6.98MB（−45%）。用 Pillow `lossless=True, exact=True, method=6` 编码（libwebp 默认会改写全透明像素 RGB，`exact` 才严格一致）；6 张图解码后 RGBA 原始 md5 与原 PNG 完全相同，原 PNG 保留。新增版本化入口 `mao_pro.webp.model3.json`、`shizuku.webp.model3.json`，`conf/model_dict.json`（及本地根 `model_dict.json`）的 mao_pro URL 指向新入口；shizuku 未进 model_dict，仅保留版本化入口备用。
- **A 缓存与预加载**：Caddy vtuber 站点把 `/live2d-models/*` 从 7 天 + SWR 改为 `public, max-age=2592000, immutable`，并把 static_immutable/libs/models/media/root 五条规则改成 `>Cache-Control` 覆盖式（此前 Caddy 与后端各写一份，Cloudflare 会把两个值合并成旧 max-age）；`server.py` 的 `_STATIC_CACHE_POLICIES` 同步改为 30 天 immutable（随下次镜像生效）。新增 `scripts/warm_live2d_cache.py`：从 model_dict 递归解析 model3 引用并并发预热边缘，80 个资源二次运行全部 HIT。
- **A 前端预加载**：`modelCache.cacheModelAssets()` 在模型加载后解析 model3 的 Textures 并写入 `ollmvt[.u<uid>].model.assets`；`web/index.html` 内联脚本按同一 uid 规则读取该键，注入 `<link rel=preload as=image fetchpriority=high>`，贴图下载与主包并行。仅当缓存里 `model.url` 与 assets.url 一致时才预加载，避免切换模型后预热错资源。
- **C 渲染侧**：`measureContent()` 的轮廓像素扫描结果按 `bounds.v1.<model3 url>` 缓存到 localStorage，二次加载跳过整屏 `extract.pixels()`；渲染 `resolution` 上限设为 2（4K 屏不再按 DPR>2 放大离屏画布）。

### 验证

- 本地 headless Edge（500×320，冷缓存）实测：贴图 preload `start=8ms`、主包 `start=6ms`，两者并行；模型加载器复用 preload（第二次 texture 请求 `transferSize=0`）；首次加载写入 bounds 并扫描，二次加载 `readPixels` 调用数为 **0**；`index-C0pWF5dv.js` 正常渲染 mao_pro 无损贴图，无 JS 异常。构建产物入口 `index-C0pWF5dv.js`、VAD `index-AFjc5Yoa.js`，CSS 不变（`index-BT7NIenF.css`）。
- 生产：宿主/容器/公网 sha256 一致；`/healthz` 200，容器日志无 ERROR/Traceback；新 model3 与 WebP 公网 200、`Content-Type: image/webp`、`cf-cache-status` HIT；原站 Caddy 直连返回单个 `Cache-Control: public, max-age=2592000, immutable`。

### 部署

- 备份 `data/backups/live2d-webp-20261025-073636/`（`frontend/index.html`、`conf/model_dict.json`、`Caddyfile.bak`）；第二份 Caddy 备份 `/etc/caddy/Caddyfile.bak.live2dwebp2.20261025`。
- 模型与 model3 经 scp 到 bind mount，`conf/model_dict.json` 同步后 `docker restart open-llm-vtuber`；前端 `index.html` + 两个新 hash 用 `docker cp` 热更新，镜像仍为 `1.2.1-oidc-cache-20261025`。`scripts/warm_live2d_cache.py` 已上传服务器。
- 回滚：恢复备份的 `frontend/index.html` 与 `conf/model_dict.json`（或把 mao URL 指回 `mao_pro.model3.json`），`docker cp` 回旧入口并重启；Caddy 用上述备份恢复后 `caddy validate` + `systemctl reload caddy`。WebP 为新增文件，无需删除。
- 补充 purge：用本机 User 级环境变量里的 Global API Key（`CLOUDFLARE_EMAIL` + `CLOUDFLARE_API_KEY`）对 model_dict 的 80 个 URL 与 shizuku 的 14 个 URL 执行 `purge_cache`，随后在服务器重跑预热。抽查 6 个模型与 shizuku 的 model3/贴图，均返回 `Cache-Control: public, max-age=2592000, immutable`；model3 全部 HIT，本机 colo 未预热的贴图首次 MISS、之后 HIT。`warm_live2d_cache.py` 只按 model_dict 预热，未启用的模型（如 shizuku）需单独处理。

## 21. 2026-10-25 移除老前端子模块（已部署）

### 变更

- **删除老前端载体**：移除 `frontend/` git submodule 与 `.gitmodules`（`Open-LLM-VTuber-Web` 的 `build`/`build-motion` 分支仅存构建产物）、`frontend-streaming.patch`（旧补丁流程已废弃），以及 `run_server.py` 里的子模块自动初始化逻辑。
- **单一来源**：前端只保留 `web/`（React 18 + Vite + TypeScript）。运行时二进制（Live2D / ONNX Runtime / Silero VAD）从原子模块 `frontend/libs` 迁入并纳入版本管理的 `web/public/libs/`（42MB，10 个文件）。
- **构建**：`web/public/libs` 不再被 `.gitignore` 排除；`web/dist` 仍不入库。`dockerfile` 增加 `node:24-slim` 多阶段构建（`npm ci && npm run build`），产物复制到镜像内 `/app/web/dist`。
- **服务**：`server.py` 的兜底挂载从 `frontend` 改为 `web/dist`（`check_dir=False`，未构建时返回 404 而不是启动失败）。`run_server.py` 启动时只检查 `web/dist/index.html`，缺失时提示在 `web/` 运行 `npm ci && npm run build`。
- 文档同步：`CLAUDE.md`、`.gemini/GEMINI.md`、`.github/copilot-instructions.md`、`BACKEND_API.md`（同源部署说明与静态目录表）。

### 验证

- `cd web && npm run build`：通过；产物 `index-BJvEhV-b.js` / `index-DXZ6JaN6.js` / `index-BT7NIenF.css` 与移除前一致（构建幂等）。
- `uv run --frozen python -m unittest discover -s tests`：**274 个测试通过**（原 275；删除子模块错误插值用例，改为断言新的构建提示）。
- `starlette.testclient` 直连后端：`/` 200 且引用新入口，`/assets/index-BJvEhV-b.js` 200，`/libs/live2d.min.js` 200（`public, max-age=2592000`）。
- 服务器 ARM64 多阶段构建通过；镜像内 `uv run --frozen python -m unittest discover -s tests` **274 个通过**，`/app/web/dist` 存在且 `/app/frontend` 不存在，构建产物 hash 与本机一致。

### 部署注意（必须重建镜像）

- 镜像内前端路径从 `/app/frontend` 变为 `/app/web/dist`，旧镜像无法只靠 `docker cp` 获得新页面，**必须重建镜像**后切换 `run-container.sh`。
- 服务器 `docker build -t open-llm-vtuber:<tag> .` 会在 `web` 阶段执行 `npm ci`（需外网）；`web/` 与 `web/public/libs` 随源码包进入构建上下文。
- 新镜像后的热更新：本地 `cd web && npm run build`，再 `docker cp web/dist/. open-llm-vtuber:/app/web/dist/`；无需重启（静态文件按请求读取）。旧 hash 资源会留在容器里，不影响打开中的页面。
- 回滚：源码侧 `git revert` 本提交可恢复 `.gitmodules` 与 gitlink（再 `git submodule update --init`）；生产可切回上一镜像 `1.2.1-oidc-cache-20261025`，其 `/app/frontend` 内容仍在；服务器旧 `frontend/` 已打包在本次备份目录。

### 部署结果（2026-10-25，服务器本地时间）

- 提交 `6f77a67` 已推送 `origin/main`。生产镜像 `open-llm-vtuber:1.2.1-web-dist-20261025`，`run-container.sh` 已切换，旧 `1.2.1-oidc-cache-20261025` 保留回滚。
- 备份 `data/backups/frontend-submodule-removal-20261025-085508/`：`run-container.sh.bak`、`dockerfile.bak`、`dockerignore.bak`、`run_server.py.bak`、`server.py.bak`、`frontend.tar.gz`（61MB 旧产物）、`web-before.tar.gz`、`runtime-sha-before/after.txt`。
- 同步：服务器旧 `web/`（Oct 24 源码）与 `frontend/`（61MB）先整目录备份再删除，`git archive HEAD` 解包（无 `frontend/`，含 `web/public/libs`）；`conf.yaml`（`7918b34b…`）与 `conf/model_dict.json`（`39caa841…`）未变。
- **事故与恢复**：`mcp_servers.json` 仍被 git 跟踪（尽管在 `.gitignore`），归档解包把生产配置覆盖成本地默认（`fdcc0fce…` → `46adaa83…`）；随后从 `data/backups/user-mcp-sse-20261024-172827/mcp_servers.json.bak` 恢复并 `chmod 600`，哈希回到 `fdcc0fce…`。
- **根治**：默认配置移到 `config_templates/mcp_servers.default.json`，根 `mcp_servers.json` 已从 git 移除并继续被忽略；`run_server.py` 首次启动时只在文件缺失时从模板生成，已有文件绝不覆盖。以后 `git archive`/clone 不再包含运行时 MCP 配置。
- 验证：容器 `Up`、`/healthz` 200；匿名浏览器 `/` 302 到 `/auth/login`（curl 默认 `Accept: */*` 为 401，属既有行为）；公网 `/assets/index-BJvEhV-b.js` 200 且 sha256 `24572931…` 与本地一致，`/libs/live2d.min.js` 200；`assets` 仍 `immutable`、`libs` 仍 30 天；`cuc-kb` MCP 正常连接，日志无 ERROR/WARNING/Traceback；DB 3 users / 295 histories / 464 messages，部署未改动数据库。新镜像内无 `/app/frontend`，页面由 `/app/web/dist` 提供，外部用户仅需普通刷新（产物 hash 未变，无缓存失效问题）。
