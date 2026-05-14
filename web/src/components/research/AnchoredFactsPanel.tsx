/**
 * AnchoredFactsPanel — SEC-EDGAR-anchored research display.
 *
 * Reads /api/stock/{ticker}/anchored. Each fact carries a verbatim
 * quote from the source 10-K + a click-through URL to SEC EDGAR.
 * The whole panel is the visible counterpart to the verbatim-quote
 * trust gate: every chip you see has been verified to exist in the
 * filing it claims to come from.
 *
 * UX: chips collapsed by default. Click to expand → see verbatim
 * quote + "View source" link to SEC.
 */
import { useState } from 'react'
import {
  ShieldCheck, ExternalLink, Sparkles, Loader2, ChevronDown, ChevronRight,
  AlertTriangle, ThumbsDown, RefreshCw,
} from 'lucide-react'
import { useAnchoredFacts, useRegenAnchored, useCorrectFact } from '@/lib/api'

interface Props {
  ticker: string
  onTickerClick?: (t: string) => void
}

export function AnchoredFactsPanel({ ticker, onTickerClick }: Props) {
  const factsQ = useAnchoredFacts(ticker)
  const regenMu = useRegenAnchored()
  const isRegenForThis = regenMu.isPending && regenMu.variables === ticker

  const data = factsQ.data
  const meta = data?.meta
  const competitors = data?.facts.competitor ?? []
  const risks = data?.facts.risk ?? []
  const summary = data?.facts.business_summary ?? []
  const segments = data?.facts.segment ?? []
  const customers = data?.facts.customer ?? []
  const suppliers = data?.facts.supplier ?? []
  const total = competitors.length + risks.length + summary.length
              + segments.length + customers.length + suppliers.length

  const filingDateRel = meta?.source_filing_date
    ? new Date(meta.source_filing_date).toLocaleDateString()
    : null

  return (
    <div className="mb-4" data-testid="anchored-facts-panel">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <ShieldCheck size={14} className="text-emerald-400" />
          <h3 className="text-[12px] font-semibold text-emerald-300">
            SEC-anchored facts
          </h3>
          {total > 0 && (
            <span className="text-[10px] text-[var(--color-dim)]">
              · {total} verified from 10-K filed {filingDateRel}
            </span>
          )}
        </div>
        <button
          onClick={() => regenMu.mutate(ticker)}
          disabled={isRegenForThis}
          className="text-[10px] px-2 py-0.5 rounded border border-emerald-500/40 hover:border-emerald-400 text-emerald-300 flex items-center gap-1 disabled:opacity-50"
          title="Fetch latest 10-K from SEC EDGAR + extract competitors / risks / summary with verbatim-quote validation. ~30-60s."
        >
          {isRegenForThis
            ? <><Loader2 size={10} className="animate-spin" /> 抽取中…</>
            : <><Sparkles size={10} /> {data && total > 0 ? 're-extract' : 'extract from SEC 10-K'}</>}
        </button>
      </div>

      {factsQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2">loading…</div>
      )}

      {!factsQ.isLoading && total === 0 && !isRegenForThis && (
        <div className="text-[11px] italic text-[var(--color-dim)] py-2 leading-[1.6]">
          点上面 ✨ extract — NeoMind 会从 SEC EDGAR 拉 {ticker} 最新 10-K，
          抽取 competitors / risks / business summary, 每条带 verbatim quote。
          编出来的会被丢弃 (确定性 substring 校验)。约 30-60 秒。
        </div>
      )}

      {regenMu.error && (
        <div className="mb-2 p-2 rounded border border-red-500/40 bg-red-500/10 text-[10px] text-red-300">
          抽取失败: {(regenMu.error as Error).message}
        </div>
      )}

      {/* Per-result-set summary (post-regen) */}
      {regenMu.data && regenMu.variables === ticker && (
        <div className="mb-3 p-2 rounded border border-emerald-500/30 bg-emerald-500/5 text-[10px]">
          <div className="font-semibold text-emerald-300 mb-1">最新一次抽取结果</div>
          {Object.entries(regenMu.data.results).map(([ft, r]) => (
            <div key={ft} className="flex items-center gap-2">
              <span className="text-[var(--color-dim)] w-24">{ft}</span>
              {r.error
                ? <span className="text-red-400">✗ {r.error}</span>
                : <span>
                    <span className="text-emerald-300">{r.n_verified ?? 0} verified</span>
                    {(r.n_dropped ?? 0) > 0 && (
                      <span className="text-amber-400 ml-1.5" title={(r.drop_reasons || []).join(', ')}>
                        · {r.n_dropped} dropped
                      </span>
                    )}
                    {r.duration_ms != null && (
                      <span className="text-[var(--color-dim)] ml-1.5">({Math.round(r.duration_ms/1000)}s)</span>
                    )}
                  </span>}
            </div>
          ))}
        </div>
      )}

      {summary.length > 0 && (
        <Section title="📝 Business" defaultOpen={true}>
          <div className="space-y-1.5">
            {summary.map((s, i) => (
              <FactChip
                key={i}
                title={s.sentence}
                quote={s.evidence_quote}
                sourceUrl={s.source_url}
                sourceSection={s.source_section}
                factId={s.fact_id}
                parentTicker={ticker}
                polarity={s.polarity}
                confidence={s.confidence}
                isStale={s.is_stale}
                requiresReextract={s.requires_reextract}
              />
            ))}
          </div>
        </Section>
      )}

      {segments.length > 0 && (
        <Section title={`📊 Segments (${segments.length})`} defaultOpen={true}>
          <div className="space-y-1">
            {segments.map((s, i) => (
              <FactChip
                key={i}
                title={s.name}
                badge={s.revenue_pct != null ? `${s.revenue_pct}%` : undefined}
                subtitle={s.period || undefined}
                quote={s.evidence_quote}
                sourceUrl={s.source_url}
                sourceSection={s.source_section}
                factId={s.fact_id}
                parentTicker={ticker}
                polarity={s.polarity}
                confidence={s.confidence}
                isStale={s.is_stale}
                requiresReextract={s.requires_reextract}
              />
            ))}
          </div>
        </Section>
      )}

      {competitors.length > 0 && (
        <Section title={`⚔ Competitors (${competitors.length})`} defaultOpen={true}>
          <div className="space-y-1">
            {competitors.map((c, i) => (
              <FactChip
                key={i}
                title={c.name}
                ticker={c.ticker || undefined}
                quote={c.evidence_quote}
                sourceUrl={c.source_url}
                sourceSection={c.source_section}
                onTickerClick={onTickerClick}
                factId={c.fact_id}
                parentTicker={ticker}
                polarity={c.polarity}
                confidence={c.confidence}
                isStale={c.is_stale}
                requiresReextract={c.requires_reextract}
              />
            ))}
          </div>
        </Section>
      )}

      {customers.length > 0 && (
        <Section title={`👥 Customers (${customers.length})`} defaultOpen={true}>
          <div className="space-y-1">
            {customers.map((c, i) => (
              <FactChip
                key={i}
                title={c.name}
                ticker={c.ticker || undefined}
                badge={c.concentration_pct != null ? `${c.concentration_pct}%` : undefined}
                quote={c.evidence_quote}
                sourceUrl={c.source_url}
                sourceSection={c.source_section}
                onTickerClick={onTickerClick}
                factId={c.fact_id}
                parentTicker={ticker}
                polarity={c.polarity}
                confidence={c.confidence}
                isStale={c.is_stale}
                requiresReextract={c.requires_reextract}
              />
            ))}
          </div>
        </Section>
      )}

      {suppliers.length > 0 && (
        <Section title={`🏭 Suppliers (${suppliers.length})`} defaultOpen={true}>
          <div className="space-y-1">
            {suppliers.map((s, i) => (
              <FactChip
                key={i}
                title={s.name}
                ticker={s.ticker || undefined}
                badge={s.criticality || undefined}
                quote={s.evidence_quote}
                sourceUrl={s.source_url}
                sourceSection={s.source_section}
                onTickerClick={onTickerClick}
                factId={s.fact_id}
                parentTicker={ticker}
                polarity={s.polarity}
                confidence={s.confidence}
                isStale={s.is_stale}
                requiresReextract={s.requires_reextract}
              />
            ))}
          </div>
        </Section>
      )}

      {risks.length > 0 && (
        <Section title={`⚠ Risks (${risks.length})`} defaultOpen={false}>
          <div className="space-y-1">
            {risks.map((r, i) => (
              <FactChip
                key={i}
                title={r.headline}
                badge={r.category}
                severity={r.severity_signal || undefined}
                quote={r.evidence_quote}
                sourceUrl={r.source_url}
                sourceSection={r.source_section}
                factId={r.fact_id}
                parentTicker={ticker}
                polarity={r.polarity}
                confidence={r.confidence}
                isStale={r.is_stale}
                requiresReextract={r.requires_reextract}
              />
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}

function Section({
  title, defaultOpen = true, children,
}: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen(!open)}
        className="text-[11px] font-semibold text-[var(--color-text)] flex items-center gap-1 mb-1 hover:opacity-80"
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {title}
      </button>
      {open && children}
    </div>
  )
}

function FactChip({
  title, ticker, quote, sourceUrl, sourceSection, badge, severity, subtitle, onTickerClick,
  // Phase W (2026-05-10) Pillar 2 additions
  factId,
  parentTicker,
  polarity,
  confidence,
  isStale,
  requiresReextract,
}: {
  title: string
  ticker?: string
  quote: string
  sourceUrl: string
  sourceSection?: string
  badge?: string
  severity?: string
  subtitle?: string
  onTickerClick?: (t: string) => void
  factId?: number
  parentTicker?: string  // owning ticker, needed for cache invalidation on 👎
  polarity?: 'pro' | 'contra' | 'neutral' | null
  confidence?: number | null
  isStale?: boolean
  requiresReextract?: boolean
}) {
  const [open, setOpen] = useState(false)
  const correctMu = useCorrectFact()
  const sevColor =
    severity === 'high'  ? 'text-red-400 border-red-500/40' :
    severity === 'medium'? 'text-amber-300 border-amber-500/40' :
    'text-[var(--color-dim)] border-[var(--color-border)]'

  // Phase W: visual encoding
  // - polarity → left border accent (green pro / red contra / gray neutral)
  // - confidence → opacity (low confidence = faded)
  // - is_stale → amber warning icon
  // - requires_reextract → strikethrough + dim
  const polarityBorder =
    polarity === 'pro'    ? 'border-l-2 border-l-emerald-500/70' :
    polarity === 'contra' ? 'border-l-2 border-l-red-500/70' :
                            ''
  const confidenceOpacity = confidence != null && confidence < 0.5
    ? 'opacity-60'    // <50% confidence = visibly faded
    : ''
  const flaggedClass = requiresReextract
    ? 'opacity-40 line-through decoration-amber-500/70 decoration-dotted'
    : ''

  function handleThumbsDown(ev: React.MouseEvent) {
    ev.stopPropagation()
    if (!factId || !parentTicker) return
    const note = prompt(
      `把这条 fact 标为错误? (后续 re-extract 会跳过它)\n` +
      `可选: 输入 "为什么错" 一句话 (会记录在 fact_corrections):`,
      '',
    )
    if (note === null) return  // user cancelled
    correctMu.mutate(
      {
        fact_id: factId,
        ticker: parentTicker,
        user_action: 'mark_wrong',
        user_note: note.trim() || undefined,
      },
      {
        onError: (err) => alert(`mark wrong failed: ${err.message}`),
      },
    )
  }

  return (
    <div className={`border border-[var(--color-border)]/40 rounded ${polarityBorder} ${confidenceOpacity} ${flaggedClass}`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-2 py-1.5 flex items-center gap-2 hover:bg-[var(--color-panel)]/40"
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {ticker && (
          <button
            data-testid={`anchored-ticker-${ticker}`}
            onClick={(e) => { e.stopPropagation(); onTickerClick?.(ticker) }}
            className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-accent)]/15 border border-[var(--color-accent)]/40 text-[var(--color-accent)] font-mono hover:bg-[var(--color-accent)]/25"
          >
            {ticker}
          </button>
        )}
        <span className="text-[11px] flex-1">
          {title}
          {subtitle && <span className="text-[9px] text-[var(--color-dim)] ml-1.5">· {subtitle}</span>}
        </span>
        {/* Phase W: stale/reextract icons */}
        {isStale && (
          <span className="text-amber-400" title="Source 10-K filed > 18 months ago — content may be outdated">
            <AlertTriangle size={10} />
          </span>
        )}
        {requiresReextract && (
          <span className="text-amber-400" title="Flagged for re-extract (model bumped or user marked wrong)">
            <RefreshCw size={10} />
          </span>
        )}
        {badge && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${sevColor}`}>
            {badge}{severity && severity !== 'medium' ? ` · ${severity}` : ''}
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 pb-2 pt-0.5 border-t border-[var(--color-border)]/30 bg-[var(--color-bg)]/30">
          <div className="text-[10px] text-[var(--color-dim)] mb-1 flex items-center gap-2 flex-wrap">
            <span>verbatim from {sourceSection ?? '10-K'}:</span>
            {polarity && polarity !== 'neutral' && (
              <span className={`px-1 rounded text-[8.5px] uppercase tracking-wider ${
                polarity === 'pro' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'
              }`}>
                {polarity === 'pro' ? '✅ pro' : '❌ contra'}
              </span>
            )}
            {confidence != null && (
              <span className="text-[var(--color-dim)]">
                conf {(confidence * 100).toFixed(0)}%
              </span>
            )}
            {isStale && (
              <span className="text-amber-400">⚠ source 10-K stale</span>
            )}
          </div>
          <blockquote className="text-[11px] italic text-[var(--color-text)]/85 border-l-2 border-emerald-500/40 pl-2 py-0.5 mb-1.5 leading-snug">
            "{quote}"
          </blockquote>
          <div className="flex items-center gap-3 flex-wrap">
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] text-emerald-400 hover:text-emerald-300 inline-flex items-center gap-0.5"
            >
              View on SEC EDGAR <ExternalLink size={9} />
            </a>
            {factId && parentTicker && (
              <button
                onClick={handleThumbsDown}
                disabled={correctMu.isPending}
                title="标记这条 fact 错误 (会被 hide + 触发 re-extract)"
                className="text-[10px] text-[var(--color-dim)] hover:text-red-300 inline-flex items-center gap-0.5 disabled:opacity-40"
              >
                <ThumbsDown size={9} /> mark wrong
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
