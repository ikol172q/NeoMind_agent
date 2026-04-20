import { useEffect, useState } from 'react'
import { filterCommands } from './commandRegistry'

interface Props {
  query: string
  onPick: (name: string) => void
}

/**
 * Dropdown shown above the chat input when the user is typing a
 * slash command. Filters commands by prefix and supports arrow-key
 * + enter selection via parent's onPick callback.
 */
export function SlashMenu({ query, onPick }: Props) {
  const items = filterCommands(query)
  const [focusIdx, setFocusIdx] = useState(0)

  // Reset focus whenever query changes so the top item is highlighted
  useEffect(() => setFocusIdx(0), [query])

  // Keyboard nav: handled by parent via imperative binding on input
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!items.length) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusIdx(i => (i + 1) % items.length)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusIdx(i => (i - 1 + items.length) % items.length)
      } else if (e.key === 'Tab' && items.length > 0) {
        e.preventDefault()
        onPick(items[focusIdx].name)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items, focusIdx, onPick])

  if (!items.length) return null

  return (
    <div
      data-testid="slash-menu"
      className="absolute bottom-full left-0 right-0 mb-2 bg-[var(--color-panel)] border border-[var(--color-border)] rounded shadow-lg max-h-64 overflow-auto z-20"
    >
      <div className="text-[10px] uppercase tracking-wider px-3 py-1.5 text-[var(--color-dim)] border-b border-[var(--color-border)]">
        Commands · Tab/Enter to pick · ↑↓ navigate
      </div>
      {items.map((c, i) => (
        <div
          key={c.name}
          data-testid={`slash-option-${c.name.slice(1)}`}
          onMouseEnter={() => setFocusIdx(i)}
          onMouseDown={e => { e.preventDefault(); onPick(c.name) }}
          className={
            'px-3 py-2 cursor-pointer ' +
            (i === focusIdx ? 'bg-[var(--color-border)]' : '')
          }
        >
          <div className="flex gap-2 items-baseline">
            <span className="text-[var(--color-accent)] font-semibold">{c.name}</span>
            <span className="text-[var(--color-dim)] text-[11px]">{c.args}</span>
          </div>
          <div className="text-[11px] text-[var(--color-dim)] mt-0.5">{c.description}</div>
        </div>
      ))}
    </div>
  )
}
