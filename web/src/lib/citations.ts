/**
 * Citation-linked claims — parsing + rendering helpers.
 *
 * Agents emit inline tags like [[AAPL]] or [[sector:Technology]] or
 * [[pos:NVDA]]. This module parses them out of the surrounding text
 * so the UI can render each as a clickable chip that jumps back to
 * the referenced symbol/widget in context.
 *
 * Graceful degradation: if the model doesn't emit tags, the text
 * renders as-is — zero broken UX.
 */

export type CiteKind = 'symbol' | 'sector' | 'pos'

export interface Citation {
  kind: CiteKind
  /** For symbol/pos: the ticker. For sector: the sector name. */
  id: string
  /** The literal text to display. Defaults to the id. */
  label: string
}

export type Segment =
  | { type: 'text'; text: string }
  | { type: 'cite'; cite: Citation }

// Accept mixed case — sector names like "Consumer Discretionary",
// "Communication Services" are title-case, not all caps.
const CITE_RE = /\[\[(?:([a-zA-Z]+):)?([A-Za-z0-9 .&/_-]{1,60})\]\]/g

function normalizeKind(raw: string | undefined): CiteKind {
  const k = (raw || '').toLowerCase()
  if (k === 'sector') return 'sector'
  if (k === 'pos' || k === 'position') return 'pos'
  // Default: anything that looks like a ticker (uppercase w/ digits) is symbol
  return 'symbol'
}

/**
 * Turn text into an ordered list of text + cite segments.
 * Never throws; worst case returns a single `{type:'text'}` segment.
 */
export function parseCitations(raw: string): Segment[] {
  if (!raw) return []
  const out: Segment[] = []
  let lastIdx = 0
  // Reset the regex — it's module-level with /g
  CITE_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = CITE_RE.exec(raw)) !== null) {
    if (m.index > lastIdx) {
      out.push({ type: 'text', text: raw.slice(lastIdx, m.index) })
    }
    const kind = normalizeKind(m[1])
    const id = m[2].trim()
    if (id) {
      out.push({ type: 'cite', cite: { kind, id, label: id } })
    }
    lastIdx = m.index + m[0].length
  }
  if (lastIdx < raw.length) {
    out.push({ type: 'text', text: raw.slice(lastIdx) })
  }
  if (out.length === 0) out.push({ type: 'text', text: raw })
  return out
}

/**
 * How many citations exist in a parsed segment list — useful for
 * quickly gating UI features (e.g. don't show the "citations" legend
 * row unless at least one exists).
 */
export function countCitations(segments: Segment[]): number {
  return segments.filter(s => s.type === 'cite').length
}
