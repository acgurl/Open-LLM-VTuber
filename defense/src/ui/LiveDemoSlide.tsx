import React, { useEffect, useMemo, useRef, useState } from 'react';
import type { DeckSource } from '../data/deck.ts';
import type { DeckCommand, DeckState } from '../core/deckController.ts';

interface LiveDemoSlideProps {
  readonly deck: DeckSource;
  readonly state: DeckState;
  readonly onDispatch: (command: DeckCommand) => void;
}

function fallbackCopyText(text: string): void {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.top = '-9999px';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } catch {
    // ignore clipboard fallback errors in restricted contexts
  }
  document.body.removeChild(ta);
}

export const LiveDemoSlide: React.FC<LiveDemoSlideProps> = ({ deck, state, onDispatch }) => {
  const copyTimerRef = useRef<number | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  const isSameSiteHttps = useMemo(() => {
    try {
      const hostPattern = new RegExp(deck.slide3.sameOriginHostPattern, 'i');
      return window.location.protocol === 'https:' && hostPattern.test(window.location.hostname);
    } catch {
      return false;
    }
  }, [deck.slide3.sameOriginHostPattern]);

  const handleCopyPrompt = (promptId: string, prompt: string) => {
    const mark = () => {
      onDispatch({ type: 'MARK_PROMPT_COPIED', promptId });
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
      copyTimerRef.current = window.setTimeout(() => {
        onDispatch({ type: 'CLEAR_COPIED_FLASH', promptId });
      }, 1800);
    };

    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(prompt).then(mark, () => {
        fallbackCopyText(prompt);
        mark();
      });
    } else {
      fallbackCopyText(prompt);
      mark();
    }
  };

  return (
    <section className={`ed-spread is-demo ${expanded ? 'is-expanded' : ''}`}>
      <div className="ed-demo-left">
        <div className="ed-demo-bar">
          <div className="ed-demo-status" title={state.liveUrl}>
            <span className="ed-live-dot" />
            <span>{expanded ? state.liveUrl : '在线真机'}</span>
          </div>
          <div className="ed-tab-strip">
            {deck.slide3.endpoints.map((ep) => (
              <button
                key={ep.url}
                type="button"
                className={`ed-btn-line ${state.liveUrl === ep.url ? 'is-active' : ''}`}
                onClick={() => onDispatch({ type: 'SET_LIVE_URL', url: ep.url })}
              >
                {ep.label}
              </button>
            ))}
            <button
              type="button"
              className="ed-btn-line"
              onClick={() => onDispatch({ type: 'RELOAD_LIVE_FRAME' })}
              title="重新加载内嵌真机页面"
            >
              ↻ 刷新
            </button>
            <button
              type="button"
              className={`ed-btn-line ${expanded ? 'is-active' : ''}`}
              onClick={() => setExpanded((prev) => !prev)}
              title="切换全宽真机展示"
            >
              {expanded ? '◫ 还原' : '⛶ 放大'}
            </button>
            <a
              className="ed-btn-line"
              href={state.liveUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              新窗口 ↗
            </a>
          </div>
        </div>

        <div className="ed-iframe-shell">
          <iframe
            key={`${state.liveUrl}-${state.iframeReloadNonce}`}
            src={state.liveUrl}
            title="Live 小智在线真机演示"
            allow="local-network-access; microphone; autoplay; clipboard-read; clipboard-write; fullscreen"
            referrerPolicy="strict-origin-when-cross-origin"
          />
        </div>
      </div>

      {!expanded && (
        <aside className="ed-demo-right">
          <div>
            <h2 className="ed-demo-prompt-head">一键复制演示提问</h2>
            <div className="ed-demo-prompt-sub">
              点击卡片即复制 → 左侧 Ctrl+V 发送（建议 {deck.slide3.recommendedOrder}）
            </div>

            <div className="ed-prompt-list">
              {deck.slide3.prompts.map((item) => {
                const isCopied = state.copiedPromptId === item.id;
                const isUsed = state.usedPromptIds.includes(item.id);
                const statusLabel = isCopied ? '✓ 已复制' : isUsed ? '✓ 已用 (再复制)' : '点击复制';
                const isOptional = item.id === '2';

                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`ed-prompt-row ${isCopied ? 'is-copied' : ''} ${
                      isOptional ? 'is-optional' : ''
                    }`}
                    onClick={() => handleCopyPrompt(item.id, item.prompt)}
                  >
                    <div className="ed-prompt-meta">
                      <span>{item.tag}</span>
                      <span>{statusLabel}</span>
                    </div>
                    <div className="ed-prompt-text">{item.prompt}</div>
                    <div className="ed-prompt-hint">{item.expectedVisual}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="ed-demo-note">
            {isSameSiteHttps ? deck.slide3.sameSiteMatchedNote : deck.slide3.sameSiteDefaultNote}
          </div>
        </aside>
      )}
    </section>
  );
};
