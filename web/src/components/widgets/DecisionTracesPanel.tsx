/**
 * DecisionTracesPanel — Audit tab drill view (#91).
 *
 * Renders the decision_traces SQLite table written by the portfolio
 * endpoint.  Each row = one (date × strategy_id) recommendation, with
 * full score breakdown + MMR alternative_weight + lattice_node_refs.
 *
 * Lets the user audit "what did the agent recommend on date X for
 * strategy Y, and what numbers backed that recommendation?" without
 * re-running the pipeline.
 */
import { useState } from 'react'
import { useDecisionTraces, type DecisionTrace } from '@/lib/api'


export interface DecisionTracesPanelProps {
  defaultDate?: string
}


export function DecisionTracesPanel({ defaultDate }: DecisionTracesPanelProps) {
  const [filterDate, setFilterDate] = useState<string>(defaultDate ?? '')
  const [filterStrategy, setFilterStrategy] = useState<string>('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const q = useDecisionTraces({
    date: filterDate || null,
    strategyId: filterStrategy || null,
    limit: 200,
  })

  const traces = q.data?.traces ?? []
  const count = q.data?.count ?? 0

  return (
    <div
      data-testid="decision-traces-panel"
      className="rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-3"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <span className="font-semibold text-[var(--color-text)]">
          🔬 Decision Traces / 决策追踪
        </span>
        <span className="font-mono">{count} rows</span>
        <div className="ml-auto flex items-center gap-2">
          <input
            data-testid="trace-filter-date"
            type="text"
            placeholder="YYYY-MM-DD"
            value={filterDate}
            onChange={(e) => setFilterDate(e.target.value)}
            className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[10px] w-24"
          />
          <input
            data-testid="trace-filter-strategy"
            type="text"
            placeholder="strategy_id"
            value={filterStrategy}
            onChange={(e) => setFilterStrategy(e.target.value)}
            className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[10px] w-32"
          />
          <button
            data-testid="trace-refresh"
            onClick={() => q.refetch()}
            className="px-1.5 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 text-[10px]"
          >
            ↻ refresh
          </button>
        </div>
      </div>

      {q.isLoading && (
        <div className="text-[10px] text-[var(--color-dim)]">loading traces…</div>
      )}
      {q.isError && (
        <div className="text-[10px] text-[var(--color-amber,#e5a200)]">
          ⚠ traces unavailable — view portfolio at /api/regime/portfolio first to populate
        </div>
      )}
      {!q.isLoading && !q.isError && traces.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)]">
          no traces yet. Open the Strategies tab — the portfolio widget writes traces on every load.
        </div>
      )}

      {traces.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] font-mono border-separate border-spacing-y-0.5">
            <thead className="text-[var(--color-dim)] uppercase tracking-wider text-[8.5px]">
              <tr>
                <th className="text-left pl-1.5">date</th>
                <th className="text-left">strategy</th>
                <th className="text-right">rank</th>
                <th className="text-right">score</th>
                <th className="text-right">mmr_w</th>
                <th className="text-left pl-2">formula</th>
                <th className="text-left pl-2">computed</th>
                <th className="pr-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t: DecisionTrace) => {
                const isExp = expanded === t.trace_id
                return (
                  <>
                    <tr
                      key={t.trace_id}
                      data-testid={`trace-row-${t.trace_id}`}
                      className="bg-[var(--color-panel)]/60 hover:bg-[var(--color-panel)] cursor-pointer"
                      onClick={() => setExpanded(isExp ? null : t.trace_id)}
                    >
                      <td className="pl-1.5 py-1">{t.fingerprint_date}</td>
                      <td className="text-[var(--color-text)]">{t.strategy_id}</td>
                      <td className="text-right">#{t.rank}</td>
                      <td className="text-right text-[var(--color-green)]">
                        {t.score.toFixed(2)}
                      </td>
                      <td className="text-right">{t.alternative_weight.toFixed(3)}</td>
                      <td className="pl-2 text-[var(--color-dim)]">{t.formula}</td>
                      <td className="pl-2 text-[var(--color-dim)] text-[8.5px]">
                        {t.computed_at?.slice(0, 19).replace('T', ' ')}
                      </td>
                      <td className="pr-1.5 text-[var(--color-dim)]">{isExp ? '▾' : '▸'}</td>
                    </tr>
                    {isExp && (
                      <tr key={t.trace_id + '_detail'}>
                        <td colSpan={8} className="px-1.5 pb-2">
                          <div className="bg-[var(--color-bg)]/80 border border-[var(--color-border)] rounded p-2 text-[9.5px]">
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <div className="uppercase tracking-wider text-[8.5px] text-[var(--color-dim)] mb-0.5">
                                  breakdown
                                </div>
                                <pre className="whitespace-pre-wrap break-words leading-[1.4]">
                                  {JSON.stringify(t.breakdown ?? {}, null, 2)}
                                </pre>
                              </div>
                              <div>
                                <div className="uppercase tracking-wider text-[8.5px] text-[var(--color-dim)] mb-0.5">
                                  portfolio_fit
                                </div>
                                <pre className="whitespace-pre-wrap break-words leading-[1.4]">
                                  {JSON.stringify(t.portfolio_fit ?? {}, null, 2)}
                                </pre>
                                {t.lattice_node_refs && t.lattice_node_refs.length > 0 && (
                                  <>
                                    <div className="uppercase tracking-wider text-[8.5px] text-[var(--color-dim)] mt-2 mb-0.5">
                                      lattice_node_refs
                                    </div>
                                    <div className="font-mono">
                                      {t.lattice_node_refs.join(', ')}
                                    </div>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-2 text-[8.5px] text-[var(--color-dim)] italic leading-[1.4]">
        Source: <span className="font-mono">decision_traces</span> table in
        {' '}<span className="font-mono">.neomind/fin/fin.db</span>. Every load of the
        Strategies tab → portfolio endpoint → 1 + n traces written. Click any row to
        see the full score breakdown (regime_contributions, payoff terms, weights used).
      </div>
    </div>
  )
}
