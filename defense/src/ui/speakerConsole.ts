import type { DeckSource } from '../data/deck.ts';
import type { SpeakerSyncPayload } from '../core/deckController.ts';

export interface SpeakerWindowHandle extends Window {
  __syncFromOpener?: (payload: SpeakerSyncPayload) => void;
}

function buildSpeakerHtml(deck: DeckSource): string {
  const slidesJson = JSON.stringify(deck.slides).replace(/</g, '\\u003c');
  const anchorsJson = JSON.stringify(deck.anchors).replace(/</g, '\\u003c');
  const qaJson = JSON.stringify(deck.qaItems).replace(/</g, '\\u003c');
  const qaCount = deck.qaItems.length;

  return [
    '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">',
    `<title>${deck.meta.title} · 演讲台</title>`,
    '<style>',
    '*{box-sizing:border-box}body{margin:0;background:#0e131e;color:#eef2fb;font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}',
    '.top{display:flex;align-items:center;justify-content:space-between;padding:14px 22px;background:#151d2e;border-bottom:1px solid rgba(255,255,255,0.12);gap:14px}',
    '.timer{font-family:Consolas,monospace;font-size:32px;font-weight:800;color:#e2e8f0}.timer.running{color:#7fe3b1}.timer.warn{color:#fbbf24}.timer.over{color:#fb7185}',
    '.milestones{display:flex;gap:8px;flex-wrap:wrap}.ms{padding:6px 12px;border-radius:999px;font-size:13px;font-weight:700;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);color:#9ca8c2}',
    '.ms.done{background:rgba(127,227,177,0.16);border-color:rgba(127,227,177,0.45);color:#7fe3b1}',
    '.bar{display:flex;gap:8px;align-items:center}button{border:1px solid rgba(255,255,255,0.18);background:#1f2a40;color:#eef2fb;padding:8px 14px;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer}',
    'button.primary{background:#7cb8ff;color:#0b1729;border-color:transparent}button.active{background:#7fe3b1;color:#0b1729;border-color:transparent}',
    '.main{flex:1;display:grid;grid-template-columns:1.45fr 0.95fr;gap:18px;padding:18px 22px;overflow:hidden}',
    '.pane{background:#151d2e;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:18px 20px;overflow-y:auto;display:flex;flex-direction:column;gap:12px}',
    '.cue-box{padding:10px 14px;border-radius:10px;background:rgba(124,184,255,0.14);border-left:4px solid #7cb8ff;font-size:15px;line-height:1.5}',
    '.seg{padding:12px 14px;border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);line-height:1.68;font-size:19px}',
    '.seg.action{background:rgba(127,227,177,0.1);border-color:rgba(127,227,177,0.34)}',
    '.seg-tag{display:inline-block;font-size:12px;font-weight:800;padding:2px 8px;border-radius:999px;background:rgba(255,255,255,0.12);margin-bottom:6px}',
    '.seg-skip{margin-top:6px;font-size:13px;color:#fbbf24}',
    '.jump-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}',
    '.qa-card{padding:12px;border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08)}',
    '.qa-q{color:#7cb8ff;font-weight:800;margin-bottom:4px;font-size:15px}.qa-a{font-size:14px;line-height:1.55;color:#cfd8eb}',
    '</style></head><body>',
    '<div class="top"><div><div id="spTimer" class="timer">00:00 / 05:00</div><div id="spSlideHead" style="font-size:14px;color:#9ca8c2">Slide 1 / 6</div></div>',
    '<div class="milestones" id="spMilestones"></div>',
    '<div class="bar"><button id="spPrev">← 上页</button><button id="spNext" class="primary">下页 →</button><button id="spTimerBtn">开始/暂停</button><button id="spResetBtn">重置</button></div></div>',
    '<div class="main"><div class="pane"><div style="display:flex;justify-content:space-between;align-items:center"><h2 id="spTitle" style="margin:0;font-size:21px"></h2><span id="spWin" style="color:#7cb8ff;font-weight:700"></span></div>',
    '<div class="cue-box" id="spCue"></div><div id="spScript" style="display:flex;flex-direction:column;gap:10px"></div></div>',
    '<div class="pane"><div style="font-size:14px;color:#9ca8c2;font-weight:700">快速跳转</div><div class="jump-grid" id="spJump"></div>',
    '<div style="font-size:14px;color:#9ca8c2;font-weight:700;margin-top:6px">下一页预告</div><div id="spNextPreview" style="padding:12px;border-radius:10px;background:rgba(255,255,255,0.04);font-size:15px"></div>',
    `<div style="font-size:14px;color:#9ca8c2;font-weight:700;margin-top:6px">Q&amp;A 高频追问弹药库（${qaCount} 问）</div><div id="spQa" style="display:flex;flex-direction:column;gap:8px"></div></div></div>`,
    '<script>(function(){',
    `var SLIDES=${slidesJson};var ANCHORS=${anchorsJson};var QA=${qaJson};`,
    'var msRoot=document.getElementById("spMilestones");',
    'ANCHORS.forEach(function(anchor){var badge=document.createElement("span");badge.className="ms";badge.id="ms-"+anchor.id;badge.textContent=anchor.label;badge.title=anchor.rescueStrategy;msRoot.appendChild(badge);});',
    'var jumpGrid=document.getElementById("spJump");',
    'SLIDES.forEach(function(slide){var jumpBtn=document.createElement("button");jumpBtn.textContent="P"+slide.id+" "+slide.shortLabel;jumpBtn.onclick=function(){window.opener&&window.opener.__defenseDeck&&window.opener.__defenseDeck.goTo(slide.id);};jumpGrid.appendChild(jumpBtn);});',
    'var qaRoot=document.getElementById("spQa");',
    'QA.forEach(function(item){var card=document.createElement("div");card.className="qa-card";var qEl=document.createElement("div");qEl.className="qa-q";qEl.textContent=item.q;var aEl=document.createElement("div");aEl.className="qa-a";aEl.textContent=item.a;card.appendChild(qEl);card.appendChild(aEl);qaRoot.appendChild(card);});',
    'document.getElementById("spPrev").onclick=function(){window.opener&&window.opener.__defenseDeck&&window.opener.__defenseDeck.prev();};',
    'document.getElementById("spNext").onclick=function(){window.opener&&window.opener.__defenseDeck&&window.opener.__defenseDeck.next();};',
    'document.getElementById("spTimerBtn").onclick=function(){window.opener&&window.opener.__defenseDeck&&window.opener.__defenseDeck.toggleTimer();};',
    'document.getElementById("spResetBtn").onclick=function(){window.opener&&window.opener.__defenseDeck&&window.opener.__defenseDeck.resetTimer();};',
    'window.__syncFromOpener=function(payload){',
    'var timerEl=document.getElementById("spTimer");timerEl.textContent=payload.formattedTimer;',
    'timerEl.className="timer "+(payload.timerTone==="idle"?"":payload.timerTone);',
    'ANCHORS.forEach(function(anchor){var badge=document.getElementById("ms-"+anchor.id);if(badge)badge.className="ms"+(payload.anchorsReached[anchor.id]?" done":"");});',
    'document.getElementById("spSlideHead").textContent="Slide "+payload.slide+" / "+payload.totalSlides+" · "+payload.slideMeta.anchorTag;',
    'document.getElementById("spTitle").textContent=payload.slideMeta.title;',
    'document.getElementById("spWin").textContent=payload.slideMeta.window;',
    'document.getElementById("spCue").textContent="💡 "+payload.slideMeta.stageCue;',
    'var scriptRoot=document.getElementById("spScript");scriptRoot.textContent="";',
    'payload.slideMeta.scriptSegments.forEach(function(seg){var segCard=document.createElement("div");segCard.className="seg "+(seg.type||"");var tagEl=document.createElement("div");tagEl.className="seg-tag";tagEl.textContent=seg.tag;var textEl=document.createElement("div");textEl.textContent=seg.text;segCard.appendChild(tagEl);segCard.appendChild(textEl);if(seg.skippableNote){var skipEl=document.createElement("div");skipEl.className="seg-skip";skipEl.textContent="⏱ "+seg.skippableNote;segCard.appendChild(skipEl);}scriptRoot.appendChild(segCard);});',
    'var jumpButtons=jumpGrid.querySelectorAll("button");for(var idx=0;idx<jumpButtons.length;idx++)jumpButtons[idx].className=(idx+1===payload.slide)?"active":"";',
    'document.getElementById("spNextPreview").textContent=payload.nextSlideMeta?("Slide "+payload.nextSlideMeta.id+" · "+payload.nextSlideMeta.title+" ("+payload.nextSlideMeta.window+")"):"已是最后一页 · 准备进入现场 Q&A";',
    '};',
    'if(window.opener&&window.opener.__defenseDeck&&window.opener.__defenseDeck.getPayload){window.__syncFromOpener(window.opener.__defenseDeck.getPayload());}',
    '})();</' + 'script></body></html>',
  ].join('');
}

export function openOrFocusSpeakerConsole(
  existingWin: SpeakerWindowHandle | null,
  deck: DeckSource,
  payload: SpeakerSyncPayload,
): SpeakerWindowHandle | null {
  if (existingWin && !existingWin.closed) {
    existingWin.focus();
    existingWin.__syncFromOpener?.(payload);
    return existingWin;
  }

  const win = window.open('', 'liveXiaozhiSpeaker', 'width=1140,height=760') as SpeakerWindowHandle | null;
  if (!win) return null;

  win.document.open();
  win.document.write(buildSpeakerHtml(deck));
  win.document.close();
  win.__syncFromOpener?.(payload);
  return win;
}

export function syncSpeakerWindow(
  win: SpeakerWindowHandle | null,
  payload: SpeakerSyncPayload,
): void {
  if (win && !win.closed) {
    win.__syncFromOpener?.(payload);
  }
}
