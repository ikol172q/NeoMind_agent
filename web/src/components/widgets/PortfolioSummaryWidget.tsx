/**
 * PortfolioSummaryWidget — top-of-Strategies summary of your actual
 * holdings (not just watchlist). Per plan §5 Pillar 6 + §7 Phase 1B.
 *
 * Shows:
 *   • Total value · Total cost · Unrealized P&L (% + $)
 *   • Sector mix bar (proportional)
 *   • vs benchmark (default SPY) — windowed 30/90/365
 *   • Top 5 positions, each clickable to open the drawer
 *
 * Per plan §2 philosophy: this is INFORMATION DISPLAY, not advice.
 * No "rebalance now" prompts; user reads the numbers and decides.
 */
import { useState } from 'react'
import { useStockResearch } from '@/components/research/StockResearchContext'
import { usePortfolioSummary, usePositionsLots, useDeleteLot, type TaxLot } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { AddLotModal } from '@/components/widgets/AddLotModal'
import {
  Briefcase, ChevronDown, ChevronRight, Plus, Pencil, Trash2,
} from 'lucide-react'

const SECTOR_COLORS: Record<string, string> = {
  Technology: 'bg-violet-500',
  Healthcare: 'bg-emerald-500',
  Financial:  'bg-blue-500',
  'Financial Services': 'bg-blue-500',
  'Consumer Cyclical':  'bg-amber-500',
  'Consumer Defensive': 'bg-cyan-500',
  Industrials:    'bg-orange-500',
  Energy:         'bg-yellow-500',
  Utilities:      'bg-teal-500',
  'Communication Services': 'bg-pink-500',
  'Basic Materials': 'bg-gray-500',
  'Real Estate':  'bg-rose-500',
  Unknown:        'bg-[var(--color-dim)]',
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—'
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

export function PortfolioSummaryWidget({
  onAddLot,
}: {
  /** When set, shown as "+ Add lot" button at top-right; opens a
   *  modal in the parent. */
  onAddLot?: () => void
}) {
  const sumQ = usePortfolioSummary('SPY')
  // Persist collapse like Watchlist section
  const [collapsed, setCollapsed] = useState<boolean>(() =>
    typeof window !== 'undefined'
      && localStorage.getItem('strategies.portfolio.collapsed') === '1'
  )
  function toggle() {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem('strategies.portfolio.collapsed', next ? '1' : '0') } catch {}
  }

  const d = sumQ.data
  const empty = !sumQ.isLoading && d?.n_lots === 0

  // Compact summary chip for collapsed state
  const headerChip = d ? (
    <span className="text-[11px] text-[var(--color-dim)] flex items-center gap-2">
      <span className="text-[var(--color-text)] font-mono">{fmtMoney(d.total_value)}</span>
      <span className={d.unrealized >= 0 ? 'text-emerald-300' : 'text-red-300'}>
        {fmtPct(d.unrealized_pct)}
      </span>
      <span className="text-[var(--color-dim)]">· {d.n_tickers} tickers</span>
    </span>
  ) : null

  return (
    <div className="mb-3">
      <button
        onClick={toggle}
        className="w-full flex items-center gap-2 px-3 py-2 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 bg-[var(--color-panel)]/60 text-left group"
        title={collapsed ? '展开 portfolio' : '折叠 portfolio'}
      >
        {collapsed
          ? <ChevronRight size={14} className="text-[var(--color-dim)] group-hover:text-[var(--color-accent)] flex-shrink-0" />
          : <ChevronDown size={14} className="text-[var(--color-dim)] group-hover:text-[var(--color-accent)] flex-shrink-0" />}
        <Briefcase size={14} className="text-[var(--color-accent)] flex-shrink-0" />
        <span className="text-[12px] font-semibold text-[var(--color-text)] flex-shrink-0">我的持仓</span>
        <span className="text-[10px] italic text-[var(--color-dim)] flex-shrink-0">
          · 实际 holdings (不是 watchlist)
        </span>
        <span className="ml-auto">{headerChip}</span>
      </button>

      {!collapsed && (
        <Card className="mt-2">
          <CardHeader
            title={<span className="flex items-center gap-1.5"><Briefcase size={14} /> Portfolio Summary</span>}
            subtitle={
              d
                ? <>{d.n_lots} lots · {d.n_tickers} tickers · 当前 {d.benchmark} 数据{d.vs_benchmark?.windows && Object.keys(d.vs_benchmark.windows).length > 0 ? '已缓存' : '未缓存'}</>
                : 'loading...'
            }
            right={
              onAddLot && (
                <button
                  onClick={onAddLot}
                  className="text-[10px] px-2 py-1 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300 flex items-center gap-1"
                >
                  <Plus size={11} /> Add lot
                </button>
              )
            }
          />
          <CardBody>
            {sumQ.isLoading && (
              <div className="text-[11px] italic text-[var(--color-dim)]">loading…</div>
            )}

            {empty && (
              <div className="text-[11px] text-[var(--color-dim)] italic py-2">
                没有持仓 — 点上面 <b>+ Add lot</b> 录入你 Schwab/Fidelity 的真实仓位.
                录入后这里会显示总值 / 分布 / vs SPY 等数据.
              </div>
            )}

            {d && d.n_lots > 0 && (
              <>
                {/* Top metrics row */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
                  <Metric label="总市值"  value={fmtMoney(d.total_value)} />
                  <Metric label="总成本"  value={fmtMoney(d.total_cost)} />
                  <Metric
                    label="未实现 P&L"
                    value={fmtMoney(d.unrealized)}
                    sub={fmtPct(d.unrealized_pct)}
                    color={d.unrealized >= 0 ? 'emerald' : 'red'}
                  />
                  <Metric
                    label={`vs ${d.benchmark}`}
                    value={(() => {
                      // Show 90d as primary; tooltip-style sub shows 30d / 365d
                      const w = d.vs_benchmark?.windows ?? {}
                      const w90 = w['90d']?.benchmark_pct
                      if (w90 == null) return '—'
                      return `90d: ${fmtPct(w90)}`
                    })()}
                    sub={(() => {
                      const w = d.vs_benchmark?.windows ?? {}
                      const w30 = w['30d']?.benchmark_pct
                      const w365 = w['365d']?.benchmark_pct
                      const parts = []
                      if (w30 != null) parts.push(`30d ${fmtPct(w30)}`)
                      if (w365 != null) parts.push(`365d ${fmtPct(w365)}`)
                      return parts.join(' · ')
                    })()}
                  />
                </div>

                {/* Sector mix bar */}
                {d.by_sector.length > 0 && (
                  <div className="mb-3">
                    <div className="text-[10px] text-[var(--color-dim)] mb-1 uppercase tracking-wider">
                      sector 分布
                    </div>
                    <div className="flex h-3 rounded overflow-hidden border border-[var(--color-border)]">
                      {d.by_sector.map(s => (
                        <div
                          key={s.sector}
                          className={SECTOR_COLORS[s.sector] || 'bg-[var(--color-dim)]'}
                          style={{ width: `${s.pct}%` }}
                          title={`${s.sector}: ${s.pct.toFixed(1)}% (${fmtMoney(s.value)})`}
                        />
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-[10px]">
                      {d.by_sector.slice(0, 6).map(s => (
                        <span key={s.sector} className="flex items-center gap-1 text-[var(--color-dim)]">
                          <span className={`w-1.5 h-1.5 rounded ${SECTOR_COLORS[s.sector] || 'bg-[var(--color-dim)]'}`} />
                          {s.sector} {s.pct.toFixed(0)}%
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Top positions table */}
                <div className="mb-1 text-[10px] text-[var(--color-dim)] uppercase tracking-wider">
                  top {Math.min(5, d.by_ticker.length)} positions
                </div>
                <div className="space-y-1">
                  {d.by_ticker.slice(0, 5).map(t => (
                    <PositionRow
                      key={t.ticker}
                      ticker={t.ticker}
                      quantity={t.quantity}
                      marketValue={t.market_value}
                      unrealizedPct={t.unrealized_pct}
                      weightPct={t.weight_pct}
                      sector={t.sector}
                    />
                  ))}
                </div>

                {d.vs_benchmark?.note && (
                  <div className="mt-2 text-[9.5px] italic text-[var(--color-dim)]">
                    📝 {d.vs_benchmark.note}
                  </div>
                )}
              </>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  )
}


function PositionRow({
  ticker, quantity, marketValue, unrealizedPct, weightPct, sector,
}: {
  ticker: string
  quantity: number
  marketValue: number | null | undefined
  unrealizedPct: number | null | undefined
  weightPct: number | null | undefined
  sector: string | null | undefined
}) {
  const { openTicker } = useStockResearch()
  const [editing, setEditing] = useState<TaxLot | null>(null)
  const lotsQ = usePositionsLots({ ticker, open_only: true })
  const deleteMu = useDeleteLot()
  const lot = lotsQ.data?.lots?.[0]  // first open lot for this ticker

  function onEdit(e: React.MouseEvent) {
    e.stopPropagation()
    if (lot) setEditing(lot)
  }
  function onDelete(e: React.MouseEvent) {
    e.stopPropagation()
    if (!lot) return
    if (!confirm(`确认删除 ${ticker} 持仓 (${quantity} 股)?`)) return
    deleteMu.mutate({ lot_id: lot.lot_id, ticker })
  }

  return (
    <>
      <div
        onClick={() => openTicker(ticker)}
        title={`点击打开 ${ticker} 详细分析`}
        className="w-full grid grid-cols-12 gap-2 items-center text-[11px] px-2 py-1 rounded border border-[var(--color-border)]/50 hover:border-[var(--color-accent)]/70 hover:bg-[var(--color-accent)]/10 transition cursor-pointer text-left group"
        data-testid={`position-row-${ticker}`}
      >
        <span className="col-span-2 font-mono font-bold text-[var(--color-text)] group-hover:text-[var(--color-accent)] underline decoration-dotted decoration-[var(--color-dim)] underline-offset-2">
          {ticker}
        </span>
        <span className="col-span-2 font-mono text-[10px] text-[var(--color-dim)]">
          {quantity.toFixed(0)}sh
        </span>
        <span className="col-span-2 font-mono text-[10px] text-[var(--color-dim)]">
          {fmtMoney(marketValue)}
        </span>
        <span className={`col-span-2 font-mono text-[10px] ${
          (unrealizedPct ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300'
        }`}>
          {fmtPct(unrealizedPct)}
        </span>
        <span className="col-span-1 text-[9px] text-[var(--color-dim)]">
          {weightPct != null ? `${weightPct.toFixed(1)}%` : '—'}
        </span>
        <span className="col-span-1 text-[9px] text-[var(--color-dim)] truncate">
          {sector}
        </span>
        <span className="col-span-2 flex items-center gap-1 justify-end opacity-0 group-hover:opacity-100 transition">
          {lot && (
            <>
              <button
                onClick={onEdit}
                title="改这笔持仓"
                className="p-1 rounded hover:bg-[var(--color-accent)]/20 text-[var(--color-dim)] hover:text-[var(--color-accent)]"
                data-testid={`edit-position-${ticker}`}
              >
                <Pencil size={11} />
              </button>
              <button
                onClick={onDelete}
                title="删除这笔持仓"
                className="p-1 rounded hover:bg-red-500/20 text-[var(--color-dim)] hover:text-red-300"
                disabled={deleteMu.isPending}
                data-testid={`delete-position-${ticker}`}
              >
                <Trash2 size={11} />
              </button>
            </>
          )}
        </span>
      </div>
      {editing && (
        <AddLotModal
          lot={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  )
}


function Metric({
  label, value, sub, color,
}: {
  label: string
  value: string
  sub?: string
  color?: 'emerald' | 'red'
}) {
  const colorClass = color === 'emerald' ? 'text-emerald-300'
                  : color === 'red'     ? 'text-red-300'
                  : 'text-[var(--color-text)]'
  return (
    <div className="border border-[var(--color-border)]/50 rounded p-2">
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">
        {label}
      </div>
      <div className={`text-[14px] font-mono font-semibold ${colorClass}`}>
        {value}
      </div>
      {sub && (
        <div className={`text-[9px] font-mono ${colorClass}/80`}>
          {sub}
        </div>
      )}
    </div>
  )
}
