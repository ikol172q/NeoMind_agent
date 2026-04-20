import { useQueryClient } from '@tanstack/react-query'
import { useChatSessions, archiveChatSession, type ChatSessionSummary } from '@/lib/api'
import { cn, fmtTs } from '@/lib/utils'
import { Plus, MessageSquare, Trash2 } from 'lucide-react'

interface Props {
  projectId: string
  currentSessionId: string | null
  onSelect: (sessionId: string) => void
  onNew: () => void
}

/**
 * Left rail of the Chat tab. Lists past sessions for the current
 * project, newest first. Click a row to load it. The "+" button up
 * top starts a fresh session. Delete (trash) archives the session
 * on disk (renamed to .archived, not deleted) so nothing is lost.
 */
export function SessionSidebar({ projectId, currentSessionId, onSelect, onNew }: Props) {
  const { data, isLoading, refetch } = useChatSessions(projectId)
  const qc = useQueryClient()
  const sessions: ChatSessionSummary[] = data?.sessions ?? []

  async function del(sid: string, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm('Archive this session?')) return
    try {
      await archiveChatSession(projectId, sid)
      qc.invalidateQueries({ queryKey: ['chat_sessions', projectId] })
      if (sid === currentSessionId) onNew()
    } catch (err) {
      console.error('archive failed', err)
    }
  }

  return (
    <aside
      className="w-56 shrink-0 border-r border-[var(--color-border)] bg-[var(--color-panel)] flex flex-col h-full"
      data-testid="chat-session-sidebar"
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)]">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] flex-1">Sessions</div>
        <button
          data-testid="chat-new-session"
          onClick={onNew}
          className="text-[var(--color-dim)] hover:text-[var(--color-accent)]"
          title="new session"
        >
          <Plus size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto" data-testid="chat-session-list">
        {isLoading && <div className="text-[10px] text-[var(--color-dim)] p-3">loading…</div>}
        {!isLoading && sessions.length === 0 && (
          <div className="text-[10px] text-[var(--color-dim)] p-3 italic">
            No past sessions. Send a message to start one.
          </div>
        )}
        {sessions.map(s => {
          const active = s.session_id === currentSessionId
          return (
            <div
              key={s.session_id}
              data-testid={`chat-session-${s.session_id.slice(0, 8)}`}
              onClick={() => onSelect(s.session_id)}
              className={cn(
                'group px-3 py-2 cursor-pointer border-b border-[var(--color-border)]/50 text-[11px] flex items-start gap-2',
                active
                  ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                  : 'text-[var(--color-text)] hover:bg-[var(--color-border)]/40',
              )}
            >
              <MessageSquare size={11} className="mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="truncate">{s.title || '(empty)'}</div>
                <div className="text-[9px] text-[var(--color-dim)] mt-0.5 flex gap-2">
                  <span>{s.message_count} msg</span>
                  <span>·</span>
                  <span>{fmtTs(s.updated_at ?? s.created_at)}</span>
                </div>
              </div>
              <button
                onClick={(e) => del(s.session_id, e)}
                className="opacity-0 group-hover:opacity-100 text-[var(--color-dim)] hover:text-[var(--color-red)] transition"
                title="archive session"
              >
                <Trash2 size={10} />
              </button>
            </div>
          )
        })}
      </div>

      <div className="px-3 py-2 border-t border-[var(--color-border)] text-[9px] text-[var(--color-dim)]">
        <button onClick={() => refetch()} className="hover:text-[var(--color-text)]">refresh</button>
        <span className="mx-2">·</span>
        <span>stored at ~/Desktop/Investment/{projectId}/chat_sessions/</span>
      </div>
    </aside>
  )
}
