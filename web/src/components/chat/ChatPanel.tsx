import { useEffect, useRef, useState } from 'react'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { MessageBubble, type Role } from './MessageBubble'
import { SlashMenu } from './SlashMenu'
import { execCommand } from './commandExec'
import { dispatchChat, getTask } from '@/lib/api'
import { Send } from 'lucide-react'

interface Msg { id: string; role: Role; content: string; ts?: string; pending?: boolean }

interface Props { projectId: string }

/**
 * Telegram-style chat panel.
 * - Typing '/' opens slash menu (filterable, tab-to-complete)
 * - Slash commands execute locally via commandExec (fast);
 *   /analyze + free-form go to the fleet agent via /api/chat
 * - Streaming: fleet returns a task_id; we poll /api/tasks/{id}
 *   and update the assistant bubble when complete.
 */
export function ChatPanel({ projectId }: Props) {
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [msgs])

  function addMsg(role: Role, content: string, pending = false) {
    const id = `${Date.now()}-${Math.random()}`
    setMsgs(m => [...m, { id, role, content, pending, ts: new Date().toLocaleTimeString() }])
    return id
  }

  function updateMsg(id: string, patch: Partial<Msg>) {
    setMsgs(m => m.map(x => (x.id === id ? { ...x, ...patch } : x)))
  }

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    addMsg('user', text)

    // slash commands first
    if (text.startsWith('/')) {
      const pendingId = addMsg('assistant', '', true)
      setBusy(true)
      try {
        const res = await execCommand(text)
        if (res) {
          updateMsg(pendingId, { content: res.markdown, pending: false, role: res.ok ? 'assistant' : 'error' })
          setBusy(false)
          return
        }
        // null → fall through to agent (e.g. /analyze)
        updateMsg(pendingId, { content: '⏳ dispatching to fleet agent…', pending: true })
      } catch (e: unknown) {
        updateMsg(pendingId, { content: `✗ ${e instanceof Error ? e.message : String(e)}`, pending: false, role: 'error' })
        setBusy(false)
        return
      }
    }

    // Free-form or /analyze → fleet agent
    const pendingId = msgs.find(m => m.pending)?.id ?? addMsg('assistant', '⏳ fleet thinking…', true)
    setBusy(true)
    try {
      const taskId = await dispatchChat(projectId, text)
      const started = Date.now()
      // poll
      while (true) {
        await new Promise(r => setTimeout(r, 1500))
        const t = await getTask(taskId)
        if (t.status === 'completed') {
          updateMsg(pendingId, { content: t.reply || '(empty reply)', pending: false })
          break
        }
        if (t.status === 'failed') {
          updateMsg(pendingId, { content: `✗ ${t.error ?? 'task failed'}`, pending: false, role: 'error' })
          break
        }
        if (Date.now() - started > 180_000) {
          updateMsg(pendingId, { content: '⚠ timed out at 180s', pending: false, role: 'error' })
          break
        }
        const secs = Math.round((Date.now() - started) / 1000)
        updateMsg(pendingId, { content: `⏳ fleet thinking (${secs}s, R1 reasoning can take 30-90s)` })
      }
    } catch (e: unknown) {
      updateMsg(pendingId, { content: `✗ ${e instanceof Error ? e.message : String(e)}`, pending: false, role: 'error' })
    } finally {
      setBusy(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // If slash menu is showing and user hits Enter without Tab-completing, treat as submit anyway
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const slashQuery = input.startsWith('/') ? input.split(/\s/)[0] : ''
  const showMenu = slashQuery.length > 0 && !input.includes(' ')

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-panel)]">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">Fin persona · DeepSeek-R1</div>
        <div className="text-xs mt-0.5">
          Project: <span className="text-[var(--color-accent)]">{projectId}</span>
          {' · '}
          <span className="text-[var(--color-dim)]">Try <code>/help</code> to see commands</span>
        </div>
      </div>

      <div ref={scrollRef} data-testid="chat-messages" className="flex-1 overflow-y-auto p-4 flex flex-col">
        {msgs.length === 0 && (
          <div className="text-[var(--color-dim)] italic text-[12px] text-center mt-8">
            输入 / 看命令菜单，或直接提问。audit log: <code>~/Desktop/Investment/_audit/</code>
          </div>
        )}
        {msgs.map(m => (
          <MessageBubble key={m.id} role={m.role} content={m.content} ts={m.ts} pending={m.pending} />
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
  )
}
