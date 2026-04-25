import { useEffect } from 'react'
import { X } from 'lucide-react'
import { WatchlistWidget } from './WatchlistWidget'
import { PortfolioHeatmapWidget } from './PortfolioHeatmapWidget'

interface Props {
  open: boolean
  onClose: () => void
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

// Lightweight right-side drawer for editing watchlist + portfolio
// without leaving the lattice. Re-uses the existing widgets — they
// already implement the full add/remove/note/upload flow against the
// /api/watchlist and /api/portfolio endpoints, so the drawer is pure
// composition.
export function ResearchConfigDrawer({ open, onClose, projectId, onJumpToChat }: Props) {
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        data-testid="research-config-backdrop"
      />
      <aside
        data-testid="research-config-drawer"
        className="fixed top-0 right-0 h-full w-[480px] max-w-[90vw] bg-[var(--color-panel)] border-l border-[var(--color-border)] z-50 flex flex-col shadow-2xl"
      >
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)] shrink-0">
          <div>
            <div className="text-xs font-semibold text-[var(--color-text)]">Research config</div>
            <div className="text-[10px] text-[var(--color-dim)]">Watchlist + Portfolio · feeds the lattice L0 layer</div>
          </div>
          <button
            data-testid="research-config-close"
            onClick={onClose}
            className="p-1 text-[var(--color-dim)] hover:text-[var(--color-text)] transition"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          <section data-testid="config-watchlist-section">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] mb-1.5">Watchlist</div>
            <div className="h-[320px] border border-[var(--color-border)] rounded">
              <WatchlistWidget projectId={projectId} onJumpToChat={onJumpToChat} />
            </div>
          </section>

          <section data-testid="config-portfolio-section">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)] mb-1.5">Portfolio</div>
            <div className="h-[320px] border border-[var(--color-border)] rounded">
              <PortfolioHeatmapWidget projectId={projectId} onJumpToChat={onJumpToChat} />
            </div>
          </section>

          <p className="text-[10px] text-[var(--color-dim)] leading-relaxed">
            Changes here update the data the lattice ingests on next refresh.
            For market-data exploration (charts, deep quotes, screeners), prefer
            external products — TradingView, Yahoo Finance, Koyfin, Finviz —
            linked from the L0 nodes in the graph.
          </p>
        </div>
      </aside>
    </>
  )
}
