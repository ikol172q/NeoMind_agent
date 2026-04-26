/**
 * HoverPopover — Phase 6 followup #6: hover-to-drill UX.
 *
 * Replaces "click X, then look at Y" instructions with on-hover preview.
 * Wraps an element; on mouse-enter (after small delay) renders an
 * absolutely-positioned popover with arbitrary content.
 *
 * - Delay 250ms before show: avoids flicker on quick mouse traversal.
 * - Stays open while cursor moves between trigger and popover (single
 *   mouseleave on the wrapper, not on the trigger alone).
 * - Auto-positions: prefers below; flips above if it would overflow
 *   viewport bottom; clamps to viewport horizontally.
 * - Lazy: content function not invoked until first hover (keeps cost
 *   off the initial render path even if the page has 100 chips).
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'


export interface HoverPopoverProps {
  /** Trigger — what the user hovers over.  Inline element. */
  children: ReactNode
  /** Popover body — function so the rendered tree is lazy. */
  content: () => ReactNode
  /** Width hint, default 280px. */
  width?: number
  /** ms before popover appears; default 250ms. */
  delay?: number
  /** Optional className for the trigger wrapper. */
  className?: string
  /** data-testid prefix; popover gets `${dataTestid}-popover`. */
  dataTestid?: string
}

export function HoverPopover({
  children,
  content,
  width = 280,
  delay = 250,
  className,
  dataTestid,
}: HoverPopoverProps) {
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number; flip: boolean } | null>(null)
  const wrapperRef = useRef<HTMLSpanElement | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (!hovered) {
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setOpen(false), 80)
      return
    }
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), delay)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [hovered, delay])

  // Compute popover position whenever it opens.
  useEffect(() => {
    if (!open) return
    const trigger = wrapperRef.current
    if (!trigger) return
    const r = trigger.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const popoverHeight = 200  // estimate; over-cautious flip
    const flip = r.bottom + popoverHeight > vh && r.top > popoverHeight

    let left = r.left
    if (left + width > vw - 8) left = vw - width - 8
    if (left < 8) left = 8

    const top = flip ? r.top - 8 : r.bottom + 6
    setPos({ left, top, flip })
  }, [open, width])

  return (
    <span
      ref={wrapperRef}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      className={className}
      data-testid={dataTestid}
    >
      {children}
      {open && pos && (
        <span
          role="tooltip"
          data-testid={dataTestid ? `${dataTestid}-popover` : undefined}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          style={{
            position: 'fixed',
            left: pos.left,
            top: pos.top,
            width,
            transform: pos.flip ? 'translateY(-100%)' : undefined,
            background: 'var(--color-panel, #0e1219)',
            border: '1px solid var(--color-border)',
            borderRadius: 4,
            padding: '6px 8px',
            zIndex: 1000,
            fontSize: 10,
            lineHeight: 1.45,
            color: 'var(--color-text)',
            boxShadow: '0 4px 16px rgba(0,0,0,0.45)',
            pointerEvents: 'auto',
          }}
        >
          {content()}
        </span>
      )}
    </span>
  )
}
