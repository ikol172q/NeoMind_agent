import { useState } from 'react'
import { useCNInfo } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtCap } from '@/lib/utils'

export function CNInfoCard() {
  const [code, setCode] = useState('600519')
  const [committed, setCommitted] = useState<string | null>('600519')
  const i = useCNInfo(committed)
  const d = i.data

  function submit() {
    const c = code.trim()
    if (/^\d{6}$/.test(c)) setCommitted(c)
  }

  return (
    <Card className="h-full flex flex-col">
      <CardHeader title="A股 基本面" subtitle={d?.name ?? committed ?? ''} />
      <CardBody className="flex-1 flex flex-col gap-3">
        <div className="flex gap-2">
          <Input value={code} onChange={e => setCode(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()} placeholder="600519" className="flex-1" />
          <Button onClick={submit}>查</Button>
        </div>
        {i.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
        {i.isError && <div className="text-[var(--color-red)] text-xs">{(i.error as Error).message}</div>}
        {d && (
          <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-xs flex-1">
            <div className="text-[var(--color-dim)]">行业</div>
            <div>{d.industry ?? '—'}</div>
            <div className="text-[var(--color-dim)]">总市值</div>
            <div>{fmtCap(d.market_cap)}</div>
            <div className="text-[var(--color-dim)]">流通市值</div>
            <div>{fmtCap(d.float_market_cap)}</div>
            <div className="text-[var(--color-dim)]">总股本</div>
            <div>{d.total_shares?.toLocaleString?.() ?? '—'}</div>
            <div className="text-[var(--color-dim)]">流通股</div>
            <div>{d.float_shares?.toLocaleString?.() ?? '—'}</div>
            <div className="text-[var(--color-dim)]">上市</div>
            <div>{d.listed_date ?? '—'}</div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
