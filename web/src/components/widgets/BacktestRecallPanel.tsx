/**
 * BacktestRecallPanel — Audit tab calibration view (#95).
 *
 * For every (date × strategy) historical run, the backtest harness
 * has stored:
 *   - predicted_score (0-10) — what the regime scorer said on that day
 *   - realized_pnl_pct       — proxy P&L from raw_market_data forward returns
 *
 * This panel aggregates per-strategy:
 *   - n_runs, mean_predicted, mean_realized, hit_rate
 *   - calibration_high (mean realized when predicted >= cutoff)
 *   - calibration_low  (mean realized when predicted <  cutoff)
 *   - delta_high_low   — the discrimination signal we want positive
 *   - spearman_corr    — rank correlation
 *
 * If delta_high_low > 0 and stat-significant, the regime score is
 * doing something useful.  If ≤0, the system "loves the wrong days".
 */
import { useState } from 'react'
import { useBacktestRecall, useBacktestRows, type BacktestRecallEntry } from '@/lib/api'


const PCT = (x: number | null | undefined, dp = 2) =>
  x == null ? '—' : `${(x * 100).toFixed(dp)}%`


export function BacktestRecallPanel() {
  const [cutoff, setCutoff] = useState<number>(4.0)
  const [holdDays, setHoldDays] = useState<number>(30)
  const [expanded, setExpanded] = useState<string | null>(null)

  const q = useBacktestRecall({ scoreCutoff: cutoff, holdDays })
  const data = q.data
  const strategies: BacktestRecallEntry[] = data?.strategies ?? []

  return (
    <div
      data-testid="backtest-recall-panel"
      className="rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-3"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <span className="font-semibold text-[var(--color-text)]">
          🎯 Backtest Recall · 历史预测 vs 真实表现
        </span>
        {data && (
          <>
            <span className="font-mono">{data.n_total_rows} rows</span>
            <span>·</span>
            <span>{strategies.length} strategies</span>
            <span>·</span>
            <span>hold={data.hold_days}d</span>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1">
            <span>cutoff:</span>
            <select
              data-testid="backtest-cutoff"
              value={cutoff}
              onChange={(e) => setCutoff(parseFloat(e.target.value))}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[10px]"
            >
              {[2, 3, 3.5, 4, 4.5, 5].map((v) => (
                <option key={v} value={v}>{v.toFixed(1)}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span>hold:</span>
            <select
              data-testid="backtest-hold"
              value={holdDays}
              onChange={(e) => setHoldDays(parseInt(e.target.value))}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[10px]"
            >
              {[7, 14, 30, 60, 90].map((v) => (
                <option key={v} value={v}>{v}d</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {q.isLoading && (
        <div className="text-[10px] text-[var(--color-dim)]">loading recall…</div>
      )}
      {q.isError && (
        <div className="text-[10px] text-[var(--color-amber,#e5a200)]">
          ⚠ recall unavailable — run regime_backtest.command first.
        </div>
      )}
      {!q.isLoading && !q.isError && strategies.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)]">
          no backtest rows yet. Double-click <span className="font-mono">regime_backtest.command</span>{' '}
          on the desktop (needs <span className="font-mono">regime_backfill_5y.command</span> first).
        </div>
      )}

      {strategies.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] font-mono border-separate border-spacing-y-0.5">
            <thead className="text-[var(--color-dim)] uppercase tracking-wider text-[8.5px]">
              <tr>
                <th className="text-left pl-1.5">strategy</th>
                <th className="text-right">n</th>
                <th className="text-right">pred avg</th>
                <th className="text-right">real avg</th>
                <th className="text-right" title="fraction of high-score days where realized > 0">
                  hit
                </th>
                <th className="text-right" title="mean realized when predicted >= cutoff">
                  cal hi
                </th>
                <th className="text-right" title="mean realized when predicted < cutoff">
                  cal lo
                </th>
                <th className="text-right" title="discrimination = cal_hi − cal_lo">
                  Δ h-l
                </th>
                <th className="text-right" title="Spearman rank correlation">
                  ρ
                </th>
                <th className="pr-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s: BacktestRecallEntry) => {
                const isExp = expanded === s.strategy_id
                const delta = s.delta_high_low
                const deltaColor =
                  delta == null ? 'var(--color-dim)' :
                  delta > 0.005 ? 'var(--color-green)' :
                  delta < -0.005 ? 'var(--color-red, #e07070)' :
                  'var(--color-amber, #e5a200)'
                return (
                  <>
                    <tr
                      key={s.strategy_id}
                      data-testid={`recall-row-${s.strategy_id}`}
                      className="bg-[var(--color-panel)]/60 hover:bg-[var(--color-panel)] cursor-pointer"
                      onClick={() => setExpanded(isExp ? null : s.strategy_id)}
                    >
                      <td className="pl-1.5 py-1 text-[var(--color-text)]">{s.strategy_id}</td>
                      <td className="text-right">{s.n_runs}</td>
                      <td className="text-right">{s.mean_predicted.toFixed(2)}</td>
                      <td className="text-right">{PCT(s.mean_realized)}</td>
                      <td className="text-right">
                        {s.hit_rate == null ? '—' : `${(s.hit_rate * 100).toFixed(0)}%`}
                      </td>
                      <td className="text-right">{PCT(s.p_calibration_high)}</td>
                      <td className="text-right">{PCT(s.p_calibration_low)}</td>
                      <td className="text-right" style={{ color: deltaColor }}>
                        {PCT(delta)}
                      </td>
                      <td className="text-right">
                        {s.spearman_corr == null ? '—' : s.spearman_corr.toFixed(3)}
                      </td>
                      <td className="pr-1.5 text-[var(--color-dim)]">{isExp ? '▾' : '▸'}</td>
                    </tr>
                    {isExp && (
                      <tr key={s.strategy_id + '_expand'}>
                        <td colSpan={10} className="px-1.5 pb-2">
                          <BacktestStrategyDetail
                            strategyId={s.strategy_id}
                            holdDays={holdDays}
                          />
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
        Source: <span className="font-mono">backtest_results</span> SQLite table populated by{' '}
        <span className="font-mono">regime_backtest.command</span>. Realized P&amp;L is a
        payoff_class-aware proxy from <span className="font-mono">raw_market_data</span> forward
        returns (NOT real options chain P&amp;L — we don't have historical option prices).
        <span className="text-[var(--color-text)]"> Δ h-l &gt; 0 + 高 ρ = scorer 在做正确的事</span>;
        {' '}<span className="text-[var(--color-text)]">Δ h-l ≤ 0 = scorer 在那些日子选错了</span>。
      </div>
    </div>
  )
}


function BacktestStrategyDetail({
  strategyId, holdDays,
}: { strategyId: string; holdDays: number }) {
  const q = useBacktestRows({ strategyId, holdDays, limit: 100 })
  const rows = q.data?.results ?? []

  if (q.isLoading) return <div className="text-[9px] text-[var(--color-dim)] py-1">loading rows…</div>

  if (rows.length === 0) {
    return <div className="text-[9px] italic text-[var(--color-dim)] py-1">no rows for {strategyId}</div>
  }

  // Bucket by score, average realized
  const buckets: { range: string; n: number; mean: number }[] = [
    { range: '0-2',  n: 0, mean: 0 },
    { range: '2-4',  n: 0, mean: 0 },
    { range: '4-6',  n: 0, mean: 0 },
    { range: '6-10', n: 0, mean: 0 },
  ]
  for (const r of rows) {
    if (r.realized_pnl_pct == null) continue
    let idx = 0
    if (r.predicted_score < 2) idx = 0
    else if (r.predicted_score < 4) idx = 1
    else if (r.predicted_score < 6) idx = 2
    else idx = 3
    buckets[idx].n += 1
    buckets[idx].mean += r.realized_pnl_pct
  }
  buckets.forEach((b) => { if (b.n > 0) b.mean = b.mean / b.n })

  // Latest 8 rows preview
  const preview = rows.slice(0, 8)

  return (
    <div className="bg-[var(--color-bg)]/80 border border-[var(--color-border)] rounded p-2 text-[9.5px]">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="uppercase tracking-wider text-[8.5px] text-[var(--color-dim)] mb-1">
            calibration buckets (predicted score → mean realized)
          </div>
          <div className="font-mono text-[9px] space-y-0.5">
            {buckets.map((b) => (
              <div key={b.range} className="flex items-center gap-2">
                <span className="text-[var(--color-text)] w-16">score {b.range}</span>
                <span className="text-[var(--color-dim)]">n={b.n}</span>
                <span
                  className="ml-auto"
                  style={{
                    color:
                      b.n === 0 ? 'var(--color-dim)' :
                      b.mean > 0 ? 'var(--color-green)' :
                      'var(--color-red, #e07070)',
                  }}
                >
                  {b.n === 0 ? '—' : PCT(b.mean)}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="uppercase tracking-wider text-[8.5px] text-[var(--color-dim)] mb-1">
            latest 8 rows
          </div>
          <div className="font-mono text-[8.5px] space-y-0.5">
            {preview.map((r) => (
              <div key={r.result_id} className="flex items-center gap-2">
                <span className="text-[var(--color-text)]">{r.fingerprint_date}</span>
                <span className="text-[var(--color-dim)]">pred {r.predicted_score.toFixed(2)}</span>
                <span
                  className="ml-auto"
                  style={{
                    color:
                      r.realized_pnl_pct == null ? 'var(--color-dim)' :
                      r.realized_pnl_pct > 0 ? 'var(--color-green)' :
                      'var(--color-red, #e07070)',
                  }}
                >
                  real {PCT(r.realized_pnl_pct)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
