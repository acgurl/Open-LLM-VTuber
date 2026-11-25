import React from 'react';
import type { DeckSource, KpiMetric, SlideDefinition } from '../data/deck.ts';

interface SlideSpreadProps {
  readonly deck: DeckSource;
  readonly slide: SlideDefinition;
  readonly onOpenQa?: () => void;
}

const KpiTileStrip: React.FC<{ readonly items: readonly KpiMetric[] }> = ({ items }) => (
  <div className="ed-kpi-tiles">
    {items.map((item) => (
      <div className="ed-kpi-tile" key={item.label}>
        <div className={`ed-kpi-val ${item.tone ?? 'accent'}`}>{item.value}</div>
        <div className="ed-kpi-lbl">{item.label}</div>
        <div className="ed-kpi-sub">{item.sub}</div>
      </div>
    ))}
  </div>
);

const SlideHeader: React.FC<{
  readonly title: string;
  readonly subtitle: string;
  readonly compactTitle?: boolean;
  readonly statValue: string;
  readonly statLabel: string;
  readonly contrastStat?: boolean;
  readonly showMascots?: boolean;
}> = ({
  title,
  subtitle,
  compactTitle = false,
  statValue,
  statLabel,
  contrastStat = false,
  showMascots = false,
}) => (
  <header className="ed-hero-header">
    <div className="ed-hero-main">
      <h1 className={`ed-h1 ${compactTitle ? 'is-compact' : ''}`}>{title}</h1>
      <p className="ed-sub">{subtitle}</p>
    </div>
    <div className="ed-hero-right">
      {showMascots && (
        <div className="ed-avatar-pair">
          <img src="./assets/xiaozhi.png" alt="小智校园吉祥物" />
          <img src="./assets/airi.png" alt="AIRI 角色" />
        </div>
      )}
      <div className="ed-hero-stat">
        <div className={`ed-hero-stat-num ${contrastStat ? 'is-contrast' : ''}`}>{statValue}</div>
        <div className="ed-hero-stat-lbl">{statLabel}</div>
      </div>
    </div>
  </header>
);

const FootnoteBar: React.FC<{ readonly left: string; readonly right: string }> = ({
  left,
  right,
}) => (
  <footer className="ed-footnote-bar">
    <span>{left}</span>
    <strong>{right}</strong>
  </footer>
);

export const SlideSpread: React.FC<SlideSpreadProps> = ({ deck, slide, onOpenQa }) => {
  switch (slide.id) {
    case 1: {
      const s1 = deck.slide1;
      return (
        <section className="ed-slide">
          <SlideHeader
            title={slide.title}
            subtitle={s1.thesis}
            statValue={s1.giantNumber}
            statLabel="268 题端到端盲测答对率"
            showMascots
          />

          <div className="ed-takeaway-strip">{s1.quote}</div>

          <div className="ed-cards-3">
            {s1.comparisons.map((fc, idx) => (
              <article className="ed-card top-accent" key={fc.question}>
                <div className="ed-card-head">
                  <span className="ed-pill">{fc.proofBadge}</span>
                  <span className="ed-pill ed-pill-mono">0{idx + 1}</span>
                </div>

                <h2 className="ed-card-q">{fc.question}</h2>

                <div className="ed-callout-stack">
                  <div className="ed-callout is-bad">
                    <span className="ed-callout-lbl">通用大模型</span>
                    {fc.genericAiFailure}
                  </div>
                  <div className="ed-callout is-good">
                    <span className="ed-callout-lbl">Live 小智</span>
                    {fc.xiaozhiResult}
                  </div>
                </div>
              </article>
            ))}
          </div>

          <KpiTileStrip items={s1.kpis} />
        </section>
      );
    }

    case 4: {
      const s4 = deck.slide4;
      const toneClasses = ['top-accent', 'top-ok', 'top-secondary'] as const;
      const metricTones = ['', 'ok', 'secondary'] as const;
      return (
        <section className="ed-slide">
          <SlideHeader
            title={slide.title}
            subtitle={s4.thesis}
            compactTitle
            statValue={s4.giantNumber}
            statLabel="证据级 hit@5 跃升 (+12pt)"
          />

          <div className="ed-takeaway-strip">{s4.quote}</div>

          <div className="ed-cards-3">
            {s4.designs.map((d, idx) => (
              <article className={`ed-card ${toneClasses[idx] ?? 'top-accent'}`} key={d.num}>
                <div className="ed-card-head">
                  <span className="ed-pill ed-pill-mono">{d.num}</span>
                  <span className={`ed-pill ${idx === 1 ? 'is-ok' : idx === 2 ? 'is-secondary' : ''}`}>
                    核心设计
                  </span>
                </div>

                <div>
                  <h2 className="ed-card-title">{d.title}</h2>
                  <div className={`ed-card-metric ${metricTones[idx] ?? ''}`} style={{ marginTop: '8px' }}>
                    {d.metric}
                  </div>
                </div>

                <ul className="ed-bullet-list">
                  {d.bullets.map((b) => (
                    <li className="ed-bullet-item" key={b.lead}>
                      <span className="ed-bullet-dot" aria-hidden="true" />
                      <span>
                        <strong>{b.lead}</strong>
                        {b.text}
                      </span>
                    </li>
                  ))}
                </ul>

                <div className="ed-callout is-good" style={{ fontSize: '16.5px', padding: '11px 14px' }}>
                  <span className="ed-callout-lbl">实测依据</span>
                  {d.keyProof}
                </div>
              </article>
            ))}
          </div>

          <FootnoteBar left={s4.footnoteLeft} right={s4.footnoteRight} />
        </section>
      );
    }

    case 5: {
      const s5 = deck.slide5;
      return (
        <section className="ed-slide">
          <SlideHeader
            title={slide.title}
            subtitle={s5.thesis}
            compactTitle
            statValue={s5.giantNumber}
            statLabel="关思考 vs 开思考编造率"
            contrastStat
          />

          <div className="ed-dash-grid">
            <article className="ed-card top-ok">
              <div className="ed-card-head">
                <h2 className="ed-card-title">{s5.thinkTitle}</h2>
                <span className="ed-pill is-ok">{s5.thinkBadge}</span>
              </div>

              <div className="ed-contrast-pair">
                <div className="ed-contrast-box is-good">
                  <div className="ed-contrast-num">2.3%</div>
                  <div className="ed-contrast-title">关闭深度思考（线上采用）</div>
                  <div className="ed-contrast-sub">5 题编造 · 11.3s · 1.0× Token</div>
                </div>
                <div className="ed-contrast-box is-bad">
                  <div className="ed-contrast-num">4.7%</div>
                  <div className="ed-contrast-title">开启深度思考（对照实验）</div>
                  <div className="ed-contrast-sub">10 题编造（翻倍）· 15.8s · 1.7×</div>
                </div>
              </div>

              <table className="ed-table">
                <thead>
                  <tr>
                    <th>对比项</th>
                    <th>关闭思考（线上）</th>
                    <th>开启思考（对照）</th>
                  </tr>
                </thead>
                <tbody>
                  {s5.thinkRows.map((r) => (
                    <tr key={r.item}>
                      <td>
                        <strong>{r.item}</strong>
                      </td>
                      <td className="ed-good">{r.noThink}</td>
                      <td className={r.isThinkWorse ? 'ed-bad' : ''}>{r.withThink}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="ed-callout is-accent" style={{ fontSize: '17.5px', padding: '11px 15px' }}>
                {s5.quote}
              </div>
            </article>

            <div className="ed-dash-right">
              <article className="ed-card top-accent" style={{ flex: '1.35 1 0%' }}>
                <div className="ed-card-head">
                  <h2 className="ed-card-title">{s5.blindTitle}</h2>
                  <span className="ed-pill">{s5.blindBadge}</span>
                </div>

                <div className="ed-bar-stack">
                  {s5.blindBars.map((bar) => (
                    <div key={bar.label}>
                      <div className="ed-bar-label">
                        <span>{bar.label}</span>
                        <strong style={{ color: bar.tone === 'ok' ? 'var(--ed-ok)' : 'var(--ed-accent)' }}>
                          {bar.value}%
                        </strong>
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
              </article>

              <article className="ed-card top-warn" style={{ flex: '0.9 1 0%' }}>
                <div className="ed-card-head">
                  <h2 className="ed-card-title">{s5.demandTitle}</h2>
                  <span className="ed-pill is-warn">{s5.demandBadge}</span>
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

                <div className="ed-legend-grid">
                  {s5.demandSegments.map((seg) => (
                    <span key={seg.label}>
                      <strong style={{ color: seg.color }}>■</strong> {seg.label} {seg.percent}%（
                      {seg.countLabel}）
                    </span>
                  ))}
                </div>
              </article>
            </div>
          </div>

          <FootnoteBar left={s5.footnoteLeft} right={s5.footnoteRight} />
        </section>
      );
    }

    case 6: {
      const s6 = deck.slide6;
      return (
        <section className="ed-slide">
          <SlideHeader
            title={slide.title}
            subtitle={s6.thesis}
            compactTitle
            statValue={s6.giantNumber}
            statLabel="公网真实试运行"
          />

          <KpiTileStrip items={s6.stats} />

          <div className="ed-cards-2">
            <article className="ed-card top-warn">
              <div className="ed-card-head">
                <h2 className="ed-card-title">当前 3 个真实缺口</h2>
                <span className="ed-pill is-warn">{s6.gapsBadge}</span>
              </div>

              <div className="ed-numbered-list">
                {s6.gaps.map((item, idx) => (
                  <div className="ed-numbered-item" key={item.lead}>
                    <span className="ed-num-badge is-warn">{idx + 1}</span>
                    <span>
                      <strong>{item.lead}</strong>
                      {item.text}
                    </span>
                  </div>
                ))}
              </div>
            </article>

            <article className="ed-card top-ok">
              <div className="ed-card-head">
                <h2 className="ed-card-title">务实演进计划</h2>
                <span className="ed-pill is-ok">{s6.roadmapBadge}</span>
              </div>

              <div className="ed-numbered-list">
                {s6.roadmap.map((item, idx) => (
                  <div className="ed-numbered-item" key={item.lead}>
                    <span className="ed-num-badge is-ok">{idx + 1}</span>
                    <span>
                      <strong>{item.lead}</strong>
                      {item.text}
                    </span>
                  </div>
                ))}
              </div>
            </article>
          </div>

          <footer className="ed-closing-bar">
            <div className="ed-closing-left">
              <div className="ed-avatar-pair is-compact">
                <img src="./assets/xiaozhi.png" alt="小智校园吉祥物" />
                <img src="./assets/airi.png" alt="AIRI 角色" />
              </div>
              <div className="ed-closing-quote">{s6.quote}</div>
            </div>

            <div className="ed-cta-actions">
              <button type="button" className="ed-btn-line is-active is-lg" onClick={onOpenQa}>
                打开 Q&amp;A 速查 (Q)
              </button>
              <a
                className="ed-btn-line is-lg"
                href={deck.meta.liveSiteUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                打开线上真机 ai.acgurl.cn ↗
              </a>
            </div>
          </footer>
        </section>
      );
    }

    default:
      return null;
  }
};
