/**
 * Serenity (@aleabitoreddit) 一手语料库 + 分析层 + 供应链时间轴 + 公司速览 drawer.
 *
 * TimelineChain:横轴=他首次提及该票的日期(时间轴,无需拖滑块),纵向=供应链分层,
 * 边=他陈述的上下游关系,节点亮度=信念(提及量)。点节点 → drawer(yfinance 实时指标)。
 */
import { useState } from 'react'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import {
  useResearchStats, useResearchChokepoint, useResearchPosts, useResearchAnalysis,
  useResearchSupplyChain, useResearchProfile, useResearchSync, type RPost,
} from '@/lib/api'
import { Sparkles, RotateCw, Search, Heart, MessageCircle, ExternalLink, Brain, AlertTriangle, GitBranch, X } from 'lucide-react'
import { fmtTs } from '@/lib/utils'

const EDGE_COLOR: Record<string, string> = { disclosed: '#34d399', high: '#38bdf8', inferred: '#fbbf24', structural: '#4b5563' }
const fmtCap = (n?: number | null) => n == null ? '—' : n >= 1e12 ? `$${(n / 1e12).toFixed(2)}T` : n >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `$${(n / 1e6).toFixed(0)}M` : `$${n}`
const fmtPct = (n?: number | null) => n == null ? '—' : `${(n * 100).toFixed(1)}%`
const fmtN = (n?: number | null, d = 1) => n == null ? '—' : n.toFixed(d)
const dayNum = (s: string) => new Date(s + 'T00:00:00Z').getTime() / 86400000

function Metric({ label, v }: { label: string; v: string }) {
  return <div className="border border-[var(--color-border)] rounded p-1.5"><div className="text-[10px] text-[var(--color-dim)]">{label}</div><div className="text-sm">{v}</div></div>
}

function ProfileDrawer({ ticker, onClose, onFilter }: { ticker: string; onClose: () => void; onFilter: (t: string) => void }) {
  const p = useResearchProfile(ticker).data as any
  const m = p?.metrics || {}
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div className="relative w-full max-w-md h-full bg-[#0b0e14] border-l border-[var(--color-border)] overflow-y-auto p-4 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <div className="font-mono font-semibold text-lg">{ticker}</div>
            <div className="text-xs text-[var(--color-dim)]">{p?.name} · {p?.stage || p?.sector || ''}</div>
          </div>
          <button onClick={onClose} className="text-[var(--color-dim)] hover:text-white"><X size={18} /></button>
        </div>
        {!p ? <div className="text-[var(--color-dim)] text-sm">加载中…(拉 yfinance 实时指标)</div> : (
          <>
            <div className="text-xs"><span className="text-violet-300 font-semibold">信念(提及量) </span><b className="text-base">{p.mentions}</b> 次 · 首提 {p.first || '?'}</div>
            <div className="grid grid-cols-2 gap-2">
              <Metric label="现价" v={m.price != null ? `${m.price} ${m.currency || ''}` : '—'} />
              <Metric label="市值" v={fmtCap(m.marketCap)} />
              <Metric label="P/E (TTM)" v={fmtN(m.trailingPE)} />
              <Metric label="P/E (远期)" v={fmtN(m.forwardPE)} />
              <Metric label="P/S" v={fmtN(m.priceToSales)} />
              <Metric label="营收(年)" v={fmtCap(m.revenue)} />
              <Metric label="营收增速" v={fmtPct(m.revenueGrowth)} />
              <Metric label="净利率" v={fmtPct(m.profitMargin)} />
            </div>
            <div className="space-y-1.5">
              <div className="text-xs text-[var(--color-dim)] font-semibold">上下游(他陈述/推断的关系)</div>
              {p.upstream?.length > 0 && <div className="text-xs">← 上游供应:{p.upstream.map((u: any) => <button key={u.ticker} onClick={() => onFilter(u.ticker)} className="font-mono mr-1.5" style={{ color: EDGE_COLOR[u.conf] }} title={u.note}>{u.ticker}</button>)}</div>}
              {p.downstream?.length > 0 && <div className="text-xs">→ 下游/客户:{p.downstream.map((d: any) => <button key={d.ticker} onClick={() => onFilter(d.ticker)} className="font-mono mr-1.5" style={{ color: EDGE_COLOR[d.conf] }} title={d.note}>{d.ticker}</button>)}</div>}
              {((p.upstream?.length || 0) + (p.downstream?.length || 0)) === 0 && <div className="text-xs text-[var(--color-dim)]">(他未在语料里明确串联此票的上下游)</div>}
            </div>
            {p.risk_flags?.length > 0 && (
              <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5">
                <div className="flex items-center gap-1.5 text-amber-300 font-semibold text-xs mb-1"><AlertTriangle size={12} />风险标记(由数据推导,非建议)</div>
                <ul className="list-disc pl-5 text-[13px] text-[var(--color-dim)] space-y-0.5">{p.risk_flags.map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>
              </div>
            )}
            {p.summary && (
              <div>
                <div className="text-xs text-[var(--color-dim)] font-semibold mb-1">业务 / 运营</div>
                <div className="text-[13px] leading-relaxed text-[var(--color-dim)]">{p.summary}</div>
              </div>
            )}
            <button onClick={() => onFilter(ticker)} className="w-full text-xs py-1.5 rounded border border-[var(--color-border)] hover:border-white/30">
              看他关于 {ticker} 说过的全部({p.mentions} 条 · 首提 {p.first || '?'})
            </button>
            <div className="text-[10px] text-[var(--color-dim)]">{p.data_note}</div>
          </>
        )}
      </div>
    </div>
  )
}

function TimelineChain({ onSelect }: { onSelect: (t: string) => void }) {
  const sc = useResearchSupplyChain().data as any
  if (!sc) return <div className="text-[var(--color-dim)] text-sm">加载中…</div>
  const nodes: any[] = (sc.nodes || []).filter((n: any) => n.first)
  const edges: any[] = sc.edges || []
  const ranks = Array.from(new Set(nodes.map((n) => n.rank))).sort((a, b) => a - b)
  const stageOf = (r: number) => nodes.find((n) => n.rank === r)?.stage ?? ''
  const dts = nodes.map((n) => dayNum(n.first))
  const dmin = Math.min(...dts) - 1, dmax = Math.max(...dts) + 3
  const maxM = Math.max(1, ...nodes.map((n) => n.mentions))
  const W = 980, axL = 108, axR = W - 14, nodeW = 72, nodeH = 24, subH = 28
  const txd = (dn: number) => axL + (axR - axL) * ((dn - dmin) / (dmax - dmin || 1))
  const tx = (s: string) => txd(dayNum(s))

  // 每层内按日期排开,同期碰撞则下移到子行
  const pos: Record<string, { x: number; y: number }> = {}
  const stageTop: Record<number, number> = {}
  let yc = 26
  ranks.forEach((r) => {
    const ns = nodes.filter((n) => n.rank === r).sort((a, b) => dayNum(a.first) - dayNum(b.first))
    const lanes: number[] = []
    ns.forEach((n) => {
      const x = tx(n.first)
      let lane = lanes.findIndex((lx) => x - lx >= nodeW + 3)
      if (lane === -1) lane = lanes.length
      lanes[lane] = x
      pos[n.ticker] = { x, y: yc + lane * subH + nodeH / 2 }
    })
    stageTop[r] = yc
    yc += Math.max(1, lanes.length) * subH + 14
  })
  const H = yc + 6

  const months: { x: number; label: string }[] = []
  const md = new Date(dmin * 86400000); md.setUTCDate(1)
  for (let i = 0; i < 9; i++) {
    const dn = md.getTime() / 86400000
    if (dn <= dmax + 1) months.push({ x: txd(dn), label: `${md.getUTCMonth() + 1}月` })
    md.setUTCMonth(md.getUTCMonth() + 1)
  }

  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="xMidYMin meet" style={{ minHeight: 420 }}>
        {months.map((m, i) => <g key={i}><line x1={m.x} y1={16} x2={m.x} y2={H - 4} stroke="rgba(148,163,184,0.13)" /><text x={m.x + 2} y={12} fontSize={9} fill="#9ca3af">{m.label}</text></g>)}
        {ranks.map((r) => <text key={r} x={4} y={stageTop[r] + 15} fontSize={10} fill="#9ca3af">{stageOf(r)}</text>)}
        {edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to]; if (!a || !b) return null
          const mx = (a.x + b.x) / 2
          return <path key={i} d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`} fill="none"
            stroke={EDGE_COLOR[e.conf] || '#4b5563'} strokeWidth={e.conf === 'structural' ? 1 : 1.6}
            strokeDasharray={e.conf === 'inferred' ? '4 3' : undefined} opacity={e.conf === 'structural' ? 0.3 : 0.7} />
        })}
        {nodes.map((n, i) => {
          const p = pos[n.ticker]
          return (
            <g key={i} onClick={() => onSelect(n.ticker)} style={{ cursor: 'pointer' }}>
              <rect x={p.x - nodeW / 2} y={p.y - nodeH / 2} width={nodeW} height={nodeH} rx={5}
                fill={`rgba(56,189,248,${(0.10 + 0.5 * (n.mentions / maxM)).toFixed(3)})`} stroke="rgba(148,163,184,0.5)" />
              <text x={p.x} y={p.y - 1} fontSize={10} fontFamily="monospace" fill="#e5e7eb" textAnchor="middle">{n.ticker.slice(1)}</text>
              <text x={p.x} y={p.y + 8} fontSize={7} fill="#94a3b8" textAnchor="middle">信念{n.mentions}·{n.first?.slice(5)}</text>
            </g>
          )
        })}
      </svg>
      <div className="text-[10px] text-[var(--color-dim)] leading-relaxed">
        <b>横轴=时间(他首次提及该票的日期),左早右晚</b> → 直接读覆盖顺序;纵向=供应链分层(上游→下游);节点越亮=信念(提及)越强;边=他陈述的关系(<span style={{ color: EDGE_COLOR.disclosed }}>绿已公布</span>/<span style={{ color: EDGE_COLOR.high }}>蓝高信心</span>/<span style={{ color: EDGE_COLOR.inferred }}>黄虚线推断</span>)。点节点看公司速览。
        ⚠️ 语料自 2/6 起 → 大批票挤在最左(2/6-7=他<b>窗口前 2025 就在喊</b>的);真正的<b>新动作看 3 月起</b>:SIVE/SOI/JBL/GFS 今年新挖的深水卡点。
      </div>
    </div>
  )
}

function PostCard({ p }: { p: RPost }) {
  const m = p.metrics || {}
  return (
    <div className="border border-[var(--color-border)] rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between text-xs text-[var(--color-dim)]">
        <span>{fmtTs(p.created_at)}</span>
        <div className="flex items-center gap-3">
          {p.is_reply ? <span className="opacity-60">↩ reply</span> : null}
          {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="hover:text-white"><ExternalLink size={12} /></a>}
        </div>
      </div>
      <div className="text-sm whitespace-pre-wrap leading-relaxed">{p.text}</div>
      {p.media_paths && p.media_paths.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {p.media_paths.map((f) => (
            <a key={f} href={`/api/research/media/${f}`} target="_blank" rel="noreferrer">
              <img src={`/api/research/media/${f}`} alt="" loading="lazy" className="h-28 rounded border border-[var(--color-border)] object-cover" />
            </a>
          ))}
        </div>
      )}
      {p.tickers && p.tickers.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          {p.tickers.map((t) => <span key={t} className="text-xs font-mono text-sky-300">{t}</span>)}
        </div>
      )}
      <div className="flex items-center gap-4 text-xs text-[var(--color-dim)]">
        <span className="flex items-center gap-1"><Heart size={11} />{m.like ?? 0}</span>
        <span className="flex items-center gap-1"><MessageCircle size={11} />{m.reply ?? 0}</span>
        {m.view ? <span>{m.view} views</span> : null}
      </div>
    </div>
  )
}

function AnalysisCard() {
  const a = useResearchAnalysis().data as any
  if (!a) return null
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Brain size={15} className="text-violet-300" />分析层 · 他到底在想什么</span>} subtitle={a.label} />
      <CardBody>
        <div className="space-y-3 text-sm leading-relaxed">
          <div><span className="text-violet-300 font-semibold">方法 · </span>{a.method}</div>
          <div><span className="text-violet-300 font-semibold">心智模型 · </span>{a.mental_model}</div>
          <div>
            <span className="text-violet-300 font-semibold">当前最高信念栈 · </span>
            <span className="inline-flex flex-wrap gap-2 align-middle">
              {a.stack?.map((s: any) => <span key={s.layer} className="text-xs px-1.5 py-0.5 rounded border border-[var(--color-border)]"><b className="text-[var(--color-dim)]">{s.layer}</b> {s.names}</span>)}
            </span>
          </div>
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2.5">
            <div className="flex items-center gap-1.5 text-amber-300 font-semibold text-xs mb-1"><AlertTriangle size={13} />必须警惕(别信他报的数)</div>
            <ul className="list-disc pl-5 space-y-1 text-[13px] text-[var(--color-dim)]">{a.flags?.map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>
          </div>
          <div className="text-[13px] italic text-[var(--color-dim)]">💡 {a.takeaway}</div>
        </div>
      </CardBody>
    </Card>
  )
}

export function SerenityTab() {
  const stats = useResearchStats()
  const chok = useResearchChokepoint()
  const sync = useResearchSync()
  const [ticker, setTicker] = useState<string | null>(null)
  const [node, setNode] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [originals, setOriginals] = useState(true)
  const posts = useResearchPosts({ ticker: ticker ?? undefined, q: q || undefined, originals_only: originals, limit: 80 })
  const s = stats.data as any
  const list = (posts.data as RPost[] | undefined) ?? []

  const headerTitle = (
    <div className="flex items-center gap-2">
      <Sparkles size={16} className="text-amber-300" />
      <span className="font-semibold">Serenity 一手语料库</span>
      <span className="text-xs text-[var(--color-dim)]">@aleabitoreddit · CPO / chokepoint 思路</span>
    </div>
  )
  const syncBtn = (
    <button onClick={() => sync.mutate()} disabled={sync.isPending}
      className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-[var(--color-border)] hover:border-white/30 disabled:opacity-50">
      <RotateCw size={12} className={sync.isPending ? 'animate-spin' : ''} />{sync.isPending ? '拉取中…' : '拉最新'}
    </button>
  )
  const filterRow = (
    <div className="flex items-center gap-3 w-full">
      <div className="flex items-center gap-1.5 flex-1">
        <Search size={13} className="text-[var(--color-dim)]" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索原文…"
          className="bg-transparent text-sm outline-none flex-1 border-b border-[var(--color-border)] focus:border-white/30 py-1" />
      </div>
      <label className="flex items-center gap-1.5 text-xs text-[var(--color-dim)] cursor-pointer">
        <input type="checkbox" checked={originals} onChange={(e) => setOriginals(e.target.checked)} />只看原创
      </label>
      {ticker && <button onClick={() => setTicker(null)} className="text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">{ticker} ✕</button>}
    </div>
  )

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden">
      <div className="p-4 space-y-4 max-w-[1100px] mx-auto">
        <Card>
          <CardHeader title={headerTitle} right={syncBtn} />
          <CardBody>
            {s ? (
              <div className="flex gap-6 text-sm flex-wrap">
                <div><span className="text-[var(--color-dim)]">总帖 </span><b>{s.total}</b></div>
                <div><span className="text-[var(--color-dim)]">原创 </span><b>{s.by_kind?.tweet ?? 0}</b></div>
                <div><span className="text-[var(--color-dim)]">回复 </span>{s.by_kind?.reply ?? 0}</div>
                <div><span className="text-[var(--color-dim)]">长文 </span>{s.by_kind?.article ?? 0}</div>
                <div className="text-[var(--color-dim)]">{s.date_range?.min?.slice(0, 10)} ~ {s.date_range?.max?.slice(0, 10)}</div>
              </div>
            ) : <div className="text-[var(--color-dim)] text-sm">加载中…</div>}
          </CardBody>
        </Card>

        <AnalysisCard />

        <Card>
          <CardHeader
            title={<span className="flex items-center gap-2"><GitBranch size={14} className="text-sky-300" />供应链 × 时间轴</span>}
            subtitle="横轴=他首次提及的时间 · 纵向=供应链层 · 边=关系 · 亮度=信念 · 点节点看公司速览" />
          <CardBody><TimelineChain onSelect={setNode} /></CardBody>
        </Card>

        <Card>
          <CardHeader title="Chokepoint 速览(点 ticker 筛选下方原文)" />
          <CardBody>
            <div className="space-y-3">
              {(chok.data as any)?.layers?.map((L: any) => (
                <div key={L.layer} className="flex gap-3 items-start">
                  <div className="text-xs text-[var(--color-dim)] w-28 shrink-0 pt-1">{L.layer}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {L.tickers.map((it: any) => (
                      <button key={it.ticker} onClick={() => setTicker(ticker === it.ticker ? null : it.ticker)}
                        className={'px-1.5 py-0.5 rounded text-xs font-mono border transition ' + (ticker === it.ticker ? 'bg-amber-500/20 border-amber-500/50 text-amber-300' : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-white hover:border-white/30')}>
                        {it.ticker} <span className="opacity-60">{it.mentions}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={filterRow} />
          <CardBody>
            {posts.isLoading ? <div className="text-[var(--color-dim)] text-sm">加载中…</div> : (
              <div className="space-y-3">
                <div className="text-xs text-[var(--color-dim)]">{list.length} 条原文</div>
                {list.map((p) => <PostCard key={p.post_id} p={p} />)}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {node && <ProfileDrawer ticker={node} onClose={() => setNode(null)} onFilter={(t) => { setTicker(t); setNode(null) }} />}
    </div>
  )
}
