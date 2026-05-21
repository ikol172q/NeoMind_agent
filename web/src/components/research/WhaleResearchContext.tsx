/**
 * Cross-component "open whale profile drawer" channel. Any whale name
 * in the app (SmartMoneyWidget per-fund header, ARK panel, news cards
 * mentioning a fund) can call openWhale(whaleKey) to slide the drawer in.
 *
 * Parallel to StockResearchContext; kept separate so the user can have
 * BOTH a ticker drawer AND a whale drawer open visually (whale on right,
 * ticker pushes from same right edge but stacked — see App.tsx).
 *
 * 2026-05-19: created for whale encyclopedia drawer feature.
 */
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'

interface WhaleResearchCtx {
  whaleKey: string | null
  openWhale: (k: string) => void
  closeWhale: () => void
}

const WhaleResearchCtxObj = createContext<WhaleResearchCtx>({
  whaleKey: null,
  openWhale: () => {},
  closeWhale: () => {},
})

export function WhaleResearchProvider({ children }: { children: ReactNode }) {
  const [whaleKey, setWhaleKey] = useState<string | null>(null)
  const openWhale = useCallback((k: string) => setWhaleKey(k), [])
  const closeWhale = useCallback(() => setWhaleKey(null), [])

  useEffect(() => {
    if (!whaleKey) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeWhale()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [whaleKey, closeWhale])

  return (
    <WhaleResearchCtxObj.Provider value={{ whaleKey, openWhale, closeWhale }}>
      {children}
    </WhaleResearchCtxObj.Provider>
  )
}

export function useWhaleResearch() {
  return useContext(WhaleResearchCtxObj)
}
