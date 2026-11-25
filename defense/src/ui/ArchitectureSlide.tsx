import React, { useState } from 'react';
import type { DeckSource, SlideDefinition } from '../data/deck.ts';

export type ArchitectureView = 'overview' | 'kb' | 'vtuber' | 'cli';

interface ArchitectureSlideProps {
  readonly deck: DeckSource;
  readonly slide: SlideDefinition;
}

type ArchTone = 'accent' | 'ok' | 'warn' | 'secondary' | 'tertiary' | 'muted';

interface ArchLine {
  readonly lead?: string;
  readonly text: string;
}

interface ArchCardProps {
  readonly title: string;
  readonly badge?: string;
  readonly tone?: ArchTone;
  readonly lines: readonly ArchLine[];
  readonly style?: React.CSSProperties;
}

interface ArchZoneProps {
  readonly title: string;
  readonly badge?: string;
  readonly tone?: ArchTone;
  readonly style?: React.CSSProperties;
  readonly children: React.ReactNode;
}

const VIEW_TABS: readonly {
  readonly id: ArchitectureView;
  readonly label: string;
  readonly footnoteLeft: string;
  readonly footnoteRight: string;
}[] = [
  {
    id: 'overview',
    label: '全景三端联动',
    footnoteLeft:
      '交互链路：Live 小智 ⇄ 云端 Streamable HTTP MCP (cuc-kb :8765) ＋ 浏览器直连本机 127.0.0.1:8788 (cuc-cli)',
    footnoteRight: '隐私红线：公共制度集中治理，个人凭据仅存本机 ~/.cuc-cli',
  },
  {
    id: 'kb',
    label: 'cuc-kb 知识库',
    footnoteLeft:
      '底座：qwen3.7-text-embedding (1024d Qdrant) + 手写稀疏 BM25 (1–3ms) + RRF 40→20 + qwen3-rerank',
    footnoteRight: 'P1 缓存：Rerank 40ms / Search 0ms · 4 只读 MCP 全校复用',
  },
  {
    id: 'vtuber',
    label: 'Live 小智对话端',
    footnoteLeft:
      '通道拆分：/client-ws (10–50ms text-delta + 本地桥接) ∥ /audio-ws (独立锁音频流) · Azure TTS 连接池 0.22–0.28s',
    footnoteRight: 'Casdoor OIDC 三层隔离 · 群聊屏蔽本机工具 · 远程禁 stdio',
  },
  {
    id: 'cli',
    label: 'cuc-cli 本机架构',
    footnoteLeft:
      '零第三方依赖 (Node.js 22.4+)：12 只读 MCP 工具 · 10 类校内业务 · 8 大官方上游 · CAS 静默换票',
    footnoteRight: 'HTTP/MCP 强制 PII 脱敏 · execFile 沙箱隔离 · 凭据不出本机',
  },
];

const ArchZone: React.FC<ArchZoneProps> = ({
  title,
  badge,
  tone = 'accent',
  style,
  children,
}) => (
  <section className={`ed-arch-zone tone-${tone}`} style={style}>
    <div className="ed-arch-zone-head">
      <span className="ed-arch-zone-title">{title}</span>
      {badge && <span className="ed-arch-zone-badge">{badge}</span>}
    </div>
    {children}
  </section>
);

const ArchCard: React.FC<ArchCardProps> = ({
  title,
  badge,
  tone = 'accent',
  lines,
  style,
}) => (
  <article className={`ed-arch-card tone-${tone}`} style={style}>
    <div className="ed-arch-card-head">
      <span className="ed-arch-card-title">{title}</span>
      {badge && <span className="ed-arch-card-badge">{badge}</span>}
    </div>
    <div className="ed-arch-card-lines">
      {lines.map((line, idx) => (
        <div className="ed-arch-line" key={`${title}-${idx}`}>
          {line.lead ? (
            <>
              <strong>{line.lead}</strong>
              {line.text}
            </>
          ) : (
            line.text
          )}
        </div>
      ))}
    </div>
  </article>
);

const OverviewDiagram: React.FC = () => (
  <div className="ed-arch-grid-overview">
    <ArchZone
      title="对话端 · Live 小智"
      badge="ai.acgurl.cn"
      tone="tertiary"
    >
      <div className="ed-arch-zone-body">
        <ArchCard
          title="多端交互入口"
          badge="React 18 + QQ"
          tone="tertiary"
          lines={[
            { lead: 'Web 前台：', text: '手绘小智 v0.1.1 (WebP -45~80%) · 实时口型' },
            { lead: '按需 VAD：', text: '@ricky0123/vad-web 拆包 · 麦克风默认关闭' },
            { lead: '地图 & QQ：', text: '零改动解析 places 高德卡 · QQ 限 @cuc.edu.cn' },
          ]}
        />
        <ArchCard
          title="边缘代理 · 双 WS"
          badge="sso.acgurl.cn"
          tone="secondary"
          lines={[
            { lead: 'Cloudflare + Caddy：', text: '静态 30d 缓存 · flush_interval -1' },
            { lead: 'Casdoor OIDC：', text: 'user_id / history_uid / token 三层隔离' },
            { lead: '双通道拆分：', text: '/client-ws (10–50ms) ∥ /audio-ws (独立锁)' },
          ]}
        />
        <ArchCard
          title="FastAPI 引擎 & SQLite"
          badge="657 项测试"
          tone="tertiary"
          lines={[
            { lead: '推理 & 并发：', text: 'DeepSeek Flash 固定关思考 · ToolExecutor 并发' },
            { lead: '云端语音：', text: 'Groq Whisper ASR + Azure 3 连接池 0.25s' },
            { lead: '隔离与存储：', text: '群聊屏蔽本机工具 · 远程禁 stdio · SQLite WAL' },
          ]}
        />
      </div>
    </ArchZone>

    <div className="ed-arch-bridge" aria-hidden="true">
      <svg viewBox="0 0 136 640" preserveAspectRatio="none">
        <defs>
          <marker id="bridge-arr-accent" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="var(--ed-accent)" />
          </marker>
          <marker id="bridge-arr-ok" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="var(--ed-ok)" />
          </marker>
          <marker id="bridge-arr-secondary" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="var(--ed-secondary)" />
          </marker>
        </defs>

        {/* Web PDF -> PAR */}
        <path
          d="M 4 95 C 55 95, 76 115, 130 115"
          fill="none"
          stroke="var(--ed-secondary)"
          strokeWidth="2.4"
          strokeDasharray="6 4"
          markerEnd="url(#bridge-arr-secondary)"
        />

        {/* FastAPI ToolExecutor -> cuc-kb MCP :8765 */}
        <path
          d="M 4 490 C 66 490, 68 232, 130 232"
          fill="none"
          stroke="var(--ed-accent)"
          strokeWidth="3"
          markerEnd="url(#bridge-arr-accent)"
        />

        {/* Browser localMcp.ts -> cuc-cli :8788 (with halo so crossing stays crisp) */}
        <path
          d="M 4 176 C 52 176, 68 524, 130 524"
          fill="none"
          stroke="var(--ed-bg)"
          strokeWidth="9"
        />
        <path
          d="M 4 176 C 52 176, 68 524, 130 524"
          fill="none"
          stroke="var(--ed-ok)"
          strokeWidth="3"
          markerEnd="url(#bridge-arr-ok)"
        />
      </svg>

      <div className="ed-arch-bridge-pill is-secondary" style={{ top: '12%' }}>
        15m 签名 PDF
      </div>
      <div className="ed-arch-bridge-pill is-accent" style={{ top: '39%' }}>
        MCP :8765
      </div>
      <div className="ed-arch-bridge-pill is-ok" style={{ top: '76%' }}>
        127.0.0.1:8788
      </div>
    </div>

    <div className="ed-arch-overview-right">
      <ArchZone
        title="绝对核心 · 云端公共知识库 (cuc-kb · Oracle ARM64)"
        badge="2,290 份 / 52,322 块"
        tone="accent"
        style={{ flex: '1.06 1 0%' }}
      >
        <div className="ed-arch-zone-row">
          <ArchCard
            title="离线语料治理"
            badge="¥2.56 全库"
            tone="secondary"
            lines={[
              { lead: '54 站 + AIHub：', text: '99% 带原链 · 条款切片保留页码' },
              { lead: '表题注入向量：', text: '纯数字表格块召回丢失 2→0' },
              { lead: '四层版本归档：', text: '278 归档 · 12/21/30 对 · 52,322 点' },
            ]}
          />
          <ArchCard
            title="在线混合检索"
            badge=":8000 · P1 40ms"
            tone="accent"
            lines={[
              { lead: '并行双路：', text: 'BM25 (1–3ms) ∥ 百炼 Dense Top40' },
              { lead: 'RRF + 精排：', text: '40→20 → qwen3-rerank (超时拒答)' },
              { lead: '取证收紧：', text: 'N=1 展开(58→70%) · P2 省 31.2% Token' },
            ]}
          />
          <ArchCard
            title="217 地点 & 4 MCP"
            badge="误差 14.6m"
            tone="accent"
            lines={[
              { lead: '217 处地点：', text: '55 楼 + 82 办公 + 5 海南 · 17 点标定' },
              { lead: 'OCI 私有桶：', text: 'SSO/Token 鉴权 · 15m PAR 直跳 #page=N' },
              { lead: '复用与盲测：', text: '4 只读 MCP · 268 题 97.7% / 拒答 90.7%' },
            ]}
          />
        </div>
      </ArchZone>

      <div className="ed-arch-redline">
        🔒 隐私安全红线：云端仅治理公开制度与地点 &nbsp;═══&nbsp; 个人 CAS 账号 / Cookie / JWT 永不上云
      </div>

      <ArchZone
        title="本机个人隐私端 · cuc-cli (127.0.0.1 · Node.js 22.4+ 零依赖)"
        badge="240 项测试 · 全程只读"
        tone="ok"
        style={{ flex: '1 1 0%' }}
      >
        <div className="ed-arch-zone-row">
          <ArchCard
            title="本机 MCP 代理"
            badge=":8788"
            tone="ok"
            lines={[
              { lead: '三模传输：', text: 'HTTP / SSE / stdio' },
              { lead: '12 只读工具：', text: 'tt · jw · lms · room · card' },
              { lead: '安全流控：', text: 'Origins 白名单 · 15s 心跳' },
            ]}
          />
          <ArchCard
            title="HTTP 防火墙脱敏"
            badge=":8787"
            tone="ok"
            lines={[
              { lead: '只读白名单：', text: '放行 10 类业务 · 禁写操作' },
              { lead: '沙箱隔离：', text: 'execFile 执行 · 禁 --show-pii' },
              { lead: '默认脱敏：', text: '掩码姓名/学号/手机不出明文' },
            ]}
          />
          <ArchCard
            title="CAS 认证 & 8 系统"
            badge="~/.cuc-cli/"
            tone="ok"
            lines={[
              { lead: '3 种登录：', text: '微信扫码 · CDP 桥接 · AES' },
              { lead: '静默换票：', text: 'session.json 存本机自动续期' },
              { lead: '8 大上游：', text: 'sso · bkjw · courses · workflow' },
            ]}
          />
        </div>
      </ArchZone>
    </div>
  </div>
);

const KbDiagram: React.FC = () => (
  <div
    className="ed-arch-3col"
    style={{ gridTemplateColumns: 'minmax(0, 29fr) minmax(0, 43fr) minmax(0, 28fr)' }}
  >
    <ArchZone title="1. 离线语料治理与入库" badge="2,290 份 / 18,107 页" tone="secondary">
      <div className="ed-arch-zone-body">
        <ArchCard
          title="多源采集 & 地点标定表"
          badge="99.0% 带原链"
          tone="secondary"
          lines={[
            { lead: '校内来源：', text: '54 个官网站点 + AIHub 原始文档' },
            { lead: '元数据回填：', text: '2,268 份 source_url · 95.5% 发布日期' },
            { lead: '217 校园地点：', text: '3D 热点 + OSM 17 点单应标定 (14.6m)' },
          ]}
        />
        <ArchCard
          title="条款级切片与向量化"
          badge="¥2.56 全库"
          tone="secondary"
          lines={[
            { lead: 'PyMuPDF 切片：', text: '按条款切分，保留文号、页码与标题' },
            { lead: '表题注入向量：', text: '107 表块重嵌，纯数字表丢失 2→0' },
            { lead: '非对称嵌入：', text: '百炼 qwen3.7-text-embedding (1024d)' },
          ]}
        />
        <ArchCard
          title="版本治理 & 双引擎存储"
          badge="52,322 块"
          tone="warn"
          lines={[
            { lead: '278 份归档：', text: '人工逐对核验 12 废止 / 21 重发 / 30 补链' },
            { lead: '热更新 & 助手：', text: '25 助手重划 · clause_updates.json 覆写' },
            { lead: '私有存储：', text: 'Qdrant + 内存快照 + OCI 私有 PDF 桶' },
          ]}
        />
      </div>
    </ArchZone>

    <ArchZone
      title="2. 在线混合检索与精准取证 DAG (:8000)"
      badge="冷查 1.2s · P1 0–40ms"
      tone="accent"
    >
      <div className="ed-arch-zone-body" style={{ gap: '8px' }}>
        <ArchCard
          title="查询入口 & P1 线程安全 TTL 缓存"
          badge="Search 0ms / Rerank 40ms"
          tone="accent"
          lines={[
            { lead: '多维过滤：', text: 'query · assistant · role · campus · prefer_current (MCP=1)' },
            { lead: '三级缓存：', text: 'Search TTL 120s · Rerank TTL 300s · Embed LRU 2048' },
          ]}
        />

        <div className="ed-arch-arrow-down" aria-hidden="true">
          ↓
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
            gap: '10px',
            flex: '0.9 1 0%',
          }}
        >
          <ArchCard
            title="稀疏 BM25"
            badge="1–3ms"
            tone="accent"
            lines={[
              { text: '手写 postings + 布尔掩码' },
              { text: '768 查与 rank_bm25 一致' },
            ]}
          />
          <ArchCard
            title="Dense 向量"
            badge="Top 40"
            tone="accent"
            lines={[
              { text: '百炼 qwen3.7-embedding' },
              { text: 'ThreadPool 并行 Qdrant' },
            ]}
          />
          <ArchCard
            title="217 地点索引"
            badge="<1ms"
            tone="ok"
            lines={[
              { text: '名称 / 别名 / 括号楼号' },
              { text: '命中地点意图 conf=0.99' },
            ]}
          />
        </div>

        <div className="ed-arch-arrow-down" aria-hidden="true">
          ↓
        </div>

        <ArchCard
          title="RRF (40→20) + 精排 + 四层版本防线"
          badge="旧版泄漏 = 0"
          tone="warn"
          lines={[
            { lead: '精排拒答门禁：', text: 'qwen3-rerank 超时或异常自动标 degraded 并拒答' },
            { lead: '降权与展开门控：', text: '新版入候选压旧版 + 禁止被替代旧版相邻展开' },
            { lead: '汇编让位单行：', text: '同族新版优先（消融掉 5–6 题）；点名旧年份可查' },
          ]}
        />

        <div className="ed-arch-arrow-down" aria-hidden="true">
          ↓
        </div>

        <ArchCard
          title="N=1 相邻条款展开 + P2 动态收紧 + 三档输出"
          badge="hit@5 58→70%"
          tone="ok"
          lines={[
            { lead: '展开与省流：', text: 'Rank 1 补全 ±1 窗口 · top1≥0.90 仅展前 2 条 (-31.2% Token)' },
            { lead: '标定三档输出：', text: 'direct / related / no_answer (65 无答案全拒)，附 places 与 PDF 直跳' },
          ]}
        />
      </div>
    </ArchZone>

    <ArchZone title="3. 多协议接口 · 鉴权与评测" badge="全校可复用" tone="ok">
      <div className="ed-arch-zone-body">
        <ArchCard
          title="4 个标准只读 MCP (:8765)"
          badge="Streamable HTTP"
          tone="accent"
          lines={[
            { lead: 'kb_search：', text: '混合检索 + 地点 + 三档拒答指引' },
            { lead: 'kb_meta / documents：', text: '25 助手标签统计与分页浏览' },
            { lead: 'kb_document_chunks：', text: '精确页码跳转与网关代理隔离' },
          ]}
        />
        <ArchCard
          title="原件鉴权 & REST 调试"
          badge="15min PAR"
          tone="secondary"
          lines={[
            { lead: '双模式鉴权：', text: 'Casdoor OIDC Cookie / 服务 Token' },
            { lead: 'PAR 预签名直跳：', text: '签发 15 分钟读链，直跳 #page=N 页' },
            { lead: 'REST / 健康检查：', text: '/v1/search · /healthz (52,322 块 / 217 地点)' },
          ]}
        />
        <ArchCard
          title="四套独立评测与门禁"
          badge="193+ 单测"
          tone="ok"
          lines={[
            { lead: '268 证据盲测：', text: '答对 97.7% · 拒答 90.7% · 编造 2.3%' },
            { lead: '留出检索集：', text: 'hit@5 100% (84/84) · MRR 0.963' },
            { lead: '165 真实探测：', text: '82% 有支撑 · 锁定 25 题语料缺口' },
          ]}
        />
      </div>
    </ArchZone>
  </div>
);

const VtuberDiagram: React.FC = () => (
  <div
    className="ed-arch-3col"
    style={{ gridTemplateColumns: 'minmax(0, 33fr) minmax(0, 27fr) minmax(0, 40fr)' }}
  >
    <ArchZone title="1. 多端用户前台 (web/ + QQ)" badge="Web / 手机 / QQ" tone="tertiary">
      <div className="ed-arch-zone-body">
        <ArchCard
          title="React 18 前端 & 手绘小智 v0.1.1"
          badge="Zustand 分域"
          tone="tertiary"
          lines={[
            { lead: '手绘 Live2D：', text: 'WebP q95 减重 45–80% · 实时口型/动作' },
            { lead: '零改动地点卡：', text: '解析 places → 高德 / 百度 / 苹果地图' },
            { lead: '历史同源复原：', text: '刷新自动重建地图卡与 PDF 页码直跳' },
          ]}
        />
        <ArchCard
          title="按需 VAD & 本机 MCP 桥接"
          badge="主包 2.09→1.31MB"
          tone="ok"
          lines={[
            { lead: '按需拆包 VAD：', text: '开麦才加载 578KB chunk，默认静音' },
            { lead: '本地桥接：', text: 'services/localMcp.ts 直连 127.0.0.1:8788' },
            { lead: '工具反向代理：', text: '注册 register-local-mcp 并回传结果' },
          ]}
        />
        <ArchCard
          title="QQ 官方机器人通道"
          badge="限 @cuc.edu.cn"
          tone="accent"
          lines={[
            { lead: 'Bot API v2 WS：', text: '主动外连官方网关，无需公网回调' },
            { lead: '跨端邮箱绑定：', text: '限 @cuc.edu.cn 邮箱校验 Casdoor' },
            { lead: '群聊隐私保护：', text: '群聊自动屏蔽本机工具与个人流水' },
          ]}
        />
      </div>
    </ArchZone>

    <ArchZone title="2. 边缘网关 · OIDC · 双 WS" badge="零文本卡顿" tone="accent">
      <div className="ed-arch-zone-body">
        <ArchCard
          title="Cloudflare + Caddy 边缘"
          badge="30d 静态 HIT"
          tone="secondary"
          lines={[
            { lead: 'CF 边缘加速：', text: '关 Rocket Loader · 静态/Live2D 30d' },
            { lead: 'Caddy 反代：', text: 'flush_interval -1 保障流式 WS' },
            { lead: '优选同步：', text: '每 2h 自动同步 Cloudflare 优选节点' },
          ]}
        />
        <ArchCard
          title="Casdoor OIDC"
          badge="sso.acgurl.cn · Lax"
          tone="warn"
          lines={[
            { lead: 'OIDC 登录流：', text: '未登录 302 → /auth/callback 换票' },
            { lead: '三层数据隔离：', text: 'user_id · history_uid · token 隔离' },
            { lead: '同站共享：', text: '*.acgurl.cn 免重复登录嵌入演示' },
          ]}
        />
        <ArchCard
          title="/client-ws ∥ /audio-ws"
          badge="独立发送锁"
          tone="accent"
          lines={[
            { lead: '/client-ws：', text: '10–50ms text-delta + local-tool-call' },
            { lead: '/audio-ws：', text: 'MP3 + synth-complete 走独立锁不阻塞' },
            { lead: '断线兜底：', text: '2s 自动重连，未就绪自动回退主通道' },
          ]}
        />
      </div>
    </ArchZone>

    <ArchZone title="3. FastAPI 后端引擎 (:12393)" badge="657 项测试" tone="ok">
      <div className="ed-arch-zone-body">
        <ArchCard
          title="SessionFactory & Agent 反直觉推理"
          badge="固定关闭思考"
          tone="ok"
          lines={[
            { lead: '单连接隔离：', text: '按连接生成独立 ServiceContext 注入引擎' },
            { lead: 'BasicMemoryAgent：', text: 'DeepSeek Flash 固定关思考：编造减半 (2.3% vs 4.7%)' },
            { lead: '角色热加载：', text: '扫描 characters/*.yaml (小智/AIRI) 绑定动作' },
          ]}
        />
        <ArchCard
          title="ToolExecutor 并发调度与安全防火墙"
          badge="单轮 8 并发"
          tone="accent"
          lines={[
            { lead: '并发路由：', text: '统一并发调度云端 MCPClient ∥ 浏览器 LocalBridge' },
            { lead: '主库直连：', text: 'Streamable HTTP 127.0.0.1:8765/mcp → cuc-kb 4 工具' },
            { lead: '安全门禁：', text: '防内网 SSRF · 远程严格禁用 stdio 防 RCE' },
          ]}
        />
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
            gap: '10px',
            flex: '0.92 1 0%',
          }}
        >
          <ArchCard
            title="云端语音工厂"
            badge="0.22–0.28s"
            tone="secondary"
            lines={[
              { lead: 'ASR：', text: 'Groq whisper-large-v3-turbo' },
              { lead: 'TTS：', text: 'Azure 3 连接池 LIFO (省 0.6s)' },
              { lead: '直推：', text: '24kHz MP3 直推 /audio-ws' },
            ]}
          />
          <ArchCard
            title="SQLite WAL"
            badge="user_id 隔离"
            tone="muted"
            lines={[
              { lead: '表结构：', text: 'users / histories / messages' },
              { lead: '并发事务：', text: 'asyncio.to_thread + 外键级联' },
              { lead: '旧版兼容：', text: '自动归档旧 JSON 至 legacy' },
            ]}
          />
        </div>
      </div>
    </ArchZone>
  </div>
);

const CliDiagram: React.FC = () => {
  const upstreams = [
    { host: 'sso.cuc.edu.cn', desc: '金智 CAS 认证源' },
    { host: 'bkjw.cuc.edu.cn', desc: '课表 · 成绩 · 方案' },
    { host: 'courses.cuc.edu.cn', desc: '畅课 (Keycloak)' },
    { host: 'workflow.cuc.edu.cn', desc: '立德 / 博学空教室' },
    { host: 'pcard.cuc.edu.cn', desc: '校园卡余额 · 流水' },
    { host: 'ilib.cuc.edu.cn', desc: '智慧图书馆 & OPAC' },
    { host: 'apps.cuc.edu.cn', desc: '活动 & 访客 JWT' },
    { host: 'i.cuc.edu.cn', desc: '融合门户消息中心' },
  ];

  return (
    <div className="ed-arch-cli-layers">
      <ArchZone
        title="L1 · 入口与零第三方依赖三模 MCP 代理 (mcp/bin/cuc-mcp.js :8788)"
        badge="仅运行在用户本机 · Node.js 22.4+"
        tone="accent"
        style={{ flex: '1 1 0%' }}
      >
        <div className="ed-arch-zone-row" style={{ gridTemplateColumns: '1fr 1.85fr' }}>
          <ArchCard
            title="本机终端 & AI 客户端"
            tone="accent"
            lines={[
              { lead: '终端 CLI：', text: 'bin/cuc.js 直接输出表格或 --json' },
              { lead: 'AI 接入：', text: 'Live 小智直连 / Claude Code / Desktop' },
            ]}
          />
          <ArchCard
            title="三模 MCP 传输 + 12 个只读工具"
            badge="全程只读"
            tone="accent"
            lines={[
              { lead: '3 种协议：', text: 'stdio (JSON-RPC) · Streamable HTTP (/mcp) · 旧版 SSE (/sse)' },
              { lead: '安全流控：', text: 'CUC_MCP_ORIGINS 白名单 · X-API-Key · 15s 心跳 · 进度与取消' },
            ]}
          />
        </div>
      </ArchZone>

      <ArchZone
        title="L2 · 本机只读防火墙 · 数据规整与默认 PII 脱敏 (src/server.js :8787)"
        badge="127.0.0.1 回环 · 240 项单测"
        tone="warn"
        style={{ flex: '1 1 0%' }}
      >
        <div className="ed-arch-zone-row">
          <ArchCard
            title="回环与只读白名单"
            tone="warn"
            lines={[
              { text: '仅监听 127.0.0.1，校验 X-API-Key' },
              { text: '放行 10 类业务，禁写与 --show-pii' },
            ]}
          />
          <ArchCard
            title="子进程沙箱 & 12 工具"
            tone="ok"
            lines={[
              { text: 'execFile 执行 --json · 60s 超时熔断' },
              { text: '覆盖 tt · jw · lms · room · card · lib 等' },
            ]}
          />
          <ArchCard
            title="结构规整 & 默认脱敏"
            tone="ok"
            lines={[
              { text: 'normalize/ 统一规整 HTML 与 JSON' },
              { text: 'privacy.js 默认掩码姓名/学号/手机' },
            ]}
          />
        </div>
      </ArchZone>

      <ArchZone
        title="L3 · 统一身份认证与透明静默换票 (~/.cuc-cli/)"
        badge="凭据绝不出本机"
        tone="secondary"
        style={{ flex: '1 1 0%' }}
      >
        <div className="ed-arch-zone-row">
          <ArchCard
            title="三种本机登录流"
            tone="secondary"
            lines={[
              { lead: '微信扫码：', text: '终端二维码 + 微信长轮询' },
              { lead: 'CDP / 密码：', text: '本地过滑块 + AES-128-CBC 加密' },
            ]}
          />
          <ArchCard
            title="本机持久化存储"
            tone="secondary"
            lines={[
              { lead: 'session.json：', text: 'CAS Cookie + apps JWT 仅存本机' },
              { lead: 'opac.json：', text: '馆藏 WAF Cookie 与浏览器配置' },
            ]}
          />
          <ArchCard
            title="静默换票与角色自愈"
            tone="secondary"
            lines={[
              { text: '子站过期自动经 sso.cuc.edu.cn 换票' },
              { text: 'bkjw 遇 403 自动切「本科学生组」' },
            ]}
          />
        </div>
      </ArchZone>

      <ArchZone
        title="L4 · 直连中国传媒大学 8 大官方上游数据源 (纯 Node.js 原生 fetch + CookieJar)"
        badge="HTTPS 直连 · 零写请求"
        tone="muted"
        style={{ flex: '0 0 auto' }}
      >
        <div className="ed-arch-upstream-grid">
          {upstreams.map((u) => (
            <div className="ed-arch-upstream-pill" key={u.host}>
              <span className="ed-arch-upstream-host">{u.host}</span>
              <span className="ed-arch-upstream-desc">{u.desc}</span>
            </div>
          ))}
        </div>
      </ArchZone>
    </div>
  );
};

export const ArchitectureSlide: React.FC<ArchitectureSlideProps> = ({ deck, slide }) => {
  const [view, setView] = useState<ArchitectureView>('overview');
  const activeTab = VIEW_TABS.find((t) => t.id === view) ?? VIEW_TABS[0];

  return (
    <section className="ed-arch-wrap">
      <div className="ed-arch-bar">
        <div className="ed-arch-head">
          <h1 className="ed-arch-title">{slide.title}</h1>
          <span className="ed-arch-badge" title={deck.slide2.privacyQuote}>
            🔒 凭据永不上云 · {deck.slide2.giantNumber}
          </span>
        </div>

        <div className="ed-tab-strip" role="tablist" aria-label="系统架构图视角切换">
          {VIEW_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={view === tab.id}
              className={`ed-btn-line ${view === tab.id ? 'is-active' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                setView(tab.id);
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="ed-arch-canvas">
        {view === 'overview' && <OverviewDiagram />}
        {view === 'kb' && <KbDiagram />}
        {view === 'vtuber' && <VtuberDiagram />}
        {view === 'cli' && <CliDiagram />}
      </div>

      <footer className="ed-footnote-bar">
        <span>{activeTab.footnoteLeft}</span>
        <strong>{activeTab.footnoteRight}</strong>
      </footer>
    </section>
  );
};
