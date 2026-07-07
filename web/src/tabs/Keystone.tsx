/**
 * Keystone — 从持仓出发,沿供应链走出去找「相关 + 低估 + 卡脖子」候选.
 *
 * 输锚点 ticker → /api/walk → Step1 锚点画像 + ③ 瓶颈候选(bet_mode / TIME / 存活)
 * + ② 直接邻域 + Serenity 对比。propose-not-dispose:只发现 + 判断,不替你下单。
 */
import { useState } from 'react'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { useKeystoneWalk } from '@/lib/api'
import { Boxes, Search, Loader2, ArrowUp, ArrowDown, Minus } from 'lucide-react'

const HOLDINGS = ['NVDA', 'AMD', 'ARM', 'MRVL', 'META', 'GOOGL', 'AAPL', 'AAOI', 'NBIS', 'MP', 'PANW', 'CBRS']
const MODE_BADGE: Record<string, { t: string; c: string }> = {
  monetized: { t: '💰 已兑现护城河', c: 'text-emerald-400' },
  early_structural: { t: '🔬 早期结构性', c: 'text-amber-400' },
  data_gap: { t: '❓ 数据缺失', c: 'text-[var(--color-dim)]' },
  reject: { t: '❌ 丢弃', c: 'text-red-400' },
}
const TIME_ICON: Record<string, typeof Minus> = { rising: ArrowUp, fading: ArrowDown, neutral: Minus }
const TIME_C: Record<string, string> = { rising: 'text-emerald-400', fading: 'text-red-400', neutral: 'text-[var(--color-dim)]' }

export function KeystoneTab() {
  const [input, setInput] = useState('')
  const [anchor, setAnchor] = useState('')
  const q = useKeystoneWalk(anchor, !!anchor)
  const d = q.data
  const go = (t: string) => { const u = t.toUpperCase().trim(); setInput(u); setAnchor(u) }

  return (
    <div className="flex flex-col gap-3 p-3 overflow-auto">
      <Card><CardBody>
        <div className="flex items-center gap-2 flex-wrap">
          <Boxes size={18} /><span className="font-semibold">Keystone · 供应链走出去</span>
          <span className="text-xs text-[var(--color-dim)]">从锚点 → 找相关低估卡脖子候选(提案,你来定)</span>
        </div>
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') go(input) }}
            placeholder="锚点 ticker,如 NVDA"
            className="px-2 py-1 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-sm w-40" />
          <button onClick={() => go(input)}
            className="px-3 py-1 rounded border border-[var(--color-border)] text-sm flex items-center gap-1 hover:bg-[var(--color-border)]">
            <Search size={14} />走出去
          </button>
          <span className="text-xs text-[var(--color-dim)]">持仓快选:</span>
          {HOLDINGS.map(h => (
            <button key={h} onClick={() => go(h)}
              className="px-1.5 py-0.5 rounded border border-[var(--color-border)] text-xs hover:bg-[var(--color-border)]">{h}</button>
          ))}
        </div>
      </CardBody></Card>

      {q.isLoading && (
        <div className="flex items-center gap-2 text-sm text-[var(--color-dim)] p-4">
          <Loader2 className="animate-spin" size={16} />走链中(~5s)…
        </div>
      )}
      {q.error && <div className="text-red-400 text-sm p-2">出错:{String(q.error).slice(0, 200)}</div>}

      {d && (<>
        <Card>
          <CardHeader title={`① 锚点 ${d.anchor} · ${d.step1_identity?.name ?? ''}`} />
          <CardBody>
            <div className="text-sm flex flex-wrap gap-x-4 gap-y-1">
              <span>层:{d.step1_identity?.serenity_layer || '—'}</span>
              <span>下注:<span className={MODE_BADGE[d.step1_identity?.bet_mode]?.c}>{MODE_BADGE[d.step1_identity?.bet_mode]?.t || d.step1_identity?.bet_mode}</span></span>
              <span>moat:{d.step1_identity?.moat_evidence?.verdict || '—'}</span>
            </div>
            <div className="text-xs text-[var(--color-dim)] mt-1">{d.step1_identity?.route}</div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="③ 瓶颈候选(GATE + TIME · 按 score 排)" />
          <CardBody>
            {!d.step3_bottlenecks?.length && <div className="text-sm text-[var(--color-dim)]">未发现瓶颈候选(数据不足 / 锚点无供应链邻居)</div>}
            <div className="flex flex-col gap-2">
              {d.step3_bottlenecks?.map((b, i) => {
                const TI = TIME_ICON[b.time_signal] || Minus
                return (
                  <div key={i} className="border border-[var(--color-border)] rounded p-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold">#{i + 1} {b.ticker}</span>
                      <span className={`text-xs ${MODE_BADGE[b.bet_mode]?.c || ''}`}>{MODE_BADGE[b.bet_mode]?.t || b.bet_mode}</span>
                      <span className={`text-xs flex items-center gap-0.5 ${TIME_C[b.time_signal] || ''}`}><TI size={12} />{b.time_signal}</span>
                      <span className="text-xs text-[var(--color-dim)]">moat {b.moat_verdict}({b.moat_score}/5)</span>
                      <span className="text-xs text-[var(--color-dim)]">score {b.total_score}</span>
                      {b.serenity_layer && <span className="text-xs text-sky-400">[{b.serenity_layer}]</span>}
                    </div>
                    {b.survival?.note && <div className="text-xs text-amber-400 mt-1">存活(L0):{b.survival.note}</div>}
                    {b.note && <div className="text-xs text-[var(--color-dim)] mt-1">📝 {b.note}</div>}
                    <div className="text-xs text-[var(--color-dim)] mt-1">→ {b.route}</div>
                  </div>
                )
              })}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="② 直接邻域" />
          <CardBody>
            <div className="text-sm">供应商 {d.step2_neighbors?.counts?.suppliers ?? 0} · 客户 {d.step2_neighbors?.counts?.customers ?? 0} · 竞品 {d.step2_neighbors?.counts?.competitors ?? 0}</div>
            {(d.step2_neighbors?.data_gaps || []).map((g: string, i: number) => <div key={i} className="text-xs text-amber-400 mt-1">⚠ {g}</div>)}
            {!!(d.step2_neighbors?.suppliers || []).length && (
              <div className="text-xs text-[var(--color-dim)] mt-1">▲ 上游:{(d.step2_neighbors.suppliers).slice(0, 10).map((s: any) => s.ticker || s.name).join(', ')}</div>
            )}
          </CardBody>
        </Card>

        {d.step4_deep_dive && Object.keys(d.step4_deep_dive).length > 0 && (
          <Card>
            <CardHeader title="④ 深挖(top 瓶颈 · 护城河信号 + 洞见)" />
            <CardBody>
              <div className="flex flex-col gap-2">
                {Object.entries(d.step4_deep_dive).map(([tk, dd]: [string, any]) => (
                  <div key={tk} className="border border-[var(--color-border)] rounded p-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold">{tk}</span>
                      {dd.bottleneck?.moat_verdict && <span className="text-xs text-[var(--color-dim)]">moat {dd.bottleneck.moat_verdict}({dd.bottleneck.moat_score}/5)</span>}
                    </div>
                    {!!(dd.bottleneck?.moat_signals || []).length && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {dd.bottleneck.moat_signals.map((s: string, i: number) => (
                          <span key={i} className="text-[11px] px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-dim)]">{s}</span>
                        ))}
                      </div>
                    )}
                    {dd.insight && <div className="text-xs text-[var(--color-dim)] mt-1">💡 {dd.insight}</div>}
                    {!!(dd.upstream_of_bottleneck || []).length && (
                      <div className="text-xs text-[var(--color-dim)] mt-1">▲ 上游:{(dd.upstream_of_bottleneck as any[]).slice(0, 8).map((u: any) => u.ticker || u.name).join(', ')}</div>
                    )}
                    {!!(dd.downstream_of_bottleneck || []).length && (
                      <div className="text-xs text-[var(--color-dim)] mt-1">▼ 下游:{(dd.downstream_of_bottleneck as any[]).slice(0, 8).map((u: any) => u.ticker || u.name).join(', ')}</div>
                    )}
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        )}

        {!!(d.step5_cross_chain || []).length && (
          <Card>
            <CardHeader title="⑤ 跨链候选" />
            <CardBody>
              <div className="flex flex-col gap-2">
                {d.step5_cross_chain.map((c: any, i: number) => (
                  <div key={i} className="border border-[var(--color-border)] rounded p-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold">{c.ticker}</span>
                      {c.sector && <span className="text-xs text-[var(--color-dim)]">{c.sector}{c.industry ? ` · ${c.industry}` : ''}</span>}
                    </div>
                    {!!(c.serenity_cross_hints || []).length && (
                      <div className="text-xs text-sky-400 mt-1">🔗 {c.serenity_cross_hints.join(', ')}</div>
                    )}
                    {c.note && <div className="text-xs text-[var(--color-dim)] mt-1">{c.note}</div>}
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        )}

        <Card>
          <CardHeader title="Serenity 对比" />
          <CardBody><div className="text-sm text-[var(--color-dim)]">{d.serenity_comparison?.interpretation || '—'}</div></CardBody>
        </Card>

        <div className="text-xs text-[var(--color-dim)]">⏱ {d.elapsed_sec}s · 这是发现 + 判断,不是买卖建议;你跑你的流程定。</div>
      </>)}
    </div>
  )
}
