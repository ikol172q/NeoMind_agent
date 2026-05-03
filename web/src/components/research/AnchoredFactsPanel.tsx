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
import { ShieldCheck, ExternalLink, Sparkles, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { useAnchoredFacts, useRegenAnchored } from '@/lib/api'

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
  const total = competitors.length + risks.length + summary.length

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
  title, ticker, quote, sourceUrl, sourceSection, badge, severity, onTickerClick,
}: {
  title: string
  ticker?: string
  quote: string
  sourceUrl: string
  sourceSection?: string
  badge?: string
  severity?: string
  onTickerClick?: (t: string) => void
}) {
  const [open, setOpen] = useState(false)
  const sevColor =
    severity === 'high'  ? 'text-red-400 border-red-500/40' :
    severity === 'medium'? 'text-amber-300 border-amber-500/40' :
    'text-[var(--color-dim)] border-[var(--color-border)]'
  return (
    <div className="border border-[var(--color-border)]/40 rounded">
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
        <span className="text-[11px] flex-1">{title}</span>
        {badge && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${sevColor}`}>
            {badge}{severity && severity !== 'medium' ? ` · ${severity}` : ''}
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 pb-2 pt-0.5 border-t border-[var(--color-border)]/30 bg-[var(--color-bg)]/30">
          <div className="text-[10px] text-[var(--color-dim)] mb-1">verbatim from {sourceSection ?? '10-K'}:</div>
          <blockquote className="text-[11px] italic text-[var(--color-text)]/85 border-l-2 border-emerald-500/40 pl-2 py-0.5 mb-1.5 leading-snug">
            "{quote}"
          </blockquote>
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-emerald-400 hover:text-emerald-300 inline-flex items-center gap-0.5"
          >
            View on SEC EDGAR <ExternalLink size={9} />
          </a>
        </div>
      )}
    </div>
  )
}
