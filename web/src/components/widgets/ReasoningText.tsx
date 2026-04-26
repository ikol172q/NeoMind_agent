/**
 * ReasoningText — Phase 6 followup #4: reasoning hyperlinks.
 *
 * Wraps an L3 call's claim / grounds / warrant / rebuttal / qualifier
 * text and turns recognised entity tokens into clickable references:
 *
 *   - Ticker symbols (1-5 uppercase letters, with optional $ prefix)
 *   - Percentages (12%, 12.3%)
 *   - Layer references (L0, L1, L1.5, L2, L3)
 *   - Layer-id references (theme:earnings_risk, sub:tax_compliance)
 *
 * Each match becomes a small inline chip with hover popover that
 * shows what was matched + a hint that clicking will search the
 * lattice for it. If `onJumpToTrace` is provided, clicking jumps
 * to the lattice graph view focused on the matching node.
 *
 * Avoiding regex pitfalls:
 * - Ticker pattern excludes a curated stop-list of all-caps English
 *   words common in trading prose ('US', 'CN', 'ETF', 'OTM', 'IV',
 *   'AND', 'THE', 'NOT', etc.) so we don't underline every other
 *   acronym.
 * - We anchor on word boundaries; exiting unchanged when no match.
 */

import { type ReactNode } from 'react'
import { HoverPopover } from './HoverPopover'


// Common English / trading stop-words that look like tickers
// but aren't. False-positive guard — keep this list small but
// effective.
const STOP_TICKERS = new Set<string>([
  'US', 'EU', 'CN', 'UK', 'JP',
  'AND', 'OR', 'BUT', 'NOT', 'THE', 'FOR', 'WITH', 'INTO', 'FROM',
  'OUT', 'IN', 'ON', 'OFF', 'OF', 'TO', 'AS', 'AT', 'BY', 'IS',
  'ETF', 'OTM', 'ITM', 'ATM', 'IV', 'RSI', 'P', 'C', 'EPS', 'PE',
  'YTD', 'QTD', 'MTD', 'WTD', 'YOY', 'QOQ', 'MOM',
  'PDT', 'IRS', 'SEC', 'FOMC', 'FED', 'CPI', 'PPI', 'GDP',
  'A', 'I', 'AI', 'API',
  'OK', 'NO', 'OK',
  // Toulmin layer labels (handled separately so they don't double-highlight)
  'L0', 'L1', 'L2', 'L3',
])


type TokenKind = 'ticker' | 'percent' | 'layer' | 'layer_id'

interface Match {
  kind: TokenKind
  text: string
  start: number
  end: number
}


function findMatches(text: string): Match[] {
  const out: Match[] = []
  // 1) Tickers — $AAPL or AAPL (1-5 caps), word boundary
  //    Capture group: optional $, then 1-5 uppercase letters.
  const tickerRe = /(?<![A-Za-z0-9_])\$?([A-Z]{1,5})(?![A-Za-z0-9])/g
  let m: RegExpExecArray | null
  while ((m = tickerRe.exec(text)) !== null) {
    const sym = m[1]
    if (STOP_TICKERS.has(sym)) continue
    if (sym.length === 1) continue  // "I", "A", "P", "C" too noisy
    out.push({
      kind: 'ticker',
      text: sym,
      start: m.index,
      end: m.index + m[0].length,
    })
  }

  // 2) Percentages — 12%, 12.3%, -5.5%
  const pctRe = /(?<![A-Za-z0-9.])-?\d+(?:\.\d+)?%/g
  while ((m = pctRe.exec(text)) !== null) {
    out.push({
      kind: 'percent',
      text: m[0],
      start: m.index,
      end: m.index + m[0].length,
    })
  }

  // 3) Layer-id references — `theme:earnings_risk`, `sub:tax_compliance`,
  //    `widget:chart`. Lower-case dotted ids common in lattice graph nodes.
  const layerIdRe = /(?<![A-Za-z0-9_])(theme|sub|sub_theme|obs|widget|call):[a-z0-9_.]+/g
  while ((m = layerIdRe.exec(text)) !== null) {
    out.push({
      kind: 'layer_id',
      text: m[0],
      start: m.index,
      end: m.index + m[0].length,
    })
  }

  // De-duplicate overlapping matches; prefer earlier start, then longer.
  out.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start))
  const filtered: Match[] = []
  let lastEnd = -1
  for (const x of out) {
    if (x.start < lastEnd) continue
    filtered.push(x)
    lastEnd = x.end
  }
  return filtered
}


function tokenStyle(kind: TokenKind): React.CSSProperties {
  if (kind === 'ticker') return {
    color: 'var(--color-accent)',
    background: 'rgba(0,180,255,0.06)',
    fontFamily: 'ui-monospace, monospace',
    padding: '0 3px',
    borderRadius: 2,
    cursor: 'help',
    fontSize: '0.95em',
  }
  if (kind === 'percent') return {
    color: 'var(--color-amber,#e5a200)',
    fontFamily: 'ui-monospace, monospace',
    padding: '0 3px',
    borderRadius: 2,
    cursor: 'help',
    fontSize: '0.95em',
  }
  if (kind === 'layer_id') return {
    color: 'var(--color-green)',
    background: 'rgba(0,200,120,0.05)',
    fontFamily: 'ui-monospace, monospace',
    padding: '0 3px',
    borderRadius: 2,
    cursor: 'help',
    fontSize: '0.92em',
  }
  return {}
}


export interface ReasoningTextProps {
  /** The text to scan + render. */
  text: string
  /** Click handler invoked with the matched token text (e.g. 'AAPL').
   *  If omitted, tokens render as hover-only highlights. */
  onJump?: (kind: TokenKind, token: string) => void
  /** Optional className passed to the wrapping span. */
  className?: string
}


export function ReasoningText({ text, onJump, className }: ReasoningTextProps) {
  if (!text) return <>{text}</>
  const matches = findMatches(text)
  if (matches.length === 0) return <span className={className}>{text}</span>

  const parts: ReactNode[] = []
  let cursor = 0
  matches.forEach((m, i) => {
    if (m.start > cursor) parts.push(<span key={`t-${i}`}>{text.slice(cursor, m.start)}</span>)
    parts.push(
      <HoverPopover
        key={`m-${i}`}
        width={220}
        delay={300}
        dataTestid={`reasoning-${m.kind}-${m.text.replace(/[^A-Za-z0-9_]/g, '_')}`}
        content={() => (
          <div className="flex flex-col gap-0.5">
            <div className="font-mono text-[10.5px] text-[var(--color-text)]">
              {m.text}
            </div>
            <div className="text-[9px] text-[var(--color-dim)] italic">
              {m.kind === 'ticker' && 'Ticker symbol — click to jump to the relevant lattice node.'}
              {m.kind === 'percent' && 'Percentage value extracted from claim text.'}
              {m.kind === 'layer_id' && 'Direct lattice node reference — click to navigate.'}
            </div>
            {onJump && (
              <div className="text-[9px] text-[var(--color-accent)]">
                {`→ click to ${m.kind === 'ticker' ? 'find in lattice' : m.kind === 'layer_id' ? 'open node' : 'search'}`}
              </div>
            )}
          </div>
        )}
      >
        <span
          data-testid={`reasoning-token-${m.kind}-${m.text}`}
          data-token-kind={m.kind}
          data-token-text={m.text}
          style={tokenStyle(m.kind)}
          onClick={onJump ? () => onJump(m.kind, m.text) : undefined}
          role={onJump ? 'button' : undefined}
        >
          {text.slice(m.start, m.end)}
        </span>
      </HoverPopover>,
    )
    cursor = m.end
  })
  if (cursor < text.length) parts.push(<span key="t-last">{text.slice(cursor)}</span>)
  return <span className={className}>{parts}</span>
}
