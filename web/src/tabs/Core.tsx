import { useState } from 'react'
import { useCoreRisk, fetchHedgePlan, postHedgeExecute, type HedgePlan } from '@/lib/api'
import { maskAccount } from '@/lib/utils'

// Bucket ① — 长期核心持仓（买入持有 + 对冲）。与 Trading tab（桶②量化 swing 沙盒）
// 严格分开：这里是你打算长期持有的钱，量化的角色是「系统化风险管理」，不是择时交易。
export function CoreTab() {
  const { data, isFetching, refetch } = useCoreRisk()
  const c = data?.concentration
  const r = data?.risk
  const concentrated = !!c && (c.top3_pct > 60 || c.hhi > 0.25)
  const fmt = (n?: number | null) => n == null ? '—' : `$${Math.round(n).toLocaleString()}`

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden">
      <div className="p-3 space-y-3 max-w-[1100px] mx-auto">
        {/* bucket banner */}
        <div className="text-[11px] rounded p-2 border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-[var(--color-accent)]">🏛 桶① 长期核心持仓</span>
          <span className="text-[var(--color-dim)]">买入持有 + 系统化风险管理/对冲。与「Trading」(桶②量化 swing 沙盒) 是<b>不同的钱</b>。量化在这里 = 监控风险 + 规则化对冲，<b>不</b>择时交易你的核心仓。</span>
        </div>

        {/* header line */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="text-[13px] font-semibold text-[var(--color-text)]">核心持仓风险监控</div>
          <button onClick={() => refetch()} disabled={isFetching}
            className="text-[10px] px-2.5 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/40">
            {isFetching ? '计算中…(拉行情/算 beta)' : '↻ 刷新'}
          </button>
        </div>

        {!data && <div className="text-[11px] text-[var(--color-dim)]">{isFetching ? '加载中…' : '—'}</div>}
        {data?.note && <div className="text-[11px] text-[var(--color-dim)]">{data.note}</div>}

        {data && data.n_tickers > 0 && (
          <>
            {/* top metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
              <Metric label="总市值" value={fmt(data.total_value)} />
              <Metric label="未实现盈亏" value={`${fmt(data.unrealized)} (${(data.unrealized_pct ?? 0).toFixed(1)}%)`}
                tone={(data.unrealized ?? 0) >= 0 ? 'green' : 'red'} />
              <Metric label="大盘 regime" value={data.regime?.regime === 'risk_off' ? '🌧 risk-off' : data.regime?.regime === 'risk_on' ? '☀️ risk-on' : '?'}
                tone={data.regime?.regime === 'risk_off' ? 'red' : 'green'} />
              <Metric label="持仓数" value={String(data.n_tickers)} />
            </div>

            {/* risk x-ray */}
            <div className="rounded border border-[var(--color-border)] p-2.5 bg-[var(--color-panel)] space-y-2">
              <div className="text-[11px] font-semibold text-[var(--color-text)]">📊 风险 X 光</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                <Metric label="beta vs QQQ" value={r?.beta_qqq != null ? `${r.beta_qqq}` : '—'}
                  tone={(r?.beta_qqq ?? 0) > 1.5 ? 'red' : 'dim'}
                  hint="组合对纳指的敏感度。>1.5 = 高 beta，跌起来放大" />
                <Metric label="年化波动率" value={r?.ann_vol_pct != null ? `${r.ann_vol_pct}%` : '—'}
                  tone={(r?.ann_vol_pct ?? 0) > 30 ? 'red' : 'dim'} />
                <Metric label="近1年最大回撤" value={r?.max_drawdown_1y_pct != null ? `${r.max_drawdown_1y_pct}%` : '—'}
                  hint="当前持仓套用过去1年价格的静态回撤" />
                <Metric label="beta vs SPY" value={r?.beta_spy != null ? `${r.beta_spy}` : '—'} tone="dim" />
              </div>

              {/* concentration — the headline risk */}
              {c && (
                <div className={`rounded p-2 text-[11px] border ${concentrated ? 'border-[var(--color-red)]/50 bg-[var(--color-red)]/10' : 'border-[var(--color-border)]'}`}>
                  <div className={concentrated ? 'text-[var(--color-red)] font-semibold' : 'text-[var(--color-text)]'}>
                    {concentrated ? '⚠️ 高集中度' : '集中度'}：最大单仓 <b>{c.largest.ticker} {c.largest.pct}%</b> · 前3占 <b>{c.top3_pct}%</b> · HHI <b>{c.hhi}</b>{c.hhi > 0.25 ? '（>0.25 偏集中）' : ''}
                  </div>
                  {concentrated && (
                    <div className="text-[var(--color-dim)] mt-1 leading-[1.5]">
                      指数对冲（QQQ put）保的是<b>市场/科技整体</b>下跌，<b>保不了单只爆雷</b>。集中度本身的首选处理是<b>减仓</b>，对冲是第二层。
                    </div>
                  )}
                </div>
              )}

              {/* correlation warnings */}
              {data.correlation_warnings && data.correlation_warnings.length > 0 && (
                <div className="text-[10px] text-[var(--color-yellow)]">
                  高相关对（≥{data.correlation_threshold}）：{data.correlation_warnings.map(w => `${w.a}~${w.b} ${w.corr}`).join(' · ')}
                </div>
              )}
            </div>

            {/* holdings table */}
            <div className="rounded border border-[var(--color-border)] p-2 bg-[var(--color-panel)]">
              <table className="w-full text-[10px] border-collapse">
                <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                  <th className="py-1 pr-2">标的</th><th className="pr-2 text-right">数量</th><th className="pr-2 text-right">现价</th>
                  <th className="pr-2 text-right">市值</th><th className="pr-2 text-right">权重</th><th className="pr-2 text-right">浮盈%</th><th className="pr-2">板块</th>
                </tr></thead>
                <tbody>
                  {data.holdings.map(h => (
                    <tr key={h.ticker} className="border-b border-[var(--color-border)]/30">
                      <td className="py-1 pr-2 font-mono text-[var(--color-text)] font-semibold">{h.ticker}</td>
                      <td className="pr-2 text-right font-mono">{h.qty}</td>
                      <td className="pr-2 text-right font-mono">{h.price != null ? h.price.toFixed(2) : '—'}</td>
                      <td className="pr-2 text-right font-mono">{fmt(h.value)}</td>
                      <td className={`pr-2 text-right font-mono ${(h.weight_pct ?? 0) >= 25 ? 'text-[var(--color-red)] font-semibold' : ''}`}>{h.weight_pct != null ? `${h.weight_pct}%` : '—'}</td>
                      <td className={`pr-2 text-right font-mono ${(h.unrealized_pct ?? 0) >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}`}>{h.unrealized_pct != null ? `${h.unrealized_pct}%` : '—'}</td>
                      <td className="pr-2 text-[var(--color-dim)]">{h.sector || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* sector mix */}
            {data.by_sector && data.by_sector.length > 0 && (
              <div className="text-[10px] text-[var(--color-dim)] flex flex-wrap gap-x-3">
                <span className="font-semibold text-[var(--color-text)]">板块分布：</span>
                {data.by_sector.map(s => <span key={s.sector}>{s.sector} {s.pct.toFixed(0)}%</span>)}
              </div>
            )}

            {/* Phase 2 — systematic hedge overlay */}
            <HedgePanel />
            {/* Phase 4 — options learning sandbox (payoff explorer, no trading) */}
            <OptionLearnPanel />
          </>
        )}
      </div>
    </div>
  )
}

// 桶③ — 期权学习沙盒：纯 payoff 探索器，不下单、不接资金。用来把 call/put 的
// 机制玩熟（亏损封顶、breakeven、保险地板），defined-risk by construction。
function OptionLearnPanel() {
  const [kind, setKind] = useState<'call' | 'put' | 'protective'>('protective')
  const [spot, setSpot] = useState('100')
  const [strike, setStrike] = useState('95')
  const [prem, setPrem] = useState('3')
  const [n, setN] = useState('1')

  const S0 = parseFloat(spot) || 0, K = parseFloat(strike) || 0
  const P = parseFloat(prem) || 0, N = (parseInt(n) || 1) * 100
  const payoff = (S: number) => {
    if (kind === 'call') return (Math.max(0, S - K) - P) * N
    if (kind === 'put') return (Math.max(0, K - S) - P) * N
    return ((S - S0) + Math.max(0, K - S) - P) * N  // protective: 持股(@S0) + 买put
  }
  const prices = [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3].map(m => +(S0 * (1 + m)).toFixed(2))
  // breakeven + max loss
  const maxLoss = kind === 'call' ? -P * N : kind === 'put' ? -P * N : (-(S0 - K) - P) * N
  const be = kind === 'call' ? K + P : kind === 'put' ? K - P : S0 + P
  const fmt = (x: number) => `${x >= 0 ? '+' : '-'}$${Math.abs(Math.round(x)).toLocaleString()}`

  return (
    <div className="rounded border border-[var(--color-border)] p-2.5 space-y-2 bg-[var(--color-panel)]">
      <div className="text-[11px] font-semibold text-[var(--color-text)]">🎓 桶③ 期权学习沙盒（payoff 探索器 · 纯学习 · 不下单）</div>
      <div className="flex items-center gap-1.5 flex-wrap text-[10px]">
        <select value={kind} onChange={e => setKind(e.target.value as 'call' | 'put' | 'protective')}
          className="px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]">
          <option value="protective">持股 + 买 Put（保险，你的用法）</option>
          <option value="call">买 Call（看涨）</option>
          <option value="put">买 Put（看跌）</option>
        </select>
        <label className="text-[var(--color-dim)]">现价<input value={spot} onChange={e => setSpot(e.target.value)} className="ml-1 w-14 px-1 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)]" /></label>
        <label className="text-[var(--color-dim)]">行权价<input value={strike} onChange={e => setStrike(e.target.value)} className="ml-1 w-14 px-1 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)]" /></label>
        <label className="text-[var(--color-dim)]">权利金<input value={prem} onChange={e => setPrem(e.target.value)} className="ml-1 w-12 px-1 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)]" /></label>
        <label className="text-[var(--color-dim)]">合约数<input value={n} onChange={e => setN(e.target.value)} className="ml-1 w-10 px-1 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)]" /></label>
      </div>
      <div className="text-[10px] text-[var(--color-dim)]">
        盈亏平衡 <b className="text-[var(--color-text)]">${be.toFixed(2)}</b> · 最大亏损 <b className="text-[var(--color-red)]">{fmt(maxLoss)}</b>
        {kind === 'protective' && <span> · 地板：跌破 {K} 后亏损封顶</span>}
        {kind === 'call' && <span> · 上行无限</span>}
      </div>
      <table className="w-full text-[9.5px] border-collapse">
        <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
          <th className="py-0.5 pr-2">到期价</th>{prices.map(p => <th key={p} className="pr-2 text-right">{p}</th>)}
        </tr></thead>
        <tbody>
          <tr><td className="py-0.5 pr-2 text-[var(--color-dim)]">到期盈亏</td>
            {prices.map(p => { const v = payoff(p); return <td key={p} className={`pr-2 text-right font-mono ${v >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'}`}>{fmt(v)}</td> })}
          </tr>
        </tbody>
      </table>
      <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
        纯计算器，帮你把机制玩熟（最多亏权利金、breakeven、保险地板）。<b>不下单、不接资金</b>。真要买保险用上面的「对冲叠加层」，且记住你红线：仅 put/collar 对冲、不投机。
      </div>
    </div>
  )
}

function HedgePanel() {
  const [coverage, setCoverage] = useState(0.5)
  const [otm, setOtm] = useState(0.10)
  const [plan, setPlan] = useState<HedgePlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirmStep, setConfirmStep] = useState(false)
  const [placing, setPlacing] = useState(false)
  const [placeMsg, setPlaceMsg] = useState<string | null>(null)

  async function calc() {
    setLoading(true); setErr(null); setConfirmStep(false); setPlaceMsg(null)
    try {
      const p = await fetchHedgePlan(coverage, otm)
      setPlan(p)
      if (p.error) setErr(p.error)
    } catch (e) { setErr(String((e as Error)?.message).slice(0, 80)) }
    finally { setLoading(false) }
  }

  async function placeHedge() {
    setPlacing(true); setPlaceMsg(null)
    try {
      const r = await postHedgeExecute(coverage, otm, true)
      if (r.ok) setPlaceMsg(`✅ 已下对冲单（${r.paper ? 'paper' : '⚠真实'} ${r.account ? maskAccount(r.account) : ''}）· 状态 ${r.result?.status || 'ok'}`)
      else setPlaceMsg(`下单未成功：${(r.result?.error || r.error || '').slice(0, 90)}`)
    } catch (e) { setPlaceMsg(`下单失败：${String((e as Error)?.message).slice(0, 80)}`) }
    finally { setPlacing(false); setConfirmStep(false) }
  }
  const fmt = (n?: number | null) => n == null ? '—' : `$${Math.round(n).toLocaleString()}`

  return (
    <div className="rounded border border-[var(--color-green)]/40 bg-[var(--color-green)]/5 p-2.5 space-y-2">
      <div className="text-[11px] font-semibold text-[var(--color-green)]">🛡 系统化对冲叠加层（仅 put/collar，守红线）</div>

      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        <span className="text-[var(--color-dim)]">对冲比例</span>
        <select value={coverage} onChange={e => setCoverage(parseFloat(e.target.value))}
          className="px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]">
          <option value={0.25}>25% beta</option><option value={0.5}>50% beta</option>
          <option value={0.75}>75% beta</option><option value={1}>100% beta（全对冲）</option>
        </select>
        <span className="text-[var(--color-dim)]">价外</span>
        <select value={otm} onChange={e => setOtm(parseFloat(e.target.value))}
          className="px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)]">
          <option value={0.05}>5% OTM（贵·保护早）</option><option value={0.10}>10% OTM（均衡）</option>
          <option value={0.15}>15% OTM（便宜·只防崩盘）</option>
        </select>
        <button onClick={calc} disabled={loading}
          className="px-2.5 py-0.5 rounded bg-[var(--color-green)]/20 text-[var(--color-green)] border border-[var(--color-green)]/40">
          {loading ? '算方案中…(拉 QQQ 期权链)' : '🛡 算对冲方案'}
        </button>
      </div>

      {err && <div className="text-[10px] text-[var(--color-red)]">{err}</div>}

      {plan && !plan.error && plan.contracts != null && (
        <div className="space-y-2 text-[10px]">
          {/* rule status */}
          {plan.rule_status && (
            <div className={`rounded p-1.5 border ${plan.rule_status.triggered ? 'border-[var(--color-red)]/50 bg-[var(--color-red)]/10 text-[var(--color-red)]' : 'border-[var(--color-border)] text-[var(--color-dim)]'}`}>
              {plan.rule_status.triggered ? '⚠️ 规则触发：' : '规则状态：'}{plan.rule_status.reason}
            </div>
          )}

          {/* the order ticket */}
          <div className="rounded p-2 bg-[var(--color-panel)] border border-[var(--color-border)]">
            <div className="text-[var(--color-dim)] mb-1">对冲方案（按 hedge_beta {plan.hedge_beta}，实测 beta {plan.realized_beta_qqq}）：</div>
            <div className="font-mono text-[12px] text-[var(--color-text)] font-semibold">{plan.order_ticket}</div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-[var(--color-dim)]">
              <span>QQQ ${plan.qqq_spot}</span><span>strike {plan.strike}</span><span>到期 {plan.expiry}</span>
              <span>保费 ${plan.premium_per_share}/股 (IV {plan.iv_pct}%)</span>
              <span className="text-[var(--color-text)]">成本 <b>{fmt(plan.cost)} ({plan.cost_pct}%)</b></span>
            </div>
          </div>

          {/* scenarios */}
          {plan.scenarios && (
            <table className="w-full text-[9.5px] border-collapse">
              <thead><tr className="text-[var(--color-dim)] text-left border-b border-[var(--color-border)]">
                <th className="py-0.5 pr-2">QQQ 跌</th><th className="pr-2 text-right">不对冲组合损失</th><th className="pr-2 text-right">put 净赔付</th><th className="pr-2 text-right">对冲后损失</th>
              </tr></thead>
              <tbody>
                {plan.scenarios.map(s => (
                  <tr key={s.qqq_move_pct} className="border-b border-[var(--color-border)]/30">
                    <td className="py-0.5 pr-2 font-mono">{s.qqq_move_pct}%</td>
                    <td className="pr-2 text-right font-mono text-[var(--color-red)]">{fmt(s.port_loss_unhedged)}</td>
                    <td className="pr-2 text-right font-mono">{fmt(s.put_net_payoff)}</td>
                    <td className="pr-2 text-right font-mono text-[var(--color-green)]">{fmt(s.port_loss_hedged)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {plan.caveats && (
            <ul className="text-[9px] text-[var(--color-dim)] leading-[1.5] list-disc pl-4">
              {plan.caveats.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          )}
          {/* Phase 2b — one-click place (BUY PUT only, DU-guard, paper unless allow_live) */}
          {plan.contracts ? (
            <div className="rounded border border-[var(--color-border)] p-2 bg-[var(--color-bg)] space-y-1.5">
              {!confirmStep ? (
                <button onClick={() => { setConfirmStep(true); setPlaceMsg(null) }} disabled={placing}
                  className="text-[10px] px-2.5 py-0.5 rounded bg-[var(--color-green)]/20 text-[var(--color-green)] border border-[var(--color-green)]/40">
                  🛡 一键下这笔对冲单（IBKR · 默认 paper）
                </button>
              ) : (
                <div className="flex items-center gap-2 flex-wrap text-[10px]">
                  <span className="text-[var(--color-yellow)]">确认买入 <b>{plan.contracts}</b> 张 QQQ {plan.expiry} {plan.strike} PUT（约 {`$${Math.round(plan.cost ?? 0).toLocaleString()}`}）?</span>
                  <button onClick={placeHedge} disabled={placing}
                    className="px-2.5 py-0.5 rounded bg-[var(--color-green)]/25 text-[var(--color-green)] border border-[var(--color-green)]/50">
                    {placing ? '下单中…' : '✅ 确认下单'}
                  </button>
                  <button onClick={() => setConfirmStep(false)} disabled={placing}
                    className="px-2.5 py-0.5 rounded text-[var(--color-dim)] border border-[var(--color-border)]">取消</button>
                </div>
              )}
              {placeMsg && <div className="text-[10px] text-[var(--color-dim)]">{placeMsg}</div>}
              <div className="text-[9px] text-[var(--color-dim)]">
                仅买入 PUT（连接器硬性拦截卖出/CALL）· DU 账户守护（默认 paper）· GTC limit。也可拿上面 order ticket 在 IBKR 手动下。
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, tone = 'text', hint }: { label: string; value: string; tone?: 'text' | 'green' | 'red' | 'dim'; hint?: string }) {
  const color = tone === 'green' ? 'var(--color-green)' : tone === 'red' ? 'var(--color-red)' : tone === 'dim' ? 'var(--color-dim)' : 'var(--color-text)'
  return (
    <div className="rounded border border-[var(--color-border)] p-2 bg-[var(--color-panel)]" title={hint}>
      <div className="text-[9px] text-[var(--color-dim)]">{label}</div>
      <div className="text-[13px] font-semibold font-mono" style={{ color }}>{value}</div>
    </div>
  )
}
