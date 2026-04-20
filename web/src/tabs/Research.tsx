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

const ResponsiveGridLayout = WidthProvider(Responsive)

// v2 added watchlist, v3 added sector heatmap, v4 adds RS grid.
// Bumping the version forces the new default so users pick up the
// new tile position without having to clear localStorage.
const LS_KEY = 'neomind.research.layout.v4'

const DEFAULT_LAYOUT: Layout[] = [
  { i: 'watchlist', x: 0,  y: 0,  w: 5,  h: 10 },
  { i: 'us_quote',  x: 5,  y: 0,  w: 4,  h: 7 },
  { i: 'cn_quote',  x: 9,  y: 0,  w: 3,  h: 7 },
  { i: 'cn_info',   x: 5,  y: 7,  w: 7,  h: 5 },
  { i: 'sectors',   x: 0,  y: 12, w: 8,  h: 10 },
  { i: 'rs_grid',   x: 8,  y: 12, w: 4,  h: 10 },
  { i: 'chart',     x: 0,  y: 22, w: 8,  h: 10 },
  { i: 'news',      x: 8,  y: 22, w: 4,  h: 10 },
  { i: 'history',   x: 0,  y: 32, w: 12, h: 8 },
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
      <div key="sectors"><div className="drag-handle h-full cursor-move"><SectorHeatmapWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="rs_grid"><div className="drag-handle h-full cursor-move"><RSGridWidget onJumpToChat={onJumpToChat} /></div></div>
      <div key="chart"><div className="drag-handle h-full cursor-move"><ChartWidget /></div></div>
      <div key="news"><div className="drag-handle h-full cursor-move"><NewsList /></div></div>
      <div key="history"><div className="drag-handle h-full cursor-move"><HistoryTable projectId={projectId} /></div></div>
    </ResponsiveGridLayout>
  )
}
