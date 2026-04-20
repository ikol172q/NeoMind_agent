import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist-min'

// Minimal Plotly React wrapper. react-plotly.js has CJS/ESM interop
// issues under Vite+TS (its default export resolves to an object,
// not a component). Rolling our own ~20-line wrapper avoids the
// dependency and gives us the exact lifecycle hooks we need.
interface PlotProps {
  data: Array<Record<string, unknown>>
  layout: Record<string, unknown>
  config?: Record<string, unknown>
  style?: React.CSSProperties
  /** Optional click handler — fires with the native plotly click
   *  event data (points array, etc). */
  onClick?: (ev: unknown) => void
}

export function Plot({ data, layout, config, style, onClick }: PlotProps) {
  const ref = useRef<HTMLDivElement>(null)
  const handlerRef = useRef<typeof onClick>(onClick)
  handlerRef.current = onClick

  useEffect(() => {
    if (!ref.current) return
    const el = ref.current
    Plotly.react(
      el,
      data,
      layout,
      config ?? { displayModeBar: false, responsive: true },
    )
    // Re-bind click each time — plotly clears listeners when data
    // changes via react(). Guard through the ref so we always use
    // the latest handler without re-running the layout effect.
    if (handlerRef.current) {
      // @ts-expect-error plotly's event API isn't typed in the dist-min build
      el.on?.('plotly_click', (ev: unknown) => handlerRef.current?.(ev))
    }
  }, [data, layout, config])

  useEffect(() => {
    const el = ref.current
    return () => {
      if (el) Plotly.purge(el)
    }
  }, [])

  return <div ref={ref} style={{ width: '100%', height: '100%', ...style }} />
}
