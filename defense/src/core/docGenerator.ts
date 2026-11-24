import type { DeckSource } from '../data/deck.ts';

export interface GeneratedDocs {
  readonly speechScriptMd: string;
  readonly demoGuideMd: string;
}

function finalizeMarkdown(lines: readonly string[]): string {
  const cleaned = lines.map((line) => line.replace(/[ \t]+$/g, ''));
  return `${cleaned.join('\n').trimEnd()}\n`;
}

function formatSpeechScript(deck: DeckSource): string {
  const lines: string[] = [
    `# ${deck.meta.title} · 5 分钟单人答辩逐字口播稿（单源同步版）`,
    '',
    `> **核心主线**：${deck.meta.subtitle}`,
    `> **总控时目标**：**4 分 50 秒（${deck.meta.totalDurationSec} 秒）**，预留 10 秒安全余量不超时。`,
    '> **配套演示**：打开 [`index.html`](./index.html) 按 `P` 键开启独立演讲台（实时同步倒计时、时间锚点与逐字稿），或单屏按 `N` 键开启底部单屏提词。',
    '',
    '---',
    '',
    '## 三大硬性时间锚点（彩排与上台必盯）',
    '',
    '| 锚点时刻 | 必须进入的页面 | 超时救场策略 |',
    '|---|---|---|',
    ...deck.anchors.map(
      (a) => `| **\`${a.timeLabel}\`** | 必须进入 **Slide ${a.slideId}（${a.label.replace(`${a.timeLabel} `, '')}）** | ${a.rescueStrategy} |`,
    ),
    '',
  ];

  deck.slides.forEach((slide, idx) => {
    const nextSlide = deck.slides[idx + 1];
    lines.push('---', '');
    lines.push(`## Slide ${slide.id} · ${slide.title}（\`${slide.window}\`）`, '');
    lines.push(`- **操作提示**：${slide.stageCue}`, '');
    lines.push('> **【口播正文】**');
    slide.scriptSegments.forEach((seg, segIdx) => {
      const prefix = seg.type === 'action' ? `**[${seg.tag}]** ` : `**【${seg.tag}】** `;
      lines.push(`> ${prefix}${seg.text}`);
      if (seg.skippableNote) {
        lines.push(`> *[超时精简]* ${seg.skippableNote}`);
      }
      if (segIdx < slide.scriptSegments.length - 1) {
        lines.push('>');
      }
    });
    lines.push('');
    if (nextSlide) {
      const matchingAnchor = deck.anchors.find((a) => a.slideId === nextSlide.id);
      const anchorPrefix = matchingAnchor ? `⏱ 锚点检查 \`${matchingAnchor.timeLabel}\`：` : '';
      lines.push(`- **[${anchorPrefix}按 \`→\` 翻至 Slide ${nextSlide.id}]**`, '');
    }
  });

  return finalizeMarkdown(lines);
}

function formatDemoGuide(deck: DeckSource): string {
  const endpointList = deck.slide3.endpoints.map((ep) => `\`${ep.url}\``).join(' / ');
  const lines: string[] = [
    `# ${deck.meta.title} · 线上真机演示、单人 SOP 与 Q&A 手册`,
    '',
    '---',
    '',
    '## 一、Slide 3（`1:10`）真机演示切源 + 5 题一键复制',
    '',
    `Slide 3 仅保留**真机演示切源**：左侧 64% 直接内嵌 ${endpointList}（支持顶栏一键切源、手动刷新与新窗口打开），右侧 36% 放置 5 张按顺序排好的演示提问卡——**点击任意卡片即复制，到左侧对话框 \`Ctrl+V\` 直接发送**。`,
    '',
    '### 1. 内嵌登录态（`SameSite=Lax`）与备选接入',
    '',
    `1. **同域静态托管（主推荐方案）**：部署至 **${deck.meta.sameOriginDeployUrl}** 后，浏览器会自动把 \`*.acgurl.cn\` 域下已登录的 \`SameSite=Lax\` 会话 Cookie 带入左侧内嵌框；若首次未登录，点右上角「新窗口 ↗」完成一次登录再点「↻ 刷新」即可。`,
    '   后续将改动同步上线可执行：',
    '   ```powershell',
    `   ${deck.meta.deployPowerShellCmd}`,
    '   ```',
    '2. **本机免登录后端（`http://localhost:12393/`）**：若现场网络屏蔽外网域名，在本地启动单用户模式后端并在 Slide 3 顶栏 1 秒切换至 `localhost:12393`（需提前同步线上配置并开启 `use_mcpp`）。',
    `3. **测试体验账号**：普通功能体验可使用 \`${deck.meta.testAccount.username}\` / \`${deck.meta.testAccount.password}\`；演示个人数据需使用本人账号在本机运行 \`cuc-cli\`。`,
    '',
    `### 2. 5 张预设一键复制提问卡（建议演示顺序：\`${deck.slide3.recommendedOrder}\`）`,
    '',
    '| 序号 | 卡片主题 | 复制内容 | 现场展示看点 |',
    '|---|---|---|---|',
    ...deck.slide3.prompts.map(
      (p) => `| **${p.id}** | ${p.tag} | \`${p.prompt}\` | ${p.expectedVisual} |`,
    ),
    '',
    '---',
    '',
    '## 二、答辩前 1 天 & 上台前 5 分钟单人执行 SOP',
    '',
    '### 答辩前 1 天准备',
    '',
    ...deck.sop.dayBefore.map((item) => `- [ ] ${item}`),
    '',
    '### 上台前 5 分钟（教室现场）',
    '',
    ...deck.sop.fiveMinBefore.map((item, i) => `${i + 1}. ${item}`),
    `- **隐私脱敏**：${deck.sop.privacyRule}`,
    '',
    '---',
    '',
    '## 三、评委高频追问 6 问 6 答 & 现场应急预案',
    '',
    '### 1. 评委最可能追问的 6 个核心问题（答辩现场按 `Q` 可一键调出）',
    '',
    ...deck.qaItems.flatMap((qa) => [`- **${qa.q}**`, `  > ${qa.a}`, '']),
    '### 2. 现场突发应急预案（纯真机版）',
    '',
    '| 突发状况 | 1 秒处置动作 |',
    '|---|---|',
    ...deck.sop.emergencies.map((em) => `| **${em.situation}** | ${em.action} |`),
    '',
  ];

  return finalizeMarkdown(lines);
}

export function generateDocs(deck: DeckSource): GeneratedDocs {
  return {
    speechScriptMd: formatSpeechScript(deck),
    demoGuideMd: formatDemoGuide(deck),
  };
}
