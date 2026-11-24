import React from 'react';
import type { DeckSource, SlideDefinition } from '../data/deck.ts';

interface SlideSpreadProps {
  readonly deck: DeckSource;
  readonly slide: SlideDefinition;
}

export const SlideSpread: React.FC<SlideSpreadProps> = ({ deck, slide }) => {
  if (slide.id === 1) {
    const s1 = deck.slide1;
    return (
      <div className="ed-spread">
        <div className="ed-left">
          <div>
            <div className="ed-giant-num">{s1.giantNumber}</div>
            <h1 className="ed-headline">{slide.title}</h1>
            <p className="ed-thesis">{s1.thesis}</p>
          </div>
          <div className="ed-quote-band">
            <div className="ed-avatar-pair">
              <img src="./assets/xiaozhi.png" alt="小智校园吉祥物" />
              <img src="./assets/airi.png" alt="AIRI 角色" />
            </div>
            <div className="ed-quote-text">{s1.quote}</div>
          </div>
        </div>

        <div className="ed-right">
          <div className="ed-list">
            {s1.comparisons.map((fc) => (
              <div className="ed-row" key={fc.question}>
                <div className="ed-row-head">
                  <span className="ed-row-title">{fc.question}</span>
                  <span className="ed-row-tag">{fc.proofBadge}</span>
                </div>
                <div className="ed-compare-grid">
                  <span className="ed-bad">通用 AI：{fc.genericAiFailure}</span>
                  <span className="ed-good">Live 小智：{fc.xiaozhiResult}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="ed-kpi-strip">
            {s1.kpis.map((k) => (
              <div key={k.label}>
                <div className={`ed-kpi-val ${k.tone || ''}`}>{k.value}</div>
                <div className="ed-kpi-lbl">{k.label}</div>
                <div className="ed-kpi-sub">{k.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (slide.id === 2) {
    const s2 = deck.slide2;
    return (
      <div className="ed-spread">
        <div className="ed-left">
          <div>
            <div className="ed-giant-num is-medium">{s2.giantNumber}</div>
            <h1 className="ed-headline">{slide.title}</h1>
            <p className="ed-thesis">{s2.thesis}</p>
          </div>
          <div className="ed-quote-band">
            <div className="ed-quote-text">{s2.privacyQuote}</div>
          </div>
        </div>

        <div className="ed-right">
          <div className="ed-list">
            {s2.pillars.map((p) => (
              <div className="ed-row" key={p.id}>
                <div className="ed-row-head">
                  <span className="ed-row-title">{p.name}</span>
                  <span className="ed-row-tag">{p.badge}</span>
                </div>
                <div className="ed-pillar-role">{p.role}</div>
                <div className="ed-pillar-items">{p.items.join(' · ')}</div>
              </div>
            ))}
          </div>
          <div className="ed-footnote">
            <span>{s2.footnoteLeft}</span>
            <span>{s2.footnoteRight}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ed-spread">
      <div className="ed-left">
        <div>
          <div className="ed-giant-num">0{slide.id}</div>
          <h1 className="ed-headline">{slide.title}</h1>
          <p className="ed-thesis">{slide.cuesSummary}</p>
        </div>
      </div>
      <div className="ed-right">
        <div className="ed-quote-band">
          <div className="ed-quote-text">{slide.stageCue}</div>
        </div>
      </div>
    </div>
  );
};
