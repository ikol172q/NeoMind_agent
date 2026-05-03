/**
 * Cross-component "open ticker research drawer" channel. Anywhere in
 * the app that has a ticker (Smart Money widget, chat reply, news
 * card, future stock screener) can call openTicker(symbol) to slide
 * the drawer in. The drawer renders at App root so it floats over
 * whatever tab is active and returns to that context when closed.
 *
 * MVP: drawer state = current ticker (or null). Stack navigation
 * (NVDA → TSM → ASML drill) deferred to a later phase.
 */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'

interface StockResearchCtx {
  ticker: string | null
  projectId: string
  openTicker: (t: string) => void
  closeTicker: () => void
}

const ResearchContext = createContext<StockResearchCtx>({
  ticker: null,
  projectId: 'fin-core',
  openTicker: () => {},
  closeTicker: () => {},
})

export function StockResearchProvider({
  children, projectId,
}: { children: ReactNode; projectId: string }) {
  const [ticker, setTicker] = useState<string | null>(null)
  const openTicker = useCallback((t: string) => setTicker(t.toUpperCase()), [])
  const closeTicker = useCallback(() => setTicker(null), [])

  // ESC closes the drawer
  useEffect(() => {
    if (!ticker) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeTicker()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ticker, closeTicker])

  return (
    <ResearchContext.Provider value={{ ticker, projectId, openTicker, closeTicker }}>
      {children}
    </ResearchContext.Provider>
  )
}

export function useStockResearch() {
  return useContext(ResearchContext)
}
