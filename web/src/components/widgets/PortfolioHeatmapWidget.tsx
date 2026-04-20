import { useEffect } from 'react'
import {
  usePaperAccount,
  usePaperPositions,
  refreshPaperPrices,
  type PaperPosition,
  type PaperAccount,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn, fmtNum } from '@/lib/utils'
import { RefreshCw, MessageSquare } from 'lucide-react'

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string) => void
}

// Color scale for per-position P&L%. Clamped so a single outlier
// doesn't wash the rest grey.
const BAND_CLAMP = 20 // +/- 20% fills the bar
function pnlColor(pct: number): string {
  if (pct >= 10) return 'var(--color-green)'
  if (pct >= 3) return 'var(--color-green)'       // same hue, bar length distinguishes
  if (pct > -3) return 'var(--color-dim)'
  if (pct > -10) return 'var(--color-amber, #e5a200)'
  return 'var(--color-red)'
}

// Row tint (very faint background wash) — same colour family as the
// bar so the whole row signals risk at a glance.
function rowTint(pct: number): string {
  if (pct >= 5) return 'bg-[var(--color-green)]/5'
  if (pct >= -5) return ''
  if (pct >= -10) return 'bg-[var(--color-amber,#e5a200)]/10'
  return 'bg-[var(--color-red)]/10'
}

/**
 * Research-tab companion to the Paper panel. Shows each paper
 * position on a colour-banded P&L heatmap + an account-level
 * summary header, so you can scan "who's bleeding, who's safe"
 * without flipping to Paper.
 *
 * Data is read-only here. New orders / closing positions still go
 * through the Paper tab. One POST /api/paper/refresh on mount
 * nudges the engine to repull live prices; after that the 15s
 * poll in usePaperPositions keeps numbers current.
 */
export function PortfolioHeatmapWidget({ projectId, onJumpToChat }: Props) {
  const posQ = usePaperPositions(projectId)
  const acctQ = usePaperAccount(projectId)

  // Kick one refresh on mount so first paint isn't stale entry_price.
  useEffect(() => {
    if (!projectId) return
    refreshPaperPrices(projectId).catch(() => { /* best effort */ })
  }, [projectId])

  const positions = (posQ.data?.positions as unknown as PaperPosition[]) ?? []
  const account = (acctQ.data as unknown as PaperAccount) ?? null

  function ask(p: PaperPosition) {
    if (!onJumpToChat) return
    const sign = p.unrealized_pnl_pct >= 0 ? '+' : ''
    const prompt =
      `${p.symbol} position: ${sign}${p.unrealized_pnl_pct.toFixed(2)}% ` +
      `($${p.unrealized_pnl >= 0 ? '+' : ''}${p.unrealized_pnl.toFixed(2)}), ` +
      `entry ${p.entry_price.toFixed(2)}, now ${p.current_price.toFixed(2)}, ` +
      `qty ${p.quantity}. Hold / trim / add / cut? Give me a one-paragraph case, ` +
      `then one line on the catalyst to watch.`
    onJumpToChat(prompt)
  }

  return (
    <Card className="h-full flex flex-col" data-testid="portfolio-heatmap-widget">
      <CardHeader
        title="Portfolio Heatmap"
        subtitle={
          account
            ? `equity $${fmtNum(account.equity)} · ` +
              `unrealized ${account.unrealized_pnl >= 0 ? '+' : ''}$${fmtNum(account.unrealized_pnl)} ` +
              `(${account.total_pnl_pct >= 0 ? '+' : ''}${fmtNum(account.total_pnl_pct)}%)`
            : '—'
        }
        right={
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              refreshPaperPrices(projectId).catch(() => {})
              posQ.refetch()
              acctQ.refetch()
            }}
            disabled={posQ.isFetching}
          >
            <RefreshCw size={11} className={posQ.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-1 overflow-hidden p-2">
        {/* Summary strip */}
        {account && (
          <div className="grid grid-cols-4 gap-2 text-[10px] px-1 pb-2 border-b border-[var(--color-border)]">
            <Stat label="Cash" value={`$${fmtNum(account.cash)}`} />
            <Stat label="Positions" value={String(account.positions)} />
            <Stat label="Realized" value={`$${fmtNum(account.realized_pnl)}`}
              tone={account.realized_pnl >= 0 ? 'pos' : 'neg'} />
            <Stat label="Win Rate" value={`${Math.round(account.win_rate * 100) || 0}%`} />
          </div>
        )}

        {/* Table header */}
        <div className="grid grid-cols-[4rem_3rem_5.5rem_3.5rem_1fr_1.5rem] gap-2 items-center px-1 text-[9px] uppercase tracking-wider text-[var(--color-dim)] border-b border-[var(--color-border)]/50 pb-1">
          <span>Symbol</span>
          <span className="text-right">Qty</span>
          <span>Entry → Now</span>
          <span className="text-right">P&L$</span>
          <span>P&L% / risk bar</span>
          <span />
        </div>

        <div className="flex-1 overflow-y-auto" data-testid="portfolio-rows">
          {posQ.isLoading && (
            <div className="text-[var(--color-dim)] text-xs p-2">loading…</div>
          )}
          {posQ.isError && (
            <div className="text-[var(--color-red)] text-[11px] p-2">
              {(posQ.error as Error).message.slice(0, 200)}
            </div>
          )}
          {!posQ.isLoading && positions.length === 0 && (
            <div className="text-[var(--color-dim)] italic text-[11px] text-center p-4">
              Empty — open a position from the Paper tab and it will show up here.
            </div>
          )}
          {positions.map(p => (
            <PositionRow key={p.symbol} p={p} onAsk={onJumpToChat ? () => ask(p) : undefined} />
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

interface StatProps { label: string; value: string; tone?: 'pos' | 'neg' }
function Stat({ label, value, tone }: StatProps) {
  const cls =
    tone === 'pos' ? 'text-[var(--color-green)]' :
    tone === 'neg' ? 'text-[var(--color-red)]' : 'text-[var(--color-text)]'
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">{label}</div>
      <div className={cn('font-mono', cls)}>{value}</div>
    </div>
  )
}

interface RowProps {
  p: PaperPosition
  onAsk?: () => void
}

function PositionRow({ p, onAsk }: RowProps) {
  const pct = p.unrealized_pnl_pct
  const pnl = p.unrealized_pnl
  const up = pnl >= 0
  const frac = Math.max(-1, Math.min(1, pct / BAND_CLAMP))
  const barColor = pnlColor(pct)
  const tint = rowTint(pct)
  const pnlCls = up ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'

  return (
    <div
      data-testid={`portfolio-row-${p.symbol}`}
      className={cn(
        'grid grid-cols-[4rem_3rem_5.5rem_3.5rem_1fr_1.5rem] gap-2 items-center px-1 py-1 text-[11px] font-mono border-b border-[var(--color-border)]/30 hover:bg-[var(--color-border)]/15',
        tint,
      )}
    >
      <span className="text-[var(--color-text)] truncate">{p.symbol}</span>
      <span className="text-right text-[var(--color-dim)]">{fmtNum(p.quantity)}</span>
      <span className="text-[var(--color-dim)]">
        {fmtNum(p.entry_price)} → <span className="text-[var(--color-text)]">{fmtNum(p.current_price)}</span>
      </span>
      <span className={cn('text-right', pnlCls)}>
        {up ? '+' : ''}{fmtNum(pnl)}
      </span>
      <div className="flex items-center gap-2">
        <div className="relative flex-1 h-3 bg-[var(--color-border)]/30 rounded-sm overflow-hidden">
          <div
            className="absolute top-0 bottom-0"
            style={{
              left: up ? '50%' : `${50 - Math.abs(frac) * 50}%`,
              width: `${Math.abs(frac) * 50}%`,
              backgroundColor: barColor,
              opacity: 0.55,
            }}
          />
          <div className="absolute top-0 bottom-0 left-1/2 w-px bg-[var(--color-border)]" />
        </div>
        <span
          className={cn('w-12 text-right', pnlCls)}
          data-testid={`portfolio-pnl-pct-${p.symbol}`}
        >
          {up ? '+' : ''}{fmtNum(pct)}%
        </span>
      </div>
      <button
        data-testid={`portfolio-ask-${p.symbol}`}
        onClick={onAsk}
        disabled={!onAsk}
        className="text-[var(--color-dim)] hover:text-[var(--color-accent)] disabled:opacity-0 transition"
        title="ask fin about this position"
      >
        <MessageSquare size={11} />
      </button>
    </div>
  )
}
