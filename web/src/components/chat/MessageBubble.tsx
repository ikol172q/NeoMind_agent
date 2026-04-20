import { cn } from '@/lib/utils'
import { ClipboardList } from 'lucide-react'

export type Role = 'user' | 'assistant' | 'system' | 'error'

interface Props {
  role: Role
  content: string
  ts?: string
  pending?: boolean
  reqId?: string
  onJumpToAudit?: (reqId: string) => void
}

/**
 * Single chat bubble. Minimal Markdown rendering via a simple
 * regex-based transform (we deliberately avoid react-markdown
 * to keep the bundle small and audit-surface narrow).
 */
export function MessageBubble({ role, content, ts, pending, reqId, onJumpToAudit }: Props) {
  const align = role === 'user' ? 'items-end' : 'items-start'
  const bubble =
    role === 'user'
      ? 'bg-[var(--color-accent)] text-[var(--color-bg)] rounded-2xl rounded-br-sm'
      : role === 'assistant'
      ? 'bg-[var(--color-panel)] border border-[var(--color-border)] rounded-2xl rounded-bl-sm'
      : role === 'error'
      ? 'bg-[var(--color-red)]/15 border border-[var(--color-red)]/50 text-[var(--color-red)] rounded-2xl'
      : 'bg-transparent text-[var(--color-dim)] italic text-[11px] px-0'

  return (
    <div className={cn('flex flex-col mb-3 max-w-[85%]', align, role === 'user' ? 'self-end' : 'self-start')}>
      <div className={cn('px-3.5 py-2 text-[13px] leading-[1.55] break-words whitespace-pre-wrap', bubble)}>
        {pending ? <TypingIndicator /> : <MarkdownLite text={content} />}
      </div>
      <div className="flex gap-2 mt-1 px-1 items-center">
        {ts && <div className="text-[10px] text-[var(--color-dim)]">{ts}</div>}
        {reqId && onJumpToAudit && (
          <button
            data-testid={`audit-link-${reqId.slice(0, 8)}`}
            onClick={() => onJumpToAudit(reqId)}
            className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-accent)] inline-flex items-center gap-1 transition"
            title={`Jump to audit entry ${reqId}`}
          >
            <ClipboardList size={10} />
            raw
          </button>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <span className="inline-flex gap-1 items-center">
      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-dim)] animate-pulse" />
      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-dim)] animate-pulse [animation-delay:150ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-dim)] animate-pulse [animation-delay:300ms]" />
    </span>
  )
}

function escapeHtml(s: string): string {
  return s.replace(/[<>&"']/g, c => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#39;',
  }[c]!))
}

/**
 * Tiny Markdown-lite: bold, italic, code, links, bullets.
 * Deliberately minimal; anything more → consider a real parser
 * later.
 */
function MarkdownLite({ text }: { text: string }) {
  const escaped = escapeHtml(text)
  // bold **x**
  let html = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // italic *x* or _x_ (simple; skip nested)
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  html = html.replace(/_([^_\n]+)_/g, '<em>$1</em>')
  // inline code `x`
  html = html.replace(/`([^`\n]+)`/g,
    '<code style="background:rgba(120,160,220,.15);padding:1px 5px;border-radius:3px;font-size:.92em">$1</code>')
  // markdown links [t](u)
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener" style="color:var(--color-accent);text-decoration:underline">$1</a>')
  // bullets at start of line
  html = html.replace(/^- /gm, '•&nbsp;')
  return <span dangerouslySetInnerHTML={{ __html: html }} />
}
