import { useState } from 'react'
import { useQuote } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtNum } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'

export function USQuoteCard() {
  const [symbol, setSymbol] = useState('AAPL')
  const [committed, setCommitted] = useState<string | null>('AAPL')
  const q = useQuote(committed)
  const d = q.data

  function submit() {
    const s = symbol.trim().toUpperCase()
    if (s) setCommitted(s)
  }

  const chg = d?.change ?? 0
  const pct = d?.change_pct ?? 0
  const up = chg >= 0
  const color = up ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'

  return (
    <Card className="h-full flex flex-col">
      <CardHeader
        title="US Quote"
        subtitle={d?.name || committed || ''}
        right={
          <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-3">
        <div className="flex gap-2">
          <Input
            value={symbol}
            onChange={e => setSymbol(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            placeholder="AAPL"
            className="flex-1 uppercase"
          />
          <Button onClick={submit}>Get</Button>
        </div>
        {q.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
        {q.isError && <div className="text-[var(--color-red)] text-xs">{(q.error as Error).message}</div>}
        {d && (
          <div className="flex-1 flex flex-col justify-center gap-2">
            <div className="text-2xl font-semibold">${fmtNum(d.price)}</div>
            <div className={`text-xs ${color}`}>
              {up ? '▲' : '▼'} {fmtNum(chg)} ({fmtNum(pct)}%)
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] text-[var(--color-dim)] mt-2">
              <div>High: <span className="text-[var(--color-text)]">${fmtNum(d.high)}</span></div>
              <div>Low: <span className="text-[var(--color-text)]">${fmtNum(d.low)}</span></div>
              <div>Open: <span className="text-[var(--color-text)]">${fmtNum(d.open)}</span></div>
              <div>Volume: <span className="text-[var(--color-text)]">{d.volume?.toLocaleString?.() ?? '—'}</span></div>
            </div>
            <div className="text-[10px] text-[var(--color-dim)] mt-1">
              {d.source} · {d.market_status}
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
