import { useNews } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { fmtRelativeTime } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'

export function NewsList() {
  const n = useNews({ limit: 20 })
  return (
    <Card className="h-full flex flex-col">
      <CardHeader
        title="News"
        subtitle={n.data ? `${n.data.count} entries` : undefined}
        right={
          <Button size="sm" variant="ghost" onClick={() => n.refetch()} disabled={n.isFetching}>
            <RefreshCw size={11} className={n.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 overflow-y-auto p-0">
        {n.isLoading && <div className="p-3 text-[var(--color-dim)] text-xs">loading…</div>}
        {n.isError && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">
            news unavailable · {(n.error as Error).message.slice(0, 200)}
          </div>
        )}
        {n.data?.entries?.length === 0 && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">
            no entries (add feeds at http://127.0.0.1:8080)
          </div>
        )}
        {n.data?.entries?.map(e => (
          <a
            key={e.id}
            href={e.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block px-3 py-2 border-b border-[var(--color-border)] hover:bg-[var(--color-border)]/30 transition"
          >
            <div className="text-[12px] leading-snug">{e.title}</div>
            <div className="flex gap-3 mt-1 text-[10px] text-[var(--color-dim)]">
              <span>{e.feed_title}</span>
              <span>{fmtRelativeTime(e.published_at)}</span>
            </div>
          </a>
        ))}
      </CardBody>
    </Card>
  )
}
