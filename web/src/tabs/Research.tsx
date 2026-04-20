import { Responsive, WidthProvider, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { USQuoteCard } from '@/components/widgets/USQuoteCard'
import { CNQuoteCard } from '@/components/widgets/CNQuoteCard'
import { CNInfoCard } from '@/components/widgets/CNInfoCard'
import { NewsList } from '@/components/widgets/NewsList'
import { HistoryTable } from '@/components/widgets/HistoryTable'
import { ChartWidget } from '@/components/widgets/ChartWidget'
import { WatchlistWidget } from '@/components/widgets/WatchlistWidget'
import { SectorHeatmapWidget } from '@/components/widgets/SectorHeatmapWidget'
import { RSGridWidget } from '@/components/widgets/RSGridWidget'
import { EarningsWidget } from '@/components/widgets/EarningsWidget'

const ResponsiveGridLayout = WidthProvider(Responsive)

// v6 reshuffles so News sits in the top viewport (user complaint:
// "can't see what's happening in the market without scrolling").
// News is right-hand column of the hero row, visible on first
// paint alongside watchlist. Quotes stack compact in the last
// hero column. Earnings + RS + Sectors form the mid analytics
// band; chart + cn_info the detail band; history at the bottom.
const LS_KEY = 'neomind.research.layout.v6'

const DEFAULT_LAYOUT: Layout[] = [
  // Hero row — visible on first paint
  { i: 'watchlist', x: 0,  y: 0,  w: 5,  h: 12 },
  { i: 'news',      x: 5,  y: 0,  w: 4,  h: 12 },
  { i: 'us_quote',  x: 9,  y: 0,  w: 3,  h: 6 },
  { i: 'cn_quote',  x: 9,  y: 6,  w: 3,  h: 6 },
  // Analytics band
  { i: 'earnings',  x: 0,  y: 12, w: 6,  h: 9 },
  { i: 'rs_grid',   x: 6,  y: 12, w: 6,  h: 9 },
  { i: 'sectors',   x: 0,  y: 21, w: 12, h: 9 },
  // Detail band
  { i: 'chart',     x: 0,  y: 30, w: 8,  h: 10 },
  { i: 'cn_info',   x: 8,  y: 30, w: 4,  h: 10 },
  // Reference
  { i: 'history',   x: 0,  y: 40, w: 12, h: 8 },
]

function loadLayout(): Layout[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw) as Layout[]
  } catch {}
  return DEFAULT_LAYOUT
}

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string) => void
}

export function ResearchTab({ projectId, onJumpToChat }: Props) {
  const layout = loadLayout()

  return (
    <ResponsiveGridLayout
      className="layout"
      layouts={{ lg: layout, md: layout, sm: layout, xs: layout }}
      breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 0 }}
      cols={{ lg: 12, md: 12, sm: 8, xs: 4 }}
      rowHeight={32}
      draggableHandle=".cursor-move, .drag-handle"
      // Inputs / buttons / selects inside a widget must not trigger a
      // grid-drag on mousedown — otherwise clicking "Add" on the
      // watchlist (and every other button inside a widget) gets
      // swallowed before the onClick handler can fire. Matches the
      // pattern react-grid-layout recommends for interactive cards.
      draggableCancel="input, select, textarea, button, a, [contenteditable='true']"
      margin={[10, 10]}
      onLayoutChange={(l) => {
        try { localStorage.setItem(LS_KEY, JSON.stringify(l)) } catch {}
      }}
    >
      <div key="watchlist"><div className="drag-handle h-full cursor-move"><WatchlistWidget projectId={projectId} onJumpToChat={onJumpToChat} /></div></div>
      <div key="us_quote"><div className="drag-handle h-full cursor-move"><USQuoteCard /></div></div>
      <div key="cn_quote"><div className="drag-handle h-full cursor-move"><CNQuoteCard /></div></div>
      <div key="cn_info"><div className="drag-handle h-full cursor-move"><CNInfoCard /></div></div>
      <div key="earnings"><div className="drag-handle h-full cursor-move"><EarningsWidget projectId={projectId} onJumpToChat={onJumpToChat} /></div></div>
      <div key="sectors"><div className="drag-handle h-full cursor-move"><SectorHeatmapWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="rs_grid"><div className="drag-handle h-full cursor-move"><RSGridWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="chart"><div className="drag-handle h-full cursor-move"><ChartWidget /></div></div>
      <div key="news"><div className="drag-handle h-full cursor-move"><NewsList /></div></div>
      <div key="history"><div className="drag-handle h-full cursor-move"><HistoryTable projectId={projectId} /></div></div>
    </ResponsiveGridLayout>
  )
}
