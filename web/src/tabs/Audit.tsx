import { useEffect, useState } from 'react'
import { useAuditRecent, useAuditStats, type AuditEntry } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtTs } from '@/lib/utils'
import { ChevronDown, ChevronRight, RefreshCw, X, Copy, Check } from 'lucide-react'
import { PastRunsView } from '@/components/widgets/PastRunsView'

type KindFilter = '' | 'request' | 'response' | 'error'

interface Props {
  /** When set (e.g. via jump from chat), pre-populates the search
   *  box and auto-expands matching entries on first render. */
  initialReqFilter?: string | null
  /** Called after we consume the incoming filter so the parent
   *  can clear it (prevents re-applying on tab re-entry). */
  onConsumeFilter?: () => void
}

export function AuditTab({ initialReqFilter, onConsumeFilter }: Props) {
  const [kind, setKind] = useState<KindFilter>('')
  const [limit, setLimit] = useState(50)
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const recent = useAuditRecent({ limit, kind: kind || undefined, days: 1 })
  const stats = useAuditStats(1)

  // When a filter comes in from chat "raw" button, seed the search
  // box + expand any entry whose req_id matches. One-shot: consume
  // via callback so leaving + re-entering the tab doesn't re-apply.
  useEffect(() => {
    if (!initialReqFilter) return
    setSearch(initialReqFilter)
    if (recent.data?.entries) {
      const nextOpen = new Set(expanded)
      recent.data.entries.forEach((e, i) => {
        if (e.req_id.startsWith(initialReqFilter)) {
          nextOpen.add(entryKey(e, i))
        }
      })
      setExpanded(nextOpen)
    }
    onConsumeFilter?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialReqFilter, recent.data])

  const entries = recent.data?.entries ?? []
  const filtered = search.trim()
    ? entries.filter(e => JSON.stringify(e).toLowerCase().includes(search.toLowerCase()))
    : entries

  function toggle(key: string) {
    const next = new Set(expanded)
    if (next.has(key)) next.delete(key); else next.add(key)
    setExpanded(next)
  }

  function entryKey(e: AuditEntry, i: number): string {
    return `${e.req_id}-${e.kind}-${i}`
  }

  const s = stats.data

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-[var(--color-panel)] border-b border-[var(--color-border)]">
        <div className="text-[var(--color-text)] font-semibold">Agent Audit</div>
        {s && (
          <div className="text-[11px] text-[var(--color-dim)]">
            {s.total_entries} entries · {s.tokens_in.toLocaleString()} in / {s.tokens_out.toLocaleString()} out tokens · today
          </div>
        )}
        <div className="flex-1" />
        <div className="relative">
          <Input
            placeholder="search content / task_id / req_id"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-72 pr-6"
            data-testid="audit-search"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-1 top-1/2 -translate-y-1/2 text-[var(--color-dim)] hover:text-[var(--color-text)]"
              title="clear"
            >
              <X size={11} />
            </button>
          )}
        </div>
        <select
          value={kind}
          onChange={e => setKind(e.target.value as KindFilter)}
          className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-xs py-1.5"
          data-testid="audit-kind-filter"
        >
          <option value="">all kinds</option>
          <option value="request">request</option>
          <option value="response">response</option>
          <option value="error">error</option>
        </select>
        <select
          value={limit}
          onChange={e => setLimit(parseInt(e.target.value, 10))}
          className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-xs py-1.5"
        >
          {[50, 100, 200, 500].map(n => <option key={n}>{n}</option>)}
        </select>
        <Button variant="ghost" size="sm" onClick={() => recent.refetch()}>
          <RefreshCw size={11} className={recent.isFetching ? 'animate-spin' : ''} />
        </Button>
      </div>

      {/* Phase 6 followup #1: detailed past run log — scheduler /
          analysis_runs history. Lives at top of Audit so the user
          sees data-side activity (who ran, when, status) right next
          to LLM-side activity (audit entries below). */}
      <div className="px-3 pt-3">
        <PastRunsView title="Past runs (scheduler + manual)" />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2" data-testid="audit-list">
        {recent.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
        {recent.isError && <div className="text-[var(--color-red)] text-xs">{(recent.error as Error).message}</div>}
        {filtered.length === 0 && !recent.isLoading && (
          <div className="text-[var(--color-dim)] italic text-center p-8 text-xs">
            no entries match current filters
          </div>
        )}
        {filtered.map((e, i) => (
          <div key={entryKey(e, i)} className="shrink-0">
            <AuditEntryCard
              entry={e}
              open={expanded.has(entryKey(e, i))}
              onToggle={() => toggle(entryKey(e, i))}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

function AuditEntryCard({
  entry,
  open,
  onToggle,
}: {
  entry: AuditEntry
  open: boolean
  onToggle: () => void
}) {
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState(false)

  const badge = {
    request: 'bg-[var(--color-blue)]/20 text-[var(--color-blue)]',
    response: 'bg-[var(--color-green)]/20 text-[var(--color-green)]',
    error: 'bg-[var(--color-red)]/25 text-[var(--color-red)]',
  }[entry.kind]

  const p = entry.payload as Record<string, unknown>
  const model = (p?.model as string) ?? ''
  const contentLen = entry.kind === 'response' ? String(p?.content ?? '').length : undefined
  const usage = (p?.usage as Record<string, number> | undefined)
  const dur = p?.duration_ms as number | undefined

  async function copyRaw() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(entry, null, 2))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard access denied; ignore
    }
  }

  return (
    <Card>
      <div
        className="px-3 py-2 cursor-pointer flex items-center gap-3 text-[11px] hover:bg-[var(--color-border)]/30"
        onClick={onToggle}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className={`uppercase tracking-wider px-2 py-0.5 rounded font-semibold ${badge}`}>
          {entry.kind}
        </span>
        <span className="text-[var(--color-dim)]">{fmtTs(entry.ts)}</span>
        <code className="text-[var(--color-text)] text-[10px]">req {entry.req_id.slice(0, 8)}</code>
        <code className="text-[var(--color-dim)] text-[10px]">task {entry.task_id?.slice(0, 14) ?? '-'}</code>
        <span className="text-[var(--color-dim)]">{entry.agent_id}</span>
        <span className="flex-1" />
        {model && <span className="text-[var(--color-dim)]">{model}</span>}
        {contentLen !== undefined && <span className="text-[var(--color-accent)]">{contentLen}c</span>}
        {usage?.total_tokens != null && <span className="text-[var(--color-text)]">{usage.total_tokens}tok</span>}
        {dur != null && <span className="text-[var(--color-text)]">{dur}ms</span>}
      </div>
      {open && (
        <div className="px-4 pb-3 border-t border-[var(--color-border)] text-[11px]">
          {/* Toggle: pretty view ↔ raw JSON */}
          <div className="flex gap-2 items-center mt-3 mb-1">
            <div className="flex gap-1">
              <button
                onClick={() => setShowRaw(false)}
                data-testid="audit-view-pretty"
                className={
                  'px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border transition ' +
                  (!showRaw
                    ? 'bg-[var(--color-border)] text-[var(--color-accent)] border-[var(--color-accent)]'
                    : 'text-[var(--color-dim)] border-[var(--color-border)] hover:text-[var(--color-text)]')
                }
              >
                pretty
              </button>
              <button
                onClick={() => setShowRaw(true)}
                data-testid="audit-view-raw"
                className={
                  'px-2 py-0.5 text-[10px] uppercase tracking-wider rounded border transition ' +
                  (showRaw
                    ? 'bg-[var(--color-border)] text-[var(--color-accent)] border-[var(--color-accent)]'
                    : 'text-[var(--color-dim)] border-[var(--color-border)] hover:text-[var(--color-text)]')
                }
              >
                raw JSON
              </button>
            </div>
            <div className="flex-1" />
            <button
              onClick={copyRaw}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] text-[var(--color-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] rounded"
              title="copy full entry as JSON"
              data-testid="audit-copy-raw"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              {copied ? 'copied' : 'copy'}
            </button>
          </div>

          {showRaw ? (
            <div data-testid="audit-raw-json">
              <SectionLabel>
                Full entry (everything that was written to ~/Desktop/Investment/_audit/YYYY-MM-DD.jsonl)
              </SectionLabel>
              <pre className="whitespace-pre-wrap break-words text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2 max-h-[60vh] overflow-y-auto">
                {JSON.stringify(entry, null, 2)}
              </pre>
            </div>
          ) : (
            <>
              {entry.kind === 'request' && (
                <>
                  <SectionLabel>Messages ({((p.messages as unknown[]) ?? []).length} turns)</SectionLabel>
                  {((p.messages as Array<{ role: string; content: string }>) ?? []).map((m, i) => (
                    <div key={i} className="bg-[#0e1219] border border-[var(--color-border)] rounded p-2 mb-1.5">
                      <div className="text-[10px] text-[var(--color-accent)] uppercase">{m.role}</div>
                      <pre className="whitespace-pre-wrap break-words mt-1 text-[11px]">{m.content}</pre>
                    </div>
                  ))}
                  <SectionLabel>Params</SectionLabel>
                  <JsonBlock data={{ model: p.model, max_tokens: p.max_tokens, temperature: p.temperature }} />
                </>
              )}
              {entry.kind === 'response' && (
                <>
                  <SectionLabel>Content ({contentLen}c)</SectionLabel>
                  <pre className="whitespace-pre-wrap break-words text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2">
                    {String(p.content ?? '')}
                  </pre>
                  {typeof p.reasoning_content === 'string' && p.reasoning_content.length > 0 && (
                    <>
                      <SectionLabel>Reasoning content ({p.reasoning_content.length}c)</SectionLabel>
                      <pre className="whitespace-pre-wrap break-words text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2 max-h-60 overflow-y-auto">
                        {p.reasoning_content}
                      </pre>
                    </>
                  )}
                  <SectionLabel>Usage · finish</SectionLabel>
                  <JsonBlock data={{ usage, finish_reason: p.finish_reason, duration_ms: dur }} />
                </>
              )}
              {entry.kind === 'error' && (
                <>
                  <SectionLabel>Error</SectionLabel>
                  <pre className="whitespace-pre-wrap text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2">
                    {String(p.error_type)}: {String(p.error_msg)}
                  </pre>
                  {p.traceback != null && (
                    <>
                      <SectionLabel>Traceback</SectionLabel>
                      <pre className="whitespace-pre-wrap text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2 max-h-60 overflow-y-auto">
                        {String(p.traceback)}
                      </pre>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] mt-3 mb-1">{children}</div>
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="whitespace-pre-wrap text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
