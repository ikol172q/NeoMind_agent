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

interface Msg {
  id: string
  role: Role
  content: string
  ts?: string
  pending?: boolean
  reqId?: string
}

interface Props {
  projectId: string
  onJumpToAudit?: (reqId: string) => void
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
export function ChatPanel({ projectId, onJumpToAudit }: Props) {
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [busy, setBusy] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [loadingSession, setLoadingSession] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const qc = useQueryClient()
  const cacheKey = `neomind.chat.${projectId}`

  // ── On mount / project change: restore from localStorage ──
  useEffect(() => {
    try {
      const raw = localStorage.getItem(cacheKey)
      if (raw) {
        const cached = JSON.parse(raw) as { sessionId: string | null; msgs: Msg[] }
        if (cached.sessionId) {
          setSessionId(cached.sessionId)
          setMsgs(cached.msgs ?? [])
          return
        }
      }
    } catch {
      /* ignore corrupt cache */
    }
    setSessionId(null)
    setMsgs([])
  }, [projectId, cacheKey])

  // ── Mirror msgs + sessionId to localStorage ──
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
    const res = await createChatSession(projectId)
    setSessionId(res.session_id)
    // Invalidate the sidebar list so the new session shows up
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
    setInput('')
    addMsg({ role: 'user', content: text })

    const sid = await ensureSession()
    // Fire-and-forget persist user msg
    void persist(sid, { role: 'user', content: text, ts: new Date().toISOString() })

    // ── Slash commands: local execution (instant) ──
    if (text.startsWith('/')) {
      const pendingId = addMsg({ role: 'assistant', content: '', pending: true })
      setBusy(true)
      try {
        const res = await execCommand(text)
        if (res) {
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
          setBusy(false)
          return
        }
        updateMsg(pendingId, { content: '' })
        await streamReply(sid, pendingId, text)
      } catch (e: unknown) {
        const errMsg = `✗ ${e instanceof Error ? e.message : String(e)}`
        updateMsg(pendingId, { content: errMsg, pending: false, role: 'error' })
        void persist(sid, { role: 'error', content: errMsg, ts: new Date().toISOString() })
      } finally {
        setBusy(false)
      }
      return
    }

    // ── Free-form: streaming ──
    const pendingId = addMsg({ role: 'assistant', content: '', pending: true })
    setBusy(true)
    try {
      await streamReply(sid, pendingId, text)
    } finally {
      setBusy(false)
    }
  }

  function streamReply(sid: string, msgId: string, text: string): Promise<void> {
    return new Promise<void>(resolve => {
      let accumulated = ''
      let firstToken = true
      let reqId: string | undefined
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
          updateMsg(msgId, {
            content: accumulated || '(empty reply)',
            pending: false,
            reqId,
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
      })
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
      <SessionSidebar
        projectId={projectId}
        currentSessionId={sessionId}
        onSelect={selectSession}
        onNew={startNewSession}
      />

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
            <MessageBubble
              key={m.id}
              role={m.role}
              content={m.content}
              ts={m.ts}
              pending={m.pending}
              reqId={m.reqId}
              onJumpToAudit={onJumpToAudit}
            />
          ))}
        </div>

        <div className="relative p-3 border-t border-[var(--color-border)] bg-[var(--color-panel)]">
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
