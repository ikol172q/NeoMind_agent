import { useHistory } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { fmtTs } from '@/lib/utils'

interface Props { projectId: string }

export function HistoryTable({ projectId }: Props) {
  const h = useHistory(projectId, 30)
  return (
    <Card className="h-full flex flex-col">
      <CardHeader title="Analysis History" subtitle={projectId} />
      <CardBody className="flex-1 overflow-y-auto p-0">
        {h.isLoading && <div className="p-3 text-[var(--color-dim)] text-xs">loading…</div>}
        {!h.data?.items?.length && !h.isLoading && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">
            no analyses yet for this project
          </div>
        )}
        <table className="w-full text-[11px]">
          {h.data?.items?.length ? (
            <thead>
              <tr className="text-[var(--color-dim)] border-b border-[var(--color-border)]">
                <th className="text-left px-3 py-2 font-normal">when</th>
                <th className="text-left px-2 py-2 font-normal">symbol</th>
                <th className="text-left px-2 py-2 font-normal">signal</th>
                <th className="text-left px-2 py-2 font-normal">conf</th>
                <th className="text-left px-2 py-2 font-normal">risk</th>
                <th className="text-left px-3 py-2 font-normal">reason</th>
              </tr>
            </thead>
          ) : null}
          <tbody>
            {h.data?.items?.map((it, i) => {
              const s = it.signal ?? {}
              const col =
                s.signal === 'buy' ? 'text-[var(--color-green)]' :
                s.signal === 'sell' ? 'text-[var(--color-red)]' :
                'text-[var(--color-yellow)]'
              return (
                <tr key={i} className="border-b border-[var(--color-border)]/60">
                  <td className="px-3 py-1.5 text-[var(--color-dim)]">{fmtTs(it.written_at)}</td>
                  <td className="px-2 py-1.5 font-semibold">{it.symbol}</td>
                  <td className={`px-2 py-1.5 font-semibold ${col}`}>{s.signal ?? '—'}</td>
                  <td className="px-2 py-1.5">{s.confidence ?? '—'}</td>
                  <td className="px-2 py-1.5">{s.risk_level ?? '—'}</td>
                  <td className="px-3 py-1.5 text-[var(--color-dim)]">{(s.reason ?? '').slice(0, 80)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </CardBody>
    </Card>
  )
}
