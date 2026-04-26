/**
 * Strategies — catalog browser over docs/strategies/strategies.yaml.
 *
 * Two-way map with the lattice (Phase 5 V4):
 *   forward:  Research call → strategy_match chip → click → land here
 *   reverse:  each strategy card shows "Used by N current L3 calls"
 *             (or "no current matches — gap?") so the user can see
 *             which catalog entries are *actually* live in today's
 *             lattice and which are dormant.
 *
 * Sort + filter so 35 entries are navigable.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDownAZ,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Filter,
  Info,
  Sparkles,
} from 'lucide-react'
import {
  useFinStrategies,
  useLatticeCalls,
  type LatticeCall,
  type StrategyEntry,
} from '@/lib/api'
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

type SortKey = 'horizon' | 'difficulty_asc' | 'min_capital_asc' | 'lattice_activity'

const SORT_LABELS: Record<SortKey, string> = {
  horizon: '按时间维度分组 (default)',
  difficulty_asc: '按难度升序',
  min_capital_asc: '按最低资金升序',
  lattice_activity: '按 lattice 当下活跃度',
}

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { project?: boolean }) => void
  /** Phase 5 V4: when set, auto-expand & scroll to the matching
   *  strategy card. Nonce re-triggers the highlight on repeat clicks. */
  focus?: { id: string; nonce: number } | null
}

const HIGHLIGHT_MS = 2500

export function StrategiesTab({ projectId, onJumpToChat, focus }: Props) {
  const q = useFinStrategies()
  const calls = useLatticeCalls(projectId)
  const [diffFilter, setDiffFilter] = useState<number | null>(null)
  const [feasibleOnly, setFeasibleOnly] = useState<boolean>(true)
  const [sortKey, setSortKey] = useState<SortKey>('horizon')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})

  // External focus (from a call's strategy_match chip): expand the
  // matching card, scroll it into view, transient highlight ring.
  useEffect(() => {
    if (!focus?.id) return
    setExpanded(focus.id)
    setHighlight(focus.id)
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

  // Reverse map: strategy_id → list of L3 calls matched to it today.
  const strategyToCalls = useMemo(() => {
    const map: Record<string, LatticeCall[]> = {}
    for (const c of calls.data?.calls ?? []) {
      const m = c.strategy_match
      if (m?.strategy_id) {
        ;(map[m.strategy_id] ??= []).push(c)
      }
    }
    return map
  }, [calls.data])

  const callsTotal = calls.data?.calls?.length ?? 0
  const callsMatched = Object.values(strategyToCalls).reduce(
    (n, arr) => n + arr.length,
    0,
  )
  const strategiesUsed = Object.keys(strategyToCalls).length

  const filteredAndSorted = useMemo(() => {
    const items = q.data?.strategies ?? []
    const filtered = items.filter((s) => {
      if (diffFilter !== null && s.difficulty !== diffFilter) return false
      if (feasibleOnly && !s.feasible_at_10k) return false
      return true
    })

    // Build (strategy, latticeUses) tuples
    const tuples = filtered.map((s) => ({
      strategy: s,
      latticeUses: strategyToCalls[s.id]?.length ?? 0,
    }))

    if (sortKey === 'horizon') {
      // Group by horizon; within each, sort by difficulty asc
      const buckets: Record<string, typeof tuples> = {}
      for (const t of tuples) {
        ;(buckets[t.strategy.horizon] ??= []).push(t)
      }
      for (const k of Object.keys(buckets)) {
        buckets[k].sort(
          (a, b) =>
            a.strategy.difficulty - b.strategy.difficulty ||
            a.strategy.id.localeCompare(b.strategy.id),
        )
      }
      return { mode: 'grouped' as const, buckets }
    }

    // Flat sort
    const sorted = [...tuples]
    if (sortKey === 'difficulty_asc') {
      sorted.sort(
        (a, b) =>
          a.strategy.difficulty - b.strategy.difficulty ||
          a.strategy.id.localeCompare(b.strategy.id),
      )
    } else if (sortKey === 'min_capital_asc') {
      sorted.sort(
        (a, b) =>
          a.strategy.min_capital_usd - b.strategy.min_capital_usd ||
          a.strategy.id.localeCompare(b.strategy.id),
      )
    } else if (sortKey === 'lattice_activity') {
      sorted.sort(
        (a, b) =>
          b.latticeUses - a.latticeUses ||
          a.strategy.difficulty - b.strategy.difficulty ||
          a.strategy.id.localeCompare(b.strategy.id),
      )
    }
    return { mode: 'flat' as const, items: sorted }
  }, [q.data, diffFilter, feasibleOnly, sortKey, strategyToCalls])

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

        {/* How this connects to Research — direct answer to user's
            'Research tab 和 Strategies tab 是怎么连起来的'. */}
        <div
          data-testid="strategies-connection-banner"
          className="mb-3 p-2.5 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 text-[10px] text-[var(--color-dim)] leading-[1.5]"
        >
          <div className="flex items-start gap-1.5">
            <Info size={12} className="mt-0.5 shrink-0 text-[var(--color-accent)]" />
            <div className="flex-1">
              <b className="text-[var(--color-text)]">How this maps to your dashboard:</b>{' '}
              Each Research-tab L3 call is run through a deterministic
              matcher (
              <code className="text-[var(--color-accent)]">
                agent.finance.lattice.strategy_matcher
              </code>
              ). When a strategy scores ≥3, it appears as a chip on the
              call. Click any chip → land here, on the focused card.
              <div className="mt-1 font-mono text-[var(--color-text)]">
                Today: <b>{callsTotal}</b> calls · <b>{callsMatched}</b> matched ·{' '}
                <b>{strategiesUsed} / {q.data?.count ?? 0}</b> strategies referenced.
                {strategiesUsed === 0 && callsTotal > 0 && (
                  <span className="text-[var(--color-amber,#e5a200)] ml-2">
                    → No matches today. Either today's themes don't fit any
                    catalog entry well (matcher threshold ≥ 3), or you
                    need more strategies of this kind. Sort by{' '}
                    <i>lattice activity</i> to see which entries DO get used.
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        <p className="text-[10px] text-[var(--color-dim)] mb-3 leading-relaxed">
          Source: <code className="text-[var(--color-accent)]">docs/strategies/strategies.yaml</code> +{' '}
          <code className="text-[var(--color-accent)]">docs/strategies/&lt;id&gt;.md</code>{' '}
          (Phase 3 subagent research, 2026-04-25). Each entry is honest about
          when it fails, US tax treatment, and PDT applicability.
        </p>

        {/* Filters + sort */}
        <div className="flex items-center gap-3 mb-4 text-[10px] text-[var(--color-dim)] flex-wrap">
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
          <span className="text-[var(--color-border)]">|</span>
          <ArrowDownAZ size={11} />
          <span>Sort:</span>
          <select
            data-testid="strategies-sort"
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text)]"
          >
            {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
              <option key={k} value={k}>
                {SORT_LABELS[k]}
              </option>
            ))}
          </select>
        </div>

        {q.isLoading && <div className="text-[var(--color-dim)]">loading…</div>}
        {q.isError && (
          <div className="text-[var(--color-red)] text-[11px]">
            failed to load: {(q.error as Error).message.slice(0, 200)}
          </div>
        )}

        {/* Render */}
        {q.data && filteredAndSorted.mode === 'grouped' && (
          <div className="flex flex-col gap-5">
            {HORIZON_ORDER.filter((h) => filteredAndSorted.buckets[h]?.length).map((h) => (
              <section key={h}>
                <div className="flex items-baseline gap-2 mb-2">
                  <h3 className="text-[12px] text-[var(--color-text)] uppercase tracking-wider">
                    {HORIZON_LABEL[h]}
                  </h3>
                  <span className="text-[9px] text-[var(--color-dim)]">
                    {filteredAndSorted.buckets[h].length} strategies
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {filteredAndSorted.buckets[h].map(({ strategy: s, latticeUses }) => (
                    <StrategyCard
                      key={s.id}
                      strategy={s}
                      latticeUses={latticeUses}
                      latticeCalls={strategyToCalls[s.id] ?? []}
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

        {q.data && filteredAndSorted.mode === 'flat' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {filteredAndSorted.items.map(({ strategy: s, latticeUses }) => (
              <StrategyCard
                key={s.id}
                strategy={s}
                latticeUses={latticeUses}
                latticeCalls={strategyToCalls[s.id] ?? []}
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
        )}
      </div>
    </div>
  )
}

function StrategyCard({
  strategy: s,
  latticeUses,
  latticeCalls,
  expanded,
  highlighted,
  registerRef,
  onToggle,
  onAsk,
}: {
  strategy: StrategyEntry
  latticeUses: number
  latticeCalls: LatticeCall[]
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

  // Reverse-mapping badge: how many current L3 calls reference this
  // strategy. None = "gap" — strategy is in catalog but not surfaced
  // by today's lattice. >0 = live.
  const usageColor =
    latticeUses > 0
      ? 'var(--color-green)'
      : 'var(--color-dim)'
  const usageLabel =
    latticeUses > 0
      ? `Live in ${latticeUses} L3 call${latticeUses === 1 ? '' : 's'} today`
      : 'No current lattice match'

  return (
    <div
      ref={registerRef}
      data-testid={`strategy-card-${s.id}`}
      data-strategy-id={s.id}
      data-source={`/api/strategies/${s.id} + /api/lattice/calls (filter strategy_match.strategy_id == ${s.id})`}
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
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-[var(--color-text)] font-medium">{s.name_zh}</span>
            <span className="text-[10px] text-[var(--color-dim)] truncate">{s.name_en}</span>
            <span
              data-testid={`lattice-usage-${s.id}`}
              data-source="/api/lattice/calls.calls[?].strategy_match.strategy_id"
              className="ml-auto text-[8px] px-1.5 py-0.5 rounded border font-mono shrink-0"
              style={{ borderColor: usageColor, color: usageColor }}
              title={
                latticeUses > 0
                  ? `Calls referencing this strategy in today's lattice:\n` +
                    latticeCalls.map((c) => `  · ${c.id}: ${c.claim.slice(0, 80)}`).join('\n')
                  : `No L3 call in today's lattice has strategy_match.strategy_id == "${s.id}". This may be a gap (data not feeding into a relevant call) or just that today's themes don't trigger this strategy.`
              }
            >
              {latticeUses > 0 ? `↳ ${latticeUses} live` : 'gap'}
            </span>
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
          {/* Reverse map: list the live L3 calls referencing this
              strategy, if any. Lets the user click through to see
              which actual recommendations grounded in this strategy. */}
          <Section
            label={`Lattice 当前引用 / Current L3 calls referencing this (${latticeUses})`}
          >
            {latticeUses === 0 ? (
              <p
                className="text-[var(--color-dim)] italic leading-[1.4]"
                title={usageLabel}
              >
                No current L3 call references this strategy. This is one
                of two things: (a) today's lattice themes don't strongly
                support this strategy (matcher threshold ≥ 3 not met),
                or (b) a real gap — the strategy is documented but the
                lattice has no widget feeding it. To investigate, look
                at the strategy's <code className="text-[var(--color-accent)]">data_requirements</code>{' '}
                below and check Research tab's L0 widget list.
              </p>
            ) : (
              <ul className="text-[var(--color-text)] flex flex-col gap-1">
                {latticeCalls.map((c) => (
                  <li
                    key={c.id}
                    className="border-l-2 border-[var(--color-accent)] pl-2 leading-[1.4]"
                  >
                    <span className="font-mono text-[var(--color-dim)] text-[8px]">
                      {c.id} · {c.confidence}/{c.time_horizon}
                    </span>
                    <div>{c.claim}</div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
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
          <Section label="数据需求 / Data requirements (provenance)">
            <ul className="text-[var(--color-dim)] flex flex-wrap gap-1">
              {s.data_requirements.map((d, i) => (
                <li
                  key={i}
                  className="font-mono text-[8px] px-1 rounded bg-[var(--color-bg)] border border-[var(--color-border)]"
                >
                  {d}
                </li>
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
                      className="text-[var(--color-accent)] hover:underline inline-flex items-center gap-1"
                    >
                      <ExternalLink size={9} />
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
              href={`/api/strategies/${s.id}`}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            >
              View raw JSON →
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
