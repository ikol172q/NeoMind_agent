import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { MessageBubble, type Role } from './MessageBubble'
import { SlashMenu } from './SlashMenu'
import { SessionSidebar } from './SessionSidebar'
import { execCommand } from './commandExec'
import {
  streamChat,
  createChatSession,
  loadChatSession,
  appendChatMessage,
  type StoredMessage,
} from '@/lib/api'
import { Send } from 'lucide-react'

interface UrlWarning {
  url: string
  fallback: string
  host: string
}

interface Msg {
  id: string
  role: Role
  content: string
  ts?: string
  pending?: boolean
  reqId?: string
  // Set on done event when LLM emitted URLs that failed HEAD
  // verification (agent.llm_url_guard). UI renders a ⚠ notice below
  // the message with Google-search fallback per dead URL so the user
  // never sees a broken link as if it were verified.
  urlWarnings?: UrlWarning[]
}

interface Props {
  projectId: string
  onJumpToAudit?: (reqId: string) => void
  /** Reverse of onJumpToChat — fired when an assistant-reply
   *  citation chip is clicked. Routes the user to the Research
   *  tab with the DigestView focused on the cited symbol. */
  onNavigateToResearch?: (focus: { symbol?: string }) => void
  /** One-shot prompt handed in from another tab (e.g. watchlist
   *  "ask agent" button). We pre-fill the input then call
   *  onConsumePendingPrompt so the parent clears it — otherwise
   *  switching away and back would replay the same prompt. */
  pendingPrompt?: string | null
  /** Synthesis context hint attached to the pending prompt. When
   *  set, the next send() passes `context_symbol` / `context_project`
   *  so the agent sees the dashboard state in its system prompt. */
  pendingContext?: { symbol?: string; project?: boolean } | null
  onConsumePendingPrompt?: () => void
  /** When true, the past-sessions sidebar is not rendered.  Used by
   *  the embedded ChatPanel in Strategies' right rail so that narrow
   *  layouts can hide sessions to give the conversation more width. */
  hideSessions?: boolean
  /** Tag any newly-created session with this ticker. Used by the
   *  Stock Research Drawer's Chat tab so all sessions started while
   *  the drawer is open on ROKU get ticker_tag='ROKU'. Backend
   *  filters by this on subsequent list calls so the drawer can show
   *  only ROKU-related sessions. Doesn't affect existing sessions. */
  tickerTag?: string | null
  /** One-shot session ID to load (mirrors pendingPrompt pattern).
   *  When set, ChatPanel calls selectSession(id) once then fires
   *  onConsumePendingSession so the parent clears it. Used by the
   *  drawer's per-ticker session picker. */
  pendingSessionId?: string | null
  onConsumePendingSession?: () => void
}

/**
 * Telegram-style chat with persistent sessions.
 *
 * Persistence strategy (two layers):
 * 1. localStorage — mirror of (sessionId, msgs) that survives tab
 *    switches within the SPA and browser refresh. Written on every
 *    state change, read once on mount.
 * 2. Backend JSONL — every completed turn (user msg + assistant
 *    reply) is POSTed to /api/chat_sessions/{sid}/append so the
 *    Investment-root data firewall has the durable record. This is
 *    what the session list sidebar reads from.
 *
 * Design choice: the localStorage cache is authoritative for "what
 * the user sees right now". The backend is authoritative for "what
 * sessions exist across devices". When you click a past session in
 * the sidebar we always fetch from backend (no localStorage for
 * other sessions) to keep the local state small.
 */
function cacheKeyFor(pid: string) {
  return `neomind.chat.${pid}`
}

function loadCache(pid: string): { sessionId: string | null; msgs: Msg[] } {
  try {
    const raw = localStorage.getItem(cacheKeyFor(pid))
    if (raw) {
      const cached = JSON.parse(raw) as { sessionId?: string | null; msgs?: Msg[] }
      return { sessionId: cached.sessionId ?? null, msgs: cached.msgs ?? [] }
    }
  } catch {
    /* corrupt cache — treat as empty */
  }
  return { sessionId: null, msgs: [] }
}

export function ChatPanel({
  projectId,
  onJumpToAudit,
  onNavigateToResearch,
  pendingPrompt,
  pendingContext,
  onConsumePendingPrompt,
  hideSessions = false,
  tickerTag = null,
  pendingSessionId = null,
  onConsumePendingSession,
}: Props) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadingSession, setLoadingSession] = useState(false)
  // Synthesis context attached to the NEXT send. Cleared after
  // that send completes so subsequent free-form messages aren't
  // silently enriched. Shown to the user as a chip so they know.
  const [nextSendContext, setNextSendContext] = useState<{ symbol?: string; project?: boolean } | null>(null)
  // Hydrate sessionId + msgs synchronously from localStorage so we
  // never race a mirror-effect that would clobber the cache with an
  // initial empty state. This was the cause of phantom "yo" sessions
  // appearing after a reload.
  const [sessionId, setSessionId] = useState<string | null>(() => loadCache(projectId).sessionId)
  const [msgs, setMsgs] = useState<Msg[]>(() => loadCache(projectId).msgs)
  // Context-window status — populated from each /api/chat_stream done
  // event. promptTokens = the prompt the LLM saw on the last turn
  // (system + history + new user); maxContext = active model's
  // advertised window. Header renders a "ctx: X / Y (Z%)" indicator
  // with warn (>70%) / critical (>90%) coloring so the user sees
  // when a long conversation is approaching the limit.
  const [ctxPromptTokens, setCtxPromptTokens] = useState<number | null>(null)
  const [ctxMaxContext, setCtxMaxContext] = useState<number | null>(null)
  // Cumulative count of auto-compactions this session has gone through
  // (server-side). Reset to 0 when the user starts a new session.
  // Surfaced in the header next to ctx so the user knows context has
  // been auto-summarized.
  const [compactCount, setCompactCount] = useState<number>(0)
  const loadedProjectRef = useRef(projectId)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const qc = useQueryClient()
  const cacheKey = cacheKeyFor(projectId)

  // Only re-hydrate on *project switch*, not on mount (the lazy
  // initializer already did that). This avoids the null-overwrite
  // race that was killing session persistence on reload.
  useEffect(() => {
    if (loadedProjectRef.current === projectId) return
    loadedProjectRef.current = projectId
    const { sessionId: sid, msgs: m } = loadCache(projectId)
    setSessionId(sid)
    setMsgs(m)
  }, [projectId])

  // Mirror msgs + sessionId to localStorage on every change.
  useEffect(() => {
    if (loadingSession) return
    try {
      localStorage.setItem(cacheKey, JSON.stringify({ sessionId, msgs }))
    } catch {
      /* quota exceeded — best effort */
    }
  }, [msgs, sessionId, cacheKey, loadingSession])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [msgs])

  useEffect(() => () => abortRef.current?.abort(), [])

  // ── Pending prompt hand-off from other tabs ──
  // When the user clicks "ask agent" on a widget (or picks a ⌘K
  // palette command), App.tsx sets pendingPrompt + optional
  // pendingContext + switches tabs. We start a CLEAN session so the
  // incoming prompt doesn't inherit irrelevant history from the last
  // conversation (e.g. a watchlist "ask about MSFT" arriving in a
  // session that had been talking about BTC), pre-fill the input,
  // attach the context to the next send, focus, then tell the parent
  // to clear so leaving + re-entering the tab doesn't replay it.
  useEffect(() => {
    if (!pendingPrompt) return
    startNewSession()           // sessionId=null, msgs=[], input=''
    setInput(pendingPrompt)     // override the '' startNewSession set
    if (pendingContext) setNextSendContext(pendingContext)
    queueMicrotask(() => inputRef.current?.focus())
    onConsumePendingPrompt?.()
  }, [pendingPrompt, pendingContext, onConsumePendingPrompt])

  // ── Pending session-id hand-off — same shape as pendingPrompt ──
  // Used by the drawer's per-ticker session picker: parent sets
  // pendingSessionId, ChatPanel loads that session into the chat,
  // then fires onConsumePendingSession so re-renders don't replay.
  useEffect(() => {
    if (!pendingSessionId) return
    if (pendingSessionId === sessionId) {
      // Already on this session — just consume so we don't loop
      onConsumePendingSession?.()
      return
    }
    void selectSession(pendingSessionId)
    onConsumePendingSession?.()
    // selectSession is defined later; closing over the ref is fine
    // because React only fires effects after render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingSessionId])

  function addMsg(m: Omit<Msg, 'id' | 'ts'>): string {
    const id = `${Date.now()}-${Math.random()}`
    setMsgs(prev => [...prev, { id, ts: new Date().toLocaleTimeString(), ...m }])
    return id
  }

  function updateMsg(id: string, patch: Partial<Msg>) {
    setMsgs(prev => prev.map(x => (x.id === id ? { ...x, ...patch } : x)))
  }

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId
    // Pass tickerTag through so drawer-created sessions get tagged
    // (backward-compat: omitted for non-drawer ChatPanel callers).
    const res = await createChatSession(projectId, tickerTag ?? undefined)
    setSessionId(res.session_id)
    // Invalidate every variant of the sessions cache (unfiltered +
    // any per-ticker filtered view) so the new session shows up
    // wherever it's listed.
    qc.invalidateQueries({ queryKey: ['chat_sessions', projectId] })
    return res.session_id
  }

  async function persist(sid: string, m: StoredMessage) {
    try {
      await appendChatMessage(projectId, sid, m)
      qc.invalidateQueries({ queryKey: ['chat_sessions', projectId] })
    } catch (err) {
      // Persistence is best-effort. localStorage still has the message.
      console.warn('chat persist failed', err)
    }
  }

  function startNewSession() {
    abortRef.current?.abort()
    setSessionId(null)
    setMsgs([])
    setInput('')
    setCtxPromptTokens(null)
    setCtxMaxContext(null)
    setCompactCount(0)
  }

  async function selectSession(sid: string) {
    if (sid === sessionId) return
    abortRef.current?.abort()
    setLoadingSession(true)
    try {
      const data = await loadChatSession(projectId, sid)
      const restored: Msg[] = data.messages.map((m, i) => ({
        id: `${sid}-${i}`,
        role: m.role as Role,
        content: m.content,
        ts: m.ts ? new Date(m.ts).toLocaleTimeString() : undefined,
        reqId: m.req_id,
      }))
      setSessionId(sid)
      setMsgs(restored)
    } catch (err) {
      console.error('load session failed', err)
    } finally {
      setLoadingSession(false)
    }
  }

  async function send() {
    const text = input.trim()
    if (!text || busy) return

    // Lock + clear synchronously so the input box empties on the very
    // next paint — do this *before* any await. We also clear the DOM
    // node via ref in case controlled-state commit is deferred (some
    // browsers paint stale value when `disabled` flips in the same
    // render cycle).
    setBusy(true)
    setInput('')
    if (inputRef.current) inputRef.current.value = ''
    addMsg({ role: 'user', content: text })

    try {
      const sid = await ensureSession()
      void persist(sid, { role: 'user', content: text, ts: new Date().toISOString() })

      // ── Slash commands: three possible paths ──
    //   1. kind:'render'   → show returned markdown inline (no LLM call)
    //   2. kind:'workflow' → attach dashboard context, stream the LLM with
    //                         a pre-crafted prompt; user bubble keeps showing
    //                         the raw /command they typed
    //   3. null            → fall through, stream raw text (e.g. /analyze)
      if (text.startsWith('/')) {
        const pendingId = addMsg({ role: 'assistant', content: '', pending: true })
        try {
          const res = await execCommand(text)
          if (res && res.kind === 'render') {
            updateMsg(pendingId, {
              content: res.markdown,
              pending: false,
              role: res.ok ? 'assistant' : 'error',
            })
            void persist(sid, {
              role: res.ok ? 'assistant' : 'error',
              content: res.markdown,
              ts: new Date().toISOString(),
            })
            return
          }
          if (res && res.kind === 'workflow') {
            updateMsg(pendingId, { content: '' })
            await streamReply(sid, pendingId, res.workflowPrompt, res.context)
            return
          }
          // null → fall through to raw streaming
          updateMsg(pendingId, { content: '' })
          await streamReply(sid, pendingId, text)
        } catch (e: unknown) {
          const errMsg = `✗ ${e instanceof Error ? e.message : String(e)}`
          updateMsg(pendingId, { content: errMsg, pending: false, role: 'error' })
          void persist(sid, { role: 'error', content: errMsg, ts: new Date().toISOString() })
        }
        return
      }

      // ── Free-form: streaming ──
      const pendingId = addMsg({ role: 'assistant', content: '', pending: true })
      await streamReply(sid, pendingId, text)
    } finally {
      setBusy(false)
    }
  }

  function streamReply(
    sid: string,
    msgId: string,
    text: string,
    explicitCtx?: { symbol?: string; project?: boolean },
  ): Promise<void> {
    return new Promise<void>(resolve => {
      let accumulated = ''
      let firstToken = true
      let reqId: string | undefined
      // Priority: explicit (workflow commands pass this directly because
      // React hasn't committed the setNextSendContext yet) → state.
      // Consume state context so subsequent free-form messages aren't
      // silently enriched.
      const ctx = explicitCtx ?? nextSendContext
      if (!explicitCtx && nextSendContext) setNextSendContext(null)
      abortRef.current?.abort()
      abortRef.current = streamChat(projectId, text, {
        onDelta: (chunk) => {
          accumulated += chunk
          if (firstToken) {
            firstToken = false
            updateMsg(msgId, { content: accumulated, pending: false })
          } else {
            updateMsg(msgId, { content: accumulated })
          }
        },
        onDone: (info) => {
          reqId = info.req_id
          if (typeof info.prompt_tokens === 'number') setCtxPromptTokens(info.prompt_tokens)
          if (typeof info.max_context === 'number') setCtxMaxContext(info.max_context)
          if (info.compacted) setCompactCount(c => c + 1)
          const urlWarnings = info.url_warnings && info.url_warnings.length > 0
            ? info.url_warnings
            : undefined
          updateMsg(msgId, {
            content: accumulated || '(empty reply)',
            pending: false,
            reqId,
            urlWarnings,
          })
          void persist(sid, {
            role: 'assistant',
            content: accumulated || '(empty reply)',
            ts: new Date().toISOString(),
            req_id: reqId,
          })
          resolve()
        },
        onError: (err) => {
          const errMsg = `✗ ${err}`
          updateMsg(msgId, { content: errMsg, pending: false, role: 'error' })
          void persist(sid, { role: 'error', content: errMsg, ts: new Date().toISOString() })
          resolve()
        },
      }, ctx ? { symbol: ctx.symbol, project: ctx.project } : undefined, sid)
    })
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const slashQuery = input.startsWith('/') ? input.split(/\s/)[0] : ''
  const showMenu = slashQuery.length > 0 && !input.includes(' ')

  return (
    <div className="h-full flex">
      {!hideSessions && (
        <SessionSidebar
          projectId={projectId}
          currentSessionId={sessionId}
          onSelect={selectSession}
          onNew={startNewSession}
        />
      )}

      <div className="flex-1 flex flex-col min-w-0 max-w-4xl mx-auto">
        <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-panel)]">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
            Fin persona · DeepSeek-chat (streaming)
          </div>
          <div className="text-xs mt-0.5">
            Project: <span className="text-[var(--color-accent)]">{projectId}</span>
            {sessionId && (
              <>
                {' · '}
                <span className="text-[var(--color-dim)]">
                  session <code className="text-[var(--color-text)]" data-testid="chat-session-id">{sessionId.slice(0, 8)}</code>
                </span>
              </>
            )}
            {ctxPromptTokens !== null && ctxMaxContext && ctxMaxContext > 0 && (() => {
              const pct = ctxPromptTokens / ctxMaxContext
              const fmt = (n: number) =>
                n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
              const color =
                pct >= 0.9 ? 'var(--color-red)'
                : pct >= 0.7 ? 'var(--color-amber, #d4a017)'
                : 'var(--color-dim)'
              return (
                <>
                  {' · '}
                  <span
                    style={{ color }}
                    data-testid="chat-ctx-status"
                    title={`Last turn used ${ctxPromptTokens.toLocaleString()} prompt tokens; model context window is ${ctxMaxContext.toLocaleString()} tokens. Start a new session if approaching the limit.`}
                  >
                    ctx {fmt(ctxPromptTokens)} / {fmt(ctxMaxContext)} ({Math.round(pct * 100)}%)
                    {pct >= 0.9 ? ' ⛔' : pct >= 0.7 ? ' ⚠' : ''}
                  </span>
                </>
              )
            })()}
            {compactCount > 0 && (
              <>
                {' · '}
                <span
                  className="text-[var(--color-dim)]"
                  data-testid="chat-compact-count"
                  title={`${compactCount} auto-compaction${compactCount === 1 ? '' : 's'} in this session — older history was summarized to fit the context window. Original turns remain in chat_sessions on disk.`}
                >
                  📦 {compactCount}×
                </span>
              </>
            )}
            {' · '}
            <span className="text-[var(--color-dim)]">
              type <code>/help</code> for commands · click <code>raw</code> on a reply to jump to its audit entry
            </span>
          </div>
        </div>

        <div
          ref={scrollRef}
          data-testid="chat-messages"
          className="flex-1 overflow-y-auto p-4 flex flex-col"
        >
          {msgs.length === 0 && !loadingSession && (
            <div className="text-[var(--color-dim)] italic text-[12px] text-center mt-8">
              输入 / 看命令菜单，或直接提问。past sessions listed on the left ←
            </div>
          )}
          {loadingSession && (
            <div className="text-[var(--color-dim)] italic text-[12px] text-center mt-8">
              loading session…
            </div>
          )}
          {msgs.map(m => (
            <div key={m.id}>
              <MessageBubble
                role={m.role}
                content={m.content}
                ts={m.ts}
                pending={m.pending}
                reqId={m.reqId}
                onJumpToAudit={onJumpToAudit}
                onCiteClick={(cite) => {
                  if (cite.kind === 'sector') {
                    setNextSendContext({ project: true })
                  } else {
                    setNextSendContext({ symbol: cite.id })
                    onNavigateToResearch?.({ symbol: cite.id })
                  }
                  inputRef.current?.focus()
                }}
              />
              {m.urlWarnings && m.urlWarnings.length > 0 && (
                <div
                  data-testid={`url-warnings-${m.id}`}
                  className="ml-3 mt-1 mb-2 px-2 py-1.5 rounded border border-[var(--color-amber,#b45309)]/50 bg-[var(--color-amber,#b45309)]/10 text-[11px] text-[var(--color-amber,#b45309)]"
                  title="NeoMind 试图引用的链接 HEAD 检查未通过 — 已替换为 Google 搜索 fallback"
                >
                  <div className="font-semibold mb-0.5">⚠ {m.urlWarnings.length} 个死链已拦截</div>
                  <ul className="space-y-0.5">
                    {m.urlWarnings.map((w, i) => (
                      <li key={i} className="font-mono">
                        <span className="line-through opacity-70">{w.host}</span>
                        {' → '}
                        <a
                          href={w.fallback}
                          target="_blank"
                          rel="noreferrer"
                          className="underline hover:opacity-80"
                        >
                          Google 搜
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="relative p-3 border-t border-[var(--color-border)] bg-[var(--color-panel)]">
          {nextSendContext && (
            <div
              data-testid="chat-context-chip"
              className="mb-2 inline-flex items-center gap-2 px-2 py-0.5 rounded bg-[var(--color-accent)]/15 border border-[var(--color-accent)]/40 text-[10px] text-[var(--color-accent)]"
              title="the next message will include the dashboard's live state for this symbol/project"
            >
              <span>+ context:</span>
              <code className="font-mono">
                {nextSendContext.symbol ?? (nextSendContext.project ? 'project snapshot' : '?')}
              </code>
              <button
                data-testid="chat-context-clear"
                onClick={() => setNextSendContext(null)}
                className="text-[var(--color-dim)] hover:text-[var(--color-red)]"
                title="drop context — next message sends without dashboard state"
              >
                ×
              </button>
            </div>
          )}
          {showMenu && (
            <SlashMenu
              query={slashQuery}
              onPick={name => {
                setInput(name + ' ')
                inputRef.current?.focus()
              }}
            />
          )}
          <div className="flex gap-2 items-center">
            <Input
              ref={inputRef}
              data-testid="chat-input"
              placeholder="Ask fin…  (type / for commands)"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              maxLength={4000}
              className="flex-1"
              disabled={busy}
            />
            <Button data-testid="chat-send" onClick={send} disabled={busy || !input.trim()}>
              <Send size={13} /> Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
