import React, { useEffect, useMemo, useRef } from 'react';
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
    <div className="ed-spread is-demo">
      <div className="ed-left" style={{ paddingRight: '26px' }}>
        <div className="ed-demo-bar">
          <div className="ed-demo-status">
            <span className="ed-live-dot" />
            <span>{state.liveUrl}</span>
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

      <div className="ed-right" style={{ paddingLeft: '26px' }}>
        <div>
          <h2 style={{ margin: '0 0 6px', fontSize: '26px', fontWeight: 800 }}>一键复制演示提问</h2>
          <div style={{ fontSize: '14px', color: 'var(--ed-muted)', marginBottom: '10px' }}>
            点击即复制 → 左侧输入框 Ctrl+V 发送（建议顺序 {deck.slide3.recommendedOrder}）
          </div>

          <div className="ed-prompt-list">
            {deck.slide3.prompts.map((item) => {
              const isCopied = state.copiedPromptId === item.id;
              const isUsed = state.usedPromptIds.includes(item.id);
              const statusLabel = isCopied ? '✓ 已复制' : isUsed ? '✓ 已用 (再复制)' : '点击复制';

              return (
                <button
                  key={item.id}
                  type="button"
                  className={`ed-prompt-row ${isCopied ? 'is-copied' : ''}`}
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

        <div className="ed-footnote">
          <span>
            {isSameSiteHttps ? deck.slide3.sameSiteMatchedNote : deck.slide3.sameSiteDefaultNote}
          </span>
        </div>
      </div>
    </div>
  );
};
