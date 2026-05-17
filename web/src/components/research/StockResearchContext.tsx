/**
 * Cross-component "open ticker research drawer" channel. Anywhere in
 * the app that has a ticker (Smart Money widget, chat reply, news
 * card, future stock screener) can call openTicker(symbol) to slide
 * the drawer in. The drawer renders at App root so it floats over
 * whatever tab is active and returns to that context when closed.
 *
 * 2026-05-16: added navStack so the user's "walk along supply chain"
 * workflow has a back button. openTicker pushes the previous ticker
 * onto the stack; back() pops one frame.
 */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'

interface StockResearchCtx {
  ticker: string | null
  projectId: string
  openTicker: (t: string) => void
  closeTicker: () => void
  navStack: string[]
  back: () => void
}

const ResearchContext = createContext<StockResearchCtx>({
  ticker: null,
  projectId: 'fin-core',
  openTicker: () => {},
  closeTicker: () => {},
  navStack: [],
  back: () => {},
})

export function StockResearchProvider({
  children, projectId,
}: { children: ReactNode; projectId: string }) {
  const [ticker, setTicker] = useState<string | null>(null)
  const [navStack, setNavStack] = useState<string[]>([])
  const openTicker = useCallback((t: string) => {
    const upper = t.toUpperCase()
    setTicker(prev => {
      // Only push to stack when navigating between different tickers
      // (avoid duplicating when user re-clicks the same one).
      if (prev && prev !== upper) {
        setNavStack(s => [...s, prev])
      }
      return upper
    })
  }, [])
  const closeTicker = useCallback(() => {
    setTicker(null)
    setNavStack([])
  }, [])
  const back = useCallback(() => {
    setNavStack(s => {
      if (s.length === 0) {
        setTicker(null)
        return s
      }
      const prev = s[s.length - 1]
      setTicker(prev)
      return s.slice(0, -1)
    })
  }, [])

  // ESC closes the drawer (clears stack too)
  useEffect(() => {
    if (!ticker) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeTicker()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ticker, closeTicker])

  return (
    <ResearchContext.Provider value={{ ticker, projectId, openTicker, closeTicker, navStack, back }}>
      {children}
    </ResearchContext.Provider>
  )
}

export function useStockResearch() {
  return useContext(ResearchContext)
}
