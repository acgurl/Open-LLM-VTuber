# Open-LLM-VTuber 部署交接

更新日期：2026-10-21

## 1. 现状概览

| 项 | 值 |
| --- | --- |
| 访问地址 | https://vtuber.acgurl.cn/ （HTTP 200） |
| 服务器 | 甲骨文凤凰城，Ubuntu 24.04 ARM64，SSH 别名 `oracle` |
| 部署目录 | `/home/ubuntu/open-llm-vtuber` |
| 容器 | `open-llm-vtuber`，镜像 `open-llm-vtuber:1.2.1-split-ws-20261022`，`--network host`，`--restart unless-stopped` |
| 应用监听 | `127.0.0.1:12393`（FastAPI + WebSocket `/client-ws`，前端由后端静态托管） |
| 健康检查 | `https://vtuber.acgurl.cn/healthz` → 200 `{"status":"ok"}` |
| 反向代理 | Caddy，`/etc/caddy/Caddyfile` 第 129-140 行，站点 `vtuber.acgurl.cn, vtuber.acgurl.qzz.io`，`flush_interval -1` 支持 WebSocket |
| DNS / 优选 | DNSPod 按线路解析到 Cloudflare 优选 IP；Cloudflare SaaS custom hostname 经 `origin.acgurl.qzz.io` 回源；`/opt/cf2dns-sync/sync_cf_bestip.py` + `/etc/cron.d/cf2dns_sync` 每 2 小时同步 |
| ASR / TTS | Groq `whisper-large-v3-turbo` + Azure Speech（`azure_tts`，japaneast F0，`zh-CN-XiaoyiNeural`） |

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
- 当前镜像 `open-llm-vtuber:1.2.1-split-ws-20261022`（2026-10-22 构建，文本/音频双 WebSocket；上一版 `1.2.1-micoff-20261022`、`1.2.1-azure-pool-20261022`、`1.2.1-azure-20261022`、`1.2.1-tts-trim-20261022`、`1.2.1-mcp-http-20261022-r2` 仍保留可回滚）。只有改源码/前端/依赖时才需要重建：

```bash
ssh oracle
cd /home/ubuntu/open-llm-vtuber
docker build -f dockerfile -t open-llm-vtuber:1.2.1-azure-pool-20261022 .
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
- `chat_history` 已挂载到宿主机 `data/chat_history`，重建容器不再丢失历史。
- `.dockerignore` 已追加 `/conf/`、`/data/`，密钥不会打进镜像；但服务器 `conf/conf.yaml` 是唯一真实密钥来源。
- 服务器保留备份 `conf/conf.yaml.bak.deepseek.20261021005452`；换音色前备份为 `conf/conf.yaml.bak.hsiaoyu.20261022060303`、`conf/conf.yaml.bak.xiaoyi.20261022060926`；切 Azure 前备份为 `conf/conf.yaml.bak.azure.20261022064712`；连接池改造前源码备份为 `*.bak.pool.20261022065834`。Azure 源码/部署脚本备份见 `*.bak.azure.20261022*`、`run-container.sh.bak.azure-pool.20261022*`。
- 当前本地未提交：`.gitmodules`（前端指向 acgurl fork）、未跟踪的 `HANDOFF.md` 与 `conf/`，以及本次 `tts/azure_tts.py`、`tts/pooled_tts.py`、`tts/tts_factory.py`、`tts/tts_interface.py`、`service_context.py`、`config_manager/tts.py`、`tests/test_pooled_tts.py`（已同步服务器并打进 Azure pool 镜像）。其余源码/测试改动已提交并推送到 `origin/main`（最新 `9767676`）。
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
