/**
 * NodeChainPanel — Phase 5 Pillar 1 side panel.
 *
 * Renders when a node in <PortfolioOnionView> is selected. Pulls the
 * 4 sections from plan §5 Pillar 1:
 *
 *   INCOMING         — why this ticker is on radar
 *                       · watchlist audit (promote / demote / thesis events)
 *                       · active theses
 *                       · recent signals (last 14d)
 *
 *   OUTGOING         — what this ticker touches
 *                       · 10-K relations (competitor / customer / supplier)
 *                       · facts grouped by type
 *
 *   DECISION CONTEXT — current state + constraints
 *                       · position (qty, cost, P/L, weight)
 *                       · exit triggers status (per thesis)
 *
 *   PRO vs CONTRA    — anchored facts by polarity (anti-confirmation-bias)
 *                       · two-column forced display, even when one side empty
 *
 * Empty sections render an explicit "(none recorded — actively look?)"
 * — the void IS the message, per plan §5 Pillar 1 chain enhancement #3.
 *
 * Layout: ~380px right-side panel, scrolls vertically. Dense, all-
 * text content (no graph viz inside the panel itself — that's the
 * canvas's job).
 */
import { useState } from 'react'
import { AlertTriangle, X, ArrowRight, Layers } from 'lucide-react'
import { useStockResearch } from '@/components/research/StockResearchContext'
import {
  useWatchlistAudit,
  useTheses,
  useRecentSignals,
  useAnchoredFacts,
  usePositionByTicker,
  useExitTriggers,
  useTickerDisagreements,
  useLatticeCalls,
  usePortfolioSummary,
  useDecisionPrefs,
  useCorrelation,
  usePortfolioView,
  useWatchlistPromote,
  useResolveDisagreement,
  type WatchlistAuditEvent,
} from '@/lib/api'

function fmtDate(iso: string): string {
  try { return new Date(iso).toISOString().slice(0, 10) } catch { return iso }
}
function fmtMoney(n?: number | null): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}
function fmtPct(n?: number | null): string {
  if (n == null) return '—'
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%'
}

const ACTION_LABEL: Record<string, string> = {
  promote:           '⬆ promote',
  demote:            '⬇ demote',
  drop:              '✕ drop',
  review:            '◐ review',
  note:              '🗒 note',
  thesis_create:     '+ thesis',
  thesis_invalidate: '✕ thesis',
}

// ── Section wrapper ──
function Section({ title, subtitle, children }: {
  title: string
  subtitle?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="border-t border-[var(--color-border)] py-2">
      <div className="px-2 pb-1 flex items-baseline gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)]">{title}</h3>
        {subtitle && <span className="text-[9px] italic text-[var(--color-dim)]">{subtitle}</span>}
      </div>
      <div className="px-2 space-y-1.5 text-[11px] text-[var(--color-text)]/85">
        {children}
      </div>
    </div>
  )
}

function EmptyLine({ note }: { note: string }) {
  return <div className="text-[10px] italic text-[var(--color-dim)] py-0.5">— {note}</div>
}


// ── FactRow — inline-collapsible fact display ──
// One row per competitor/customer/supplier with an inline "📎"
// toggle that reveals the verbatim 10-K quote + source URL + filing
// section. Honors the "信息多一些没事 + 必须有根有据" rule: every
// claim must be one-click away from its primary source.
function FactRow({
  ticker, name, quote, url, section, extra,
}: {
  ticker?: string | null
  name: string
  quote?: string | null
  url?: string | null
  section?: string | null
  extra?: string | null
}) {
  const [open, setOpen] = useState(false)
  const hasProvenance = !!(quote || url)
  const { openTicker } = useStockResearch()
  // EDGAR full-text search URL — when entity has no ticker (LLM only
  // captured the company name from the 10-K), give the user a 1-click
  // path to find it on SEC. Closes the anchor-walk 1-hop break:
  // even non-tradable / ADR-only / private subsidiary names become
  // explorable instead of dead text.
  const edgarSearchUrl = !ticker && name
    ? `https://efts.sec.gov/LATEST/search-index?q=${encodeURIComponent(`"${name}"`)}&forms=10-K`
    : null
  return (
    <div className="text-[10px] pl-2 leading-tight">
      <div className="flex items-baseline gap-1 flex-wrap">
        {ticker ? (
          <button
            onClick={() => openTicker(ticker)}
            title={`walk to ${ticker} (打开 chain panel)`}
            className="text-[var(--color-text)] font-medium underline decoration-dotted decoration-[var(--color-dim)] underline-offset-2 hover:text-[var(--color-accent)] hover:decoration-[var(--color-accent)]"
          >
            {ticker}
          </button>
        ) : null}
        {ticker && <span className="text-[var(--color-dim)] mx-1">·</span>}
        <span className="text-[var(--color-text)]/80">{name}</span>
        {edgarSearchUrl && (
          <a
            href={edgarSearchUrl}
            target="_blank"
            rel="noopener noreferrer"
            title={`SEC EDGAR full-text search for "${name}" — find this company's 10-K filings + ticker`}
            className="text-[9px] text-[var(--color-accent)] hover:underline ml-0.5"
          >🔍 EDGAR</a>
        )}
        {extra && <span className="text-[var(--color-dim)] ml-1">({extra})</span>}
        {hasProvenance && (
          <button
            onClick={() => setOpen(o => !o)}
            title={open ? 'collapse 原文 quote' : 'show verbatim 10-K quote + source'}
            className="text-[9px] text-[var(--color-dim)] hover:text-[var(--color-accent)] ml-1 underline decoration-dotted underline-offset-2"
          >
            {open ? '▾ hide' : '📎 quote'}
          </button>
        )}
      </div>
      {open && hasProvenance && (
        <div className="mt-0.5 mb-1 ml-1 pl-2 border-l-2 border-[var(--color-border)] text-[9px] leading-snug text-[var(--color-text)]/80">
          {quote && (
            <div className="italic">"{quote}"</div>
          )}
          <div className="text-[var(--color-dim)] mt-0.5 flex items-center gap-1 flex-wrap">
            {section && <span>§ {section}</span>}
            {section && url && <span>·</span>}
            {url && (
              <a href={url} target="_blank" rel="noopener noreferrer"
                 className="underline hover:text-[var(--color-accent)]">
                source ↗
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── INCOMING section ──
function Incoming({ ticker }: { ticker: string }) {
  const auditQ = useWatchlistAudit(ticker)
  const thesesQ = useTheses(ticker, 'active')
  const sigsQ = useRecentSignals({ ticker, limit: 6 })
  const latticeQ = useLatticeCalls('fin-core')

  const events: WatchlistAuditEvent[] = auditQ.data?.events ?? []
  const theses = thesesQ.data?.theses ?? []
  const sigs = sigsQ.data?.events ?? []
  // Phase 6: lattice L2 themes that mention this ticker.
  const mentioningThemes = (latticeQ.data?.themes ?? []).filter(t =>
    (t.tags ?? []).includes(`symbol:${ticker}`)
  )

  return (
    <Section title="Incoming" subtitle="why on radar">
      {/* Promotion / recent watchlist events */}
      {events.length === 0 && theses.length === 0 && (
        <EmptyLine note="no watchlist events yet" />
      )}
      {events.slice(0, 4).map(e => (
        <div key={e.audit_id} className="leading-tight">
          <span className="text-[10px] text-[var(--color-dim)] mr-1">{fmtDate(e.ts)}</span>
          <span className="text-[10px] mr-1">{ACTION_LABEL[e.action] ?? e.action}</span>
          {e.from_tier && e.to_tier && (
            <span className="text-[10px] text-[var(--color-dim)]">
              {e.from_tier} → {e.to_tier}
            </span>
          )}
          {e.note && <div className="text-[10px] italic text-[var(--color-dim)] pl-2">{e.note}</div>}
        </div>
      ))}

      {/* Lattice L2 theme memberships */}
      {mentioningThemes.length > 0 && (
        <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40">
          <div className="text-[10px] text-[var(--color-dim)] mb-0.5 flex items-center gap-1">
            <Layers size={9} /> In today's L2 themes ({mentioningThemes.length}):
          </div>
          {mentioningThemes.map(t => (
            <div key={t.id} className="text-[10px] pl-1 leading-tight">
              <span className={
                t.severity === 'alert' ? 'text-red-300' :
                t.severity === 'warn'  ? 'text-amber-300' :
                'text-[var(--color-text)]'
              }>● </span>
              <span>{t.title}</span>
              <span className="text-[var(--color-dim)] ml-1">({t.members.length} obs)</span>
            </div>
          ))}
        </div>
      )}

      {/* Theses */}
      {theses.length > 0 && (
        <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40">
          <div className="text-[10px] text-[var(--color-dim)] mb-0.5">Active theses:</div>
          {theses.map(t => (
            <div key={t.thesis_id} className="leading-tight pl-1">
              <span className={
                t.status === 'requires_review'
                  ? 'text-amber-300' : 'text-emerald-300'
              }>● </span>
              <span className="text-[10px]">{t.sections.bull_case?.slice(0, 80) || '(no bull case)'}</span>
              {t.status === 'requires_review' && (
                <span className="text-[9px] text-amber-300 ml-1">⚠ requires_review</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Recent signals — each row exposes severity, scanner, source URL
          inline so the user can verify the claim without leaving the
          panel. "有根有据" = every signal traceable in one click. */}
      {sigs.length > 0 && (
        <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40">
          <div className="text-[10px] text-[var(--color-dim)] mb-0.5">Recent signals ({sigs.length}):</div>
          {sigs.slice(0, 5).map(s => (
            <div key={s.event_id} className="leading-tight pl-1 text-[10px] flex items-baseline gap-1 flex-wrap">
              <span className="text-[var(--color-dim)]">{fmtDate(s.detected_at)}</span>
              <span className={
                s.severity === 'high' ? 'text-red-300' :
                s.severity === 'med'  ? 'text-amber-300' :
                'text-[var(--color-dim)]'
              }>[{s.severity}]</span>
              <span className="text-[var(--color-text)]">{s.signal_type}</span>
              <span className="text-[var(--color-dim)]">· {s.scanner_name}</span>
              {s.source_url && (
                <a
                  href={s.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`open source: ${s.source_url}`}
                  className="text-[9px] text-[var(--color-accent)] hover:underline ml-0.5"
                >↗</a>
              )}
              {s.title && (
                <span className="text-[9px] italic text-[var(--color-dim)] ml-1 truncate flex-1 min-w-0">
                  — {s.title}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}

// ── OUTGOING section ──
function Outgoing({ ticker }: { ticker: string }) {
  const factsQ = useAnchoredFacts(ticker)
  const facts = factsQ.data?.facts
  const meta = factsQ.data?.meta
  // 90-day correlation top peers (only available for tickers in the
  // user's portfolio matrix; computed from market_data_daily history).
  const corrQ = useCorrelation('fin-core', 90, true)
  const topCorrelated: Array<{ ticker: string; rho: number }> = (() => {
    const m = corrQ.data
    if (!m) return []
    const i = m.symbols.indexOf(ticker)
    if (i < 0) return []
    const row = m.matrix[i] ?? []
    return m.symbols
      .map((s, j) => ({ ticker: s, rho: row[j] }))
      .filter(x => x.ticker !== ticker && Number.isFinite(x.rho))
      .sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho))
      .slice(0, 4)
  })()

  const comp = facts?.competitor ?? []
  const cust = facts?.customer ?? []
  const supp = facts?.supplier ?? []
  const seg  = facts?.segment ?? []
  const risks = facts?.risk ?? []

  // Macro factor classification — per plan §5 Pillar 1 OUTGOING block.
  // Risks already extracted from 10-K typically name the macro exposure
  // (China export, USD/CNY, AI regulation, ...). Bucket them via
  // keyword scan so the panel surfaces "what macro could move this
  // ticker" without needing a separate macro_factors table.
  const MACRO_BUCKETS: Array<{ key: string; label: string; rx: RegExp }> = [
    { key: 'trade',     label: 'Trade / China',          rx: /\b(china|export.{0,15}restriction|tariff|trade war|customs|sanction|huawei)\b/i },
    { key: 'currency',  label: 'FX / USD-CNY',           rx: /\b(currency|foreign exchange|fx|exchange rate|usd[\\/-]cny|cny[\\/-]usd|yuan)\b/i },
    { key: 'regul_ai',  label: 'AI / privacy regulation', rx: /\b(ai act|ai regulation|gdpr|ccpa|antitrust|privacy law|content moderation|section 230)\b/i },
    { key: 'rates',     label: 'Interest rates / inflation', rx: /\b(interest rate|inflation|fed|federal reserve|monetary policy)\b/i },
    { key: 'supply',    label: 'Supply chain',           rx: /\b(supply chain|semiconductor shortage|chip shortage|logistics|shipping)\b/i },
    { key: 'climate',   label: 'Climate / ESG',          rx: /\b(climate|carbon|emission|esg)\b/i },
  ]
  const macroHits: Array<{ label: string; n: number }> = MACRO_BUCKETS
    .map(b => ({
      label: b.label,
      n: risks.filter(r =>
        b.rx.test(r.headline ?? '') || b.rx.test(r.evidence_quote ?? '')
      ).length,
    }))
    .filter(x => x.n > 0)

  const empty = comp.length === 0 && cust.length === 0 && supp.length === 0
    && seg.length === 0 && topCorrelated.length === 0 && macroHits.length === 0

  return (
    <Section
      title="Outgoing"
      subtitle={
        <>
          who it touches (10-K)
          {meta?.source_filing_date && (
            <span className="ml-1.5">
              · filing <span className="text-[var(--color-text)]/80">{meta.source_filing_date.slice(0, 10)}</span>
            </span>
          )}
          {meta?.extracted_at && (
            <span className="ml-1.5">
              · extracted <span className="text-[var(--color-text)]/80">{meta.extracted_at.slice(0, 10)}</span>
            </span>
          )}
        </>
      }
    >
      {empty && <EmptyLine note="no 10-K relations extracted yet" />}

      {comp.length > 0 && (
        <div>
          <div className="text-[10px] text-red-300 mb-0.5">⚔ Competitors ({comp.length}):</div>
          {comp.slice(0, 5).map((c, i) => (
            <FactRow key={i} ticker={c.ticker} name={c.name}
              quote={c.evidence_quote} url={c.source_url} section={c.source_section} />
          ))}
        </div>
      )}

      {cust.length > 0 && (
        <div>
          <div className="text-[10px] text-blue-300 mb-0.5">→ Customers ({cust.length}):</div>
          {cust.slice(0, 4).map((c, i) => (
            <FactRow key={i} ticker={c.ticker} name={c.name}
              quote={c.evidence_quote} url={c.source_url} section={c.source_section}
              extra={c.concentration_pct != null ? `${c.concentration_pct}% conc` : null} />
          ))}
        </div>
      )}

      {supp.length > 0 && (
        <div>
          <div className="text-[10px] text-violet-300 mb-0.5">← Suppliers ({supp.length}):</div>
          {supp.slice(0, 4).map((c, i) => (
            <FactRow key={i} ticker={c.ticker} name={c.name}
              quote={c.evidence_quote} url={c.source_url} section={c.source_section}
              extra={c.criticality ? `[${c.criticality}]` : null} />
          ))}
        </div>
      )}

      {seg.length > 0 && (
        <div>
          <div className="text-[10px] text-emerald-300 mb-0.5">$ Segments ({seg.length}):</div>
          {seg.slice(0, 4).map((s, i) => (
            <div key={i} className="text-[10px] pl-2 leading-tight">
              <span className="text-[var(--color-text)]">{s.name}</span>
              {s.revenue_pct != null && (
                <span className="text-[var(--color-dim)] ml-1">({s.revenue_pct}% rev)</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 90-day price correlation — only available for portfolio holdings */}
      {topCorrelated.length > 0 && (
        <div>
          <div className="text-[10px] text-[var(--color-dim)] mb-0.5">~ Correlated (90d):</div>
          {topCorrelated.map(c => (
            <div key={c.ticker} className="text-[10px] pl-2 leading-tight">
              <span className="text-[var(--color-text)] font-medium">{c.ticker}</span>
              <span className="text-[var(--color-dim)] ml-1">ρ = </span>
              <span className={
                c.rho >= 0.7  ? 'text-amber-300' :
                c.rho <= -0.3 ? 'text-blue-300' :
                'text-[var(--color-text)]'
              }>{c.rho.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Macro factors — derived from extracted 10-K risk text */}
      {macroHits.length > 0 && (
        <div>
          <div className="text-[10px] text-[var(--color-dim)] mb-0.5">🌐 Macro exposure (from 10-K risks):</div>
          {macroHits.map(m => (
            <div key={m.label} className="text-[10px] pl-2 leading-tight">
              <span className="text-amber-300">●</span>
              <span className="ml-1 text-[var(--color-text)]">{m.label}</span>
              <span className="text-[var(--color-dim)] ml-1">({m.n} risk mention{m.n === 1 ? '' : 's'})</span>
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}

// ── DECISION CONTEXT section ──
function DecisionContext({ ticker }: { ticker: string }) {
  const posQ = usePositionByTicker(ticker)
  const thesesQ = useTheses(ticker, 'active')
  const prefsQ = useDecisionPrefs()
  const summaryQ = usePortfolioSummary()
  const theses = thesesQ.data?.theses ?? []
  const summary = posQ.data?.summary
  const lots = posQ.data?.lots ?? []
  const held = !!summary && summary.total_quantity > 0
  const prefs = prefsQ.data?.preferences
  const portfolio = summaryQ.data

  // Per-ticker weight in portfolio + sector concentration.
  const byTickerRow = portfolio?.by_ticker.find(r => r.ticker === ticker)
  const weightPct = byTickerRow?.weight_pct ?? null
  const sectorOfTicker = byTickerRow?.sector
  const sectorRow = sectorOfTicker
    ? portfolio?.by_sector.find(s => s.sector === sectorOfTicker)
    : null
  const sectorPct = sectorRow?.pct ?? null
  const maxPosition = prefs?.max_position_pct ?? null
  const maxSector = prefs?.max_sector_pct ?? null
  const positionOverLimit = weightPct != null && maxPosition != null && weightPct > maxPosition
  const sectorOverLimit = sectorPct != null && maxSector != null && sectorPct > maxSector

  // Tax lot ST/LT timing — pick the SOONEST lot to roll to LT (most decision-relevant).
  const soonestST = held
    ? lots.filter(l => !l.is_long_term).sort((a, b) => a.days_until_lt - b.days_until_lt)[0]
    : null

  // Portfolio-level vs benchmark windows (we don't have per-ticker
  // alpha computed server-side; surface the portfolio number so the
  // user sees overall performance context next to a single position).
  const vsBench = portfolio?.vs_benchmark

  return (
    <Section title="Decision context" subtitle="current state">
      {/* Position */}
      <div>
        <div className="text-[10px] text-[var(--color-dim)] mb-0.5">Position:</div>
        {held && summary ? (
          <div className="text-[10px] pl-1 leading-tight space-y-0.5">
            <div>
              <span className="text-[var(--color-text)]">{summary.total_quantity.toFixed(2)} sh</span>
              <span className="text-[var(--color-dim)] mx-1">·</span>
              <span className="text-[var(--color-dim)]">avg ${summary.avg_cost.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-[var(--color-dim)]">MV </span>
              <span className="text-[var(--color-text)]">{fmtMoney(summary.market_value)}</span>
              <span className="text-[var(--color-dim)] mx-1">·</span>
              <span className={summary.unrealized != null && summary.unrealized >= 0 ? 'text-emerald-300' : 'text-red-300'}>
                {fmtMoney(summary.unrealized)} ({fmtPct(summary.unrealized_pct)})
              </span>
            </div>
          </div>
        ) : (
          <div className="text-[10px] italic text-[var(--color-dim)] pl-1">not held</div>
        )}
      </div>

      {/* Concentration: portfolio weight + sector */}
      {held && portfolio && (
        <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40 space-y-0.5">
          {weightPct != null && (
            <div className="text-[10px] pl-1 leading-tight">
              <span className="text-[var(--color-dim)]">Portfolio weight: </span>
              <span className={positionOverLimit ? 'text-red-300 font-medium' : 'text-[var(--color-text)]'}>
                {weightPct.toFixed(1)}%
              </span>
              {maxPosition != null && (
                <span className="text-[var(--color-dim)] ml-1">
                  (your max: {maxPosition}%){positionOverLimit && ' ⚠'}
                </span>
              )}
            </div>
          )}
          {sectorOfTicker && sectorPct != null && (
            <div className="text-[10px] pl-1 leading-tight">
              <span className="text-[var(--color-dim)]">{sectorOfTicker}: </span>
              <span className={sectorOverLimit ? 'text-red-300 font-medium' : 'text-[var(--color-text)]'}>
                {sectorPct.toFixed(1)}%
              </span>
              {maxSector != null && (
                <span className="text-[var(--color-dim)] ml-1">
                  (warn: {maxSector}%){sectorOverLimit && ' ⚠'}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tax lot ST/LT timing — only when there's an open ST lot */}
      {held && soonestST && (
        <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40">
          <div className="text-[10px] pl-1 leading-tight">
            <span className="text-[var(--color-dim)]">Tax lot: </span>
            <span className="text-[var(--color-text)]">{soonestST.open_quantity.toFixed(2)} sh</span>
            <span className="text-[var(--color-dim)]"> @ ${soonestST.open_price.toFixed(2)}</span>
            <span className="text-[var(--color-dim)] mx-1">·</span>
            <span className={soonestST.days_until_lt <= 90 ? 'text-amber-300' : 'text-[var(--color-dim)]'}>
              ST ({soonestST.days_until_lt}d to LT)
            </span>
          </div>
        </div>
      )}

      {/* Portfolio-level vs benchmark — context, not per-ticker alpha */}
      {held && vsBench && (
        <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40">
          <div className="text-[10px] text-[var(--color-dim)] mb-0.5">
            Portfolio vs {vsBench.benchmark}:
          </div>
          <div className="text-[10px] pl-1 leading-tight space-x-2 flex flex-wrap">
            {Object.entries(vsBench.windows).map(([win, row]) => (
              <span key={win}>
                <span className="text-[var(--color-dim)]">{win}:</span>{' '}
                <span className="text-[var(--color-text)]">
                  {row.benchmark_pct != null ? fmtPct(row.benchmark_pct) : '—'}
                </span>
              </span>
            ))}
          </div>
          {vsBench.note && (
            <div className="text-[9px] italic text-[var(--color-dim)] mt-0.5">{vsBench.note}</div>
          )}
        </div>
      )}

      {/* Exit triggers — for ALL active theses. Previously only the
          first thesis was evaluated; users with multiple concurrent
          theses on a ticker missed the rest. */}
      <div className="pt-1 mt-1 border-t border-[var(--color-border)]/40">
        <div className="text-[10px] text-[var(--color-dim)] mb-0.5">
          Exit triggers
          {theses.length > 0 && (
            <span className="text-[9px] italic ml-1">
              ({theses.length} active thes{theses.length === 1 ? 'is' : 'es'})
            </span>
          )}:
        </div>
        {theses.length === 0 ? (
          <EmptyLine note="no active thesis — exit triggers undefined" />
        ) : (
          theses.map((thesis) => (
            <ThesisTriggersBlock key={thesis.thesis_id} thesis={thesis} showThesisHeader={theses.length > 1} />
          ))
        )}
      </div>
    </Section>
  )
}

// ── Per-thesis triggers block ──
// Each active thesis owns its own exit-trigger list; rendering them
// one-block-per-thesis preserves ownership so the user knows which
// thesis a fired trigger belongs to (matters when you have e.g. a
// growth thesis + a hedge thesis on the same ticker — different exit
// rules apply per thesis).
function ThesisTriggersBlock({
  thesis,
  showThesisHeader,
}: {
  thesis: { thesis_id: string; status: string; sections?: Record<string, string> }
  showThesisHeader: boolean
}) {
  const exitQ = useExitTriggers(thesis.thesis_id)
  const triggers = exitQ.data?.triggers ?? []
  const firstLine = thesis.sections?.bull_case?.split('\n')[0]?.slice(0, 60)
                  ?? `thesis ${thesis.thesis_id.slice(0, 8)}`
  return (
    <div className={showThesisHeader ? 'mt-1' : ''}>
      {showThesisHeader && (
        <div className="text-[9px] text-[var(--color-dim)] italic pl-1 leading-tight border-l-2 border-[var(--color-border)] ml-0.5">
          {thesis.status === 'requires_review' && (
            <span className="text-amber-300 mr-1">⚠</span>
          )}
          {firstLine}
        </div>
      )}
      {exitQ.isLoading ? (
        <div className="text-[10px] italic text-[var(--color-dim)] pl-1">loading…</div>
      ) : triggers.length === 0 ? (
        <EmptyLine note="thesis has no parseable triggers in body_md" />
      ) : (
        triggers.map((t, i) => {
          const fired = t.fired === true
          const safe = t.fired === false
          const manual = t.fired === null
          return (
            <div key={i} className="text-[10px] pl-1 leading-tight">
              <span className={fired ? 'text-red-300' : safe ? 'text-emerald-300' : 'text-[var(--color-dim)]'}>
                {fired ? '🔥' : safe ? '✓' : '◐'}
              </span>
              <span className="ml-1">{t.text}</span>
              {!manual && t.current_value != null && (
                <span className="text-[var(--color-dim)] ml-1">(now: {t.current_value.toFixed(1)})</span>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}


// ── PROVENANCE section ──
// Collapsible list of every anchored fact with verbatim quote + source
// URL. Per plan §5 Pillar 1 ("All quotes verbatim, click to view
// source"). Default collapsed — it's bulky but trust-critical when the
// user wants to audit any claim made elsewhere in the panel.
function Provenance({ ticker }: { ticker: string }) {
  // Default-expanded: "有根有据" is core to the system — hiding the
  // quote list behind a "+ show all" click made provenance feel
  // optional rather than canonical. Collapse remains available via
  // the same button if the user wants to hide noise.
  const [expanded, setExpanded] = useState(true)
  const factsQ = useAnchoredFacts(ticker)
  const facts = factsQ.data?.facts
  const meta = factsQ.data?.meta

  type FlatFact = {
    type: string
    label: string
    quote: string
    url: string
    section: string
  }
  const flat: FlatFact[] = []
  for (const c of facts?.competitor ?? [])
    flat.push({ type: 'competitor', label: c.ticker ? `${c.ticker} (${c.name})` : c.name,
      quote: c.evidence_quote, url: c.source_url, section: c.source_section })
  for (const c of facts?.customer ?? [])
    flat.push({ type: 'customer', label: c.ticker ? `${c.ticker} (${c.name})` : c.name,
      quote: c.evidence_quote, url: c.source_url, section: c.source_section })
  for (const c of facts?.supplier ?? [])
    flat.push({ type: 'supplier', label: c.ticker ? `${c.ticker} (${c.name})` : c.name,
      quote: c.evidence_quote, url: c.source_url, section: c.source_section })
  for (const c of facts?.risk ?? [])
    flat.push({ type: 'risk', label: c.headline,
      quote: c.evidence_quote, url: c.source_url, section: c.source_section })
  for (const c of facts?.segment ?? [])
    flat.push({ type: 'segment', label: c.name,
      quote: c.evidence_quote, url: c.source_url, section: c.source_section })
  for (const c of facts?.business_summary ?? [])
    flat.push({ type: 'business', label: c.sentence.slice(0, 60),
      quote: c.evidence_quote, url: c.source_url, section: c.source_section })

  return (
    <Section title="Provenance" subtitle={`${flat.length} verbatim quotes`}>
      {flat.length === 0 ? (
        <EmptyLine note="no extracted facts — run 10-K re-extract" />
      ) : (
        <>
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-accent)] underline"
          >
            {expanded ? '− collapse' : `+ show all ${flat.length} quotes`}
          </button>
          {meta && meta.source_filing_date && (
            <div className="text-[9px] italic text-[var(--color-dim)] mt-0.5">
              all from filing {meta.source_filing_date.slice(0, 10)}
              {meta.source_url && (
                <>
                  {' '}·{' '}
                  <a href={meta.source_url} target="_blank" rel="noopener noreferrer"
                     className="underline hover:text-[var(--color-accent)]">filing root</a>
                </>
              )}
            </div>
          )}
          {expanded && flat.map((f, i) => (
            <div key={i} className="border-l-2 border-[var(--color-border)] pl-2 mt-1.5 text-[9px] leading-snug">
              <div className="text-[var(--color-dim)] flex items-baseline gap-1">
                <span className="text-[var(--color-accent)] uppercase">{f.type}</span>
                <span className="text-[var(--color-text)]">{f.label}</span>
              </div>
              <div className="italic text-[var(--color-text)]/80 my-0.5">"{f.quote}"</div>
              <div className="text-[var(--color-dim)]">
                <span>§ {f.section}</span>
                {f.url && (
                  <>
                    {' '}·{' '}
                    <a href={f.url} target="_blank" rel="noopener noreferrer"
                       className="underline hover:text-[var(--color-accent)]">source</a>
                  </>
                )}
              </div>
            </div>
          ))}
        </>
      )}
    </Section>
  )
}

// ── PRO vs CONTRA section ──
function ProContra({ ticker }: { ticker: string }) {
  const factsQ = useAnchoredFacts(ticker)
  const facts = factsQ.data?.facts
  // Pull bull/bear case bullets from active theses. Per plan §5 Pillar 1
  // chain enhancement #3, the user-authored bear case is one of three
  // contra-evidence sources (alongside polarity='contra' facts and
  // contradicting signal events). Bull case feeds the pro side.
  const thesesQ = useTheses(ticker, 'active')
  const thesesItems = (thesesQ.data?.theses ?? [])
    .flatMap(t => {
      const out: Array<{ side: 'pro' | 'contra'; summary: string }> = []
      const bull = t.sections?.bull_case?.trim()
      const bear = t.sections?.bear_case?.trim()
      // Each section is a markdown block; split into bullets if any
      const toBullets = (md: string) => md
        .split(/\n/)
        .map(s => s.replace(/^[-*]\s+/, '').trim())
        .filter(s => s.length > 4 && !s.startsWith('#'))
      if (bull) for (const b of toBullets(bull)) out.push({ side: 'pro', summary: b })
      if (bear) for (const b of toBullets(bear)) out.push({ side: 'contra', summary: b })
      return out
    })

  // Flatten all facts into one list with their type + polarity.
  type FlatFact = {
    type: string
    summary: string
    polarity: 'pro' | 'contra' | 'neutral' | null | undefined
    quote?: string
    url?: string
  }
  const all: FlatFact[] = []
  for (const c of facts?.competitor ?? [])
    all.push({ type: 'competitor', summary: c.ticker ? `${c.ticker} (${c.name})` : c.name, polarity: c.polarity, quote: c.evidence_quote, url: c.source_url })
  for (const c of facts?.customer ?? [])
    all.push({ type: 'customer', summary: c.ticker ? `${c.ticker} (${c.name})` : c.name, polarity: c.polarity, quote: c.evidence_quote, url: c.source_url })
  for (const c of facts?.supplier ?? [])
    all.push({ type: 'supplier', summary: c.ticker ? `${c.ticker} (${c.name})` : c.name, polarity: c.polarity, quote: c.evidence_quote, url: c.source_url })
  for (const c of facts?.risk ?? [])
    all.push({ type: 'risk', summary: c.headline, polarity: c.polarity, quote: c.evidence_quote, url: c.source_url })
  for (const c of facts?.business_summary ?? [])
    all.push({ type: 'business', summary: c.sentence.slice(0, 100), polarity: c.polarity, quote: c.evidence_quote, url: c.source_url })
  for (const c of facts?.segment ?? [])
    all.push({ type: 'segment', summary: c.name, polarity: c.polarity, quote: c.evidence_quote, url: c.source_url })

  // Polarity inference (2026-05-16 Need #5): when extractor didn't
  // label polarity, fall back to fact_type defaults + keyword scan
  // on the quote text. Better than dumping everything in neutral —
  // user gets meaningful pro/contra split even on legacy data.
  const CONTRA_KEYWORDS = /\b(risk|decline|loss|litigation|lawsuit|impair|breach|fraud|shortage|tariff|sanction|fine|regulation|antitrust|restructur|layoff|downgrad|miss(?:ed|es)?|underperform|weak|volatil|adverse)\b/i
  const PRO_KEYWORDS = /\b(growth|expand|lead|outperform|beat|exceed|innovat|partnership|acquisition|launch|gain|increase|invest|moat|advantage|premium|robust)\b/i
  const inferred = (f: FlatFact): 'pro' | 'contra' | 'neutral' => {
    if (f.polarity) return f.polarity
    if (f.type === 'risk') return 'contra'
    if (f.type === 'business' || f.type === 'segment') return 'pro'
    // Keyword scan on quote text (verbatim from 10-K) — most reliable
    // because LLM had no chance to muddy it.
    const txt = `${f.summary} ${f.quote ?? ''}`
    if (CONTRA_KEYWORDS.test(txt)) return 'contra'
    if (PRO_KEYWORDS.test(txt)) return 'pro'
    return 'neutral'
  }
  const factPros = all.filter(f => inferred(f) === 'pro')
  const factContras = all.filter(f => inferred(f) === 'contra')
  // Merge thesis bullets in (typed as 'thesis_bull' / 'thesis_bear')
  const pros: FlatFact[] = [
    ...thesesItems.filter(b => b.side === 'pro').map(b =>
      ({ type: 'thesis_bull', summary: b.summary, polarity: 'pro' as const })),
    ...factPros,
  ]
  const contras: FlatFact[] = [
    ...thesesItems.filter(b => b.side === 'contra').map(b =>
      ({ type: 'thesis_bear', summary: b.summary, polarity: 'contra' as const })),
    ...factContras,
  ]

  return (
    <Section title="Pro vs Contra" subtitle="anti-confirmation-bias">
      <div className="grid grid-cols-2 gap-2">
        {/* PRO column */}
        <div>
          <div className="text-[10px] text-emerald-300 mb-0.5">✓ PRO ({pros.length}):</div>
          {pros.length === 0 ? (
            <EmptyLine note="no pro evidence — actively look?" />
          ) : (
            pros.slice(0, 6).map((f, i) => (
              <div key={i} className="text-[9px] pl-1 leading-tight mb-0.5">
                <span className="text-[var(--color-dim)] mr-1">[{f.type}]</span>
                <span>{f.summary}</span>
              </div>
            ))
          )}
        </div>
        {/* CONTRA column */}
        <div>
          <div className="text-[10px] text-red-300 mb-0.5">✕ CONTRA ({contras.length}):</div>
          {contras.length === 0 ? (
            <EmptyLine note="no contra evidence — actively look?" />
          ) : (
            contras.slice(0, 6).map((f, i) => (
              <div key={i} className="text-[9px] pl-1 leading-tight mb-0.5">
                <span className="text-[var(--color-dim)] mr-1">[{f.type}]</span>
                <span>{f.summary}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </Section>
  )
}

// ── Conflict banner ──
// Each disagreement is expandable: click → reveal each scanner's
// underlying signal_event (title + severity + source URL + timestamp)
// so the user can audit which side they agree with. Honors "有根有据":
// no claim shown without one-click traversal to source.
function ConflictBanner({ ticker }: { ticker: string }) {
  const q = useTickerDisagreements(ticker)
  const resolveMu = useResolveDisagreement()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const items = q.data?.items ?? []
  if (items.length === 0) return null
  function toggle(id: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  const sevColor = (s?: string | null) =>
    s === 'high' ? 'text-red-300' :
    s === 'med'  ? 'text-amber-300' :
    'text-[var(--color-dim)]'
  const posColor = (p: string) =>
    p === 'bullish' ? 'text-emerald-300' :
    p === 'bearish' ? 'text-red-300' :
    'text-[var(--color-dim)]'
  return (
    <div className="mx-2 mt-2 mb-1 rounded border border-red-500/50 bg-red-500/10 p-2">
      <div className="flex items-center gap-1 text-[11px] font-semibold text-red-300 mb-1">
        <AlertTriangle size={11} />
        <span>{items.length} unresolved disagreement{items.length === 1 ? '' : 's'}</span>
      </div>
      {items.slice(0, 5).map(d => {
        const isOpen = expanded.has(d.disagreement_id)
        return (
          <div key={d.disagreement_id} className="text-[10px] mb-1.5 last:mb-0 border-l-2 border-red-500/40 pl-2">
            <button
              onClick={() => toggle(d.disagreement_id)}
              className="w-full flex items-baseline gap-1.5 text-left"
            >
              <span className="text-[var(--color-dim)] flex-shrink-0">{isOpen ? '▾' : '▸'}</span>
              <span className="text-[var(--color-text)] leading-tight flex-1">{d.headline}</span>
              <span className="text-[9px] text-[var(--color-dim)] flex-shrink-0">
                {fmtDate(d.detected_at)}
              </span>
            </button>
            <div className="text-[9px] text-[var(--color-dim)] mt-0.5 ml-3">
              {d.sources.map((s, i) => (
                <span key={i}>
                  {s.scanner}/<span className={posColor(s.position)}>{s.position}</span>
                  {i < d.sources.length - 1 ? ' ↔ ' : ''}
                </span>
              ))}
            </div>
            {isOpen && (
              <div className="mt-1 ml-3 space-y-1">
                {d.sources.map((s, i) => (
                  <div key={i} className="border-l border-[var(--color-border)] pl-2 py-0.5">
                    <div className="flex items-baseline gap-1 flex-wrap">
                      <span className="font-mono text-[var(--color-text)]">{s.scanner}</span>
                      <span className="text-[var(--color-dim)]">/</span>
                      <span className="font-mono text-[var(--color-text)]">{s.signal_type}</span>
                      <span className="text-[var(--color-dim)]">·</span>
                      <span className={`font-semibold ${posColor(s.position)}`}>{s.position}</span>
                      {s.severity && (
                        <span className={sevColor(s.severity)}>[{s.severity}]</span>
                      )}
                      {s.ts && (
                        <span className="text-[var(--color-dim)] ml-auto">{fmtDate(s.ts)}</span>
                      )}
                    </div>
                    {s.title && (
                      <div className="text-[var(--color-text)]/80 leading-snug">
                        {s.title}
                      </div>
                    )}
                    {s.source_url ? (
                      <a
                        href={s.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[9px] text-[var(--color-accent)] hover:underline"
                      >source ↗ {s.source_url.slice(0, 60)}…</a>
                    ) : s.event_id ? (
                      <span className="text-[9px] italic text-[var(--color-dim)]">
                        event {s.event_id.slice(0, 8)} (no source_url)
                      </span>
                    ) : (
                      <span className="text-[9px] italic text-[var(--color-dim)]">
                        original event not matched (scanner ran but no event row found within ±24h)
                      </span>
                    )}
                  </div>
                ))}
                <button
                  onClick={() => resolveMu.mutate({
                    disagreement_id: d.disagreement_id, ticker,
                    note: 'manually resolved from panel',
                  })}
                  disabled={resolveMu.isPending}
                  className="text-[9.5px] mt-1 px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] disabled:opacity-50"
                  title="标记为 resolved (你已自己评估清楚哪边对了)"
                >
                  {resolveMu.isPending ? 'resolving…' : '✓ mark resolved'}
                </button>
                {resolveMu.isError && (
                  <span className="text-[9px] text-red-300 ml-2">
                    ✗ {String((resolveMu.error as Error)?.message).slice(0, 50)}
                  </span>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Main panel ──
// ── Outside-ring discovery panel ──
// Tickers in the Outside ring aren't in the user's watchlist — so the
// usual chain sections (audit / theses / position / 10-K facts) are
// empty. Instead surface the SIGNAL-CONFLUENCE that landed it here +
// recent signals + a Promote CTA so the user can act on a fresh
// discovery candidate.
function OutsideDiscovery({
  ticker,
  node,
}: {
  ticker: string
  node: { n_outside_events?: number; n_outside_sources?: number; n_outside_high?: number; outside_latest_at?: string | null }
}) {
  const sigsQ = useRecentSignals({ ticker, limit: 12 })
  const sigs = sigsQ.data?.events ?? []
  const promoteMu = useWatchlistPromote()
  return (
    <>
      <div className="mx-2 mt-2 mb-1 rounded border border-violet-500/40 bg-violet-500/10 p-2">
        <div className="text-[11px] font-semibold text-violet-300 mb-1">
          Outside-ring discovery
        </div>
        <div className="text-[10px] text-[var(--color-text)]/80 mb-2 leading-snug">
          <b>{ticker}</b> isn't in your watchlist yet — surfaced here because{' '}
          <b>{node.n_outside_sources ?? '?'}</b> scanner sources flagged it in the last 14 days,
          including <b>{node.n_outside_high ?? 0}</b> high-severity events
          ({node.n_outside_events ?? '?'} total).
        </div>
        <div className="flex gap-1 text-[10px] items-center">
          {/* Adjacent intentionally omitted — promoting to adjacent
              requires a parent_ticker (the core whose 10-K this name
              came from), which we don't have for outside-ring discoveries.
              Add as 'watching' first; if it earns research, open the
              relevant core's drawer and use ✨ Expand from 10-K. */}
          {(['watching', 'core'] as const).map(tier => (
            <button
              key={tier}
              onClick={() => promoteMu.mutate({ ticker, tier })}
              disabled={promoteMu.isPending}
              className="px-2 py-1 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-40"
              title={`Add ${ticker} to ${tier} tier`}
            >
              + {tier}
            </button>
          ))}
          <span className="text-[9px] italic text-[var(--color-dim)] ml-1">
            (adjacent 需要先打开 core 的 drawer 用 ✨ Expand)
          </span>
          {promoteMu.isSuccess && (
            <span className="text-emerald-300 text-[10px] italic ml-1 self-center">
              promoted ✓
            </span>
          )}
          {promoteMu.isError && (
            <span className="text-red-300 text-[10px] italic ml-1 self-center">
              ✗ {String((promoteMu.error as Error)?.message).slice(0, 60)}
            </span>
          )}
        </div>
        {/* Velocity warning (Need #7 discipline) */}
        {promoteMu.isSuccess && promoteMu.data?.velocity_warning && (
          <div className="mt-1 px-2 py-1 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300 text-[9.5px] leading-snug">
            {promoteMu.data.velocity_warning}
          </div>
        )}
      </div>

      <Section title="Recent signals" subtitle="why it surfaced">
        {sigsQ.isLoading ? (
          <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
        ) : sigs.length === 0 ? (
          <EmptyLine note="no signals — outside-ring requires ≥2 sources × 14d" />
        ) : (
          sigs.map(s => (
            <div key={s.event_id} className="text-[10px] leading-tight pl-1">
              <span className="text-[var(--color-dim)] mr-1">{fmtDate(s.detected_at)}</span>
              <span className={
                s.severity === 'high' ? 'text-red-300' :
                s.severity === 'med'  ? 'text-amber-300' :
                'text-[var(--color-text)]'
              }>[{s.severity}]</span>{' '}
              <span className="text-[var(--color-text)]">{s.signal_type}</span>
              <span className="text-[var(--color-dim)] ml-1">· {s.scanner_name}</span>
              {s.title && (
                <div className="text-[9px] italic text-[var(--color-dim)] pl-1 mt-0.5">
                  {s.title.slice(0, 100)}
                </div>
              )}
            </div>
          ))
        )}
      </Section>
    </>
  )
}

// ── HeldUnwatched panel ──
// User owns the ticker (tax_lots open lot) but hasn't promoted it to any
// watchlist tier → zero research surface. This panel surfaces the
// position size + a fast-path CTA to either promote-to-research or
// close the lot.
function HeldUnwatchedPanel({
  ticker,
  node,
}: {
  ticker: string
  node: { held_qty?: number | null; held_cost?: number | null }
}) {
  const sigsQ = useRecentSignals({ ticker, limit: 8 })
  const sigs = sigsQ.data?.events ?? []
  const promoteMu = useWatchlistPromote()
  const qty = node.held_qty ?? 0
  const cost = node.held_cost ?? 0
  return (
    <>
      <div className="mx-2 mt-2 mb-1 rounded border border-red-500/50 bg-red-500/10 p-2.5">
        <div className="text-[11px] font-semibold text-red-300 mb-1 flex items-center gap-1">
          <AlertTriangle size={11} /> 持仓但未研究
        </div>
        <div className="text-[10px] text-[var(--color-text)]/90 mb-2 leading-snug">
          你拥有 <b>{qty.toFixed(0)} 股 {ticker}</b>（成本 ${cost.toLocaleString()}），
          但 <b>{ticker} 不在任何 watchlist tier 里</b> ——
          意味着<b>没有</b> 10-K facts、active thesis、exit triggers、scanner pulse。
          下个决策点（卖出/加仓/止损）你手里没数据。
        </div>
        <div className="flex gap-1 text-[10px] items-center flex-wrap">
          <span className="text-[var(--color-dim)] mr-1">加进:</span>
          {(['core', 'watching'] as const).map(tier => (
            <button
              key={tier}
              onClick={() => promoteMu.mutate({ ticker, tier })}
              disabled={promoteMu.isPending}
              className="px-2 py-1 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-40"
              title={`Add ${ticker} to ${tier} — 让研究系统开始追踪 thesis + signals + 10-K facts`}
            >
              + {tier}
            </button>
          ))}
          {promoteMu.isSuccess && (
            <span className="text-emerald-300 text-[10px] italic ml-1">promoted ✓</span>
          )}
          {promoteMu.isError && (
            <span className="text-red-300 text-[10px] italic ml-1">
              ✗ {String((promoteMu.error as Error)?.message).slice(0, 60)}
            </span>
          )}
        </div>
        <div className="text-[9px] italic text-[var(--color-dim)] mt-1.5">
          或者直接关 lot（如果只是错误录入或已经卖出）— 打开 drawer → 单笔 lot 明细 → 🗑
        </div>
      </div>

      {sigs.length > 0 && (
        <Section title="Recent signals" subtitle="scanner-emitted (no thesis to compare against yet)">
          {sigs.map(s => (
            <div key={s.event_id} className="text-[10px] leading-tight pl-1">
              <span className="text-[var(--color-dim)] mr-1">{fmtDate(s.detected_at)}</span>
              <span className={
                s.severity === 'high' ? 'text-red-300' :
                s.severity === 'med'  ? 'text-amber-300' :
                'text-[var(--color-text)]'
              }>[{s.severity}]</span>{' '}
              <span className="text-[var(--color-text)]">{s.signal_type}</span>
              <span className="text-[var(--color-dim)] ml-1">· {s.scanner_name}</span>
            </div>
          ))}
        </Section>
      )}
    </>
  )
}


export function NodeChainPanel({
  ticker,
  onClose,
  onOpenFullDetail,
  asOf,
}: {
  ticker: string
  onClose: () => void
  onOpenFullDetail?: () => void
  // Tier detection must follow the canvas's time-travel state — when
  // user pins as_of=30d, a ticker that was 'core' then but 'watching'
  // now should still show as core. Without this the panel disagreed
  // with the visual ring the user clicked on.
  asOf?: string | null
}) {
  // Detect Outside-ring tier so the panel switches into discovery
  // mode (rather than rendering five empty sections).
  const pvQ = usePortfolioView(asOf)
  const node = pvQ.data?.nodes.find(n => n.id === ticker)
  const isOutside = node?.tier === 'outside'
  const isHeldUnwatched = node?.tier === 'held_unwatched'

  return (
    <div className="flex flex-col h-full bg-[var(--color-panel)]/95 border-l border-[var(--color-border)] backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)]">
        <h2 className="text-[14px] font-semibold text-[var(--color-text)] flex-1">
          {ticker}{' '}
          <span className={`text-[10px] font-normal italic ${
            isHeldUnwatched ? 'text-red-300' : 'text-[var(--color-dim)]'
          }`}>
            {isHeldUnwatched ? '⚠ held but unwatched' : isOutside ? 'discovery' : 'chain'}
          </span>
        </h2>
        {onOpenFullDetail && (
          <button
            onClick={onOpenFullDetail}
            className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-accent)] flex items-center gap-0.5"
            title="Open full StockResearchDrawer for editing thesis/notes"
          >
            full detail <ArrowRight size={10} />
          </button>
        )}
        <button
          onClick={onClose}
          className="text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="Close chain panel (canvas deselects too)"
        >
          <X size={14} />
        </button>
      </div>

      {/* Sections (scrollable) */}
      <div className="flex-1 overflow-y-auto">
        {isOutside ? (
          <OutsideDiscovery ticker={ticker} node={node!} />
        ) : isHeldUnwatched ? (
          <HeldUnwatchedPanel ticker={ticker} node={node!} />
        ) : (
          <>
            <ConflictBanner ticker={ticker} />
            <Incoming ticker={ticker} />
            <Outgoing ticker={ticker} />
            <DecisionContext ticker={ticker} />
            <ProContra ticker={ticker} />
            <Provenance ticker={ticker} />
          </>
        )}
      </div>
    </div>
  )
}
