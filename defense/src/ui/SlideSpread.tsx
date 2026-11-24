import React from 'react';
import type { DeckSource, SlideDefinition } from '../data/deck.ts';

interface SlideSpreadProps {
  readonly deck: DeckSource;
  readonly slide: SlideDefinition;
  readonly onOpenQa?: () => void;
}

interface EditorialHeroLeftProps {
  readonly giantNumber: string;
  readonly mediumNumber?: boolean;
  readonly title: string;
  readonly thesis: string;
  readonly quote: string;
  readonly showMascots?: boolean;
  readonly actions?: React.ReactNode;
}

const EditorialHeroLeft: React.FC<EditorialHeroLeftProps> = ({
  giantNumber,
  mediumNumber = false,
  title,
  thesis,
  quote,
  showMascots = false,
  actions,
}) => (
  <div className="ed-left">
    <div>
      <div className={`ed-giant-num ${mediumNumber ? 'is-medium' : ''}`}>{giantNumber}</div>
      <h1 className="ed-headline">{title}</h1>
      <p className="ed-thesis">{thesis}</p>
    </div>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div className="ed-quote-band">
        {showMascots && (
          <div className="ed-avatar-pair">
            <img src="./assets/xiaozhi.png" alt="小智校园吉祥物" />
            <img src="./assets/airi.png" alt="AIRI 角色" />
          </div>
        )}
        <div className="ed-quote-text">{quote}</div>
      </div>
      {actions}
    </div>
  </div>
);

export const SlideSpread: React.FC<SlideSpreadProps> = ({ deck, slide, onOpenQa }) => {
  if (slide.id === 1) {
    const s1 = deck.slide1;
    return (
      <div className="ed-spread">
        <EditorialHeroLeft
          giantNumber={s1.giantNumber}
          title={slide.title}
          thesis={s1.thesis}
          quote={s1.quote}
          showMascots
        />
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
        <EditorialHeroLeft
          giantNumber={s2.giantNumber}
          mediumNumber
          title={slide.title}
          thesis={s2.thesis}
          quote={s2.privacyQuote}
        />
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

  if (slide.id === 4) {
    const s4 = deck.slide4;
    return (
      <div className="ed-spread">
        <EditorialHeroLeft
          giantNumber={s4.giantNumber}
          mediumNumber
          title={slide.title}
          thesis={s4.thesis}
          quote={s4.quote}
        />
        <div className="ed-right">
          <div className="ed-list">
            {s4.designs.map((d) => (
              <div className="ed-row" key={d.num}>
                <div className="ed-row-head">
                  <span className="ed-row-title">
                    {d.num}. {d.title}
                  </span>
                  <span className="ed-row-tag">{d.metric}</span>
                </div>
                <div className="ed-pillar-items" style={{ marginBottom: '6px' }}>
                  {d.plainSummary}
                </div>
                <div className="ed-good" style={{ fontSize: '14px' }}>
                  实测依据：{d.keyProof}
                </div>
              </div>
            ))}
          </div>
          <div className="ed-footnote">
            <span>{s4.footnoteLeft}</span>
            <span>{s4.footnoteRight}</span>
          </div>
        </div>
      </div>
    );
  }

  if (slide.id === 5) {
    const s5 = deck.slide5;
    return (
      <div className="ed-spread">
        <EditorialHeroLeft
          giantNumber={s5.giantNumber}
          mediumNumber
          title={slide.title}
          thesis={s5.thesis}
          quote={s5.quote}
        />
        <div className="ed-right">
          <div className="ed-list">
            <div className="ed-row">
              <div className="ed-row-head">
                <span className="ed-row-title">{s5.blindTitle}</span>
                <span className="ed-row-tag">{s5.blindBadge}</span>
              </div>
              <div className="ed-bars-grid">
                {s5.blindBars.map((bar) => (
                  <div key={bar.label}>
                    <div className="ed-bar-label">
                      <span>{bar.label}</span>
                      <strong>{bar.value}%</strong>
                    </div>
                    <div className="ed-bar-track">
                      <div
                        className={`ed-bar-fill ${bar.tone === 'ok' ? 'ok' : ''}`}
                        style={{ width: `${bar.value}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="ed-row">
              <div className="ed-row-head">
                <span className="ed-row-title">{s5.thinkTitle}</span>
                <span className="ed-row-tag">{s5.thinkBadge}</span>
              </div>
              <table className="ed-table">
                <thead>
                  <tr>
                    <th>对比项</th>
                    <th>关闭思考（线上采用）</th>
                    <th>开启思考（对照实验）</th>
                  </tr>
                </thead>
                <tbody>
                  {s5.thinkRows.map((r) => (
                    <tr key={r.item}>
                      <td>{r.item}</td>
                      <td className="ed-good">{r.noThink}</td>
                      <td className={r.isThinkWorse ? 'ed-bad' : ''}>{r.withThink}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="ed-row">
              <div className="ed-row-head">
                <span className="ed-row-title">{s5.demandTitle}</span>
                <span className="ed-row-tag">{s5.demandBadge}</span>
              </div>
              <div className="ed-stacked-bar">
                {s5.demandSegments.map((seg) => (
                  <div
                    key={seg.label}
                    className="ed-stacked-seg"
                    style={{ width: `${seg.percent}%`, background: seg.color }}
                    title={`${seg.label} ${seg.percent}% (${seg.countLabel})`}
                  >
                    {seg.percent >= 6 ? `${seg.percent}%` : ''}
                  </div>
                ))}
              </div>
              <div className="ed-legend-row">
                {s5.demandSegments.map((seg) => (
                  <span key={seg.label}>
                    <strong style={{ color: seg.color }}>■</strong> {seg.label} {seg.percent}%（
                    {seg.countLabel}）
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="ed-footnote">
            <span>{s5.footnoteLeft}</span>
            <span>{s5.footnoteRight}</span>
          </div>
        </div>
      </div>
    );
  }

  const s6 = deck.slide6;
  return (
    <div className="ed-spread">
      <EditorialHeroLeft
        giantNumber={s6.giantNumber}
        mediumNumber
        title={slide.title}
        thesis={s6.thesis}
        quote={s6.quote}
        actions={
          <div className="ed-cta-actions">
            <button type="button" className="ed-btn-line is-active" onClick={onOpenQa}>
              打开 Q&amp;A 速查 (Q)
            </button>
            <a
              className="ed-btn-line"
              href={deck.meta.liveSiteUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              打开线上真机 ai.acgurl.cn ↗
            </a>
          </div>
        }
      />

      <div className="ed-right">
        <div
          className="ed-kpi-strip"
          style={{
            borderTop: 'none',
            paddingTop: 0,
            borderBottom: '1px solid var(--ed-rule)',
            paddingBottom: '14px',
          }}
        >
          {s6.stats.map((st) => (
            <div key={st.label}>
              <div className={`ed-kpi-val ${st.tone || 'accent'}`}>{st.value}</div>
              <div className="ed-kpi-lbl">{st.label}</div>
              <div className="ed-kpi-sub">{st.sub}</div>
            </div>
          ))}
        </div>

        <div className="ed-list">
          <div className="ed-row">
            <div className="ed-row-head">
              <span className="ed-row-title">当前真实缺口</span>
              <span className="ed-row-tag" style={{ color: 'var(--ed-warn)' }}>
                {s6.gapsBadge}
              </span>
            </div>
            <div className="ed-pillar-items" style={{ lineHeight: 1.62 }}>
              {s6.gaps.map((g, i) => (
                <div key={g}>
                  {i + 1}. {g}
                </div>
              ))}
            </div>
          </div>

          <div className="ed-row">
            <div className="ed-row-head">
              <span className="ed-row-title">务实演进计划</span>
              <span className="ed-row-tag" style={{ color: 'var(--ed-ok)' }}>
                {s6.roadmapBadge}
              </span>
            </div>
            <div className="ed-good" style={{ fontSize: '15px', lineHeight: 1.62 }}>
              {s6.roadmap.map((r, i) => (
                <div key={r}>
                  {i + 1}. {r}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
