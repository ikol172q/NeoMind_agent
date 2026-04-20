import { useEffect, useMemo, useRef, useState } from 'react'
import { COMMANDS, filterCommands } from './commandRegistry'
import { Search } from 'lucide-react'

interface Props {
  open: boolean
  onClose: () => void
  /** Invoked with the chosen command + its args (e.g. "/prep AAPL").
   *  Caller is responsible for actually dispatching (route to chat,
   *  populate input, hit send). */
  onPick: (fullText: string) => void
}

/**
 * Global command palette — ⌘K / Ctrl+K. Lists the slash-command
 * registry, fuzzy-filters by typed prefix, Enter dispatches.
 *
 * The palette deliberately does NOT execute commands itself; it
 * hands the chosen text back to the parent (App.tsx) which routes
 * to chat + enqueues the send. This keeps the dispatch path
 * identical to typing the command by hand in the chat input.
 */
export function CommandPalette({ open, onClose, onPick }: Props) {
  const [query, setQuery] = useState('')
  const [idx, setIdx] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setIdx(0)
    // Focus when opened
    const t = setTimeout(() => inputRef.current?.focus(), 0)
    // Document-level Escape so closing works even when focus isn't
    // inside the input (rare, but happens after a mouseover).
    function onDocKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
    }
    window.addEventListener('keydown', onDocKey)
    return () => {
      clearTimeout(t)
      window.removeEventListener('keydown', onDocKey)
    }
  }, [open, onClose])

  const filtered = useMemo(() => {
    if (!query.trim()) return COMMANDS
    const q = query.trim().startsWith('/') ? query.trim() : '/' + query.trim()
    return filterCommands(q.split(/\s+/)[0])
  }, [query])

  // Keep the selection index in range when the list shrinks
  useEffect(() => {
    if (idx >= filtered.length) setIdx(Math.max(0, filtered.length - 1))
  }, [filtered.length, idx])

  if (!open) return null

  function dispatch(name: string) {
    // If the user typed args after the command (e.g. "prep AAPL"),
    // preserve them. Otherwise send just the command name.
    const q = query.trim()
    const parts = q.split(/\s+/)
    const args = parts.length > 1 ? parts.slice(1).join(' ') : ''
    const full = args ? `${name} ${args}` : name
    onPick(full)
    onClose()
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(i + 1, filtered.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(i - 1, 0)) }
    if (e.key === 'Enter') {
      e.preventDefault()
      const cmd = filtered[idx]
      if (cmd) dispatch(cmd.name)
    }
  }

  return (
    <div
      data-testid="command-palette"
      className="fixed inset-0 z-[1000] flex items-start justify-center pt-[18vh] bg-black/60"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[560px] max-w-[90vw] bg-[var(--color-panel)] border border-[var(--color-border)] rounded-lg shadow-2xl overflow-hidden"
      >
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)]">
          <Search size={14} className="text-[var(--color-dim)]" />
          <input
            ref={inputRef}
            data-testid="command-palette-input"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Type a command… (e.g. brief, prep AAPL, check)"
            className="flex-1 bg-transparent outline-none text-[13px] text-[var(--color-text)] placeholder:text-[var(--color-dim)]"
          />
          <kbd className="text-[9px] text-[var(--color-dim)] px-1.5 py-0.5 rounded border border-[var(--color-border)]">
            esc
          </kbd>
        </div>
        <div className="max-h-[50vh] overflow-y-auto" data-testid="command-palette-list">
          {filtered.length === 0 && (
            <div className="p-4 text-[var(--color-dim)] italic text-[12px]">
              no matching commands
            </div>
          )}
          {filtered.map((c, i) => (
            <div
              key={c.name}
              data-testid={`command-palette-item-${c.name.slice(1)}`}
              onClick={() => dispatch(c.name)}
              onMouseEnter={() => setIdx(i)}
              className={
                'flex items-baseline gap-3 px-3 py-2 cursor-pointer text-[12px] ' +
                (i === idx
                  ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                  : 'hover:bg-[var(--color-border)]/40 text-[var(--color-text)]')
              }
            >
              <code className="font-mono text-[12px] text-[var(--color-accent)] w-20 shrink-0">
                {c.name}
              </code>
              <span className="text-[11px] text-[var(--color-dim)] w-28 shrink-0 truncate">
                {c.args}
              </span>
              <span className="flex-1 truncate">{c.description}</span>
            </div>
          ))}
        </div>
        <div className="px-3 py-1.5 text-[9px] text-[var(--color-dim)] border-t border-[var(--color-border)] bg-[var(--color-bg)]/40 flex items-center gap-3">
          <span><kbd className="px-1 rounded border border-[var(--color-border)]">↑↓</kbd> navigate</span>
          <span><kbd className="px-1 rounded border border-[var(--color-border)]">↵</kbd> run</span>
          <span><kbd className="px-1 rounded border border-[var(--color-border)]">esc</kbd> close</span>
        </div>
      </div>
    </div>
  )
}
