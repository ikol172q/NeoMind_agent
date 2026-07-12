import { useCallback, useState } from 'react'

/**
 * Persisted collapse state for a home-tab module, so a module you fold stays
 * folded across reloads. Follows the existing `strategies.<key>.collapsed`
 * = '1'/'0' localStorage convention (see Watchlist). Default is EXPANDED so
 * nothing hides by surprise — the user folds what they don't want to see.
 *
 *   const [collapsed, toggle] = useCollapsed('research-inbox')
 */
export function useCollapsed(
  key: string,
  defaultCollapsed = false,
): [boolean, () => void] {
  const storageKey = `strategies.${key}.collapsed`
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(storageKey)
      return v === null ? defaultCollapsed : v === '1'
    } catch {
      return defaultCollapsed
    }
  })
  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(storageKey, next ? '1' : '0')
      } catch {
        /* private mode / quota — degrade to in-memory only */
      }
      return next
    })
  }, [storageKey])
  return [collapsed, toggle]
}
