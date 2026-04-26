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
  useFinStrategiesFit,
  useFinStrategiesTimeAware,
  useFinWidgetCoverage,
  useLatticeCalls,
  useLatticeLanguage,
  useWidgetStrategies,
  type LatticeCall,
  type StrategyEntry,
  type StrategyFitEntry,
  type StrategyTimeAware,
  type StrategyWidgetCoverage,
  type WidgetMeta,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { HoverPopover } from '@/components/widgets/HoverPopover'

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

type SortKey =
  | 'today_fit'
  | 'horizon'
  | 'difficulty_asc'
  | 'min_capital_asc'
  | 'lattice_activity'

const SORT_LABELS: Record<SortKey, string> = {
  today_fit: '按今日相关度 (recommended when no L3 calls)',
  horizon: '按时间维度分组',
  difficulty_asc: '按难度升序',
  min_capital_asc: '按最低资金升序',
  lattice_activity: '按 lattice L3-call 引用数',
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
  const fit = useFinStrategiesFit(projectId)
  const coverage = useFinWidgetCoverage()
  // Phase 6 followup #2: time-aware events per strategy (FOMC,
  // quad-witching, Russell rebal, earnings season).
  const timeAware = useFinStrategiesTimeAware(projectId)
  // Phase 6 followup #3: bilingual one-button — pick lang for
  // every name_en / name_zh render below based on global toggle.
  const lang = useLatticeLanguage()
  const activeLang = lang.data?.active
  const [diffFilter, setDiffFilter] = useState<number | null>(null)
  const [feasibleOnly, setFeasibleOnly] = useState<boolean>(true)
  // Default to today_fit sort — answers 'what's relevant right now?'
  // even on days the lattice produces zero L3 calls.
  const [sortKey, setSortKey] = useState<SortKey>('today_fit')
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

  // Theme-level fit score per strategy (0-10). Same matcher logic as
  // L3-call tagging, but run against today's L2 themes' aggregate tags
  // — so we have a signal even on no-L3-calls days.
  const fitByStrategy = useMemo(() => {
    const map: Record<string, StrategyFitEntry> = {}
    for (const f of fit.data?.fit ?? []) {
      map[f.strategy_id] = f
    }
    return map
  }, [fit.data])

  // Phase 6 followup #2: time-aware events per strategy.
  const timeAwareById = useMemo(() => {
    const map: Record<string, StrategyTimeAware> = {}
    for (const t of timeAware.data?.entries ?? []) {
      map[t.id] = t
    }
    return map
  }, [timeAware.data])

  // Phase 6 Step 4: widget coverage per strategy (forward bidirectional map).
  const coverageByStrategy = useMemo(() => {
    const map: Record<string, StrategyWidgetCoverage> = {}
    for (const c of coverage.data?.strategies ?? []) {
      map[c.id] = c
    }
    return map
  }, [coverage.data])

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

    // Build (strategy, latticeUses, todayFit) tuples
    const tuples = filtered.map((s) => ({
      strategy: s,
      latticeUses: strategyToCalls[s.id]?.length ?? 0,
      todayFit: fitByStrategy[s.id]?.score ?? 0,
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
    } else if (sortKey === 'today_fit') {
      sorted.sort(
        (a, b) =>
          b.todayFit - a.todayFit ||
          b.latticeUses - a.latticeUses ||
          a.strategy.difficulty - b.strategy.difficulty ||
          a.strategy.id.localeCompare(b.strategy.id),
      )
    }
    return { mode: 'flat' as const, items: sorted }
  }, [q.data, diffFilter, feasibleOnly, sortKey, strategyToCalls, fitByStrategy])

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
                Today: <b>{callsTotal}</b> L3 calls · <b>{callsMatched}</b> matched ·{' '}
                <b>{strategiesUsed} / {q.data?.count ?? 0}</b> strategies referenced.
                {callsTotal === 0 && (
                  <span className="text-[var(--color-amber,#e5a200)] ml-2">
                    → No L3 calls today (lattice didn't reach high-conviction
                    threshold). Even so, the matcher scored every strategy
                    against today's themes — see <i>Today's relevance</i>{' '}
                    column / sort for which strategies DO align with today's
                    data.
                  </span>
                )}
                {strategiesUsed === 0 && callsTotal > 0 && (
                  <span className="text-[var(--color-amber,#e5a200)] ml-2">
                    → No L3 call passed the matcher's score-≥3 threshold.
                    Sort by 'today_fit' to see weakly-aligned strategies anyway.
                  </span>
                )}
              </div>
              {fit.data && (
                <div className="mt-1.5 text-[10px] text-[var(--color-dim)]">
                  Top 5 by today's themes fit:{' '}
                  {fit.data.fit.slice(0, 5).map((f, i) => (
                    <span key={f.strategy_id} className="font-mono">
                      {i > 0 && <span className="text-[var(--color-border)]"> · </span>}
                      <span style={{ color: f.score >= 5 ? 'var(--color-green)' : f.score >= 1 ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)' }}>
                        {f.strategy_id} ({f.score})
                      </span>
                    </span>
                  ))}
                </div>
              )}
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
                  {filteredAndSorted.buckets[h].map(({ strategy: s, latticeUses, todayFit }) => (
                    <StrategyCard
                      key={s.id}
                      strategy={s}
                      latticeUses={latticeUses}
                      latticeCalls={strategyToCalls[s.id] ?? []}
                      todayFit={todayFit}
                      todayFitBreakdown={fitByStrategy[s.id]?.score_breakdown}
                      widgetCoverage={coverageByStrategy[s.id]}
                      timeAware={timeAwareById[s.id]}
                      activeLang={activeLang}
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
            {filteredAndSorted.items.map(({ strategy: s, latticeUses, todayFit }) => (
              <StrategyCard
                key={s.id}
                strategy={s}
                latticeUses={latticeUses}
                latticeCalls={strategyToCalls[s.id] ?? []}
                todayFit={todayFit}
                todayFitBreakdown={fitByStrategy[s.id]?.score_breakdown}
                widgetCoverage={coverageByStrategy[s.id]}
                timeAware={timeAwareById[s.id]}
                activeLang={activeLang}
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
  todayFit,
  todayFitBreakdown,
  widgetCoverage,
  timeAware,
  activeLang,
  expanded,
  highlighted,
  registerRef,
  onToggle,
  onAsk,
}: {
  strategy: StrategyEntry
  latticeUses: number
  latticeCalls: LatticeCall[]
  todayFit: number
  todayFitBreakdown?: Record<string, number>
  widgetCoverage?: StrategyWidgetCoverage
  timeAware?: StrategyTimeAware
  activeLang?: 'en' | 'zh-CN-mixed'
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
            {/* Phase 6 followup #3: bilingual one-button switch — when
                active is en, show only EN; when zh, show only ZH; when
                undefined (loading) show both like before. */}
            {activeLang === 'en' ? (
              <span className="text-[var(--color-text)] font-medium">{s.name_en}</span>
            ) : activeLang === 'zh-CN-mixed' ? (
              <span className="text-[var(--color-text)] font-medium">{s.name_zh}</span>
            ) : (
              <>
                <span className="text-[var(--color-text)] font-medium">{s.name_zh}</span>
                <span className="text-[10px] text-[var(--color-dim)] truncate">{s.name_en}</span>
              </>
            )}
            {/* Phase 6 followup #2: time-aware urgency chip — fires for
                event-driven strategies (FOMC, quad witching, Russell
                rebal, earnings season). Always-on strategies have no
                chip. Color escalates as event approaches. */}
            {timeAware?.days_until != null && timeAware.event_label && (
              <TimeAwareChip ta={timeAware} activeLang={activeLang} />
            )}
            {/* Today's fit chip — same matcher, score against today's
                themes. Always present (even on no-L3-call days). */}
            <span
              data-testid={`today-fit-${s.id}`}
              data-source="/api/strategies/lattice-fit.fit[?].score"
              className="ml-auto text-[8px] px-1.5 py-0.5 rounded border font-mono shrink-0"
              style={{
                borderColor: todayFit >= 5 ? 'var(--color-green)' : todayFit >= 1 ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)',
                color: todayFit >= 5 ? 'var(--color-green)' : todayFit >= 1 ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)',
              }}
              title={
                `Today's theme-level fit score (0-10): ${todayFit}\n` +
                (todayFitBreakdown
                  ? `breakdown: ${JSON.stringify(todayFitBreakdown)}\n`
                  : '') +
                `Same matcher as the L3-call chip, run against today's L2 themes' aggregate tags. ` +
                `Refreshes when the lattice rebuilds.`
              }
            >
              fit {todayFit}/10
            </span>
            {/* L3-call usage chip — only present when ≥1 real call grounds in this strategy. */}
            {latticeUses > 0 && (
              <span
                data-testid={`lattice-usage-${s.id}`}
                data-source="/api/lattice/calls.calls[?].strategy_match.strategy_id"
                className="text-[8px] px-1.5 py-0.5 rounded border font-mono shrink-0"
                style={{ borderColor: usageColor, color: usageColor }}
                title={
                  `Calls referencing this strategy in today's lattice:\n` +
                  latticeCalls.map((c) => `  · ${c.id}: ${c.claim.slice(0, 80)}`).join('\n')
                }
              >
                ↳ {latticeUses} live
              </span>
            )}
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
          <Section label="数据需求 / Data requirements (lattice widget mapping)">
            {widgetCoverage ? (
              <div className="flex flex-col gap-1">
                {/* widget chips with status badges */}
                <div className="flex flex-wrap gap-1">
                  {widgetCoverage.widgets.map((w) => (
                    <WidgetChip key={w.id} widget={w} />
                  ))}
                </div>
                {/* coverage summary */}
                <div className="text-[9px] text-[var(--color-dim)] mt-0.5">
                  <span className="text-[var(--color-green)]">{widgetCoverage.available_count} available</span>
                  {' · '}
                  <span style={{ color: widgetCoverage.planned_count > 0 ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)' }}>
                    {widgetCoverage.planned_count} planned (gap)
                  </span>
                  {widgetCoverage.unresolved.length > 0 && (
                    <>
                      {' · '}
                      <span className="text-[var(--color-red)]">
                        {widgetCoverage.unresolved.length} unresolved: {widgetCoverage.unresolved.join(', ')}
                      </span>
                    </>
                  )}
                </div>
                {/* Free-text equivalent shown as secondary line for human-readable context */}
                <details className="mt-0.5">
                  <summary className="text-[8px] uppercase tracking-wider text-[var(--color-dim)] cursor-pointer hover:text-[var(--color-text)]">
                    show free-text source
                  </summary>
                  <ul className="text-[var(--color-dim)] flex flex-wrap gap-1 mt-1">
                    {widgetCoverage.free_text_requirements.map((d, i) => (
                      <li
                        key={i}
                        className="font-mono text-[8px] px-1 rounded bg-[var(--color-bg)] border border-[var(--color-border)] italic"
                      >
                        {d}
                      </li>
                    ))}
                  </ul>
                </details>
              </div>
            ) : (
              // Fallback: data not loaded yet, show free-text
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
            )}
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

/**
 * WidgetChip — Phase 6 Step 5. Renders one L0 widget data-requirement
 * with status icon (✓ available / ⚠ planned / ? unknown), color-coded
 * border, and tooltip with full description. Click jumps to lattice
 * graph viewer focused on that widget (Step 6).
 */
function WidgetChip({ widget }: { widget: WidgetMeta }) {
  const statusColor =
    widget.status === 'available'
      ? 'var(--color-green)'
      : widget.status === 'planned'
        ? 'var(--color-amber,#e5a200)'
        : 'var(--color-dim)'
  const icon =
    widget.status === 'available' ? '✓' : widget.status === 'planned' ? '⚠' : '·'

  // Phase 6 followup #6: hover-to-drill — replace the bare native
  // tooltip with a rich popover that shows the description AND the
  // reverse map ('also used by N other strategies'). Closes the
  // 'click chip → switch tab → look at it' instruction loop.
  return (
    <HoverPopover
      width={320}
      delay={300}
      dataTestid={`widget-chip-${widget.id}`}
      content={() => <WidgetChipPopover widget={widget} />}
    >
      <span
        data-widget-id={widget.id}
        data-source={`/api/lattice/widgets/${widget.id}`}
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[8px] font-mono cursor-help"
        style={{ borderColor: statusColor, color: statusColor }}
      >
        <span>{icon}</span>
        <span>{widget.id}</span>
      </span>
    </HoverPopover>
  )
}


/** Popover body for WidgetChip — fetches the reverse map lazily on
 *  first hover, so we don't fire 50× /strategies queries on tab open. */
function WidgetChipPopover({ widget }: { widget: WidgetMeta }) {
  const reverse = useWidgetStrategies(widget.id)
  const statusColor =
    widget.status === 'available'
      ? 'var(--color-green)'
      : widget.status === 'planned'
        ? 'var(--color-amber,#e5a200)'
        : 'var(--color-dim)'
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span
          className="px-1 rounded font-mono text-[9px]"
          style={{ borderColor: statusColor, color: statusColor, border: `1px solid ${statusColor}` }}
        >
          {widget.status}
        </span>
        <span className="font-mono text-[10px] text-[var(--color-text)]">{widget.id}</span>
      </div>
      <div className="text-[10px] text-[var(--color-text)]">
        {widget.label_en ?? widget.id}
        {widget.label_zh ? <span className="text-[var(--color-dim)]"> · {widget.label_zh}</span> : null}
      </div>
      {widget.description && (
        <div className="text-[9.5px] text-[var(--color-dim)] leading-snug">
          {widget.description}
        </div>
      )}
      <div className="text-[9px] text-[var(--color-dim)] mt-0.5">
        {reverse.isLoading ? (
          <span className="italic">checking other strategies…</span>
        ) : reverse.data ? (
          <>
            Also needed by{' '}
            <span className="text-[var(--color-text)]">{reverse.data.strategy_count}</span>
            {' '}other catalog{' '}
            {reverse.data.strategy_count === 1 ? 'strategy' : 'strategies'}.
            {reverse.data.strategy_count > 0 && (
              <div className="flex flex-wrap gap-0.5 mt-1">
                {reverse.data.strategies.slice(0, 6).map((s) => (
                  <span
                    key={s.id}
                    className="font-mono text-[8.5px] px-1 rounded border border-[var(--color-border)]"
                  >
                    {s.id}
                  </span>
                ))}
                {reverse.data.strategy_count > 6 && (
                  <span className="text-[var(--color-dim)] italic">
                    …+{reverse.data.strategy_count - 6}
                  </span>
                )}
              </div>
            )}
          </>
        ) : (
          <span className="italic">reverse map unavailable</span>
        )}
      </div>
    </div>
  )
}


/** Phase 6 followup #2: time-aware chip rendered on the strategy
 *  card header. Color escalates with proximity to the event. */
function TimeAwareChip({
  ta,
  activeLang,
}: {
  ta: StrategyTimeAware & { event_label_zh?: string | null }
  activeLang?: 'en' | 'zh-CN-mixed'
}) {
  const days = ta.days_until ?? 0
  const cfg = {
    imminent: { color: 'var(--color-red,#f06060)', label_en: 'fires in', icon: '🔥' },
    soon:     { color: 'var(--color-amber,#e5a200)', label_en: 'in', icon: '⏳' },
    upcoming: { color: 'var(--color-accent)', label_en: 'in', icon: '📅' },
    distant:  { color: 'var(--color-dim)', label_en: 'in', icon: '·' },
    none:     { color: 'var(--color-dim)', label_en: '', icon: '·' },
  }[ta.urgency] ?? { color: 'var(--color-dim)', label_en: 'in', icon: '·' }

  const evtLabel =
    activeLang === 'zh-CN-mixed'
      ? (ta as { event_label_zh?: string | null }).event_label_zh ?? ta.event_label
      : ta.event_label

  const inWord = activeLang === 'zh-CN-mixed' ? `${days}天后` : `${cfg.label_en} ${days}d`
  return (
    <HoverPopover
      width={260}
      delay={200}
      dataTestid={`time-aware-${ta.id}`}
      content={() => (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span style={{ color: cfg.color }}>{cfg.icon}</span>
            <span className="text-[10px] text-[var(--color-text)]">{evtLabel}</span>
          </div>
          <div className="text-[9px] text-[var(--color-dim)]">
            {ta.event_date} · {days} days from today · urgency: <span style={{ color: cfg.color }}>{ta.urgency}</span>
          </div>
          <div className="text-[9px] text-[var(--color-dim)] italic leading-snug">
            Strategies tied to deterministic calendar events get this chip.
            Always-on strategies (DCA, factor tilts) don't.
          </div>
        </div>
      )}
    >
      <span
        className="text-[8.5px] px-1.5 py-0.5 rounded border font-mono"
        style={{ borderColor: cfg.color, color: cfg.color }}
        data-urgency={ta.urgency}
      >
        {cfg.icon} {inWord}
      </span>
    </HoverPopover>
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
