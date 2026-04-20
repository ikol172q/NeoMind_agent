import { useState } from 'react'
import { useFund } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtNum } from '@/lib/utils'
import { RefreshCw, MessageSquare } from 'lucide-react'

interface Props {
  onJumpToChat?: (prompt: string) => void
}

// Asset-class keys from yfinance → human labels
const ASSET_CLASS_LABELS: Record<string, string> = {
  stockPosition: 'Stocks',
  bondPosition: 'Bonds',
  cashPosition: 'Cash',
  preferredPosition: 'Preferred',
  convertiblePosition: 'Convertibles',
  otherPosition: 'Other',
}
// Colors in rough signal order (growth / income / hedge / cash)
const ASSET_CLASS_COLORS: Record<string, string> = {
  stockPosition: '#4dd0e1',
  bondPosition: '#b388ff',
  cashPosition: '#6fd07a',
  preferredPosition: '#f3c969',
  convertiblePosition: '#e57373',
  otherPosition: '#8b93a8',
}

function fmtAUM(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  return `$${fmtNum(v)}`
}

/**
 * Fund / ETF deep-dive. Enter a ticker → profile card with NAV,
 * AUM, expense ratio, yields, trailing returns, asset-class
 * breakdown (stacked bar) + top 10 holdings with weights.
 */
export function FundExplorerWidget({ onJumpToChat }: Props) {
  const [input, setInput] = useState('VTI')
  const [committed, setCommitted] = useState<string | null>('VTI')
  const q = useFund(committed)
  const d = q.data

  function load() {
    const s = input.trim().toUpperCase()
    if (s) setCommitted(s)
  }

  function ask() {
    if (!onJumpToChat || !d) return
    const pct = (v: number | null) => v == null ? 'n/a' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
    const prompt =
      `${d.symbol} (${d.short_name}, ${d.category}, ${d.family}): AUM ${fmtAUM(d.total_assets)}, ` +
      `expense ${d.expense_ratio_pct ?? 'n/a'}%, yield ${d.yield_pct?.toFixed(2) ?? 'n/a'}%, ` +
      `YTD ${pct(d.ytd_return_pct)}, 3Y ${pct(d.three_year_return_pct)}, 5Y ${pct(d.five_year_return_pct)}. ` +
      `Should I hold this long-term given current valuation and rate regime? ` +
      `2 points for, 2 against, then one alternative to consider. <200 words.`
    onJumpToChat(prompt)
  }

  // Normalise asset class values so the stacked bar fills width.
  const acTotal = d?.asset_classes
    ? Object.values(d.asset_classes).reduce((a, b) => a + b, 0) || 1
    : 1

  return (
    <Card className="h-full flex flex-col" data-testid="fund-explorer-widget">
      <CardHeader
        title="Fund / ETF"
        subtitle={d ? `${d.short_name || d.symbol}${d.family ? ` · ${d.family}` : ''}` : 'enter a ticker'}
        right={
          <div className="flex gap-1">
            {onJumpToChat && d && (
              <Button size="sm" variant="ghost" onClick={ask} data-testid="fund-ask" title="ask fin about this fund">
                <MessageSquare size={11} />
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
              <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
            </Button>
          </div>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-3 overflow-y-auto p-3">
        <div className="flex gap-2">
          <Input
            data-testid="fund-symbol-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && load()}
            placeholder="VTI / SPY / QQQ / …"
            className="flex-1 uppercase"
          />
          <Button data-testid="fund-load" onClick={load}>Load</Button>
        </div>

        {q.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
        {q.isError && (
          <div className="text-[var(--color-red)] text-[11px]">
            {(q.error as Error).message.slice(0, 200)}
          </div>
        )}

        {d && !q.isError && (
          <>
            {/* Headline */}
            <div className="grid grid-cols-3 gap-2 text-[11px]" data-testid="fund-headline">
              <Stat label="NAV" value={d.nav_price != null ? `$${fmtNum(d.nav_price)}` : '—'} />
              <Stat label="AUM" value={fmtAUM(d.total_assets)} />
              <Stat
                label="Expense"
                value={d.expense_ratio_pct != null ? `${d.expense_ratio_pct.toFixed(2)}%` : '—'}
              />
              <Stat label="Yield" value={d.yield_pct != null ? `${d.yield_pct.toFixed(2)}%` : '—'} />
              <Stat
                label="Category"
                value={d.category || '—'}
                small
              />
              <Stat label="P/E" value={d.trailing_pe != null ? fmtNum(d.trailing_pe) : '—'} />
            </div>

            {/* Returns */}
            <div className="grid grid-cols-3 gap-2 text-[11px]">
              <ReturnStat label="YTD" value={d.ytd_return_pct} />
              <ReturnStat label="3Y avg" value={d.three_year_return_pct} />
              <ReturnStat label="5Y avg" value={d.five_year_return_pct} />
            </div>

            {/* Asset class bar */}
            {Object.keys(d.asset_classes).length > 0 && (
              <div data-testid="fund-asset-classes">
                <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
                  Asset mix
                </div>
                <div className="flex h-4 rounded overflow-hidden border border-[var(--color-border)]">
                  {Object.entries(d.asset_classes).map(([key, pct]) => {
                    const w = Math.max(0, (pct / acTotal) * 100)
                    if (w < 0.3) return null
                    return (
                      <div
                        key={key}
                        style={{
                          width: `${w}%`,
                          background: ASSET_CLASS_COLORS[key] || '#8b93a8',
                        }}
                        title={`${ASSET_CLASS_LABELS[key] || key}: ${pct.toFixed(2)}%`}
                      />
                    )
                  })}
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-[10px] text-[var(--color-dim)]">
                  {Object.entries(d.asset_classes).map(([key, pct]) => (
                    <span key={key} className="inline-flex items-center gap-1">
                      <span
                        className="inline-block w-2 h-2 rounded-sm"
                        style={{ background: ASSET_CLASS_COLORS[key] || '#8b93a8' }}
                      />
                      {ASSET_CLASS_LABELS[key] || key} {pct.toFixed(1)}%
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Top holdings */}
            {d.top_holdings.length > 0 && (
              <div data-testid="fund-holdings">
                <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
                  Top {d.top_holdings.length} holdings
                </div>
                <div className="flex flex-col gap-0.5">
                  {d.top_holdings.map(h => (
                    <div
                      key={h.symbol}
                      data-testid={`fund-holding-${h.symbol}`}
                      className="grid grid-cols-[3.5rem_1fr_3rem] gap-2 items-center text-[11px] font-mono"
                    >
                      <span className="text-[var(--color-text)]">{h.symbol}</span>
                      <span className="text-[var(--color-dim)] truncate">{h.name}</span>
                      <span className="text-right">{h.weight_pct.toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}

interface StatProps { label: string; value: string; small?: boolean }
function Stat({ label, value, small }: StatProps) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">{label}</div>
      <div className={small ? 'text-[11px]' : 'text-[13px] font-mono'}>{value}</div>
    </div>
  )
}

function ReturnStat({ label, value }: { label: string; value: number | null }) {
  const tone =
    value == null ? 'text-[var(--color-dim)]' :
    value >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">{label}</div>
      <div className={`text-[13px] font-mono ${tone}`}>
        {value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`}
      </div>
    </div>
  )
}
