/**
 * Strategies — catalog browser over docs/strategies/strategies.yaml.
 *
 * Reads /api/strategies (Phase 3 subagent output, 35 entries spanning
 * long-term / mid-term / short-term / defined-risk options / crypto /
 * China-via-US ETFs). Grouped by horizon, with filters for difficulty
 * and "$10k feasibility" (the user's stated capital tier).
 *
 * Click a strategy to expand: starter step (literal week-1 to-do),
 * key risks, tax notes, and an "ask the agent" button that drops a
 * pre-filled prompt into Chat.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Filter, Sparkles } from 'lucide-react'
import { useFinStrategies, type StrategyEntry } from '@/lib/api'
import { cn } from '@/lib/utils'

const HORIZON_ORDER: StrategyEntry['horizon'][] = [
  'long_term',
  'months',
  'weeks',
  'swing',
  'days',
  'intraday',
]

const HORIZON_LABEL: Record<StrategyEntry['horizon'], string> = {
  long_term: '长期 / Long-term',
  months: '中期 (months) / Multi-month',
  weeks: '中期 (weeks) / Multi-week',
  swing: '中期 (swing) / Swing',
  days: '短期 (days) / Multi-day',
  intraday: '日内 / Intraday',
}

interface Props {
  onJumpToChat?: (prompt: string, ctx?: { project?: boolean }) => void
  /** Phase 5 V4: when set, auto-expand & scroll to the matching
   *  strategy card. Nonce re-triggers the highlight on repeat clicks. */
  focus?: { id: string; nonce: number } | null
}

const HIGHLIGHT_MS = 2500

export function StrategiesTab({ onJumpToChat, focus }: Props) {
  const q = useFinStrategies()
  const [diffFilter, setDiffFilter] = useState<number | null>(null)
  const [feasibleOnly, setFeasibleOnly] = useState<boolean>(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})

  // External focus (from a call's strategy_match chip): expand the
  // matching card, scroll it into view, transient highlight ring.
  useEffect(() => {
    if (!focus?.id) return
    setExpanded(focus.id)
    setHighlight(focus.id)
    // Filters might be hiding the focused strategy — relax them so
    // the user actually sees the card they navigated to.
    setDiffFilter(null)
    setFeasibleOnly(false)
    const t = window.setTimeout(() => {
      const el = cardRefs.current[focus.id]
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 80)
    const t2 = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS)
    return () => {
      window.clearTimeout(t)
      window.clearTimeout(t2)
    }
  }, [focus?.id, focus?.nonce])

  const grouped = useMemo(() => {
    const items = q.data?.strategies ?? []
    const filtered = items.filter((s) => {
      if (diffFilter !== null && s.difficulty !== diffFilter) return false
      if (feasibleOnly && !s.feasible_at_10k) return false
      return true
    })
    const buckets: Record<string, StrategyEntry[]> = {}
    for (const s of filtered) {
      ;(buckets[s.horizon] ??= []).push(s)
    }
    for (const k of Object.keys(buckets)) {
      buckets[k].sort((a, b) => a.difficulty - b.difficulty || a.id.localeCompare(b.id))
    }
    return buckets
  }, [q.data, diffFilter, feasibleOnly])

  return (
    <div className="h-full overflow-y-auto p-4 text-[12px]">
      <div className="max-w-[1100px] mx-auto">
        {/* Header */}
        <div className="flex items-baseline gap-3 mb-2">
          <h2 className="text-[15px] text-[var(--color-text)] font-semibold">
            投资策略目录 · Strategies
          </h2>
          <span className="text-[10px] text-[var(--color-dim)]">
            {q.data ? `${q.data.count} strategies` : 'loading…'}
          </span>
        </div>
        <p className="text-[11px] text-[var(--color-dim)] mb-4 leading-relaxed">
          Catalog of investment methods accessible to a personal investor
          (~$10k starting capital). Each entry is honest about{' '}
          <i>when it fails</i>, US tax treatment, and PDT applicability.
          Source: <code className="text-[var(--color-accent)]">docs/strategies/strategies.yaml</code> +
          per-strategy markdown files.
        </p>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-4 text-[10px] text-[var(--color-dim)]">
          <Filter size={11} />
          <span>Filter:</span>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={feasibleOnly}
              onChange={(e) => setFeasibleOnly(e.target.checked)}
            />
            <span>$10k 可行的</span>
          </label>
          <span className="text-[var(--color-border)]">|</span>
          <span>Difficulty:</span>
          <button
            className={cn(
              'px-1.5 py-0.5 rounded border',
              diffFilter === null
                ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                : 'border-[var(--color-border)] text-[var(--color-dim)]',
            )}
            onClick={() => setDiffFilter(null)}
          >
            all
          </button>
          {[1, 2, 3, 4, 5].map((d) => (
            <button
              key={d}
              className={cn(
                'px-1.5 py-0.5 rounded border',
                diffFilter === d
                  ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                  : 'border-[var(--color-border)] text-[var(--color-dim)]',
              )}
              onClick={() => setDiffFilter(d)}
            >
              {d}★
            </button>
          ))}
        </div>

        {q.isLoading && <div className="text-[var(--color-dim)]">loading…</div>}
        {q.isError && (
          <div className="text-[var(--color-red)] text-[11px]">
            failed to load: {(q.error as Error).message.slice(0, 200)}
          </div>
        )}

        {/* Grouped lanes */}
        {q.data && (
          <div className="flex flex-col gap-5">
            {HORIZON_ORDER.filter((h) => grouped[h]?.length).map((h) => (
              <section key={h}>
                <div className="flex items-baseline gap-2 mb-2">
                  <h3 className="text-[12px] text-[var(--color-text)] uppercase tracking-wider">
                    {HORIZON_LABEL[h]}
                  </h3>
                  <span className="text-[9px] text-[var(--color-dim)]">
                    {grouped[h].length} strategies
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {grouped[h].map((s) => (
                    <StrategyCard
                      key={s.id}
                      strategy={s}
                      expanded={expanded === s.id}
                      highlighted={highlight === s.id}
                      registerRef={(el) => { cardRefs.current[s.id] = el }}
                      onToggle={() => setExpanded(expanded === s.id ? null : s.id)}
                      onAsk={() =>
                        onJumpToChat?.(
                          `Tell me how to actually start using "${s.name_en}" (id: ${s.id}) in my account this week. Account: ~$10k, US-based. Walk me through step-by-step what to do and what to watch out for.`,
                          { project: true },
                        )
                      }
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StrategyCard({
  strategy: s,
  expanded,
  highlighted,
  registerRef,
  onToggle,
  onAsk,
}: {
  strategy: StrategyEntry
  expanded: boolean
  highlighted?: boolean
  registerRef?: (el: HTMLDivElement | null) => void
  onToggle: () => void
  onAsk: () => void
}) {
  const stars = '★'.repeat(s.difficulty) + '☆'.repeat(5 - s.difficulty)
  const taxColor = {
    low: 'var(--color-green)',
    medium: 'var(--color-amber,#e5a200)',
    high: 'var(--color-red)',
  }[s.tax_treatment.wash_sale_risk]
  return (
    <div
      ref={registerRef}
      data-testid={`strategy-card-${s.id}`}
      data-highlighted={highlighted ? 'true' : undefined}
      className={cn(
        "border rounded bg-[var(--color-panel)] hover:border-[var(--color-accent)]/50 transition",
        highlighted
          ? "border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]/40"
          : "border-[var(--color-border)]",
      )}
    >
      <button
        onClick={onToggle}
        className="w-full text-left px-3 py-2 flex items-start gap-2"
      >
        <span className="text-[var(--color-dim)] mt-0.5">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-[var(--color-text)] font-medium">{s.name_zh}</span>
            <span className="text-[10px] text-[var(--color-dim)] truncate">{s.name_en}</span>
          </div>
          <div className="flex items-center gap-2 mt-1 text-[9px] text-[var(--color-dim)] flex-wrap">
            <span className="text-[var(--color-amber,#e5a200)]">{stars}</span>
            <span>·</span>
            <span>≥${s.min_capital_usd.toLocaleString()}</span>
            <span>·</span>
            <span>{s.asset_class}</span>
            {s.pdt_relevant && (
              <>
                <span>·</span>
                <span className="text-[var(--color-amber,#e5a200)]">PDT</span>
              </>
            )}
            {s.defined_risk && (
              <>
                <span>·</span>
                <span className="text-[var(--color-green)]">defined-risk</span>
              </>
            )}
            <span>·</span>
            <span style={{ color: taxColor }} title={`wash sale risk: ${s.tax_treatment.wash_sale_risk}`}>
              wash:{s.tax_treatment.wash_sale_risk}
            </span>
            {s.tax_treatment.section_1256 && (
              <>
                <span>·</span>
                <span className="text-[var(--color-blue,#5fa8ff)]">§1256</span>
              </>
            )}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-[var(--color-border)] flex flex-col gap-2 text-[10px]">
          <Section label="第一周怎么开始 / Week 1 starter">
            <p className="text-[var(--color-text)] leading-relaxed">{s.starter_step}</p>
          </Section>
          <Section label="主要风险 / Key risks">
            <ul className="list-disc list-inside text-[var(--color-dim)] leading-relaxed">
              {s.key_risks.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </Section>
          <Section label="税务 / Tax">
            <div className="text-[var(--color-dim)] leading-relaxed">
              <span style={{ color: taxColor }}>wash sale risk: {s.tax_treatment.wash_sale_risk}</span>
              {s.tax_treatment.section_1256 && (
                <span className="ml-2 text-[var(--color-blue,#5fa8ff)]">§1256 (60/40)</span>
              )}
              {s.tax_treatment.qualifies_long_term ? (
                <span className="ml-2">eligible for long-term holding</span>
              ) : (
                <span className="ml-2">always short-term</span>
              )}
              {s.tax_treatment.notes && (
                <div className="mt-1 italic">{s.tax_treatment.notes}</div>
              )}
            </div>
          </Section>
          <Section label="$10k 可行性 / $10k feasibility">
            <p className="text-[var(--color-dim)]">{s.feasible_at_10k_reason}</p>
          </Section>
          <Section label="历史胜率 / Typical win rate">
            <p className="text-[var(--color-dim)]">{s.typical_win_rate}</p>
          </Section>
          <Section label="最大亏损 / Max loss">
            <p className="text-[var(--color-dim)] font-mono">{s.max_loss}</p>
          </Section>
          {s.sources.length > 0 && (
            <Section label="参考 / Sources">
              <ul className="text-[9px] text-[var(--color-dim)]">
                {s.sources.slice(0, 5).map((u, i) => (
                  <li key={i} className="truncate">
                    <a
                      href={u}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--color-accent)] hover:underline"
                    >
                      {u}
                    </a>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={onAsk}
              className="inline-flex items-center gap-1 px-2 py-1 rounded border border-[var(--color-accent)] text-[var(--color-accent)] text-[10px] hover:bg-[var(--color-accent)]/10"
            >
              <Sparkles size={10} />
              Ask the agent
            </button>
            <a
              href={`/docs/strategies/${s.id}.md`}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            >
              Open full markdown →
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[8px] uppercase tracking-wider text-[var(--color-dim)] mb-0.5">
        {label}
      </div>
      {children}
    </div>
  )
}
