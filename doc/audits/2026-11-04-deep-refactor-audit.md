# 深度重构审计报告 — 2026-11-04

- **审计基线**：`origin/main` @ `8c82c7c`（PR #11 已合并；PR #10 `feat/parallel-tool-calls` 仍 OPEN，改动 `mcpp/mcp_client.py`、`mcpp/tool_executor.py`）
- **测试基线**：`PYTHONPATH=src uv run --frozen python -m unittest discover -s tests` → `Ran 374 tests … OK`（@`8c82c7c`）
- **前端门槛**：`cd web && npm run build`（tsc + vite）→ 绿（@`8c82c7c`，审计 agent 在副本中执行）
- **方法**：5 个只读分区审计（agent/MCP、对话/WS、HTTP/鉴权/存储/连接器、配置/引擎/构建、前端）+ 第二轮复审 + 扫描器。每个缺陷都有探针或代码行证据；每个重构候选都有 pin 清单。

> 本报告中的所有计数都是**带日期的测量**，不是事实。后续任何一节车厢开工前，必须在自己的分支点上用同一条命令重新计数。

## 0. 架构总评

**架构本身没问题；债务集中在三处：(1) 同一业务规则在“单聊/群聊”“Claude/OpenAI 工具循环”两条并行路径上漂移；(2) `service_context.py`（1033 行）承担 6 种职责；(3) 一批从未被测试覆盖的失败路径（prompt 模式工具调用、群聊解散、切换配置）实际上是坏的。**

- 分层与依赖方向清晰：factory → interface → engine；routes 只依赖 `auth`/`storage`/`ServiceContext`；前端只依赖 WS/HTTP 契约（`BACKEND_API.md`）。
- 鉴权失败即拒绝；SQL 全部参数化，所有权校验写在 `WHERE` 子句里；会话 token 用 HMAC + `compare_digest`；WS 校验 Origin。
- 文本级重复率很低：`symilar -d 8` 测得 `percent=0.26`（@`8c82c7c`）。真正的重复是**语义漂移**，不是文本拷贝。
- 扫描器信号：`uvx ruff check src --select C901 --output-format concise | grep -c C901` → **22**；`grep -rnE 'except (Exception|BaseException)' src | wc -l` → **124**（大部分位于任务/套接字边界并且有日志，只有标注的几处需要收窄）；`vulture --min-confidence 60` 几乎全是 pydantic 校验器误报。

## 1. 缺陷（优先级高于所有重构）

| ID | 缺陷 | 位置 | 证据 | Pins |
|---|---|---|---|---|
| D-ACL1 | `/live2d-models/info` 匿名可见受限模型的目录名和头像路径 | `routes.py:183` `_scan_live2d_models`、`auth/middleware.py:20-27` | 探针：`allowed_users:[alice]` 的 `secretmodel` 在匿名 GET 下返回 200 | 无 |
| D-ACL2 | 预设 YAML 解析失败时跳过 `is_allowed`，受限预设的文件名会出现在列表里 | `config_manager/utils.py:192-196` | 代码阅读 | 无 |
| D-AUTH1 | 不检查 `email_verified`，而 email 域名决定 QQ 机器人绑定资格 | `auth/manager.py:239`、`connectors/binding.py:33` | `grep -rn email_verified src tests` → 0 | 无 |
| D-CACHE1 | OIDC 模式下 `/tts-ws` 生成的音频永远 404（stem 没有带用户作用域） | `routes.py:58`、`server.py:167`、`web_tool/main.js:149` | 探针：已登录用户 GET `/cache/<stem>.wav` → 404 | `test_webtool_routes.py:51` 不受影响 |
| D-TOOL1 | prompt 模式工具调用被静默丢弃：模板要求 `arguments` 是对象，代码却去 `json.loads`，TypeError 被宽泛的 except 吞掉；`{}` 参数也会被 `all()` 拒掉 | `mcpp/tool_executor.py:151-172` | 探针 `p1.py`：对象参数 → `[]` | 无；**与 PR #10 同文件** |
| D-TOOL2 | `mcp_prompt.txt` 示例 JSON 在 `"mcp_server"` 后缺逗号 | `prompts/utils/mcp_prompt.txt:22` | 代码阅读 | 无 |
| D-TOOL3 | prompt 模式第 2 轮丢失 assistant 消息；解析失败时把同样的消息原样重发直到 10 轮上限 | `basic_memory_agent.py:570-605` | 探针：10 次相同的 LLM 调用 | 无 |
| D-TOOL4 | 模型一旦拒绝 tools，`support_tools=False` 永久生效且跨会话共享，而 agent 每轮又重置为 native 模式 → 之后既不发 tools，也不注入 MCP 提示 | `openai_compatible_llm.py:55,101,220-226`、`basic_memory_agent.py:657` | 探针 `p2.py` | 无 |
| D-TOOL5 | `tool_call_status.timestamp` 生成 `…+00:00Z`，`Date.parse` → NaN，违反 `BACKEND_API.md:424` | `tool_executor.py:191` | 探针输出 | `test_tool_executor.py:18` 只断言 `endswith("Z")`，修复后仍通过 |
| D-LLM1 | 模板 LLM 不传 `temperature`，永远是 1.0 | `agent/stateless_llm_factory.py:25-33` | 代码阅读 | 无 |
| D-LLM2 | 未启用 MCP 时每次构建 agent 都打一条误报 warning（`_json_detector` 总是被创建） | `basic_memory_agent.py:105-114` | 代码阅读 | 无 |
| D-GRP1 | 群聊在运行中解散后，AI 对 AI 的循环任务永不停止（停止路径都按 `client_uid` 查找，而任务按 `group_id` 存储） | `conversation_handler.py:135-149`、`chat_group.py:92-98` | 探针 `p2.py` | `patch.object(conversation_handler,"process_group_conversation")` |
| D-GRP2 | 群聊在多个 await 之间遍历活的 `group.members` 集合 → `RuntimeError: Set changed size` | `conversation_handler.py:140` | 探针 | 无 |
| D-GRP3 | 群聊成员某一轮没有 TTS 任务时不发 `force-new-message`/`conversation-chain-end`；`tts_manager.task_list` 无限增长 | `group_conversation.py:269` | 代码阅读 | 无 |
| D-GRP4 | 群聊轮次写入“当时打开的”历史，而不是本轮绑定的历史；群聊工具调用会落到之前单聊遗留的历史里 | `group_conversation.py:101,293`、`conversation_utils.py:208` | 代码阅读 | 保留 `getattr(…, default)` |
| D-HIST1 | proactive/`skip_history` 轮次的工具调用仍然被保存（`None` 同时表示“不保存”和“用当前历史”） | `service_context.py:515` | 代码阅读 | `test_conversation_utils.py:62-64` 的 fake 用的是 `**kwargs` |
| D-CTX1 | 切到不开翻译的角色后，旧翻译引擎仍然生效 | `service_context.py:804-806` | 探针 `p1.py` | 无 |
| D-CTX2 | 每次 `switch-config` 都泄漏一个 MCP client（以及 stdio 子进程）；旧 Hume agent 不关闭 | `service_context.py:150-160` | 探针：`aclose called: False` | `patch.object(service_context_module, "MCPClient"/…)`、`_init_mcp_components` |
| D-WS1 | `message_handler` 的 `finally` 通过 defaultdict 为已清理的客户端重新创建空条目 | `message_handler.py:50-51` | 探针 | 模块属性 `message_handler` 必须保留 |
| D-WS2 | 打断时 `cancel()` 后不等待，可能与正在落库的 AI 消息竞争 → 重复保存（**未用探针确认**） | `conversation_handler.py:182` | 代码阅读 | — |
| D-PRX1 | proxy 遍历活的 `self.clients` | `proxy_handler.py:285` | 代码阅读 | `test_proxy_handler` 私有属性 |
| D-PRX2 | proxy 队列只在 `conversation-chain-end` 时释放，任何错误回复都会让后续输入永远排队（OIDC 模式禁用 proxy，所以生产不受影响） | `proxy_message_queue.py:119` | 代码阅读 | — |
| D-CONN1 | QQ 对非幂等的 `POST …/messages` 在 `ReadTimeout`/502-504 时重试 → 可能重复发送；group/c2c 被去重拒绝时 `_reply` 静默丢掉剩余分段 | `connectors/qq.py:189`、`dispatcher.py:475-480` | 代码阅读（QQ 是否按 `msg_seq` 去重**未验证**） | **测试固化了这个 bug**：`test_qq_connector.py:232,238,245` |
| D-CONN2 | 删除绑定或 `/bind` 会在会话处于轮次中途时直接关闭它 | `dispatcher.py:372-375` | 代码阅读 | 只有行为断言 |
| D-TTS1 | `tts_model: pyttsx3_tts` 能通过校验，但 `init_tts` 时 AttributeError | `config_manager/tts.py:535`、`service_context.py:738` | 探针 | `test_factories.py:44,48` |
| D-TTS2 | `cartesia_tts` 用绝对导入 `open_llm_vtuber.*`，本地 `uv run run_server.py` 下 ModuleNotFoundError（Docker 里能跑，只是因为装了第二份包） | `tts/cartesia_tts.py:8` | 探针 | `test_engine_error_paths.py:9` |
| D-TTS3 | cosyvoice/cosyvoice2/spark 依赖 `gradio_client`，fish_api 依赖 `fish_audio_sdk`，两者都没声明 | `pyproject.toml` | 导入遍历探针 | `test_tts_logging.py:12-18` |
| D-CFG1 | 两份模板的 `use_mcpp` 不一致（EN True / ZH False；模型默认 False） | `conf.default.yaml:131` | 键集机械比对 | `test_connector_character.py:12` |
| D-ARC1 | `archive.py` 对非 dict 的 JSON 抛 AttributeError → `server.initialize()` 中止；docstring 与实现不符 | `storage/archive.py` | 代码阅读 | — |
| D-WEB1 | 麦克风 VAD 误触发（咳嗽、点击）后 `speaking` 一直为 true，持续推 `mic-audio-data` → 反复弹“音频过长”；误触发也会打断 AI | `web/src/services/mic.ts:68-90` | vad-web 源码 + grep `Misfire` → 0 | 无前端测试 |
| D-WEB2 | VAD 在 20s 超时后才启动时实例永不销毁，麦克风一直占用；`doStart` 期间调用 `stop()` 被忽略 | `mic.ts:65-93` | 代码阅读 | — |
| D-WEB3 | 本地 SSE MCP 流自然结束后不 reject 挂起的请求 → 每次工具调用干等 35s | `web/src/services/localSseMcpClient.ts:154-157` | 代码阅读 | — |
| D-WEB4 | `history-deleted` 不看 `success` | `web/src/services/incoming.ts:162-164` | 代码阅读 | — |

## 2. 依赖与镜像

| ID | 项 | 证据 | 类别 |
|---|---|---|---|
| X1 | `ruff`、`pre-commit` 是运行时依赖 → 移到 dev 组（`.venv` 实测约 40 MB） | 阻断导入后 374 个测试全过；CI lint 用的是 `uvx pre-commit` | DEP-WIN |
| X2 | `duckduckgo-mcp-server`、`websocket-client` 没有任何导入方 | 阻断导入后 374 个测试全过；site-packages 里没有调用时导入 | DEP-WIN |
| X3 | `numpy<2` 是为已删除的 onnxruntime 加的（`feab42a`） | 需要重新 lock 并跑测试才能确认 | DEP-WIN（待验证） |
| X4 | `requirements*.txt` 用 `uv pip compile` 现场解析，与 `uv.lock` 漂移；workflow 在任意分支 push 时都会触发并自动提交 | 本地重跑 → anthropic 2.4.0，而 lock 里是 0.76.0 | DEFECT（CI） |
| X5 | `.dockerignore` 没排除 `.git`（本地 64 MB）和 `web/`（41 MB 的 `public` 被重复打包）；`uv:latest` 没固定版本；`start-app` 启动时会 sync | 磁盘实测 | PERF |
| X6 | `blivedm` 已于 2025-04 移除，B 站直播实际不可用 | `git log` `4645003` | DELIBERATE／需补文档 |

## 3. 可安全执行的重构（测试冻结）

| ID | 内容 | 规范归属 | Pins | 依赖 |
|---|---|---|---|---|
| R1 | Claude/OpenAI 工具循环里三份工具轮次代码合并为 `_run_tool_round`，统一“缺少 executor”的消息与 assistant 文本落库规则；按 native/prompt 拆分 `_openai_tool_interaction_loop`（C901 27） | `basic_memory_agent.py` | 方法名/签名；测试用 `__new__` 构造（新增状态要有类级默认值）；子串 `"not configured"` | D-TOOL1..4 之后 |
| R2 | 单聊/群聊共用的轮次落库 helper（human/AI/interrupt 三组）、`skip_history` 只在一处计算 | `conversation_utils.py` | `single_conversation.finalize_conversation_turn` 名称导入、`conversation_utils.process_agent_output`/`prepare_audio_payload`、`conversation_handler.process_single_conversation`/`prompt_loader` | D-GRP4、D-HIST1 之后 |
| R3 | 抽一个 `request_user_id(request, auth, ctx)` helper，替换 `mcp_routes._request_user_id`、`connector_routes._user_id`、`routes._default_user_id`（后者硬编码了 `"local"`）；把 `init_*_routes` 里的处理函数提到模块级（C901 21/17/16） | `auth/` | 必须保留回退到 `default_context_cache.user_id`（`test_connector_routes.py:35`） | — |
| R4 | `user_servers.py` 的主机后缀黑名单两份已漂移 + 两处重复的 `getaddrinfo` 公网检查 → `_resolve_public` | `mcpp/user_servers.py` | 9 处错误文本 `assertIn` | — |
| R5 | 死代码一批：`isinstance(potential_json, dict)` 分支、恒真的 `_json_detector` 守卫、`len(choices)==0` 重复分支、`FormattedTool.generic_schema`、`ServerRegistry.remove_server`、`_is_valid_*` 转发、`user_servers` 不可达的端口 try、`SiliconFlowTTS` 的空覆盖、错误注释（`types.py:16` 超时、`json_detector.py:140`、`pyttsx3_tts.py:9`、`archive.py`、`legacy._is_safe_filename` 注释）、`send_conversation_end_signal` 的 emoji 参数 | 各自模块 | 见各项 | `MCPClient` 未使用的参数要等 PR #10 合并后再删 |
| R6 | 用户 ID 正则三处重复 → `config_manager/storage` 导入 `validate_user_id` | `storage/base.py` | — | — |
| R7 | TTS：cosyvoice/cosyvoice2 约 30 行近似拷贝；x_tts/gpt_sovits 共用的状态检查与写文件块；统一错误处理（返回 None 加 `remove_partial_file`） | `tts/` | `test_engine_error_paths.py:14` 期望返回 None | — |
| R8 | 前端：两个 SSE 帧解析器合并；`camera.ts`/`capture.ts` 共用 `drawToJpeg`；`useCopied()`；`icons.tsx`；删除 `live2d.destroy`/`onLocalMcpUnregistered`（或接上调用） | `web/src/services`、`components` | 无测试，按各项做浏览器 smoke | — |
| R9 | C901 拆分：OpenAI/Claude `chat_completion`、`local_bridge.call_tool`、`parse_user_mcp_config`、`_validate_conversation_input`、`_process_buffer`、`forward_server_messages`（在 D-PRX1 之后）、`dispatcher._handle_message`、`qq.parse_event` | 原文件内 | 只有名称 pin | 对应缺陷修复之后 |

## 4. 结构性工单（放在最后，唯一允许改测试的车厢）

- **S1** `service_context.py` 拆分：MCP 工具装配（约 280 行，含两组近似重复的 `_init_*`/`_build_*`）→ `SessionTooling`；历史透传 → 直接暴露 `UserHistoryStore`；角色切换不再在 context 里发 WS 帧。Pins：`patch.object(service_context_module, "MCPClient"/"ToolExecutor"/"ToolManager"/"ServerRegistry"/"ToolAdapter"/"validate_config"/"read_yaml")`、`ServiceContext.load_from_config`、`context._init_mcp_components`/`_base_mcp_tools`/`_user_mcp_records`/`_local_mcp_config`。需要逐个列出允许修改的测试。L。
- **S2** `web/src/live2d/controller.ts`（771 行）→ `gestures.ts` + `framing.ts`。M。

## 5. 被 pin 阻塞 / 拒绝 / 刻意保留（不要重提）

| ID | 项 | 状态 | 理由 |
|---|---|---|---|
| B1 | `storage` 里 `create/update/delete_user_mcp_server` 只有测试在用 | Rejected | 测试把它们当作仓储 API 契约（10 个调用点）；删掉没有收益 |
| B2 | `SentenceDivider._full_response`/`complete_response`、`ToolAdapter.get_tools` 只有测试在用 | Rejected | 同上，代价大于收益 |
| B3 | i18n DESCRIPTIONS 约 675 行没有运行时消费者 | Rejected | 由 `DescriptionKeyTests` 固定，属于配置文档；不是缺陷 |
| K1 | 三个路径守卫（`resolve_existing_file_within` / `_get_safe_history_path` / `validate_file`） | Deliberate — do not fix | 安全语义各不相同 |
| K2 | OpenAI 工具 schema 扁平化、Claude 用原始 schema | Deliberate | 改了会改变模型看到的东西，属于产品决策 |
| K3 | `chain-start` 与 audio 分属两条 WS，相互之间无序 | Deliberate | 修复需要在协议里加 turn id，而协议冻结 |
| K4 | `BACKEND_API.md` §19 的已知坑（#2/#4/#10/#17/#19） | Deliberate | 属于契约 |
| K5 | 鉴权、Cookie、OIDC state、SQLite 事务、绑定码 | 已检查，干净 | — |
| K6 | DNS rebinding 窗口（校验与连接之间） | Deliberate | 已知设计限制 |
| K7 | `config_manager/auth.py` 的 `_COOKIE_NAME_PATTERN` 与用户 ID 正则写法相同 | Deliberate（C11） | 两者是互不相关的规则（cookie 名与用户 ID），合并会把它们耦合在一起 |
| K8 | 角色切换时由 context 自己发 WS 帧 | Deliberate（C14） | 测试直接调用 `handle_config_switch(websocket, …)`；拆出去需要改调用方或测试，对可读性的收益很小 |
| Q1 | 受限角色 ACL 按 `display_name` 匹配（用户在 IdP 改名后即可冒用） | **Approved（2026-11-04）→ C1** | 只按 user id 或已验证的 email 匹配；线上 `allowed_users` 需要迁移 |
| Q2 | 把 barge-in 打断从 `onSpeechStart` 移到 `onSpeechRealStart` | **Rejected（2026-11-04，用户决定）** | 保持现有打断时机；C6 只修误触发后的推流 |

## 6. 清理台账（车厢顺序）

状态取值：`Proposed` / `Approved` / `In progress` / `Blocked` / `Superseded` / `Done` / `Rejected`

| 车厢 | 内容 | 冻结侧 | 验证命令 | 依赖 | 状态 |
|---|---|---|---|---|---|
| C1 | 访问控制与鉴权缺陷：D-ACL1、D-ACL2、D-AUTH1、D-CACHE1、Q1，每项一个锁定测试 | 测试；Q1 允许修改 `test_character_access.py`/`test_character_assets.py` 中按名字匹配的用例 | unittest + `npm run build` 不受影响 | — | Done（#17） |
| C2 | 工具调用缺陷：D-TOOL1..5、D-LLM1、D-LLM2、D-MCP1、D-MCP2 | 测试；唯一允许修改的是 `test_mcp_client.py:24` 的 fixture（`metadata`→`meta`） | unittest | **PR #10 合并或 rebase 之后**（同文件） | Done（#15） |
| C3 | 会话/WS 缺陷：D-GRP1..3、D-CTX1、D-WS1、D-WS2、D-PRX1、D-PRX2、P-TR1 | 测试 | unittest | — | Done（#16） |
| C4 | 历史归属：D-GRP4、D-HIST1；切换配置泄漏 D-CTX2 | 测试 | unittest | C3 | Done（#21） |
| C5 | 引擎与配置（含删除 Letta：生产 `conf.yaml` 仍有 `letta_agent:` 段 → 配置类必须继续接受该键并忽略 + warning；`conversation_agent_choice: letta_agent` 给出明确报错）：D-TTS1、D-TTS2、D-TTS3（extra + 模板注释）、D-CFG1、D-ARC1、D-HUME1..3、D-LETTA1、D-TR1、W-HTTPX1、D-LIVE1、P-OLL1 | 测试 | unittest + 导入遍历探针 | — | Done（#18） |
| C6 | 前端缺陷：D-WEB1..4 | — | `npm run build` + 浏览器 smoke | — | Done（#14） |
| C7 | QQ 重试只针对连接阶段错误；D-CONN2 | **测试 fixture 编码了这个 bug**：`test_qq_connector.py:232/238/245` 显式允许修改 | unittest | — | Done（#13） |
| C8 | 依赖瘦身：X1、X2、X3（验证不过就 Rejected）、X4、X5，附镜像守卫（CI smoke 导入） | 测试 | unittest + docker build + 容器内 import smoke | — | Done（#24） |
| C9 | R1 + R4 + R5 中 agent/mcpp 的部分 + R9 中 LLM 的部分 | 测试 | unittest | C2 | Done（#23） |
| C10 | R2 + R9 中会话的部分 | 测试 | unittest | C3、C4 | Done（#26） |
| C11 | R3 + R6 + R9 中路由/连接器的部分（R4 移到 C9，因为 `mcpp/` 归 C9） | 测试 | unittest | C1、C7 | Done（#20） |
| C12 | R7 + R5 中引擎的部分 | 测试 | unittest | C5 | Done（#22） |
| C13 | R8（前端清理） | — | build + smoke | C6 | Done（#19） |
| C14 | S1 结构拆分（目标是零测试修改；实际也是零修改） | 测试（最终没有改任何测试） | unittest | C4、C9、C10 | Done（#27） |
| C15 | S2 controller 拆分 | — | build + smoke | C13 | Done（#25） |

## 7. 第二轮复审（新视角，覆盖第一轮扫得较浅的区域）

第二轮在 hume/letta/translate/ollama 找到了新问题。下面这些区域标记为 **dry**：17 处 `create_task`（引用都有保留，也都能取消）、启动/关闭顺序、`user_store`、`session_factory`、connector↔ServiceContext 衔接、`transformers`/`streaming`、`utils/`、缺少 encoding 的 `open(`、其余同步 I/O。

| ID | 缺陷 | 位置 | 证据 | Pins | 车厢 |
|---|---|---|---|---|---|
| D-HUME1 | 15s 内的第二轮必定 AttributeError：websockets 16 的 `ClientConnection` 没有 `.closed` | `agent/agents/hume_ai.py:139` | `'closed' in dir(ClientConnection)` → False；autospec 探针复现 | `test_hume_ai.py` 只覆盖 `_spawn`/`close` | C5 |
| D-HUME2 | `__del__` 会删掉共享 `./cache` 下所有 `evi_audio_*.wav`，包括其他会话正在读的文件 | `hume_ai.py` | 代码阅读 | — | C5 |
| D-HUME3 | `ConnectionClosed` 后无界递归调用 `chat()` | `hume_ai.py` | 代码阅读 | — | C5 |
| D-LETTA1 | 调用了不存在的 `agents.messages.create_stream`（letta-client 1.7.6 只有 `stream`）；同步客户端在 async 生成器里迭代会阻塞事件循环 | `agent/agents/letta_agent.py:61` | `'create_stream' in dir(...)` → False | `test_agent_interface.py` 不受影响 | C5 |
| D-TR1 | 腾讯翻译 API 出错时（HTTP 200 + `Error`）把字符串 "Translation failed" 当作译文送去 TTS 念出来 | `translate/tencent.py` | 代码阅读 | 无 | C5 |
| P-TR1 | 每句话的翻译都在事件循环上同步 `httpx.post`，开启翻译后阻塞所有连接 | `conversation_utils.py:374` | 调用链 | `test_translate_error_paths.py` patch 了 `deeplx.httpx.post` 且同步调用 → 在调用处包 `asyncio.to_thread`，`translate()` 保持同步 | C3 |
| P-OLL1 | `OllamaLLM.__init__` 同步预加载最长 120s，在 `switch-config` 的 WS 处理链路上执行；每次构造都 `atexit.register`，旧实例无法释放 | `stateless_llm/ollama_llm.py` | 调用链 | 无 | C5 |
| Q3 | Letta 所有用户共用同一个 agent id → OIDC 多用户下记忆跨用户共享 | `letta_agent.py` | 代码阅读 | — | **Approved（2026-11-04）：整体删除 Letta agent → C5**（D-LETTA1 随之 Superseded） |

## 8. 第三轮复审（专门扫第三方 SDK 的 API 漂移）

探针：对 `.venv` 里实际安装的包做 `hasattr`/`inspect.signature`/`model_fields` 检查，覆盖 anthropic 0.76.0、openai 2.15.0、groq、azure speech、edge-tts、elevenlabs、cartesia、httpx、websockets 16、PyJWT、mcp 1.26.0、aiohttp。结果：`SUMMARY {'OK': 88, 'DEPRECATED': 1, 'OK*': 1, 'N/A': 4, 'SILENT': 2}`（@`8c82c7c`）。**没有新的会在运行时抛错的缺陷 → 审计收敛。**

| ID | 问题 | 位置 | 证据 | Pins | 车厢 |
|---|---|---|---|---|---|
| D-MCP1 | 读取 `response.metadata`，但 `CallToolResult` 的字段是 `meta`（别名 `_meta`）→ stagehand `liveViewData` 分支永远拿不到数据 | `mcpp/mcp_client.py:244,274` → `tool_executor.py:285` | `CallToolResult.model_fields` = `['meta','content','structuredContent','isError']` | **fixture 编码了这个 bug**：`test_mcp_client.py:24` 的 `SimpleNamespace(metadata={})` → 允许修改，并在 C2 中列出；**与 PR #10 同文件** | C2 |
| D-MCP2 | `ResourceLink.uri`、`EmbeddedResource.resource` 的内容被丢弃，只剩 `type` | `mcp_client.py:253` | 字段比对 | 无 | C2 |
| W-HTTPX1 | `httpx.post(data=<str>)` 每次调用都发 DeprecationWarning，将来会变成运行时错误 | `translate/deeplx.py:18`、`translate/tencent.py:113` | `-W always` 探针 | `test_translate_error_paths.py:12,20` 整个替换了 `post` | C5 |
| D-LIVE1 | `ClientConnection` 既没有 `.closed` 也没有 `.open`，断线检测失效（有 hasattr 保护，不会抛错） | `live/bilibili_live.py:72-77` | 同上 | `test_bilibili_live.py:85` | C5 |

## 9. 新发现的 pin 类别与教训（留给下一次审计）

- **假对象照抄了错误的属性名**（`SimpleNamespace(metadata=…)`）：测试通过恰恰掩盖了 SDK 漂移。今后凡是用假对象替身 SDK 返回值，都要用 `create_autospec(真实类)` 或者对照 `model_fields`。
- **版本没设上限的依赖**（`letta-client>=0.1.100` 锁到了 1.7.6）：方法被改名后静默失效。探针手段是对锁定版本做 `dir()`/`signature` 比对，扫描器看不出这一类问题。
- **`upgrade_codes/` 不是历史代码**：`run_server.py:10,104` 每次启动都会执行它。
- **`git stash` 在所有 worktree 之间共享**：并行车厢用 stash 验证“没有修复时测试会失败”，结果 C1 和 C3 的 stash 被互相 pop 走。今后改用 `git diff > patch` + `git checkout` + `git apply`。
- **`update-requirements.yml` 曾在任意分支 push 时自动提交到车厢分支上**：C8 已改为只在 main 上触发，并且从 `uv.lock` 导出。
- **为了保住 patch 目标而保留的生产代码接缝**：`service_context.py` 里 `MCPClient`/`ToolManager`/`ToolExecutor` 带 `# noqa: F401` 的导入，以及 `ToolingField` 描述符，都是为了让 `patch.object(service_context_module, …)` 继续生效。下一次审计如果允许修改测试，可以把这些 patch 目标迁到 `session_tooling`，再删掉这几个导入。

## 10. 清理列车执行结果（2026-11-04）

- **结果**：C1–C15 全部合并（#13–#27），另外 PR #10（并行工具调用）按用户决定先于 C2 合并。
- **测试数**：`PYTHONPATH=src uv run --frozen python -m unittest discover -s tests` 从 374（@`8c82c7c`）增加到 495（@`1c555a7`，全部车厢合并之后）。新增的都是锁定测试或特征测试。
- **C901**：`uvx ruff check src --select C901 --output-format concise | grep -c C901` 从 22（@`8c82c7c`）降到 4（@`1c555a7`）。剩下的 4 个：`asset_access._build_rules`、`json_detector._extract_json`（审计时就判断不需要拆）、`legacy._read_legacy_file`、`legacy.import_legacy_histories`。状态为 Rejected：它们是旧格式导入的一次性路径，拆分没有收益。
- **授权范围内修改过的测试**（都在各自 PR 正文里逐条列出）：
  - C1：`test_character_access.py`、`test_character_assets.py` 中按显示名匹配的用例（Q1）。
  - C2：`test_mcp_client.py` 的 fixture，`metadata` 改为 `meta`。
  - C5：`test_agent_interface.py` 中关于 Letta 的断言（Letta 已删除）。
  - C7：`test_qq_connector.py` 的重试用例。
  - 其余车厢没有修改任何测试。
- **尚未验证、需要人工处理**：
  - C6/C13/C15 的浏览器 smoke：步骤写在各自 PR 正文里。前端没有测试框架；C15 已经做过数值等价对比。
  - C8 的镜像体积前后对比：本机没有 docker，CI 的 arm64 构建和镜像内 smoke 已通过。
  - **部署**：以上改动都还没有上线。上线前要注意：`characters/zh_yifan.yaml` 中的 `"acgurl"` 条目按显示名匹配，Q1 之后会失效（同文件的 user id 条目仍然有效）；生产 `conf.yaml` 里的 `letta_agent:` 段会被忽略，并打一次 warning。
- **后续项（Proposed，放产品 backlog，未估点：unsized——单人项目没有估点刻度）**：
  - `web/src/utils/capture.ts` 的一次性截图仍在 `await video.play()`，在后台标签页里可能卡住（C13 发现，未能复现）。
  - 本地 MCP bridge 的结果路径不保留 `ResourceLink.uri`（C2 发现）。
  - `BACKEND_API.md` 中引用的源码行号已经漂移（例如 `tool_call_status` 一节）。
