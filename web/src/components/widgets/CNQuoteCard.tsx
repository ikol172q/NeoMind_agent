import { useState } from 'react'
import { useCNQuote } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtNum } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'

export function CNQuoteCard() {
  const [code, setCode] = useState('600519')
  const [committed, setCommitted] = useState<string | null>('600519')
  const q = useCNQuote(committed)
  const d = q.data

  function submit() {
    const c = code.trim()
    if (/^\d{6}$/.test(c)) setCommitted(c)
  }

  const pct = d?.change_pct ?? 0
  const up = pct >= 0
  const color = up ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'

  return (
    <Card className="h-full flex flex-col">
      <CardHeader
        title="A股 Quote"
        subtitle={committed ? `${committed}` : ''}
        right={
          <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-3">
        <div className="flex gap-2">
          <Input
            value={code}
            onChange={e => setCode(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            placeholder="600519"
            className="flex-1"
          />
          <Button onClick={submit}>查</Button>
        </div>
        {q.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
        {q.isError && <div className="text-[var(--color-red)] text-xs">{(q.error as Error).message}</div>}
        {d && (
          <div className="flex-1 flex flex-col justify-center gap-2">
            <div className="text-2xl font-semibold">¥{fmtNum(d.price)}</div>
            <div className={`text-xs ${color}`}>
              {up ? '▲' : '▼'} {fmtNum(d.change)} ({fmtNum(pct)}%)
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] text-[var(--color-dim)] mt-2">
              <div>今开: <span className="text-[var(--color-text)]">¥{fmtNum(d.open)}</span></div>
              <div>昨收: <span className="text-[var(--color-text)]">¥{fmtNum(d.prev_close)}</span></div>
              <div>最高: <span className="text-[var(--color-text)]">¥{fmtNum(d.high)}</span></div>
              <div>最低: <span className="text-[var(--color-text)]">¥{fmtNum(d.low)}</span></div>
              <div>涨停: <span className="text-[var(--color-green)]">¥{fmtNum(d.limit_up)}</span></div>
              <div>跌停: <span className="text-[var(--color-red)]">¥{fmtNum(d.limit_down)}</span></div>
              <div>换手: <span className="text-[var(--color-text)]">{fmtNum(d.turnover_rate_pct, 2)}%</span></div>
              <div>成交: <span className="text-[var(--color-text)]">{d.volume?.toLocaleString?.() ?? '—'}</span></div>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
