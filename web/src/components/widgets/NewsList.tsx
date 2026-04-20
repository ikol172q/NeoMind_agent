import { useState } from 'react'
import { useNews, useNewsCategories } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn, fmtRelativeTime } from '@/lib/utils'
import { RefreshCw, ExternalLink } from 'lucide-react'

/**
 * News widget with category tabs (US / Tech / Global / A-Shares /
 * Macro, whatever Miniflux has populated). A synthetic "All" tab is
 * always present and sends no category filter.
 *
 * Each entry is both an anchor (for right-click / middle-click to new
 * tab) AND has an explicit onClick handler that calls window.open —
 * the grid-drag wrapper was previously swallowing link activations,
 * and even after adding `a` to draggableCancel, an explicit open is
 * cheap insurance on the click path.
 */
export function NewsList() {
  const cats = useNewsCategories()
  const [activeCat, setActiveCat] = useState<number | null>(null) // null = All

  const n = useNews({ limit: 30, categoryId: activeCat })

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
      {/* Tab bar */}
      <div
        className="flex gap-1 px-3 py-1.5 border-b border-[var(--color-border)] overflow-x-auto"
        data-testid="news-tabs"
      >
        <TabButton
          label="All"
          active={activeCat === null}
          onClick={() => setActiveCat(null)}
          testId="news-tab-all"
        />
        {cats.data?.categories?.map(c => (
          <TabButton
            key={c.id}
            label={c.title}
            count={c.feed_count}
            active={activeCat === c.id}
            onClick={() => setActiveCat(c.id)}
            testId={`news-tab-${c.title.toLowerCase().replace(/[^a-z0-9]/g, '-')}`}
          />
        ))}
      </div>
      <CardBody className="flex-1 overflow-y-auto p-0" data-testid="news-entries">
        {n.isLoading && <div className="p-3 text-[var(--color-dim)] text-xs">loading…</div>}
        {n.isError && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">
            news unavailable · {(n.error as Error).message.slice(0, 200)}
          </div>
        )}
        {n.data?.entries?.length === 0 && (
          <div className="p-3 text-[var(--color-dim)] text-[11px] italic">
            no entries in this category — add feeds at{' '}
            <a
              href="http://127.0.0.1:8080"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--color-accent)] underline"
            >
              http://127.0.0.1:8080
            </a>
          </div>
        )}
        {n.data?.entries?.map(e => (
          <a
            key={e.id}
            href={e.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={`news-entry-${e.id}`}
            onClick={(ev) => {
              // Belt + suspenders: react-grid-layout's drag wrapper
              // has, in the past, eaten link activation on mouseup.
              // Explicitly open so the click always lands.
              ev.preventDefault()
              window.open(e.url, '_blank', 'noopener,noreferrer')
            }}
            className="group block px-3 py-2 border-b border-[var(--color-border)] hover:bg-[var(--color-border)]/30 transition cursor-pointer"
          >
            <div className="flex items-start gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-[12px] leading-snug">{e.title}</div>
                <div className="flex gap-3 mt-1 text-[10px] text-[var(--color-dim)]">
                  <span className="truncate max-w-[160px]">{e.feed_title}</span>
                  <span>{fmtRelativeTime(e.published_at)}</span>
                </div>
              </div>
              <ExternalLink
                size={11}
                className="text-[var(--color-dim)] opacity-0 group-hover:opacity-100 transition shrink-0 mt-0.5"
              />
            </div>
          </a>
        ))}
      </CardBody>
    </Card>
  )
}

interface TabProps {
  label: string
  count?: number
  active: boolean
  onClick: () => void
  testId: string
}

function TabButton({ label, count, active, onClick, testId }: TabProps) {
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      className={cn(
        'px-2 py-1 text-[10px] uppercase tracking-wider rounded whitespace-nowrap transition',
        active
          ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
          : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/40',
      )}
    >
      {label}
      {count != null && <span className="ml-1 text-[9px] opacity-70">({count})</span>}
    </button>
  )
}
