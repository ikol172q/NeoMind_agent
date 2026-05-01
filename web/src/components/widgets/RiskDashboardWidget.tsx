/**
 * RiskDashboardWidget — Phase H (#101).
 *
 * Replaces the single 0-10 fit score with a math-backed 6-dimension
 * view per strategy.  No future prediction — all from historical
 * realized P&L distribution conditional on regime k-NN analogs.
 *
 * Dimensions:
 *   1. Return distribution (median + p10/p90 + std)
 *   2. Tail risk (VaR/CVaR/Max DD)
 *   3. Position sizing (half-Kelly)
 *   4. Hedge candidates (negatively-correlated strategies)
 *   5. Stop-loss (ATR + time stop)
 *   6. Regime fit (per-bucket ✓/⚠/✗)
 *
 * Plus composite recommendation (green/amber/red) with reasons for + against.
 */
import { useState } from 'react'
import { useRiskDashboardAll, type RiskDashboardEntry } from '@/lib/api'


const PCT = (x: number | null | undefined, dp = 2) =>
  x == null ? '—' : `${(x * 100).toFixed(dp)}%`

const SIGN_PCT = (x: number | null | undefined, dp = 2) => {
  if (x == null) return '—'
  const v = x * 100
  return `${v >= 0 ? '+' : ''}${v.toFixed(dp)}%`
}


export interface RiskDashboardWidgetProps {
  asOf?: string
}


export function RiskDashboardWidget({ asOf }: RiskDashboardWidgetProps) {
  const [holdDays, setHoldDays] = useState<number>(30)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [colorFilter, setColorFilter] = useState<'all' | 'green' | 'amber' | 'red' | 'real' | 'proxy'>('real')

  const q = useRiskDashboardAll({ asOf, holdDays })
  const all = q.data?.strategies ?? []
  const filtered =
    colorFilter === 'all'   ? all :
    colorFilter === 'real'  ? all.filter(s => s.data_quality === 'real') :
    colorFilter === 'proxy' ? all.filter(s => s.data_quality === 'proxy_only') :
    all.filter(s => s.recommendation?.color === colorFilter)

  const realStrategies  = all.filter(s => s.data_quality === 'real')
  const proxyStrategies = all.filter(s => s.data_quality === 'proxy_only')
  const dsrSurvivors95 = realStrategies.filter(s =>
    (s.walk_forward?.deflated_sharpe?.dsr_prob ?? 0) > 0.95
  ).length
  const dsrSurvivors80 = realStrategies.filter(s =>
    (s.walk_forward?.deflated_sharpe?.dsr_prob ?? 0) > 0.80
  ).length
  const tally = {
    green: realStrategies.filter(s => s.recommendation?.color === 'green').length,
    amber: realStrategies.filter(s => s.recommendation?.color === 'amber').length,
    red:   realStrategies.filter(s => s.recommendation?.color === 'red').length,
    proxy: proxyStrategies.length,
    dsr95: dsrSurvivors95,
    dsr80: dsrSurvivors80,
  }

  return (
    <div
      data-testid="risk-dashboard-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <span className="font-semibold text-[var(--color-text)]">
          📊 Risk Dashboard / 多维度风险量化（替代单一 fit score）
        </span>
        {q.data && (
          <>
            <span className="font-mono">{q.data.fingerprint_date}</span>
            <span>·</span>
            <span>{q.data.n} strategies</span>
            <span>·</span>
            <span className="text-[var(--color-green)]">{tally.green} green</span>
            <span className="text-[var(--color-amber,#e5a200)]">{tally.amber} amber</span>
            <span className="text-[var(--color-red,#e07070)]">{tally.red} red</span>
            <span className="text-[var(--color-dim)]">{tally.proxy} proxy</span>
            <span>·</span>
            <span
              title="Strategies surviving Deflated Sharpe Ratio > 0.95 — i.e., real after multiple-testing correction across 36 candidates"
              className="text-[var(--color-green)]"
            >
              DSR&gt;0.95: {tally.dsr95}/{realStrategies.length}
            </span>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1">
            <span>show:</span>
            <select
              value={colorFilter}
              onChange={(e) => setColorFilter(e.target.value as 'all' | 'green' | 'amber' | 'red' | 'real' | 'proxy')}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[10px]"
            >
              <option value="real">REAL data only (recommended)</option>
              <option value="all">all (incl proxy)</option>
              <option value="green">green only</option>
              <option value="amber">amber only</option>
              <option value="red">red only</option>
              <option value="proxy">proxy only</option>
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span>hold:</span>
            <select
              value={holdDays}
              onChange={(e) => setHoldDays(parseInt(e.target.value))}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[10px]"
            >
              {[7, 14, 30, 60, 90].map((v) => (
                <option key={v} value={v}>{v}d</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {q.isLoading && (
        <div className="text-[10px] text-[var(--color-dim)] py-3">
          正在算 {36} 个 strategy 的 6 维度风险（需要 ~30s 第一次 — 后续缓存）…
        </div>
      )}

      {q.isError && (
        <div className="text-[10px] text-[var(--color-amber,#e5a200)] py-2">
          ⚠ Risk Dashboard 不可用 — 需要 backtest_results 表先有数据。
          双击桌面 regime_backtest.command。
        </div>
      )}

      {filtered.length > 0 && (
        <div className="grid gap-1.5">
          {filtered.map((s) => (
            <RiskCard
              key={s.strategy_id}
              entry={s}
              isExpanded={expanded === s.strategy_id}
              onToggle={() => setExpanded(expanded === s.strategy_id ? null : s.strategy_id)}
            />
          ))}
        </div>
      )}

      <div className="mt-2 text-[8.5px] text-[var(--color-dim)] italic leading-[1.4]">
        <strong className="text-[var(--color-text)]">REAL data only</strong>: 长持类
        (DCA / buy-and-hold / factor ETF) — anchor 资产的 5 年 forward return = 真实策略收益，
        所有 VaR/Kelly/止损 都是真金白银可用的。
        <br />
        <strong className="text-[var(--color-amber,#e5a200)]">PROXY</strong>: 期权 / 主动动量 /
        对冲 / 事件类 — 需要 paper trade 几个月才有真 P&L。当前只显示 regime fit。
        <br />
        Math: VaR/CVaR (Rockafellar-Uryasev), half-Kelly (1956), Markowitz hedge, ATR (Wilder 1978),
        regime k-NN. <strong>不预测未来</strong> — 只描述历史分布。
      </div>
    </div>
  )
}


function RiskCard({
  entry, isExpanded, onToggle,
}: {
  entry: RiskDashboardEntry
  isExpanded: boolean
  onToggle: () => void
}) {
  const rec = entry.recommendation
  const rd  = entry.return_distribution
  const tr  = entry.tail_risk
  const ps  = entry.position_sizing
  const sl  = entry.stop_loss
  const rf  = entry.regime_fit
  const hc  = entry.hedge_candidates

  const isProxy = entry.data_quality === 'proxy_only'
  const wf      = entry.walk_forward
  const dsrProb = wf?.deflated_sharpe?.dsr_prob
  const colorBg = isProxy
    ? 'border-[var(--color-border)] bg-[var(--color-bg)]/40 opacity-70'
    : rec?.color === 'green' ? 'border-[var(--color-green)]/60 bg-[var(--color-green)]/[0.05]'
    : rec?.color === 'red'   ? 'border-[var(--color-red,#e07070)]/60 bg-[var(--color-red,#e07070)]/[0.05]'
    :                          'border-[var(--color-amber,#e5a200)]/40 bg-[var(--color-amber,#e5a200)]/[0.03]'

  return (
    <div
      data-testid={`risk-card-${entry.strategy_id}`}
      className={`rounded border ${colorBg}`}
    >
      <button
        onClick={onToggle}
        className="w-full text-left px-2.5 py-1.5 hover:bg-[var(--color-panel)]/30 transition"
      >
        <div className="flex items-center gap-2 text-[10px]">
          <span
            className="font-mono px-1.5 py-0.5 rounded"
            style={{
              background: isProxy           ? 'var(--color-dim)' :
                          rec?.color === 'green' ? 'var(--color-green)' :
                          rec?.color === 'red'   ? 'var(--color-red, #e07070)' :
                                                    'var(--color-amber, #e5a200)',
              color: '#000',
              fontSize: '8.5px',
            }}
          >
            {isProxy ? 'PROXY' : rec?.color?.toUpperCase()}
          </span>
          <span className="text-[var(--color-text)] font-medium">
            {entry.name_zh ?? entry.name_en ?? entry.strategy_id}
          </span>
          <span className="text-[8.5px] text-[var(--color-dim)] font-mono truncate">
            ({entry.strategy_id})
          </span>
          <div className="ml-auto flex items-center gap-3 text-[9.5px] font-mono text-[var(--color-dim)]">
            {isProxy ? (
              <span className="italic">paper trade required for risk numbers</span>
            ) : (
              <>
                <span>median {SIGN_PCT(rd?.median, 2)}</span>
                <span>VaR {PCT(tr?.var, 1)}</span>
                <span>kelly½ {PCT(ps?.half_kelly, 1)}</span>
                <span
                  title="Deflated Sharpe Ratio (Bailey-Lopez de Prado 2014). >0.95 = real after multiple-testing correction."
                  style={{
                    color:
                      dsrProb == null ? 'var(--color-dim)' :
                      dsrProb > 0.95  ? 'var(--color-green)' :
                      dsrProb < 0.50  ? 'var(--color-red, #e07070)' :
                      'var(--color-amber, #e5a200)',
                  }}
                >
                  DSR {dsrProb == null ? '—' : dsrProb.toFixed(2)}
                </span>
                <span>fit {(rf?.fit_score ?? 0).toFixed(2)}</span>
              </>
            )}
            <span>{isExpanded ? '▾' : '▸'}</span>
          </div>
        </div>
      </button>

      {isExpanded && isProxy && (
        <div className="px-2.5 pb-2.5 pt-1 text-[10px]">
          <div className="rounded border border-[var(--color-amber,#e5a200)]/40 bg-[var(--color-amber,#e5a200)]/[0.06] p-2 mb-2">
            <div className="font-semibold text-[var(--color-text)] mb-1">
              ⚠ PROXY only — VaR / Kelly / 止损 / 对冲 数字不可信
            </div>
            <div className="text-[9.5px] text-[var(--color-dim)] leading-[1.5]">
              这个 strategy 涉及期权定价 / 主动交易 / 对冲 / 事件时机，
              backtest_results 表里的 realized P&L 是用一个简化公式估出来的，
              <strong className="text-[var(--color-text)]"> 不能</strong>当真金白银决策依据。
              下面只显示 regime fit（rule-based，可信）。
              <br /><br />
              <strong className="text-[var(--color-text)]">用法</strong>：用
              regime fit 决定"今天的市场环境是否适合这类策略"，但具体 sizing /
              止损 / 对冲数字必须**先 paper trade 几个月**收集真实 P&L 后再算。
            </div>
          </div>
          <Section
            title="Regime 对应 / Regime fit"
            subtitle={`今日 fit_score = ${(rf?.fit_score ?? 0).toFixed(2)} (${rf?.verdict})`}
            spanFull
          >
            <div className="grid grid-cols-5 gap-1 text-[8.5px]">
              {Object.entries(rf?.buckets ?? {}).map(([key, b]) => {
                const fitColor =
                  b.fit === 'good'    ? 'var(--color-green)' :
                  b.fit === 'bad'     ? 'var(--color-red, #e07070)' :
                  b.fit === 'warning' ? 'var(--color-amber, #e5a200)' :
                  'var(--color-dim)'
                const icon =
                  b.fit === 'good' ? '✓' : b.fit === 'bad' ? '✗' : b.fit === 'warning' ? '⚠' : '·'
                return (
                  <div
                    key={key}
                    className="text-center px-1 py-1 rounded border border-[var(--color-border)]"
                    title={`prefers ${b.strategy_pref}, today ${b.today} (${b.today_value.toFixed(0)})`}
                  >
                    <div className="font-medium text-[var(--color-text)]" style={{ fontSize: '8px' }}>
                      {key.replace('_', ' ')}
                    </div>
                    <div className="text-[10px]" style={{ color: fitColor }}>{icon}</div>
                  </div>
                )
              })}
            </div>
          </Section>
        </div>
      )}

      {isExpanded && !isProxy && (
        <div className="px-2.5 pb-2.5 pt-1 grid gap-2 grid-cols-1 lg:grid-cols-2 text-[9.5px]">
          {/* 1) Return distribution */}
          <Section title="1. 收益分布 / Return distribution" subtitle={`k-NN ${rd?.k_nn ?? 0} similar regime days`}>
            {rd?.n === 0 || rd?.error ? (
              <div className="italic text-[var(--color-dim)]">no data</div>
            ) : (
              <>
                <Bar label="median"      val={SIGN_PCT(rd.median)} />
                <Bar label="p10..p90"     val={`${SIGN_PCT(rd.p10)} .. ${SIGN_PCT(rd.p90)}`} />
                <Bar label="mean ± std"  val={`${SIGN_PCT(rd.mean)} ± ${PCT(rd.std)}`} />
                <Bar label="similar days" val={String(rd.n)} />
              </>
            )}
          </Section>

          {/* 2) Tail risk */}
          <Section title="2. 尾部风险 / Tail risk" subtitle="Rockafellar-Uryasev CVaR + max DD over full 5y">
            {tr?.n === 0 || tr?.error ? (
              <div className="italic text-[var(--color-dim)]">no data</div>
            ) : (
              <>
                <Bar label={`VaR(${((tr.confidence ?? 0.95) * 100).toFixed(0)}%)`}   val={PCT(tr.var)} />
                <Bar label={`CVaR(${((tr.confidence ?? 0.95) * 100).toFixed(0)}%)`}  val={PCT(tr.cvar)} />
                <Bar label="max DD"   val={`${PCT(tr.max_drawdown)} on ${tr.max_drawdown_date}`} />
                <Bar label="win rate" val={PCT(tr.win_rate, 1)} />
              </>
            )}
          </Section>

          {/* 3) Position sizing */}
          <Section title="3. 仓位建议 / Position sizing" subtitle="Kelly criterion (1956) — 半凯利保守版">
            {ps?.error ? (
              <div className="italic text-[var(--color-dim)]">{ps.error}</div>
            ) : ps?.n ? (
              <>
                <Bar label="full Kelly"      val={PCT(ps.kelly, 1)} />
                <Bar label="half Kelly (建议)" val={PCT(ps.half_kelly, 1)} valueColor={ps.half_kelly && ps.half_kelly > 0.05 ? 'var(--color-green)' : ps.half_kelly === 0 ? 'var(--color-red, #e07070)' : 'var(--color-text)'} />
                <Bar label="gain/loss ratio" val={(ps.gain_loss_ratio ?? 0).toFixed(2)} />
                <Bar label="win/avg-win/avg-loss" val={`${PCT(ps.win_rate, 1)} / ${SIGN_PCT(ps.avg_win)} / ${SIGN_PCT(ps.avg_loss)}`} />
              </>
            ) : (
              <div className="italic text-[var(--color-dim)]">no data</div>
            )}
            {ps?.interpretation && (
              <div className="text-[8.5px] text-[var(--color-dim)] italic mt-1">
                {ps.interpretation}
              </div>
            )}
          </Section>

          {/* 4) Hedge candidates */}
          <Section title="4. 对冲候选 / Hedge candidates" subtitle="Markowitz: 负相关 + 最优 size 比">
            {hc?.error || !hc?.top || hc.top.length === 0 ? (
              <div className="italic text-[var(--color-dim)]">no candidates</div>
            ) : (
              <div className="space-y-0.5">
                {hc.top.map((h) => (
                  <div key={h.strategy_id} className="font-mono text-[9px] flex items-center gap-2">
                    <span className="text-[var(--color-text)]">{h.strategy_id}</span>
                    <span className="text-[var(--color-dim)]">ρ={h.correlation.toFixed(2)}</span>
                    <span className="text-[var(--color-dim)]">size {h.size_ratio.toFixed(2)}×</span>
                    <span className="text-[var(--color-dim)]">n={h.n_overlap}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* 5) Stop-loss */}
          <Section title="5. 止损建议 / Stop-loss" subtitle="ATR (Wilder 1978) — 1σ 历史波动">
            {sl?.error ? (
              <div className="italic text-[var(--color-dim)]">{sl.error}</div>
            ) : (
              <>
                <Bar label="suggested stop" val={PCT(sl?.suggested_stop, 1)} valueColor="var(--color-red, #e07070)" />
                <Bar label="time stop"      val={`${sl?.time_stop_days ?? '—'} days`} />
                <Bar label="historical sigma" val={PCT(sl?.sigma, 1)} />
                <Bar label="coverage"       val={PCT(sl?.coverage, 1)} />
                {sl?.interpretation && (
                  <div className="text-[8.5px] text-[var(--color-dim)] italic mt-1">
                    {sl.interpretation}
                  </div>
                )}
              </>
            )}
          </Section>

          {/* 6) Regime fit */}
          <Section title="6. Regime 对应 / Regime fit" subtitle={`今日 fit_score = ${(rf?.fit_score ?? 0).toFixed(2)} (${rf?.verdict})`}>
            <div className="grid grid-cols-5 gap-1 text-[8.5px]">
              {Object.entries(rf?.buckets ?? {}).map(([key, b]) => {
                const fitColor =
                  b.fit === 'good'    ? 'var(--color-green)' :
                  b.fit === 'bad'     ? 'var(--color-red, #e07070)' :
                  b.fit === 'warning' ? 'var(--color-amber, #e5a200)' :
                  'var(--color-dim)'
                const icon =
                  b.fit === 'good' ? '✓' : b.fit === 'bad' ? '✗' : b.fit === 'warning' ? '⚠' : '·'
                return (
                  <div
                    key={key}
                    className="text-center px-1 py-1 rounded border border-[var(--color-border)]"
                    title={`prefers ${b.strategy_pref}, today ${b.today} (${b.today_value.toFixed(0)})`}
                  >
                    <div className="font-medium text-[var(--color-text)]" style={{ fontSize: '8px' }}>
                      {key.replace('_', ' ')}
                    </div>
                    <div className="text-[10px]" style={{ color: fitColor }}>{icon}</div>
                  </div>
                )
              })}
            </div>
          </Section>

          {/* 7) Walk-forward + DSR — the real-money gate */}
          <Section
            title="7. Walk-Forward + Deflated Sharpe Ratio"
            subtitle="Bailey & Lopez de Prado (2014) — 多重检验校正后是不是真的有 alpha"
            spanFull
          >
            {wf?.error ? (
              <div className="italic text-[var(--color-dim)]">{wf.error}</div>
            ) : wf?.deflated_sharpe ? (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Bar label="IS Sharpe (annualized)"  val={(wf.is_sharpe_ann  ?? 0).toFixed(3)} />
                  <Bar label="OOS Sharpe (annualized)" val={(wf.oos_sharpe_ann ?? 0).toFixed(3)}
                       valueColor={(wf.oos_sharpe_ann ?? 0) > 0 ? 'var(--color-green)' : 'var(--color-red, #e07070)'} />
                  <Bar label="IS-OOS gap" val={(wf.is_oos_gap ?? 0).toFixed(3)}
                       valueColor={(wf.is_oos_gap ?? 0) > 1.5 ? 'var(--color-red, #e07070)' : 'var(--color-text)'} />
                  <Bar label="overfit ratio (IS/OOS)"
                       val={wf.overfitting_ratio == null ? '—' : wf.overfitting_ratio.toFixed(2)} />
                </div>
                <div>
                  <Bar label={`DSR P(true SR>0)`}
                       val={wf.deflated_sharpe.dsr_prob.toFixed(3)}
                       valueColor={
                         wf.deflated_sharpe.dsr_prob > 0.95 ? 'var(--color-green)' :
                         wf.deflated_sharpe.dsr_prob < 0.50 ? 'var(--color-red, #e07070)' :
                         'var(--color-amber, #e5a200)'
                       } />
                  <Bar label={`expected max SR (null, N=${wf.deflated_sharpe.n_trials})`}
                       val={wf.deflated_sharpe.sr_max_expected.toFixed(3)} />
                  <Bar label="OOS skew"      val={wf.deflated_sharpe.skewness.toFixed(2)} />
                  <Bar label="OOS kurtosis"  val={wf.deflated_sharpe.kurtosis.toFixed(2)} />
                  <Bar label="verdict" val={wf.verdict ?? '—'}
                       valueColor={
                         wf.verdict === 'ship'      ? 'var(--color-green)' :
                         wf.verdict === 'noise'     ? 'var(--color-red, #e07070)' :
                         wf.verdict === 'overfit'   ? 'var(--color-red, #e07070)' :
                         'var(--color-amber, #e5a200)'
                       } />
                </div>
              </div>
            ) : (
              <div className="italic text-[var(--color-dim)]">no walk-forward data</div>
            )}
            <div className="text-[8.5px] text-[var(--color-dim)] italic mt-1.5 leading-[1.4]">
              IS/OOS split = 80/20 by date. DSR &gt; 0.95: 真信号 (survives N={wf?.deflated_sharpe?.n_trials ?? 36} trials)；
              DSR &lt; 0.50: 比随机 null 还差。IS-OOS gap &gt; 1.5 = overfit signal。
            </div>
          </Section>

          {/* Recommendation reasons */}
          <Section
            title="决策辅助 / Recommendation"
            subtitle={`${rec?.color?.toUpperCase()} — based on multiple dimensions`}
            spanFull
          >
            <div className="grid grid-cols-2 gap-2 text-[9px]">
              <div>
                <div className="text-[var(--color-green)] uppercase tracking-wider mb-0.5" style={{ fontSize: '8.5px' }}>
                  reasons for ✓
                </div>
                {rec?.reasons_for?.length ? (
                  <ul className="space-y-0.5">
                    {rec.reasons_for.map((r, i) => (
                      <li key={i} className="text-[var(--color-text)]">• {r}</li>
                    ))}
                  </ul>
                ) : <div className="italic text-[var(--color-dim)]">none</div>}
              </div>
              <div>
                <div className="text-[var(--color-red, #e07070)] uppercase tracking-wider mb-0.5" style={{ fontSize: '8.5px' }}>
                  reasons against ✗
                </div>
                {rec?.reasons_against?.length ? (
                  <ul className="space-y-0.5">
                    {rec.reasons_against.map((r, i) => (
                      <li key={i} className="text-[var(--color-text)]">• {r}</li>
                    ))}
                  </ul>
                ) : <div className="italic text-[var(--color-dim)]">none</div>}
              </div>
            </div>
          </Section>
        </div>
      )}
    </div>
  )
}


function Section({
  title, subtitle, children, spanFull,
}: {
  title:    string
  subtitle?: string
  children: React.ReactNode
  spanFull?: boolean
}) {
  return (
    <div className={`rounded bg-[var(--color-panel)]/60 border border-[var(--color-border)] p-1.5 ${spanFull ? 'lg:col-span-2' : ''}`}>
      <div className="text-[9px] font-semibold text-[var(--color-text)] mb-0.5">{title}</div>
      {subtitle && (
        <div className="text-[8px] italic text-[var(--color-dim)] mb-1">{subtitle}</div>
      )}
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}


function Bar({ label, val, valueColor }: {
  label: string
  val: string
  valueColor?: string
}) {
  return (
    <div className="flex items-center gap-2 font-mono text-[9px]">
      <span className="text-[var(--color-dim)] w-32 truncate">{label}</span>
      <span style={{ color: valueColor ?? 'var(--color-text)' }}>{val}</span>
    </div>
  )
}
