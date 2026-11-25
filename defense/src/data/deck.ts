export type ThemeMode = 'light' | 'dark';

export interface ScriptSegment {
  readonly tag: string;
  readonly type?: 'speech' | 'action';
  readonly text: string;
  readonly skippableNote?: string;
}

export interface SlideDefinition {
  readonly id: number;
  readonly shortLabel: string;
  readonly kicker: string;
  readonly title: string;
  readonly window: string;
  readonly durationSec: number;
  readonly anchorTag: string;
  readonly stageCue: string;
  readonly cuesSummary: string;
  readonly scriptSegments: readonly ScriptSegment[];
}

export interface TimeAnchor {
  readonly id: 'demo' | 'design' | 'closing';
  readonly atSeconds: number;
  readonly timeLabel: string;
  readonly slideId: number;
  readonly label: string;
  readonly rescueStrategy: string;
}

export interface FailureComparisonItem {
  readonly question: string;
  readonly genericAiFailure: string;
  readonly xiaozhiResult: string;
  readonly proofBadge: string;
}

export interface KpiMetric {
  readonly value: string;
  readonly label: string;
  readonly sub: string;
  readonly tone?: 'accent' | 'ok' | 'secondary' | 'tertiary';
}

export interface PillarItem {
  readonly id: 'cuc-kb' | 'live-xiaozhi' | 'cuc-cli';
  readonly badge: string;
  readonly name: string;
  readonly role: string;
  readonly items: readonly string[];
}

export interface DemoEndpoint {
  readonly label: string;
  readonly url: string;
}

export interface DemoPromptItem {
  readonly id: string;
  readonly tag: string;
  readonly prompt: string;
  readonly expectedVisual: string;
}

export interface StructuredBullet {
  readonly lead: string;
  readonly text: string;
}

export interface HardDesignItem {
  readonly num: string;
  readonly title: string;
  readonly metric: string;
  readonly bullets: readonly StructuredBullet[];
  readonly keyProof: string;
}

export interface EvalBarMetric {
  readonly label: string;
  readonly value: number;
  readonly tone: 'ok' | 'accent';
}

export interface ThinkCompareRow {
  readonly item: string;
  readonly noThink: string;
  readonly withThink: string;
  readonly isThinkWorse?: boolean;
}

export interface QaItem {
  readonly q: string;
  readonly a: string;
}

export interface EmergencyItem {
  readonly situation: string;
  readonly action: string;
}

export interface DeckSource {
  readonly meta: {
    readonly title: string;
    readonly competitionTag: string;
    readonly subtitle: string;
    readonly totalDurationSec: number;
    readonly safetyLimitSec: number;
    readonly warnAtSec: number;
    readonly overAtSec: number;
    readonly sameOriginDeployUrl: string;
    readonly liveSiteUrl: string;
    readonly testAccount: {
      readonly username: string;
      readonly password: string;
    };
    readonly deployPowerShellCmd: string;
  };
  readonly anchors: readonly TimeAnchor[];
  readonly slides: readonly SlideDefinition[];
  readonly slide1: {
    readonly giantNumber: string;
    readonly thesis: string;
    readonly quote: string;
    readonly comparisons: readonly FailureComparisonItem[];
    readonly kpis: readonly KpiMetric[];
  };
  readonly slide2: {
    readonly giantNumber: string;
    readonly thesis: string;
    readonly privacyQuote: string;
    readonly pillars: readonly PillarItem[];
    readonly footnoteLeft: string;
    readonly footnoteRight: string;
  };
  readonly slide3: {
    readonly endpoints: readonly DemoEndpoint[];
    readonly prompts: readonly DemoPromptItem[];
    readonly recommendedOrder: string;
    readonly sameSiteDefaultNote: string;
    readonly sameSiteMatchedNote: string;
    readonly sameOriginHostPattern: string;
  };
  readonly slide4: {
    readonly giantNumber: string;
    readonly thesis: string;
    readonly quote: string;
    readonly designs: readonly HardDesignItem[];
    readonly footnoteLeft: string;
    readonly footnoteRight: string;
  };
  readonly slide5: {
    readonly giantNumber: string;
    readonly thesis: string;
    readonly quote: string;
    readonly blindTitle: string;
    readonly blindBadge: string;
    readonly blindBars: readonly EvalBarMetric[];
    readonly thinkTitle: string;
    readonly thinkBadge: string;
    readonly thinkRows: readonly ThinkCompareRow[];
    readonly demandTitle: string;
    readonly demandBadge: string;
    readonly demandSegments: readonly {
      readonly label: string;
      readonly percent: number;
      readonly countLabel: string;
      readonly color: string;
    }[];
    readonly footnoteLeft: string;
    readonly footnoteRight: string;
  };
  readonly slide6: {
    readonly giantNumber: string;
    readonly thesis: string;
    readonly quote: string;
    readonly stats: readonly KpiMetric[];
    readonly gapsBadge: string;
    readonly gaps: readonly StructuredBullet[];
    readonly roadmapBadge: string;
    readonly roadmap: readonly StructuredBullet[];
  };
  readonly qaItems: readonly QaItem[];
  readonly sop: {
    readonly dayBefore: readonly string[];
    readonly fiveMinBefore: readonly string[];
    readonly emergencies: readonly EmergencyItem[];
    readonly privacyRule: string;
  };
}

export const DECK_SOURCE: DeckSource = {
  meta: {
    title: 'Live 小智：校园事务问答智能体',
    competitionTag: '2026“智启未来·体创万象”首届智能体节 · 管理类',
    subtitle: '以校园 QA 知识库（cuc-kb）为核心证据引擎，Live 小智做亲和入口，cuc-cli 做本机隐私补位。',
    totalDurationSec: 290,
    safetyLimitSec: 300,
    warnAtSec: 260,
    overAtSec: 290,
    sameOriginDeployUrl: 'https://ppt.acgurl.cn/',
    liveSiteUrl: 'https://ai.acgurl.cn/',
    testAccount: {
      username: 'test',
      password: 'TestCuc@2026',
    },
    deployPowerShellCmd:
      'tar.exe -cf "$env:TEMP\\ppt_deploy.tar" -C defense index.html assets/xiaozhi.png assets/airi.png; scp.exe -o ConnectTimeout=15 "$env:TEMP\\ppt_deploy.tar" oracle:/tmp/ppt_deploy.tar; ssh.exe -o ConnectTimeout=15 oracle "tar -xf /tmp/ppt_deploy.tar -C /var/www/ppt-acgurl && rm -f /tmp/ppt_deploy.tar && chmod 644 /var/www/ppt-acgurl/index.html /var/www/ppt-acgurl/assets/*"',
  },
  anchors: [
    {
      id: 'demo',
      atSeconds: 70,
      timeLabel: '1:10',
      slideId: 3,
      label: '1:10 真机实测',
      rescueStrategy:
        '若 Slide 1–2 耗时偏长，一句话收束安全边界（公共制度上云治理、个人会话留本机），立即按 → 进入第 3 页真机实测',
    },
    {
      id: 'design',
      atSeconds: 145,
      timeLabel: '2:25',
      slideId: 4,
      label: '2:25 硬核三设计',
      rescueStrategy:
        '结束第 ⑤ 题演示立刻切 Slide 4；若现场节奏略紧，保住第 ① 题 4 秒原声，第 ③④⑤ 题按一句一景紧凑推进',
    },
    {
      id: 'closing',
      atSeconds: 250,
      timeLabel: '4:10',
      slideId: 6,
      label: '4:10 实绩与展望',
      rescueStrategy:
        '跳过 Slide 5 留出集次要数字，保住「关思考编造减半」核心结论后直接切 Slide 6 讲清缺口并邀测',
    },
  ],
  slides: [
    {
      id: 1,
      shortLabel: '痛点钩子',
      kicker: 'ACT 01 · 核心命题',
      title: '通用大模型不懂校规：知识库决定问答上限',
      window: '0:00–0:35 (35s)',
      durationSec: 35,
      anchorTag: '开场定调',
      stageCue: '站姿面向评委启动计时，先讲右侧 3 个真实问法对比，再抛出“查得到、带出处、查不到就明说”。',
      cuesSummary:
        '① 三类校园真翻车对比（旧文误引 / 找错楼 / 硬编票价） → ② 核心命题：知识库决定上限 → ③ 2,290份 / 52,322片段 / 99%原链 / 97.7%盲测答对。',
      scriptSegments: [
        {
          tag: '痛点破题',
          text: '各位老师好！我是「Live 小智：校园事务问答智能体」。做校园问答最常见的翻车有三类：拿已废止的旧文件当现行校规、把搬迁前后的楼号搞混、遇上库里没有的实时票价直接顺嘴编。',
        },
        {
          tag: '核心判断',
          text: '所以我们的判断非常明确：通用大模型并不懂校规，问答上限完全由知识库决定——必须查得到、带出处、查不到就明说。我们的 cuc-kb 已把 2,290 份校内文件治理成 52,322 个检索片段，99% 带官网原链，268 题盲测答对 97.7%。',
        },
      ],
    },
    {
      id: 2,
      shortLabel: '三端与边界',
      kicker: 'ACT 02 · 架构分工',
      title: '公共知识集中治理，个人凭据永不上云',
      window: '0:35–1:10 (35s)',
      durationSec: 35,
      anchorTag: '1:10 必进真机',
      stageCue: '快速点明三部分各自职责与隐私红线，准备按 → 提前进入第 3 页线上真机。',
      cuesSummary:
        '① cuc-kb 负责公开制度与217处地点（4只读MCP） → ② Live 小智负责手绘Live2D与0.2秒级语音入口 → ③ cuc-cli 仅跑本机查课表待办空教室，凭据不出本机。',
      scriptSegments: [
        {
          tag: '三端职责',
          text: '围绕这个定位，系统严格切分公共知识与个人数据：核心是云端治理全校公开制度的 cuc-kb，并以 4 个标准只读 MCP 向全校复用；对话前台 Live 小智重写了 React 前端并手绘小智 Live2D，配合双 WebSocket 和连接池压低交互延迟。',
        },
        {
          tag: '隐私边界',
          text: '而课表、畅课待办和空教室这类涉及统一身份认证的个人数据，则交给零依赖的 cuc-cli 只在用户本机运行、由浏览器本地桥接，认证凭据永不上云。',
        },
      ],
    },
    {
      id: 3,
      shortLabel: '真机实测',
      kicker: 'ACT 03 · 75s 真机实测（已提前）',
      title: '线上真机四连测：版本让位 · 地点卡 · 拒答 · 本机补位',
      window: '1:10–2:25 (75s)',
      durationSec: 75,
      anchorTag: '1:10 准时真机 · 2:25 必切原理',
      stageCue: '右侧点选提问卡一键复制，切左侧内嵌 ai.acgurl.cn 发送（推荐顺序 ① → ③ → ④ → ⑤）。',
      cuesSummary:
        '点选复制→左侧Ctrl+V：① 导师聘任(版本让位+PDF页码直跳，停4s听原声) → ③ 校医院/教务处(高德地点卡) → ④ 游泳馆票价(标定拒答) → ⑤ 本机cuc-cli(课表/待办/空教室)。',
      scriptSegments: [
        {
          tag: '开场与版本让位 · 0:00–0:30',
          text: '下面我们在第 1 分 10 秒直接连线上真机实测。先复制第 ① 题问研究生导师聘任要求：可以看到知识库自动压低 2023 旧版，返回带页码的 15 分钟签名 PDF 直跳链接，先听 4 秒实时语音——',
        },
        {
          tag: '操作提示 · 停顿 4 秒放原声',
          type: 'action',
          text: '（发送第 ① 题后保持微笑，让评委听清 4 秒语音流与 Live2D 口型同步，随后依次复制第 ③、④ 题）',
        },
        {
          tag: '地点卡与标定拒答 · 0:30–0:55',
          text: '接着复制第 ③ 题查校医院和教务处位置，前端零协议改动渲染出高德交互地点卡；再追问第 ④ 题游泳馆本周五开放与票价，知识库触发标定拒答，如实告知未收录、绝不编造。',
        },
        {
          tag: '本机补位 · 0:55–1:15',
          text: '最后第 ⑤ 题查个人今日课表、畅课待办和博学楼空教室，由浏览器直连我本机 127.0.0.1 的 cuc-cli 并发查回，凭据不出本机。',
        },
      ],
    },
    {
      id: 4,
      shortLabel: '硬核三设计',
      kicker: 'ACT 04 · 原理拆解',
      title: '为什么比普通 RAG 靠谱：三个决定体验的硬设计',
      window: '2:25–3:20 (55s)',
      durationSec: 55,
      anchorTag: '2:25 准时拆解',
      stageCue: '结合刚看完的真机效果，逐条讲清版本让位、条款展开与 217 地点标定。',
      cuesSummary:
        '① 四层版本防线：278归档 + 12废止/21重发/30补链降权门控 + 汇编让单行 → ② N=1相邻条款展开+表题注入：证据hit@5 58%→70% → ③ 217地点标定(14.6m) + 4只读MCP(底层BM25 1-3ms/P1缓存40ms)。',
      scriptSegments: [
        {
          tag: '设计一 · 四层版本防线',
          text: '刚才的效果背后不是简单灌向量库，而是三个硬设计。第一是四层版本防线：278 份旧版与重复件直接归档，人工逐对核验 12 对废止与 21 对逐年重发文件，新版命中时自适应降权并阻断旧版上下文回流，同时汇编让位单行本，点名查旧年份仍可追溯。',
        },
        {
          tag: '设计二与三 · 精准取证与地点 MCP',
          text: '第二是“找对文件更要找对条款”：把表题注入向量消除纯数字表块丢失，再用相邻条款展开补全前提与例外，把证据级 hit@5 从 58% 提到 70%。第三是经 OSM 17 控制点标定的 217 处地点（中位误差 14.6 米），与全部检索能力一起封装成 4 个标准只读 MCP。',
          skippableNote: '若接近 3:20 节点，略去 17 控制点等细节，直接强调“hit@5 58%→70% 与 14.6 米标定误差”。',
        },
      ],
    },
    {
      id: 5,
      shortLabel: '评测与反直觉',
      kicker: 'ACT 05 · 数据实证',
      title: '四套独立评测把关：关掉深度思考反而编造减半',
      window: '3:20–4:10 (50s)',
      durationSec: 50,
      anchorTag: '4:10 必进收尾',
      stageCue: '先点右列 268 题达标条，再重点抛“关闭思考反比开启思考编造减半”的反直觉发现。',
      cuesSummary:
        '① 268题盲测：97.7%答对、90.7%如实拒答、2.3%编造 → ② 关键对照：开思考答对持平(209/214)但编造翻倍(10对5)、慢1.4倍 → ③ 165题真实探测82%有支撑、锁定25题缺口。',
      scriptSegments: [
        {
          tag: '268 题盲测与反直觉发现',
          text: '所有改动都先过评测再上线。在 268 题证据级盲测中，214 道可答题答对 97.7%、54 道无答案题 90.7% 如实拒答、编造压到 2.3%。更关键的是思考模式对照：开启思考后答对数完全持平，但编造直接翻倍、耗时慢 1.4 倍，因此生产环境有扎实证据时固定关闭思考。',
        },
        {
          tag: '留出集与真实需求探测',
          text: '在留出检索集上多答案 hit@5 达到 100%、MRR 0.963；脱离文档按 6 类师生真实提问探测 165 题，82% 有原文支撑，并精准暴露出 25 题语料缺口。',
          skippableNote: '超时可略去 MRR 数字，直接带出“82% 有原文支撑并锁定 25 题缺口”。',
        },
      ],
    },
    {
      id: 6,
      shortLabel: '实绩与缺口',
      kicker: 'ACT 06 · 试运行收尾',
      title: '公网 834 轮试运行：坦诚三个缺口，按缺口补采不盲目调参',
      window: '4:10–4:50 (40s)',
      durationSec: 40,
      anchorTag: '4:10 准时收尾 · 4:50 邀测',
      stageCue: '语速沉稳收尾，讲清试运行实绩、三个坦诚缺口和补采规划，微笑邀请老师现场出题。',
      cuesSummary:
        '① 成果：1,090+测试 / 834轮试运行 / ¥2.56嵌入成本 / 4个标准MCP → ② 3缺口：25题生活收费缺口、11-08后增量、真实对话复评 → ③ 计划：按清单补采+周增量+对接信息化部 → ④ 邀测 ai.acgurl.cn。',
      scriptSegments: [
        {
          tag: '试运行实绩与坦诚缺口',
          text: '截至 11 月 23 日，三端已通过 1,090 项自动化测试，公网试运行 834 轮真实提问，全库向量嵌入仅花费 2.56 元。同时我们坦诚记录下三个缺口：25 题当期活动与收费标准语料缺口、11 月 8 日后的通知时效滞后，以及大规模真实自然问法复评。',
        },
        {
          tag: '务实演进与结束语',
          text: '接下来我们不做无效调参，直接按缺口清单精准补采、上线官网周级增量与零回归门禁，并争取对接学校信息化部门开放正规统一认证。线上 ai.acgurl.cn 与本机 cuc-cli 均已就绪，欢迎老师们出题实测，谢谢！',
        },
      ],
    },
  ],
  slide1: {
    giantNumber: '97.7%',
    thesis: '通用大模型不懂本校现行制度与实时属性；把 2,290 份校内文件治理成可引用证据，问答质量才真正可靠。',
    quote: '核心判断：不靠通用模型背校规，让 cuc-kb 决定问答上限——查得到、带出处、查不到就明说。',
    comparisons: [
      {
        question: '研究生导师岗位聘任最新有什么要求？',
        genericAiFailure: '误用 2023 已废止旧文或常识拼凑，无页码依据',
        xiaozhiResult: '触发版本让位压低旧版，返回现行文件 + 签名 PDF 页码直跳',
        proofBadge: '版本让位 · 页码溯源',
      },
      {
        question: '校医院和教务处办事窗口分别在哪栋楼？',
        genericAiFailure: '易混淆旧址 41 号楼与现址 20 号楼，无法精准导航',
        xiaozhiResult: '命中 217 处地点坐标层，零改动渲染高德 / 百度 / 苹果卡',
        proofBadge: '217 地点 · 误差 14.6m',
      },
      {
        question: '学校游泳馆这周五晚开放到几点、票价多少？',
        genericAiFailure: '顺着常识编造“开放至 21 点、票价 20 元”等虚假属性',
        xiaozhiResult: '触发标定拒答：如实告知未收录当期时段与票价，拒绝猜测',
        proofBadge: '标定拒答 · 90.7% 拒答',
      },
    ],
    kpis: [
      { value: '2,290 份', label: '收录校内正式文件', sub: '18,107 页 · 54 校内站 + AIHub', tone: 'accent' },
      { value: '52,322 个', label: '治理后检索片段', sub: '44,415 现行 · 278 旧版/重复归档', tone: 'ok' },
      { value: '99.0%', label: '可追回官网原链', sub: '2,268 份带出处 · 96.1% 带日期', tone: 'secondary' },
      { value: '97.7%', label: '268 题端到端答对', sub: '不可答 90.7% 拒答 · 编造仅 2.3%', tone: 'tertiary' },
    ],
  },
  slide2: {
    giantNumber: '127.0.0.1',
    thesis: 'cuc-kb 集中治理全校共享制度，Live 小智做零门槛对话与地图入口，cuc-cli 仅在本机查询个人实时校园数据。',
    privacyQuote: '安全与合规红线：公共制度在云端集中治理，统一身份认证会话只留在本机 ~/.cuc-cli，绝不上云。',
    pillars: [
      {
        id: 'cuc-kb',
        badge: '绝对核心 · 云端公共知识',
        name: 'cuc-kb（校园 QA 知识库）',
        role: '决定问答上限：查得到、带出处、查不到就明说',
        items: [
          '治理 2,290 份公开校规与 217 处校园地点坐标层',
          '对外暴露 4 个标准只读 MCP 工具（kb_search 等），可供全校智能体复用',
          '原件 PDF 存私有对象存储桶，经 Casdoor SSO 或服务 Token 鉴权后签发 15 分钟短时链接',
        ],
      },
      {
        id: 'live-xiaozhi',
        badge: '亲和入口 · 网页 / 手机 / QQ',
        name: 'Live 小智（对话前台）',
        role: '让师生张口能问、看得见出处、看得到地图',
        items: [
          '基于 Open-LLM-VTuber 深度重写 React 18 前端与手绘小智 Live2D（WebP 减重 45–80%）',
          '拆分 /client-ws（10–50ms 文字流）与 /audio-ws，自研 Azure TTS 连接池 0.22–0.28s',
          'Casdoor OIDC 三层用户隔离，支持限 cuc.edu.cn 邮箱的 QQ 机器人跨端绑定',
        ],
      },
      {
        id: 'cuc-cli',
        badge: '本机隐私 · 个人实时数据',
        name: 'cuc-cli（本机个人工具）',
        role: '补足公共库管不到的课表、教务、畅课待办与空教室',
        items: [
          'Node.js 22.4+ 零第三方依赖，覆盖 10 类校园业务、12 个只读 MCP 工具',
          '仅运行在用户本机（会话存 ~/.cuc-cli），浏览器直连 127.0.0.1 反向桥接',
          '统一认证凭据永不上云、群聊自动屏蔽不广播，远程环境禁用 stdio 防 RCE',
        ],
      },
    ],
    footnoteLeft: '三端交互链路：Live 小智 ⇄ 云端 Streamable HTTP MCP (cuc-kb) ＋ 本机 127.0.0.1 SSE (cuc-cli)',
    footnoteRight: '测试账号 test / TestCuc@2026（个人业务仅在本机 cuc-cli 演示）',
  },
  slide3: {
    endpoints: [
      { label: 'ai.acgurl.cn', url: 'https://ai.acgurl.cn/' },
      { label: 'vtuber.acgurl.cn', url: 'https://vtuber.acgurl.cn/' },
      { label: 'localhost:12393', url: 'http://localhost:12393/' },
    ],
    prompts: [
      {
        id: '1',
        tag: '① 版本让位 + 页码直跳',
        prompt: '研究生导师岗位聘任最新有什么要求？请附学校文件出处。',
        expectedVisual: '新版压过 2023 旧版 · 15 分钟签名 PDF 页码直跳 · 停顿 4 秒放原声',
      },
      {
        id: '2',
        tag: '② 跨条款精准检索（备选）',
        prompt: '本科生申请缓考需要满足什么条件、走什么流程？',
        expectedVisual: 'N=1 相邻条款展开补全截断前提与例外',
      },
      {
        id: '3',
        tag: '③ 217 处地点坐标卡',
        prompt: '校医院和教务处办事窗口分别在哪栋楼？',
        expectedVisual: 'place_answer=true · 前端零 WS 改动渲染高德交互卡',
      },
      {
        id: '4',
        tag: '④ 标定拒答防幻觉',
        prompt: '学校游泳馆这周五晚开放到几点、单次票价多少？',
        expectedVisual: '库外实时属性触发 no_answer · 如实说不知道',
      },
      {
        id: '5',
        tag: '⑤ 本机 cuc-cli 补位',
        prompt: '帮我看看今天还有什么课、畅课有哪些待办，博学楼下午哪几间教室空着？',
        expectedVisual: '本机 127.0.0.1 并发只读 · 凭据不出本机',
      },
    ],
    recommendedOrder: '① → ③ → ④ → ⑤',
    sameSiteDefaultNote:
      '注：OIDC Cookie 为 SameSite=Lax；建议将 defense/ 托管到 https://ppt.acgurl.cn/ 同站共享登录态，或切 localhost:12393 / 点「新窗口 ↗」打开。',
    sameSiteMatchedNote:
      '当前已与 ai.acgurl.cn 同站 HTTPS 部署，登录态自动共享；若首次未登录，点「新窗口 ↗」登录一次再点「↻ 刷新」即可。',
    sameOriginHostPattern: '(^|\\.)acgurl\\.cn$',
  },
  slide4: {
    giantNumber: '58→70%',
    thesis: '真机高可靠背后不是套现成向量库，而是死磕版本打架、条款切碎和校园建筑坐标漂移三个真实坑。',
    quote: '“找对文件 ≠ 找对条款”：版本让位 + 相邻条款展开，是证据命中率跃升 12 个百分点的关键。',
    designs: [
      {
        num: '01',
        title: '四层版本让位：新旧校规不打架',
        metric: '278 归档 · 12 / 21 / 30 对核验',
        bullets: [
          { lead: '源头归档：', text: '278 份旧版与 97% 真重复归档不召回' },
          { lead: '人工逐对核验：', text: '12 废止 + 21 重发 + 30 补链自适应降权、阻断展开' },
          { lead: '汇编让单行本：', text: '同族新版优先；点名查旧年份仍可追溯' },
        ],
        keyProof: '关闭「汇编让位单行本」消融测试：首位命中掉 5–6 题；支持条款热更新（国奖 8k→1w）',
      },
      {
        num: '02',
        title: '条款级取证：补全前提与数字表',
        metric: '证据 hit@5 58% → 70%',
        bullets: [
          { lead: 'PyMuPDF 切片：', text: '按条款切分并保留文号、页码与标题' },
          { lead: '表题注入向量：', text: '消除纯数字表格块召回丢失（丢失 2→0）' },
          { lead: 'N=1 相邻展开：', text: '补全截断前提与例外，P1/P2/P3 省 Token 31.2%' },
        ],
        keyProof: 'N=1 相邻展开将 268 题证据 hit@5 提至 70%（+12pt），端到端答对 61%→70%',
      },
      {
        num: '03',
        title: '217 校园地点标定 + 4 只读 MCP',
        metric: '中位误差 14.6m · 4 只读工具',
        bullets: [
          { lead: '217 处全覆盖：', text: '55 楼宇 + 82 办公 + 门餐饮医疗 + 5 海南校区' },
          { lead: '17 控制点标定：', text: '3D 热点 + OSM 单应标定，内置 WGS/GCJ/BD 三坐标' },
          { lead: '4 只读 MCP 复用：', text: 'kb_search / meta / documents / chunks 全校共享' },
        ],
        keyProof: '204 题配对显著性验证 rerank（p=0.02），冷查 1.2–1.35s 瓶颈已定位至海外→北京 RTT',
      },
    ],
    footnoteLeft: '混合底座：qwen3.7-embedding (1024d Qdrant) + 手写 BM25 (1–3ms, 768 查逐位同) + RRF 40→20 + qwen3-rerank',
    footnoteRight: 'P1 缓存：Rerank 40ms / Search 0ms · 65 无答案全拒',
  },
  slide5: {
    giantNumber: '2.3% vs 4.7%',
    thesis: '每次改动先过评测再上线；268 题对照实验证明：扎实证据支撑下，关思考准确率持平、编造减半。',
    quote: '扎实证据面前，固定关闭思考：编造减半、耗时省约 30%、Token 省约 40%。',
    blindTitle: '268 题证据级端到端盲测（qwen-plus 判分）',
    blindBadge: '214 可答 + 54 不可答',
    blindBars: [
      { label: '可答题答对 (209 / 214)', value: 97.7, tone: 'ok' },
      { label: '单次检索前 5 含完整证据 (200 / 214)', value: 93.5, tone: 'accent' },
      { label: '可答题回答完整 (197 / 214)', value: 92.1, tone: 'accent' },
      { label: '不可答题如实拒答 (49 / 54)', value: 90.7, tone: 'ok' },
    ],
    thinkTitle: 'DeepSeek Flash 思考模式对照实验',
    thinkBadge: '线上固定关闭思考',
    thinkRows: [
      { item: '可答题答对数', noThink: '209 / 214 (97.7%)', withThink: '209 / 214 (97.7%) 持平' },
      {
        item: '可答 / 不可答编造',
        noThink: '5 (2.3%) / 4 题',
        withThink: '10 (4.7%) / 7 题（翻倍）',
        isThinkWorse: true,
      },
      { item: '耗时 P50 / Token', noThink: '11.3s / 1.0×', withThink: '15.8s (1.4×) / 1.7×', isThinkWorse: true },
    ],
    demandTitle: '165 题真实需求探测（6 类师生真实问法）',
    demandBadge: '锁定 25 题语料缺口',
    demandSegments: [
      { label: '有原文支撑', percent: 82, countLabel: '135 题', color: '#1d4ed8' },
      { label: '部分支撑', percent: 6, countLabel: '10 题', color: '#60a5fa' },
      { label: '如实说没有', percent: 10, countLabel: '16 题', color: '#64748b' },
      { label: '无原文支撑', percent: 2.4, countLabel: '4 题', color: '#be123c' },
    ],
    footnoteLeft: '留出检索集复测（11-13 多答案）：跨部门 hit@1 94.0% (79/84 · 单文档 79.8%) · hit@5 100% (84/84) · MRR 0.963',
    footnoteRight: '无答案判定 97.9% (47/48) · 助手越权泄露 = 0',
  },
  slide6: {
    giantNumber: '834 轮',
    thesis: '已通过 1,090+ 项自动化测试并在公网试运行 834 轮；同时明确距离全校好用还差哪 25 个缺口与周更计划。',
    quote: '线上 ai.acgurl.cn 与本地 cuc-cli 均已就绪，欢迎评委老师出题实测！',
    stats: [
      { value: '1,090+', label: '三端自动化测试', sub: '对话 657 + 知识库 193+ + CLI 240', tone: 'accent' },
      { value: '834 轮', label: '公网真实试运行', sub: '截至 11-23 · 29 账号 · 707 次检索', tone: 'ok' },
      { value: '¥2.56', label: '全库嵌入总成本', sub: '1,014 万 token · 新文档增量入库', tone: 'secondary' },
      { value: '4 个', label: '标准只读 MCP 工具', sub: '知识与模型解耦 · 全校智能体可复用', tone: 'tertiary' },
    ],
    gapsBadge: '由 165 题需求探测暴露',
    gaps: [
      {
        lead: '内容缺口（25 题 + 1 上下文）：',
        text: '集中在当期活动安排（运动会/考务）、收费金额（医保/游泳馆）及生活服务（断电/班车/失物）。',
      },
      {
        lead: '时效更新滞后：',
        text: '最近一次全量入库停在 11 月 8 日，校历与临时通知会随学期更迭而过时。',
      },
      {
        lead: '评测口径局限：',
        text: '当前 268 题主要来自库内文档与单次机器判分，尚缺大规模真实师生自然问法复评。',
      },
    ],
    roadmapBadge: '不做无效调参，直击缺口',
    roadmap: [
      {
        lead: '按缺口清单精准补采：',
        text: '现有评测上限已近饱和，优先补充高频生活服务与当期收费标准语料。',
      },
      {
        lead: '官网通知按周增量：',
        text: '建立官网通知周级自动采集、版本关联校验与零回归评测门禁。',
      },
      {
        lead: '真实复评 & 合规对接：',
        text: '用试运行真实问答复评；争取对接信息化部门，以正规统一认证服务全校师生。',
      },
    ],
  },
  qaItems: [
    {
      q: 'Q1：新旧校规版本打架、甚至同一年汇编和单行本混在一起怎么防？',
      a: '四层治理防线：① 278 份过时与 97% 真重复文档标为 superseded 归档不召回；② 逐对核验 12 对正式废止与 21 对逐年重发、外加 30 对活跃补链，新版在候选时对旧版自适应降权，并做「展开门控」防止旧版上下文回流，同时标明已被哪份文件替代；③ 同族新版优先且汇编让位单行本（消融显示关闭后首位命中掉 5–6 题）；④ 若用户明确点名查历史年份（如 2022 版），仍保留可检索。',
    },
    {
      q: 'Q2：你们为什么敢在生产环境关掉大模型的“深度思考模式”？',
      a: '不是拍脑袋，是 268 题证据级对比实测决定的：在 DeepSeek Flash 上关闭思考与开启思考，可答题答对数完全持平（都是 209/214, 97.7%），但开启思考后可答题编造翻倍（10 对 5）、不可答题编造也更多（7 对 4）、单题耗时增加约 1.4 倍（15.8s 对 11.3s）、Token 消耗多约 1.7 倍。因此知识库证据扎实的前提下，关闭思考更准、更快、更省。',
    },
    {
      q: 'Q3：怎么保证不是“找对文件但答非所问”？以及怎么做到不编造？',
      a: '两条核心措施：① 自建 268 题「证据级」盲测集核验前 5 条片段是否含完整答案原文；发现基线仅 58% 后引入 N=1 相邻条款展开补全前提与例外，将证据 hit@5 提升到 70%、端到端答对从 61% 提到 70%。② 拒答阈值在 65 无答案+204 有答案标定集上校准（65 道全拒），MCP 分三档提示模型，重排超时自动降级拒答，不可答题如实拒答率达 90.7%。',
    },
    {
      q: 'Q4：校园地点坐标卡的精度可靠吗？需要改后端 WebSocket 协议吗？',
      a: '可靠且零协议入侵。11-20 上线的 217 处校园地点表，核心楼宇经校方 3D 地图热点与 OSM 17 个控制点做单应性变换标定（留一中位误差仅 14.6 米），内置 WGS-84 / GCJ-02 / BD-09 三套坐标；同时后端未新增任何 WS 字段，前端直接从 kb_search 原文 JSON 提取 places，刷新历史记录也能同源复原地图卡并一键跳高德/百度/苹果地图。',
    },
    {
      q: 'Q5：cuc-cli 查教务和校园卡，个人账号密码和原件 PDF 怎么保证安全？',
      a: '公共与个人彻底分离：个人数据依赖学校统一身份认证，cuc-cli 以零第三方依赖只运行在用户本机（会话存 ~/.cuc-cli），浏览器直连本机 127.0.0.1 反向桥接且群聊不广播，云端永不碰账密、同时禁用 stdio 防 RCE；而知识库源 PDF 存放在私有对象存储桶，须经 Casdoor SSO 或服务 Token 鉴权后才签发 15 分钟短时签名链接。',
    },
    {
      q: 'Q6：为什么单次检索 P50 是 1.2–1.35 秒？还能更低吗？',
      a: '本地工作已经压到极致——手写稀疏倒排 BM25 仅耗时 1–3ms，11-23 上线的 P1 线程安全缓存命中时 Rerank 仅 40ms、Search 为 0ms。冷查 1.2s 的耗时大头在于海外云主机到北京百炼向量/精排接口的网络 RTT；如果需要压到 200ms 级，只需将节点迁至北京近端即可，无需改动检索算法。',
    },
  ],
  sop: {
    dayBefore: [
      '同域与离线校验：确认 https://ai.acgurl.cn/ 与 https://ppt.acgurl.cn/ 登录态正常、本机 cuc-cli 可连通，同时将完整 defense/ 拷入 U 盘做本地备份。',
      '卡表彩排 3 遍：按 P 打开独立演讲台，启动 5 分钟计时器演练，牢记 **1:10（真机）、2:25（原理）、4:10（收尾）** 三个进度灯。',
    ],
    fiveMinBefore: [
      '双屏扩展（强烈推荐）：投影仪设为“扩展显示”，全屏（F）拖动 index.html 到投影屏；按 P 打开演讲台留在笔记本看逐字稿、计时与 Q&A 弹药库。',
      '单屏镜像：按 N 在当前屏底部开启单屏提词；默认亮色杂志版面适配强光教室，如需关灯暗色按 T 切换。',
      '音频与本地热备：若接入外放音响先在 Slide 3 测一次语音音量；演示第 ⑤ 题请提前本机登录并启动 cuc-server (127.0.0.1:8787) 与 cuc-mcp --http (127.0.0.1:8788)；普通体验测试账号为 test / TestCuc@2026。',
    ],
    emergencies: [
      {
        situation: '内嵌 iframe 未带登录态',
        action: '同站 https://ppt.acgurl.cn/ 会自动带入 SameSite=Lax Cookie；若首次未登录，点右上「新窗口 ↗」登录一次再点「↻ 刷新」，或直接切右上 localhost:12393 免登录后端。',
      },
      {
        situation: '教室屏蔽外网域名或延迟抖动',
        action: '1 秒在 Slide 3 顶栏切换到本地免登录后端 http://localhost:12393/（提前同步线上配置并打开 use_mcpp），不依赖外网照样真机演示。',
      },
      {
        situation: '现场投影无声音',
        action: '跳过 4 秒原声停顿，直接引导评委看页面流式文字、PDF 页码出处卡与 Live2D 口型同步，顺势节省 4 秒时间。',
      },
      {
        situation: '教室非校园网导致 cuc-cli 个人接口超时',
        action: '坦诚说明校园内网限制正好印证了 cuc-cli 不出本机的隐私边界，并用第 ① ③ ④ 题跑通云端知识库版本让位、217 地点卡与标定拒答。',
      },
    ],
    privacyRule:
      '现场真机演示禁止展示成绩单、学号明文或校园卡大额消费流水；演示 cuc-cli 仅查询当日课表、畅课待办与空教室。',
  },
};
