import { useMemo } from 'react'
import { useResearchBrief, useAnomalies } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { CitedText } from '@/components/ui/CitedText'
import { Sparkles, RefreshCw, MessageSquare, AlertTriangle } from 'lucide-react'

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

/**
 * Narrative hero for the Research tab. Pattern: Robinhood Cortex
 * Digests / Bloomberg ASKB summaries — the agent writes a short
 * prose read, widgets below are the evidence. Auto-refreshes every
 * 5 min; the server already caches on the same interval so the LLM
 * isn't hit on every page paint.
 *
 * Rejected the "drawer chat" pattern because (a) it still forces a
 * context-switch into a chat mental mode and (b) external research
 * calls it fake-sophistication. Inline narrative is the primitive.
 */
export function ResearchBriefWidget({ projectId, onJumpToChat }: Props) {
  const q = useResearchBrief(projectId)
  const anomalies = useAnomalies(projectId)

  const lines = useMemo(() => {
    const txt = q.data?.text ?? ''
    // The backend prompt pins three labelled lines: "Market:", "Book:",
    // "Next:". Split by newline and tolerate a model that adds blank
    // lines or minor drift. Fallback: render the whole thing as one
    // paragraph so we never show nothing.
    const raw = txt.split('\n').map(s => s.trim()).filter(Boolean)
    if (raw.length < 3) return raw.length ? raw : [txt]
    return raw.slice(0, 3)
  }, [q.data?.text])

  const askMore = () => onJumpToChat?.(
    'Expand on the current market/book/next read: what would change the call?',
    { project: true },
  )

  return (
    <div
      data-testid="research-brief-widget"
      className="h-full flex flex-col bg-[var(--color-panel)] border border-[var(--color-border)] rounded-md overflow-hidden"
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--color-border)] shrink-0">
        <Sparkles size={12} className="text-[var(--color-accent)]" />
        <span className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] flex-1">
          Today's read · agent synthesis
          {q.data?.fetched_at && (
            <span className="ml-2 text-[var(--color-dim)]/80">
              updated {new Date(q.data.fetched_at).toLocaleTimeString()}
            </span>
          )}
        </span>
        {onJumpToChat && (
          <Button
            size="sm"
            variant="ghost"
            onClick={askMore}
            data-testid="brief-ask-more"
            title="dig deeper in chat (project context attached)"
          >
            <MessageSquare size={11} />
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => q.refetch()}
          disabled={q.isFetching}
          data-testid="brief-refresh"
          title="force a fresh read (bypasses the 5-min cache)"
        >
          <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
        </Button>
      </div>
      {/* Anomaly flag strip — renders only when flags exist */}
      {(anomalies.data?.flags?.length ?? 0) > 0 && (
        <div
          data-testid="anomaly-flags"
          className="flex flex-wrap gap-1 px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg)]/40"
        >
          {anomalies.data!.flags.slice(0, 6).map((f, i) => {
            const color =
              f.severity === 'alert' ? 'var(--color-red)' :
              f.severity === 'warn' ? 'var(--color-amber, #e5a200)' :
              'var(--color-accent)'
            return (
              <button
                key={i}
                data-testid={`anomaly-flag-${f.kind}-${f.symbol}`}
                onClick={() => onJumpToChat?.(
                  `Dig into this flag: "${f.message}". What should I actually do about it?`,
                  { symbol: f.symbol },
                )}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border whitespace-nowrap transition"
                style={{ color, borderColor: color }}
                title={`[${f.severity.toUpperCase()}] ${f.kind} · click to ask fin`}
              >
                <AlertTriangle size={9} />
                {f.message}
              </button>
            )
          })}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-3 text-[12px] leading-[1.6]" data-testid="brief-body">
        {q.isLoading && (
          <div className="text-[var(--color-dim)] italic">loading today's read…</div>
        )}
        {q.isError && (
          <div className="text-[var(--color-red)] text-[11px]">
            {(q.error as Error).message.slice(0, 200)}
          </div>
        )}
        {!q.isLoading && !q.isError && lines.length > 0 && (
          <div className="flex flex-col gap-1">
            {lines.map((line, i) => {
              const m = line.match(/^(Market|Book|Next)[:：]\s*(.*)$/)
              if (m) {
                return (
                  <div key={i} className="flex gap-2" data-testid={`brief-line-${m[1].toLowerCase()}`}>
                    <span className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] w-14 shrink-0 pt-0.5">
                      {m[1]}
                    </span>
                    <span className="flex-1 text-[var(--color-text)]">
                      <CitedText
                        text={m[2]}
                        onCiteClick={cite => {
                          if (!onJumpToChat) return
                          if (cite.kind === 'sector') {
                            onJumpToChat(
                              `What's driving the ${cite.id} sector right now?`,
                              { project: true },
                            )
                          } else {
                            onJumpToChat(
                              `Expand on ${cite.id}: what's the current setup and risk?`,
                              { symbol: cite.id },
                            )
                          }
                        }}
                      />
                    </span>
                  </div>
                )
              }
              return (
                <div key={i} className="text-[var(--color-text)]">
                  <CitedText text={line} />
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
