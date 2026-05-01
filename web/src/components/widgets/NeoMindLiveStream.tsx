/**
 * NeoMindLiveStream — Phase L: real-time agent activity tail.
 *
 * Polling-based for v1 (every 30s).  Shows the last N signal events
 * across all scanners — gives the user transparency into what NeoMind
 * is doing in the background.  This is the "watching the agent think"
 * surface, modeled on Operator/Claude Tools UX but persisted to SQLite
 * so it survives across sessions.
 */
import { useState } from 'react'
import {
  useRecentSignals, useUserWatchlist, useAuditRecent, useRecentRuns,
  type SignalEvent, type AuditEntry, type AnalysisRun,
} from '@/lib/api'


const SEV_COLOR: Record<string, string> = {
  high: 'text-[var(--color-danger)]',
  med:  'text-[var(--color-warn)]',
  low:  'text-[var(--color-dim)]',
}


const KIND_COLOR: Record<string, string> = {
  request:  'text-[var(--color-accent)]',
  response: 'text-[var(--color-success)]',
  error:    'text-[var(--color-danger)]',
}


function relTime(iso: string): string {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return iso
  const secs = (Date.now() - dt.getTime()) / 1000
  if (secs < 60) return `${Math.floor(secs)}s 前`
  if (secs < 3600) return `${Math.floor(secs / 60)}m 前`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h 前`
  return `${Math.floor(secs / 86400)}d 前`
}


const SCANNER_ICON: Record<string, string> = {
  watchlist:    '📊',
  news:         '📰',
  '13f':        '🐋',
  stock_act:    '🏛️',
  earnings:     '💰',
}


type ViewMode = 'scanners' | 'chat' | 'ops' | 'all'


export function NeoMindLiveStream() {
  const [open, setOpen]       = useState(false)
  const [view, setView]       = useState<ViewMode>('scanners')
  const [scannerFilter, setScannerFilter] = useState<string>('')

  const events  = useRecentSignals({
    limit: 100,
    scanner: view === 'scanners' ? (scannerFilter || undefined) : undefined,
  })
  const audit = useAuditRecent({
    limit: 50,
    days: 1,
  })
  const runs = useRecentRuns(50)
  const wl      = useUserWatchlist()

  const universeSize = wl.data?.total_universe.length ?? 0
  const userCount    = wl.data?.user_watchlist.length ?? 0
  const supplyCount  = wl.data?.supply_chain.length ?? 0

  const lastEvent = events.data?.events?.[0]
  const lastTime = lastEvent ? relTime(lastEvent.detected_at) : '—'

  return (
    <div
      data-testid="neomind-live"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40"
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-2.5 py-1.5 flex items-center gap-2 text-[10px] hover:bg-[var(--color-panel)]/30"
      >
        <span className="font-semibold text-[var(--color-text)]">
          🔬 NeoMind Live — agent 实时活动
        </span>
        <span className="text-[9.5px] text-[var(--color-dim)] font-mono">
          扫描中: {userCount} 你 + {supplyCount} 上下游 = {universeSize} 只票
        </span>
        <span className="text-[9.5px] text-[var(--color-dim)] ml-auto">
          last event: {lastTime}
        </span>
        <span className="text-[9px] text-[var(--color-dim)]">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="px-2.5 pb-2.5">
          <div className="flex items-center gap-2 mb-1.5 text-[9px] text-[var(--color-dim)]">
            <span>view:</span>
            <select
              value={view}
              onChange={(e) => setView(e.target.value as ViewMode)}
              className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[9.5px]"
            >
              <option value="scanners">📊 scanners (后台扫)</option>
              <option value="chat">💬 chat (你问 agent 答)</option>
              <option value="ops">⚙️ ops (scanner 运行日志)</option>
              <option value="all">🌐 all (混合按时间)</option>
            </select>
            {view === 'scanners' && (
              <select
                value={scannerFilter}
                onChange={(e) => setScannerFilter(e.target.value)}
                className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[9.5px]"
              >
                <option value="">all scanners</option>
                <option value="watchlist">watchlist (price/RSI/MA)</option>
                <option value="news">news</option>
                <option value="13f">13F whales</option>
                <option value="stock_act">Congressional STOCK Act</option>
                <option value="policy">policy (RSS)</option>
              </select>
            )}
            <span>
              {view === 'scanners'
                ? `${events.data?.n ?? 0} events`
                : view === 'chat'
                ? `${audit.data?.entries?.length ?? 0} llm/tool calls`
                : view === 'ops'
                ? `${runs.data?.n ?? 0} runs`
                : `${(events.data?.n ?? 0)
                   + (audit.data?.entries?.length ?? 0)
                   + (runs.data?.n ?? 0)} merged`}
            </span>
            <span className="ml-auto italic">poll 30s</span>
          </div>

          <div className="font-mono text-[9px] space-y-0.5 max-h-[300px] overflow-y-auto">
            {view === 'scanners' && (
              <ScannerEventsList events={events.data?.events ?? []} />
            )}
            {view === 'chat' && (
              <ChatActivityList entries={audit.data?.entries ?? []} />
            )}
            {view === 'ops' && (
              <RunsList runs={runs.data?.runs ?? []} />
            )}
            {view === 'all' && (
              <MergedActivityList
                events={events.data?.events ?? []}
                entries={audit.data?.entries ?? []}
                runs={runs.data?.runs ?? []}
              />
            )}
          </div>

          <div className="mt-2 text-[8.5px] italic text-[var(--color-dim)] leading-[1.4]">
            {view === 'scanners' && (
              <>
                每条事件落地 SQLite (signal_events) 永久保留。≥2 个独立 scanner
                在 72h 窗口内击中同一 ticker → 自动 promote 成"Today's Signals"。
              </>
            )}
            {view === 'chat' && (
              <>
                来自 chat 面板的每次 LLM 调用 / tool 调用。包含 raw input + output。
                落地 audit log，跟 Audit tab 是同一份数据。
              </>
            )}
            {view === 'ops' && (
              <>
                每次 cron / 立即扫描 / 手动 trigger 都会写一条 analysis_runs 行。
                即使 dedup 把所有事件吃掉 (n_emitted=0)，仍能看到 scanner
                确实跑了 — 这是判断"是不是后台真的在动"的真相来源。
              </>
            )}
            {view === 'all' && (
              <>
                Scanner events + chat agent steps + ops runs 按时间线合并。看 agent 整体在做什么。
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


// ── ScannerEventsList ───────────────────────────────────────────────
// Background scanners (watchlist / news / 13F / stock_act / policy)
// emit one row per detection.  Each row: icon + scanner + ticker + title
// + relative timestamp.  Severity colors the title.

function ScannerEventsList({ events }: { events: SignalEvent[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  if (!events.length) {
    return (
      <div className="text-[var(--color-dim)] italic">
        no events yet — scanners 还没触发；点 "Scan now" 强制跑一次
      </div>
    )
  }
  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  return (
    <>
      {events.map((ev) => {
        const icon = SCANNER_ICON[ev.scanner_name] ?? '·'
        const sev  = SEV_COLOR[ev.severity] ?? ''
        const tag  = ev.ticker || ev.theme || ''
        const isOpen = expanded.has(ev.event_id)
        return (
          <div
            key={ev.event_id}
            className="border-b border-[var(--color-border)]/30 py-0.5"
          >
            <div
              onClick={() => toggle(ev.event_id)}
              className="flex items-start gap-1.5 cursor-pointer hover:bg-[var(--color-panel)]/30"
            >
              <span className="flex-shrink-0 w-[10px]">{isOpen ? '▾' : '▸'}</span>
              <span className="flex-shrink-0">{icon}</span>
              <span className="flex-shrink-0 text-[var(--color-dim)] w-[70px] truncate">
                {ev.scanner_name}
              </span>
              {tag && (
                <span className="flex-shrink-0 text-[var(--color-accent)] font-semibold w-[55px] truncate">
                  {tag}
                </span>
              )}
              <span className={`flex-1 truncate ${sev}`} title={ev.title}>
                {ev.title}
              </span>
              {ev.source_url && (
                <a
                  href={ev.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="flex-shrink-0 text-[var(--color-accent)] hover:underline text-[9px]"
                  title="open original source in new tab"
                >
                  ↗
                </a>
              )}
              <span className="flex-shrink-0 text-[var(--color-dim)] text-[8.5px]">
                ({relTime(ev.detected_at)})
              </span>
            </div>
            {isOpen && (
              <div className="mt-1 ml-5 mr-2 p-1.5 bg-[var(--color-panel)]/40 border border-[var(--color-border)]/50 rounded text-[9px] leading-[1.5] text-[var(--color-dim)]">
                <div className="grid grid-cols-[80px_1fr] gap-x-2 gap-y-0.5 mb-1">
                  <span>signal_type:</span>
                  <span className="text-[var(--color-text)] font-mono break-all">{ev.signal_type}</span>
                  <span>severity:</span>
                  <span className={sev}>{ev.severity}</span>
                  {ev.source_timestamp && (
                    <>
                      <span>source_ts:</span>
                      <span className="font-mono">{ev.source_timestamp}</span>
                    </>
                  )}
                  <span>detected_at:</span>
                  <span className="font-mono">{ev.detected_at}</span>
                  {ev.source_url && (
                    <>
                      <span>source_url:</span>
                      <a
                        href={ev.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[var(--color-accent)] hover:underline break-all"
                      >
                        {ev.source_url}
                      </a>
                    </>
                  )}
                  <span>event_id:</span>
                  <span className="font-mono break-all">{ev.event_id}</span>
                </div>
                {ev.body && Object.keys(ev.body).length > 0 && (
                  <>
                    <div className="text-[var(--color-dim)] mb-0.5">body:</div>
                    <pre className="whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto bg-[var(--color-bg)]/40 p-1 rounded text-[8.5px]">
                      {JSON.stringify(ev.body, null, 2)}
                    </pre>
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}


// ── ChatActivityList ────────────────────────────────────────────────
// LLM / tool calls from the chat panel.  Each entry has kind=request/
// response/error + endpoint + payload.  Click to expand raw JSON.

function ChatActivityList({ entries }: { entries: AuditEntry[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  if (!entries.length) {
    return (
      <div className="text-[var(--color-dim)] italic">
        no chat activity in last 24h — 在右侧 Ask NeoMind 问点啥就会出现
      </div>
    )
  }

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <>
      {entries.map((e) => {
        const isOpen = expanded.has(e.req_id)
        const kc     = KIND_COLOR[e.kind] ?? ''
        const preview = previewPayload(e.payload)
        return (
          <div
            key={`${e.req_id}-${e.kind}-${e.ts}`}
            className="border-b border-[var(--color-border)]/30 py-0.5"
          >
            <div
              onClick={() => toggle(e.req_id)}
              className="flex items-start gap-1.5 cursor-pointer hover:bg-[var(--color-panel)]/30"
            >
              <span className="flex-shrink-0 w-[10px]">{isOpen ? '▾' : '▸'}</span>
              <span className={`flex-shrink-0 w-[55px] uppercase ${kc}`}>
                {e.kind}
              </span>
              <span className="flex-shrink-0 text-[var(--color-dim)] w-[110px] truncate">
                {e.endpoint || '—'}
              </span>
              <span className="flex-1 truncate text-[var(--color-text)]" title={preview}>
                {preview}
              </span>
              <span className="flex-shrink-0 text-[var(--color-dim)] text-[8.5px]">
                ({relTime(e.ts)})
              </span>
            </div>
            {isOpen && (
              <pre className="mt-1 ml-5 p-1.5 bg-[var(--color-panel)]/40 border border-[var(--color-border)]/50 rounded text-[8.5px] leading-[1.4] text-[var(--color-dim)] whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto">
                {JSON.stringify(e.payload, null, 2)}
              </pre>
            )}
          </div>
        )
      })}
    </>
  )
}


// ── RunsList ────────────────────────────────────────────────────────
// analysis_runs rows — every cron tick or manual scan trigger creates
// one. Shows started_at, status (running/completed/failed), per-scanner
// n_emitted from summary, took_ms.  Click ▸ to expand the full summary
// JSON.  This is the "did the scanner actually run?" answer for the
// user — even when dedup kills every emission, the row is still here.

const RUN_STATUS_COLOR: Record<string, string> = {
  running:   'text-[var(--color-warn)]',
  completed: 'text-[var(--color-success)]',
  failed:    'text-[var(--color-danger)]',
}

function RunsList({ runs }: { runs: AnalysisRun[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  if (!runs.length) {
    return (
      <div className="text-[var(--color-dim)] italic">
        no scanner runs yet — cron 还没 fire 过。点 Today's Signals 旁边的
        "立即扫描" 按钮强制跑一次。
      </div>
    )
  }
  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  return (
    <>
      {runs.map((r) => {
        const isOpen = expanded.has(r.run_id)
        const sc = RUN_STATUS_COLOR[r.status] ?? ''
        const summary = summarizeRun(r)
        return (
          <div key={r.run_id} className="border-b border-[var(--color-border)]/30 py-0.5">
            <div
              onClick={() => toggle(r.run_id)}
              className="flex items-start gap-1.5 cursor-pointer hover:bg-[var(--color-panel)]/30"
            >
              <span className="flex-shrink-0 w-[10px]">{isOpen ? '▾' : '▸'}</span>
              <span className="flex-shrink-0 w-[14px]">⚙️</span>
              <span className={`flex-shrink-0 w-[80px] uppercase ${sc}`}>{r.status}</span>
              <span className="flex-shrink-0 text-[var(--color-accent)] w-[140px] truncate">
                {r.job_name}
              </span>
              <span className="flex-1 truncate text-[var(--color-text)]" title={summary}>
                {summary}
              </span>
              <span className="flex-shrink-0 text-[var(--color-dim)] text-[8.5px]">
                ({relTime(r.started_at)})
              </span>
            </div>
            {isOpen && (
              <pre className="mt-1 ml-5 p-1.5 bg-[var(--color-panel)]/40 border border-[var(--color-border)]/50 rounded text-[8.5px] leading-[1.4] text-[var(--color-dim)] whitespace-pre-wrap break-all max-h-[260px] overflow-y-auto">
                {JSON.stringify({
                  run_id:        r.run_id,
                  job_name:      r.job_name,
                  status:        r.status,
                  started_at:    r.started_at,
                  completed_at:  r.completed_at,
                  duration_s:    r.duration_s,
                  rows_written:  r.rows_written,
                  error_message: r.error_message,
                  summary:       r.summary,
                }, null, 2)}
              </pre>
            )}
          </div>
        )
      })}
    </>
  )
}


function summarizeRun(r: AnalysisRun): string {
  if (r.error_message) return `⚠ ${r.error_message.slice(0, 200)}`
  const s: any = r.summary ?? {}
  const parts: string[] = []
  // signal_hourly job stashes per-scanner results in summary
  for (const k of ['watchlist_scan', 'news_scan', 'congressional_scan',
                    'policy_scan', 'whale_scan']) {
    const sub = s[k]
    if (sub && typeof sub === 'object') {
      const n = sub.n_emitted ?? sub.n ?? null
      if (n != null) parts.push(`${k.replace(/_scan$/, '')}=${n}`)
      if (sub.error)  parts.push(`${k}:err(${String(sub.error).slice(0, 40)})`)
    }
  }
  if (typeof s.new_confluences === 'number') parts.push(`confluences=${s.new_confluences}`)
  if (r.duration_s != null) parts.push(`${r.duration_s.toFixed?.(1) ?? r.duration_s}s`)
  if (r.rows_written != null) parts.push(`rows=${r.rows_written}`)
  return parts.length ? parts.join(' · ') : (r.run_type ?? 'no summary')
}


// ── MergedActivityList ──────────────────────────────────────────────
// Interleave scanner events + audit entries + ops runs by timestamp
// DESC.  Lets the user see "what was the agent doing at 14:23?"
// across all activity sources.

type MergedRow =
  | { kind: 'scanner'; ts: string; ev: SignalEvent }
  | { kind: 'audit';   ts: string; entry: AuditEntry }
  | { kind: 'run';     ts: string; run: AnalysisRun }

function MergedActivityList({
  events, entries, runs,
}: { events: SignalEvent[]; entries: AuditEntry[]; runs: AnalysisRun[] }) {
  const merged: MergedRow[] = [
    ...events.map((ev): MergedRow => ({
      kind: 'scanner', ts: ev.detected_at, ev,
    })),
    ...entries.map((entry): MergedRow => ({
      kind: 'audit', ts: entry.ts, entry,
    })),
    ...runs.map((run): MergedRow => ({
      kind: 'run', ts: run.started_at, run,
    })),
  ].sort((a, b) => (a.ts < b.ts ? 1 : -1))

  if (!merged.length) {
    return (
      <div className="text-[var(--color-dim)] italic">
        nothing yet — scanners + chat 都还没活动
      </div>
    )
  }

  return (
    <>
      {merged.map((row, i) => {
        if (row.kind === 'scanner') {
          const ev   = row.ev
          const icon = SCANNER_ICON[ev.scanner_name] ?? '·'
          const sev  = SEV_COLOR[ev.severity] ?? ''
          const tag  = ev.ticker || ev.theme || ''
          return (
            <div
              key={`s-${ev.event_id}-${i}`}
              className="flex items-start gap-1.5 py-0.5 border-b border-[var(--color-border)]/30"
            >
              <span className="flex-shrink-0">{icon}</span>
              <span className="flex-shrink-0 text-[var(--color-dim)] w-[60px] truncate">
                scan
              </span>
              {tag && (
                <span className="flex-shrink-0 text-[var(--color-accent)] font-semibold w-[55px] truncate">
                  {tag}
                </span>
              )}
              <span className={`flex-1 truncate ${sev}`} title={ev.title}>
                {ev.title}
              </span>
              <span className="flex-shrink-0 text-[var(--color-dim)] text-[8.5px]">
                ({relTime(row.ts)})
              </span>
            </div>
          )
        }
        if (row.kind === 'audit') {
          const e  = row.entry
          const kc = KIND_COLOR[e.kind] ?? ''
          return (
            <div
              key={`a-${e.req_id}-${e.kind}-${i}`}
              className="flex items-start gap-1.5 py-0.5 border-b border-[var(--color-border)]/30"
            >
              <span className="flex-shrink-0">💬</span>
              <span className={`flex-shrink-0 w-[60px] uppercase ${kc}`}>
                {e.kind}
              </span>
              <span className="flex-shrink-0 text-[var(--color-dim)] w-[55px] truncate">
                {e.endpoint?.split('/').pop() || '—'}
              </span>
              <span className="flex-1 truncate text-[var(--color-text)]">
                {previewPayload(e.payload)}
              </span>
              <span className="flex-shrink-0 text-[var(--color-dim)] text-[8.5px]">
                ({relTime(row.ts)})
              </span>
            </div>
          )
        }
        // ops run
        const r  = row.run
        const sc = RUN_STATUS_COLOR[r.status] ?? ''
        return (
          <div
            key={`r-${r.run_id}-${i}`}
            className="flex items-start gap-1.5 py-0.5 border-b border-[var(--color-border)]/30"
          >
            <span className="flex-shrink-0">⚙️</span>
            <span className={`flex-shrink-0 w-[60px] uppercase ${sc}`}>{r.status}</span>
            <span className="flex-shrink-0 text-[var(--color-accent)] w-[55px] truncate">
              {r.job_name.split('_')[0]}
            </span>
            <span className="flex-1 truncate text-[var(--color-text)]">
              {summarizeRun(r)}
            </span>
            <span className="flex-shrink-0 text-[var(--color-dim)] text-[8.5px]">
              ({relTime(row.ts)})
            </span>
          </div>
        )
      })}
    </>
  )
}


// ── helpers ─────────────────────────────────────────────────────────


function previewPayload(payload: Record<string, unknown> | undefined): string {
  if (!payload) return ''
  // Try common fields chat audit emits
  const p = payload as any
  if (typeof p.user_message === 'string') return `❓ ${p.user_message}`
  if (typeof p.message === 'string')      return p.message
  if (typeof p.prompt === 'string')       return `❓ ${p.prompt}`
  if (typeof p.content === 'string')      return p.content
  if (typeof p.tool === 'string')         return `🔧 ${p.tool}(${JSON.stringify(p.args ?? {}).slice(0, 60)})`
  if (typeof p.tool_name === 'string')    return `🔧 ${p.tool_name}`
  if (typeof p.error === 'string')        return `⚠ ${p.error}`
  if (Array.isArray(p.messages) && p.messages.length) {
    const last = p.messages[p.messages.length - 1]
    if (last?.content) return String(last.content).slice(0, 120)
  }
  // Fallback — first 100 chars of JSON
  try {
    return JSON.stringify(payload).slice(0, 120)
  } catch {
    return '[unserializable]'
  }
}
