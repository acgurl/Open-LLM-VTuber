import React from 'react';
import type { DeckSource, SlideDefinition } from '../data/deck.ts';
import { formatMMSS, type DeckKeyAction, type DeckState } from '../core/deckController.ts';

interface DeckChromeProps {
  readonly deck: DeckSource;
  readonly state: DeckState;
  readonly currentSlide: SlideDefinition;
  readonly dockVisible: boolean;
  readonly onAction: (action: DeckKeyAction) => void;
}

export const DeckChrome: React.FC<DeckChromeProps> = ({
  deck,
  state,
  currentSlide,
  dockVisible,
  onAction,
}) => {
  const timerText = `${formatMMSS(state.timerSeconds)} / ${formatMMSS(deck.meta.safetyLimitSec)}`;
  const timerClass =
    state.timerTone === 'idle' ? 'ed-dock-timer' : `ed-dock-timer ${state.timerTone}`;

  return (
    <>
      <div className="ed-hover-zone">
        <nav className={`ed-dock ${dockVisible ? 'is-visible' : ''}`} aria-label="演示控制台">
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => onAction({ type: 'PREV_SLIDE' })}
            title="上一页 (←)"
          >
            ←
          </button>
          <span className="ed-dock-num">
            0{state.slide} / 0{deck.slides.length}
          </span>
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => onAction({ type: 'NEXT_SLIDE' })}
            title="下一页 (→)"
          >
            →
          </button>
          <span className="ed-dock-sep" />
          <button
            type="button"
            className={timerClass}
            onClick={() => onAction({ type: 'TOGGLE_TIMER' })}
            title="点击开始/暂停计时 (R 重置)"
          >
            {timerText}
          </button>
          <span className="ed-dock-sep" />
          <button
            type="button"
            className={`ed-dock-btn ${state.teleprompterOpen ? 'is-active' : ''}`}
            onClick={() => onAction({ type: 'TOGGLE_TELEPROMPTER' })}
            title="单屏提词条 (N)"
          >
            提词(N)
          </button>
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => onAction({ type: 'OPEN_SPEAKER' })}
            title="独立演讲台弹窗 (P)"
          >
            演讲台(P)
          </button>
          <button
            type="button"
            className={`ed-dock-btn ${state.qaModalOpen ? 'is-active' : ''}`}
            onClick={() => onAction({ type: 'TOGGLE_QA_MODAL' })}
            title="Q&A 评委高频追问速查 (Q)"
          >
            Q&amp;A(Q)
          </button>
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => onAction({ type: 'TOGGLE_THEME' })}
            title="切换亮/暗投影模式 (T)"
          >
            亮/暗(T)
          </button>
          <button
            type="button"
            className="ed-dock-btn"
            onClick={() => onAction({ type: 'TOGGLE_FULLSCREEN' })}
            title="全屏切换 (F)"
          >
            全屏(F)
          </button>
        </nav>
      </div>

      {state.teleprompterOpen && (
        <aside className="ed-teleprompter" aria-label="单屏提词">
          <div className="ed-tele-head">
            <span>
              Slide {currentSlide.id} · {currentSlide.title}
            </span>
            <span>
              {currentSlide.window} · {currentSlide.anchorTag}
            </span>
          </div>
          <div className="ed-tele-body">{currentSlide.cuesSummary}</div>
        </aside>
      )}

      {state.qaModalOpen && (
        <div
          className="ed-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="qaModalTitle"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              onAction({ type: 'TOGGLE_QA_MODAL', force: false });
            }
          }}
        >
          <div className="ed-modal-card">
            <div className="ed-modal-head">
              <h2 id="qaModalTitle" style={{ margin: 0, fontSize: '20px' }}>
                Q&amp;A 评委高频追问速查（按 Esc 或 Q 关闭）
              </h2>
              <button
                type="button"
                className="ed-btn-line"
                onClick={() => onAction({ type: 'TOGGLE_QA_MODAL', force: false })}
              >
                关闭
              </button>
            </div>
            <div className="ed-modal-list">
              {deck.qaItems.map((item) => (
                <div className="ed-qa-item" key={item.q}>
                  <div className="ed-qa-q">{item.q}</div>
                  <div className="ed-qa-a">{item.a}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
};
