import { useState } from 'react'
import { usePaperAccount, usePaperPositions, usePaperTrades, usePaperOrder } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtNum } from '@/lib/utils'

type OrderSide = 'buy' | 'sell'
type OrderType = 'market' | 'limit' | 'stop'

interface Props { projectId: string }

export function PaperAccountCard({ projectId }: Props) {
  const a = usePaperAccount(projectId)
  const d = a.data as Record<string, any> | undefined
  if (!d) {
    return (
      <Card className="h-full"><CardHeader title="Paper Account" subtitle={projectId} />
        <CardBody>{a.isLoading ? 'loading…' : a.error ? (a.error as Error).message : '—'}</CardBody>
      </Card>
    )
  }
  const pnl = d.total_pnl ?? 0
  const col = pnl > 0 ? 'text-[var(--color-green)]' : pnl < 0 ? 'text-[var(--color-red)]' : ''
  return (
    <Card className="h-full">
      <CardHeader title="Paper Account" subtitle={projectId} />
      <CardBody>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <div><div className="text-[var(--color-dim)] text-[10px]">Cash</div><div className="text-sm">${fmtNum(d.cash)}</div></div>
          <div><div className="text-[var(--color-dim)] text-[10px]">Equity</div><div className="text-sm">${fmtNum(d.equity)}</div></div>
          <div><div className="text-[var(--color-dim)] text-[10px]">Total PnL</div><div className={`text-sm ${col}`}>${fmtNum(pnl)} ({fmtNum(d.total_pnl_pct)}%)</div></div>
          <div><div className="text-[var(--color-dim)] text-[10px]">Realized</div><div>${fmtNum(d.realized_pnl)}</div></div>
          <div><div className="text-[var(--color-dim)] text-[10px]">Unrealized</div><div>${fmtNum(d.unrealized_pnl)}</div></div>
          <div><div className="text-[var(--color-dim)] text-[10px]">Trades</div><div>{d.total_trades} ({fmtNum(d.win_rate, 0)}% win)</div></div>
        </div>
      </CardBody>
    </Card>
  )
}

export function PaperPositionsTable({ projectId }: Props) {
  const p = usePaperPositions(projectId)
  const rows = (p.data?.positions ?? []) as Array<Record<string, any>>
  return (
    <Card className="h-full flex flex-col">
      <CardHeader title="Positions" subtitle={`${rows.length} open`} />
      <CardBody className="flex-1 overflow-y-auto p-0">
        {!rows.length && !p.isLoading && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">no positions</div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-[var(--color-dim)] border-b border-[var(--color-border)]">
                <th className="text-left px-3 py-2 font-normal">Symbol</th>
                <th className="text-left px-2 py-2 font-normal">Side</th>
                <th className="text-right px-2 py-2 font-normal">Qty</th>
                <th className="text-right px-2 py-2 font-normal">Entry</th>
                <th className="text-right px-2 py-2 font-normal">Current</th>
                <th className="text-right px-3 py-2 font-normal">PnL</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const c = (r.unrealized_pnl ?? 0) > 0 ? 'text-[var(--color-green)]' :
                          (r.unrealized_pnl ?? 0) < 0 ? 'text-[var(--color-red)]' : ''
                return (
                  <tr key={i} className="border-b border-[var(--color-border)]/60">
                    <td className="px-3 py-1.5 font-semibold">{r.symbol}</td>
                    <td className="px-2 py-1.5">{r.side}</td>
                    <td className="px-2 py-1.5 text-right">{fmtNum(r.quantity, 0)}</td>
                    <td className="px-2 py-1.5 text-right">${fmtNum(r.entry_price)}</td>
                    <td className="px-2 py-1.5 text-right">${fmtNum(r.current_price)}</td>
                    <td className={`px-3 py-1.5 text-right ${c}`}>
                      ${fmtNum(r.unrealized_pnl)} ({fmtNum(r.unrealized_pnl_pct)}%)
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </CardBody>
    </Card>
  )
}

export function PaperTradesTable({ projectId }: Props) {
  const t = usePaperTrades(projectId, 30)
  const rows = (t.data?.trades ?? []) as Array<Record<string, any>>
  return (
    <Card className="h-full flex flex-col">
      <CardHeader title="Recent Trades" subtitle={`last ${rows.length}`} />
      <CardBody className="flex-1 overflow-y-auto p-0">
        {!rows.length && !t.isLoading && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">no trades yet</div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-[var(--color-dim)] border-b border-[var(--color-border)]">
                <th className="text-left px-3 py-2 font-normal">When</th>
                <th className="text-left px-2 py-2 font-normal">Sym</th>
                <th className="text-left px-2 py-2 font-normal">Side</th>
                <th className="text-right px-2 py-2 font-normal">Qty</th>
                <th className="text-right px-2 py-2 font-normal">Price</th>
                <th className="text-right px-3 py-2 font-normal">PnL</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-[var(--color-border)]/60">
                  <td className="px-3 py-1.5 text-[var(--color-dim)]">{(r.timestamp || '').slice(0, 16)}</td>
                  <td className="px-2 py-1.5 font-semibold">{r.symbol}</td>
                  <td className="px-2 py-1.5">{r.side}</td>
                  <td className="px-2 py-1.5 text-right">{fmtNum(r.quantity, 0)}</td>
                  <td className="px-2 py-1.5 text-right">${fmtNum(r.price)}</td>
                  <td className="px-3 py-1.5 text-right">${fmtNum(r.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardBody>
    </Card>
  )
}

export function PaperOrderForm({ projectId }: Props) {
  const [symbol, setSymbol] = useState('AAPL')
  const [side, setSide] = useState<OrderSide>('buy')
  const [orderType, setOrderType] = useState<OrderType>('market')
  const [qty, setQty] = useState('10')
  const [price, setPrice] = useState('')
  const [msg, setMsg] = useState('')
  const mut = usePaperOrder()

  async function submit() {
    setMsg('')
    try {
      const result = await mut.mutateAsync({
        project_id: projectId,
        symbol: symbol.trim().toUpperCase(),
        side,
        quantity: parseFloat(qty),
        order_type: orderType,
        price: orderType !== 'market' ? parseFloat(price) : undefined,
        stop_price: orderType === 'stop' ? parseFloat(price) : undefined,
      })
      const order = result.order as Record<string, unknown>
      const status = String(order?.status ?? 'unknown')
      if (status === 'filled') {
        setMsg(`✓ ${side} ${qty} ${symbol} @ $${fmtNum(order?.filled_price as number)}`)
      } else if (status === 'rejected') {
        setMsg(`✗ rejected: ${order?.error ?? 'unknown'}`)
      } else {
        setMsg(`${status}: ${symbol}`)
      }
    } catch (e: unknown) {
      setMsg(`✗ ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return (
    <Card className="h-full flex flex-col">
      <CardHeader title="Place Order" subtitle="paper only" />
      <CardBody className="flex-1 flex flex-col gap-2">
        <div className="grid grid-cols-2 gap-2">
          <Input value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="AAPL" className="uppercase" />
          <select value={side} onChange={e => setSide(e.target.value as OrderSide)}
            className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-xs">
            <option value="buy">buy</option>
            <option value="sell">sell</option>
          </select>
          <select value={orderType} onChange={e => setOrderType(e.target.value as OrderType)}
            className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-xs">
            <option value="market">market</option>
            <option value="limit">limit</option>
            <option value="stop">stop</option>
          </select>
          <Input value={qty} onChange={e => setQty(e.target.value)} placeholder="qty" type="number" />
          {orderType !== 'market' && (
            <Input value={price} onChange={e => setPrice(e.target.value)} placeholder="price" type="number"
              className="col-span-2" />
          )}
        </div>
        <Button onClick={submit} disabled={mut.isPending}>
          {mut.isPending ? 'placing…' : `Place ${side}`}
        </Button>
        {msg && <div className="text-xs text-[var(--color-dim)]">{msg}</div>}
      </CardBody>
    </Card>
  )
}
