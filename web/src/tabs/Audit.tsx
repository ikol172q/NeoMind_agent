import { useState } from 'react'
import { useAuditRecent, useAuditStats, type AuditEntry } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { fmtTs } from '@/lib/utils'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'

type KindFilter = '' | 'request' | 'response' | 'error'

export function AuditTab() {
  const [kind, setKind] = useState<KindFilter>('')
  const [limit, setLimit] = useState(50)
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const recent = useAuditRecent({ limit, kind: kind || undefined, days: 1 })
  const stats = useAuditStats(1)

  const entries = recent.data?.entries ?? []
  const filtered = search.trim()
    ? entries.filter(e => JSON.stringify(e).toLowerCase().includes(search.toLowerCase()))
    : entries

  function toggle(key: string) {
    const next = new Set(expanded)
    if (next.has(key)) next.delete(key); else next.add(key)
    setExpanded(next)
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
        <Input
          placeholder="search content / task_id / req_id"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-72"
          data-testid="audit-search"
        />
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
          <AuditEntryCard
            key={e.req_id + '-' + e.kind + '-' + i}
            entry={e}
            open={expanded.has(e.req_id + '-' + e.kind + '-' + i)}
            onToggle={() => toggle(e.req_id + '-' + e.kind + '-' + i)}
          />
        ))}
      </div>
    </div>
  )
}

function AuditEntryCard({ entry, open, onToggle }: { entry: AuditEntry; open: boolean; onToggle: () => void }) {
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
          {entry.kind === 'request' && (
            <>
              <SectionLabel>Messages ({((p.messages as unknown[]) ?? []).length} turns)</SectionLabel>
              {((p.messages as Array<{role: string; content: string}>) ?? []).map((m, i) => (
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
              {p.reasoning_content && String(p.reasoning_content).length > 0 && (
                <>
                  <SectionLabel>Reasoning content</SectionLabel>
                  <pre className="whitespace-pre-wrap break-words text-[11px] bg-[#0e1219] border border-[var(--color-border)] rounded p-2 max-h-60 overflow-y-auto">
                    {String(p.reasoning_content)}
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
