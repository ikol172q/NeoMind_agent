import { useState, useEffect } from 'react'
import {
  useWatchlist,
  useWatchlistUpsert,
  useWatchlistPatchNote,
  useWatchlistRemove,
  useQuote,
  useCNQuote,
  useSymbolInsight,
  type WatchEntry,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { InsightHover } from '@/components/ui/InsightHover'
import { FactorPills } from '@/components/ui/FactorPills'
import { fmtNum } from '@/lib/utils'
import { Plus, X, MessageSquare, RefreshCw, ChevronRight, ChevronDown } from 'lucide-react'

interface Props {
  projectId: string
  /** When provided, clicking the row's "ask" button prefills a chat
   *  prompt and switches the App to the Chat tab. If omitted the
   *  button is hidden. */
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

/**
 * Project-scoped watchlist. Rows are `(market, symbol)` pairs with a
 * free-form note. Prices are fetched per row via the same hooks the
 * quote cards use, so we inherit their polling / caching behavior.
 */
export function WatchlistWidget({ projectId, onJumpToChat }: Props) {
  const list = useWatchlist(projectId)
  const upsert = useWatchlistUpsert(projectId)
  const remove = useWatchlistRemove(projectId)

  const [newSymbol, setNewSymbol] = useState('')
  const [newMarket, setNewMarket] = useState<'US' | 'CN' | 'HK'>('US')

  async function addEntry() {
    const sym = newSymbol.trim().toUpperCase()
    if (!sym) return
    await upsert.mutateAsync({ symbol: sym, market: newMarket, note: '' })
    setNewSymbol('')
  }

  const entries = list.data?.entries ?? []

  return (
    <Card className="h-full flex flex-col" data-testid="watchlist-widget">
      <CardHeader
        title="Watchlist"
        subtitle={`${entries.length} tracked · project ${projectId}`}
        right={
          <Button size="sm" variant="ghost" onClick={() => list.refetch()} disabled={list.isFetching}>
            <RefreshCw size={11} className={list.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-2 overflow-hidden">
        {/* Add row */}
        <div className="flex gap-2 items-center">
          <select
            data-testid="watchlist-new-market"
            value={newMarket}
            onChange={e => setNewMarket(e.target.value as 'US' | 'CN' | 'HK')}
            className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-xs py-1.5"
          >
            <option value="US">US</option>
            <option value="CN">CN</option>
            <option value="HK">HK</option>
          </select>
          <Input
            data-testid="watchlist-new-symbol"
            value={newSymbol}
            onChange={e => setNewSymbol(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addEntry()}
            placeholder={newMarket === 'CN' ? '600519' : 'AAPL'}
            className="flex-1 uppercase"
          />
          <Button data-testid="watchlist-add" onClick={addEntry} disabled={!newSymbol.trim() || upsert.isPending}>
            <Plus size={11} /> Add
          </Button>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto" data-testid="watchlist-rows">
          {list.isLoading && (
            <div className="text-[var(--color-dim)] text-xs p-2">loading…</div>
          )}
          {!list.isLoading && entries.length === 0 && (
            <div className="text-[var(--color-dim)] italic text-xs text-center p-4">
              Empty. Add a symbol above.
            </div>
          )}
          {entries.map(entry => (
            <InsightHover
              key={`${entry.market}:${entry.symbol}`}
              projectId={projectId}
              symbol={entry.symbol}
            >
              <div className="relative">
                <WatchRow
                  projectId={projectId}
                  entry={entry}
                  onRemove={() => remove.mutate({ symbol: entry.symbol, market: entry.market })}
                  onJumpToChat={onJumpToChat}
                />
              </div>
            </InsightHover>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

interface RowProps {
  projectId: string
  entry: WatchEntry
  onRemove: () => void
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

function WatchRow({ projectId, entry, onRemove, onJumpToChat }: RowProps) {
  // Debounced note patch
  const patchNote = useWatchlistPatchNote(projectId)
  const [noteDraft, setNoteDraft] = useState(entry.note ?? '')
  useEffect(() => { setNoteDraft(entry.note ?? '') }, [entry.note])

  // 3-tier density. Tier 1 = just the 1-line row (default, Seeking
  // Alpha's "letter grade" altitude). Tier 2 = factor pills (math,
  // no LLM). Tier 3 = inline agent narrative (LLM, shares the
  // insight cache with hover tooltips).
  const [tier, setTier] = useState<1 | 2 | 3>(1)

  const usQ = useQuote(entry.market === 'US' ? entry.symbol : null)
  const cnQ = useCNQuote(entry.market === 'CN' ? entry.symbol : null)

  const q =
    entry.market === 'US' ? usQ.data :
    entry.market === 'CN' ? cnQ.data :
    null
  const price = q?.price ?? null
  const chg = q?.change ?? null
  const pct = q?.change_pct ?? null
  const up = (chg ?? 0) >= 0
  const color = chg == null ? 'text-[var(--color-dim)]' : up ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'

  function saveNote() {
    if ((noteDraft ?? '') === (entry.note ?? '')) return
    patchNote.mutate({ symbol: entry.symbol, market: entry.market, note: noteDraft })
  }

  function askAgent() {
    if (!onJumpToChat) return
    const prompt = `Analyze ${entry.market}:${entry.symbol}${entry.note ? ` (my note: "${entry.note}")` : ''}. Cover: latest price action, what's driving it today, any risks I should watch. Keep it under 200 words.`
    onJumpToChat(prompt, { symbol: entry.symbol })
  }

  function bumpTier() {
    setTier(t => (t === 1 ? 2 : t === 2 ? 3 : 1))
  }

  // Factors only applicable to US for now (yfinance fundamental coverage).
  const showFactors = entry.market === 'US' && tier >= 2

  return (
    <div
      data-testid={`watchlist-row-${entry.market}-${entry.symbol}`}
      className="flex flex-col px-1 py-1 text-[11px] border-b border-[var(--color-border)]/40 hover:bg-[var(--color-border)]/20"
    >
      {/* Tier 1: one-line row (always visible) */}
      <div className="flex items-center gap-2">
        <button
          data-testid={`watchlist-tier-toggle-${entry.market}-${entry.symbol}`}
          onClick={bumpTier}
          className="text-[var(--color-dim)] hover:text-[var(--color-accent)] transition w-4 shrink-0"
          title={
            tier === 1 ? 'expand: factor pills (M V Q G R)'
              : tier === 2 ? 'expand: raw + agent read'
                : 'collapse'
          }
        >
          {tier === 1 ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
        </button>
        <div className="w-8 text-[10px] text-[var(--color-dim)] uppercase">{entry.market}</div>
        <div className="w-16 font-mono text-[var(--color-text)] truncate">{entry.symbol}</div>
        <div className="w-16 text-right font-mono">
          {price != null ? fmtNum(price) : <span className="text-[var(--color-dim)]">—</span>}
        </div>
        <div className={`w-20 text-right font-mono ${color}`}>
          {pct != null ? `${up ? '+' : ''}${fmtNum(pct)}%` : ''}
        </div>
        <input
          data-testid={`watchlist-note-${entry.market}-${entry.symbol}`}
          value={noteDraft}
          onChange={e => setNoteDraft(e.target.value)}
          onBlur={saveNote}
          onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          placeholder="note…"
          className="flex-1 min-w-0 bg-transparent border-0 border-b border-transparent hover:border-[var(--color-border)] focus:border-[var(--color-accent)] focus:outline-none px-1 py-0.5 text-[11px]"
        />
        {onJumpToChat && (
          <button
            data-testid={`watchlist-ask-${entry.market}-${entry.symbol}`}
            onClick={askAgent}
            className="text-[var(--color-dim)] hover:text-[var(--color-accent)] transition"
            title="ask fin about this (opens chat with context)"
          >
            <MessageSquare size={11} />
          </button>
        )}
        <button
          data-testid={`watchlist-del-${entry.market}-${entry.symbol}`}
          onClick={onRemove}
          className="text-[var(--color-dim)] hover:text-[var(--color-red)] transition"
          title="remove"
        >
          <X size={11} />
        </button>
      </div>

      {/* Tier 2: factor pills row */}
      {tier >= 2 && (
        <div
          className="flex items-center gap-2 mt-1 pl-6 pb-1"
          data-testid={`watchlist-tier2-${entry.market}-${entry.symbol}`}
        >
          {showFactors ? (
            <FactorPills symbol={entry.symbol} enabled={tier >= 2} />
          ) : (
            <span className="text-[10px] text-[var(--color-dim)] italic">
              factor grades available for US symbols only
            </span>
          )}
        </div>
      )}

      {/* Tier 3: raw numbers + agent narrative */}
      {tier >= 3 && showFactors && (
        <Tier3Detail symbol={entry.symbol} projectId={projectId} />
      )}
    </div>
  )
}

function Tier3Detail({ symbol, projectId }: { symbol: string; projectId: string }) {
  // Reuse the same insight endpoint — this is exactly the "deep
  // read" the hover tooltip short-forms. No new LLM call if the
  // cache is warm from an earlier hover.
  const insight = useSymbolInsight(projectId, symbol, true)
  return (
    <div
      data-testid={`watchlist-tier3-${symbol}`}
      className="mt-1 pl-6 pb-1 flex flex-col gap-1"
    >
      <div className="text-[10px] text-[var(--color-dim)] italic">
        agent read (cached 5 min) — same source as the hover tooltip
      </div>
      <div className="text-[11px] text-[var(--color-text)] leading-snug">
        {insight.isLoading && <span className="text-[var(--color-dim)] italic">thinking…</span>}
        {insight.isError && (
          <span className="text-[var(--color-red)]">
            {(insight.error as Error).message.slice(0, 120)}
          </span>
        )}
        {insight.data && insight.data.text}
      </div>
    </div>
  )
}
