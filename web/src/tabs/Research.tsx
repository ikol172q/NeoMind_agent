import { Responsive, WidthProvider, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { USQuoteCard } from '@/components/widgets/USQuoteCard'
import { CNQuoteCard } from '@/components/widgets/CNQuoteCard'
import { CNInfoCard } from '@/components/widgets/CNInfoCard'
import { NewsList } from '@/components/widgets/NewsList'
import { HistoryTable } from '@/components/widgets/HistoryTable'
import { ChartWidget } from '@/components/widgets/ChartWidget'

const ResponsiveGridLayout = WidthProvider(Responsive)

const LS_KEY = 'neomind.research.layout.v1'

const DEFAULT_LAYOUT: Layout[] = [
  { i: 'us_quote',  x: 0,  y: 0, w: 4,  h: 7 },
  { i: 'cn_quote',  x: 4,  y: 0, w: 4,  h: 7 },
  { i: 'cn_info',   x: 8,  y: 0, w: 4,  h: 7 },
  { i: 'chart',     x: 0,  y: 7, w: 8,  h: 10 },
  { i: 'news',      x: 8,  y: 7, w: 4,  h: 10 },
  { i: 'history',   x: 0,  y: 17, w: 12, h: 8 },
]

function loadLayout(): Layout[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw) as Layout[]
  } catch {}
  return DEFAULT_LAYOUT
}

interface Props { projectId: string }

export function ResearchTab({ projectId }: Props) {
  const layout = loadLayout()

  return (
    <ResponsiveGridLayout
      className="layout"
      layouts={{ lg: layout, md: layout, sm: layout, xs: layout }}
      breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 0 }}
      cols={{ lg: 12, md: 12, sm: 8, xs: 4 }}
      rowHeight={32}
      draggableHandle=".cursor-move, .drag-handle"
      margin={[10, 10]}
      onLayoutChange={(l) => {
        try { localStorage.setItem(LS_KEY, JSON.stringify(l)) } catch {}
      }}
    >
      <div key="us_quote"><div className="drag-handle h-full cursor-move"><USQuoteCard /></div></div>
      <div key="cn_quote"><div className="drag-handle h-full cursor-move"><CNQuoteCard /></div></div>
      <div key="cn_info"><div className="drag-handle h-full cursor-move"><CNInfoCard /></div></div>
      <div key="chart"><div className="drag-handle h-full cursor-move"><ChartWidget /></div></div>
      <div key="news"><div className="drag-handle h-full cursor-move"><NewsList /></div></div>
      <div key="history"><div className="drag-handle h-full cursor-move"><HistoryTable projectId={projectId} /></div></div>
    </ResponsiveGridLayout>
  )
}
