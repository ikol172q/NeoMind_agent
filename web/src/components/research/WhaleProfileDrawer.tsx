/**
 * Whale Profile Drawer — bilingual encyclopedia for a Smart Money entity.
 *
 * Opens via WhaleResearchContext.openWhale(key) — fires two backend calls:
 *   GET /api/regime/whales/{key}        — curated profile + recent 13F  (fast, sync)
 *   GET /api/regime/whales/{key}/news   — Tavily news search             (slow, async)
 *
 * Renders BOTH zh and en side-by-side so the user can compare directly,
 * with a single-language toggle for users who only want one column.
 *
 * Sections (top → bottom):
 *   1. Identity header (name / horizon emoji / bias / signal_weight)
 *   2. Summary 📋 (zh | en) — 1-liner
 *   3. Strategy 📜 (zh | en) — 2-3 paragraph deep dive
 *   4. Track record (✅ wins + ❌ losses)
 *   5. Must-know quirks ⚠️
 *   6. Recent 13F moves 📊 (live)
 *   7. Latest news 📰 (live Tavily)
 *   8. Links 🔗
 */
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchJSON,
  useWhaleResearch as useWhaleResearchSummary,
  useRegenWhaleResearch,
  useWhaleResearchHistory,
  type WhaleResearchRow,
  type WhaleResearchSummary as ResearchSummary,
} from '@/lib/api'
import { useWhaleResearch } from './WhaleResearchContext'
import { fmtTs } from '@/lib/utils'

/** whale research generated_at can be naive (no TZ) — treat as UTC, render local */
const asLocal = (s?: string | null): string =>
  s ? fmtTs(/Z$|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z') : ''
import {
  X, Languages, TrendingUp, TrendingDown, AlertTriangle,
  ExternalLink, BookOpen, Mic, AtSign, FileText, Newspaper,
  Loader2, Globe, ChevronDown, ChevronUp,
} from 'lucide-react'

type BilingualStr = { zh?: string; en?: string }
type Event = { year?: string; title_zh?: string; title_en?: string; body_zh?: string; body_en?: string }
type Quirk = { title_zh?: string; title_en?: string; body_zh?: string; body_en?: string }
type Link = { type: string; label: string; url: string }

interface WhaleProfile {
  summary: BilingualStr
  strategy: BilingualStr
  wins: Event[]
  losses: Event[]
  must_know: Quirk[]
  links: Link[]
}

interface RecentMove {
  event_id: string
  ticker: string
  title: string
  filing_date: string
  change_type?: string
  delta_pct?: number
  current_shares?: number
  source_url?: string
}

interface WhaleDetail {
  key: string
  name: string
  cik: string
  horizon: string
  horizon_emoji: string
  style: string
  signal_weight: number
  bias: string
  bias_emoji: string
  philosophy?: string
  famous_for?: string
  letters_url?: string
  derivative_note?: string
  profile: WhaleProfile | null
  recent_moves: RecentMove[]
  n_recent_moves: number
}

interface WhaleNews {
  query: string
  items: Array<{
    title: string
    url: string
    source?: string
    snippet?: string
    published?: string | null
  }>
  total: number
  error?: string | null
  fallback_url: string
}

type Lang = 'both' | 'zh' | 'en'

export function WhaleProfileDrawer() {
  const { whaleKey, closeWhale } = useWhaleResearch()
  const [lang, setLang] = useState<Lang>('both')

  const detailQ = useQuery({
    queryKey: ['whale-detail', whaleKey],
    queryFn: () => fetchJSON<WhaleDetail>(`/api/regime/whales/${whaleKey}`),
    enabled: !!whaleKey,
  })
  const newsQ = useQuery({
    queryKey: ['whale-news', whaleKey],
    queryFn: () => fetchJSON<WhaleNews>(`/api/regime/whales/${whaleKey}/news?limit=6`),
    enabled: !!whaleKey,
    staleTime: 60_000 * 30,
  })
  const researchQ = useWhaleResearchSummary(whaleKey)
  const regenResearchMu = useRegenWhaleResearch()
  const historyQ = useWhaleResearchHistory(whaleKey)

  useEffect(() => {
    // Reset language toggle when switching whales
    setLang('both')
  }, [whaleKey])

  if (!whaleKey) return null

  const d = detailQ.data
  const profile = d?.profile

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={closeWhale}
      />
      {/* Drawer panel */}
      <aside className="fixed top-0 right-0 h-full w-full md:w-[700px] bg-[var(--color-panel)] border-l border-[var(--color-border)] z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <header className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-border)] shrink-0">
          {d ? (
            <>
              <span className="text-xl">{d.horizon_emoji}</span>
              <span className="text-xl">{d.bias_emoji}</span>
              <div className="flex flex-col min-w-0">
                <h2 className="text-[14px] font-semibold text-[var(--color-text)] truncate">
                  {d.name}
                </h2>
                <div className="flex items-center gap-1.5 text-[9.5px] text-[var(--color-dim)] font-mono">
                  <span>{d.horizon}</span>
                  <span>·</span>
                  <span>{d.bias}</span>
                  <span>·</span>
                  <span>w={d.signal_weight.toFixed(1)}</span>
                  <span>·</span>
                  <span>CIK {d.cik}</span>
                </div>
              </div>
            </>
          ) : (
            <h2 className="text-[14px] font-semibold text-[var(--color-text)]">Loading…</h2>
          )}
          <div className="ml-auto flex items-center gap-1">
            {/* Lang toggle */}
            <button
              onClick={() => setLang(prev => (prev === 'both' ? 'zh' : prev === 'zh' ? 'en' : 'both'))}
              className="px-2 py-1 text-[10px] rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-text)] flex items-center gap-1"
              title={lang === 'both' ? '现在: 中英双栏 (click → 仅中)' : lang === 'zh' ? '现在: 仅中 (click → 仅英)' : '现在: 仅英 (click → 双栏)'}
            >
              <Languages className="w-3 h-3" />
              {lang === 'both' ? '中/EN' : lang === 'zh' ? '中文' : 'EN'}
            </button>
            <button
              onClick={closeWhale}
              className="p-1.5 rounded hover:bg-[var(--color-border)]/30 text-[var(--color-dim)] hover:text-[var(--color-text)]"
              title="Close (ESC)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </header>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {detailQ.isLoading && <Loading />}

          {detailQ.error && (
            <div className="text-[11px] text-[var(--color-red,#e07070)]">
              加载失败: {String(detailQ.error)}
            </div>
          )}

          {d && !profile && (
            <NoCurationNotice name={d.name} philosophy={d.philosophy} famousFor={d.famous_for} />
          )}

          {/* NeoMind 研究总结 — Tavily + LLM synthesized, URL-validated.
              Lives at the top because it's the freshest signal — auto-updated
              + on-demand regen. Collapsed by default to avoid overwhelming. */}
          {d && (
            <ResearchSummarySection
              whaleKey={d.key}
              researchQ={researchQ}
              regenMu={regenResearchMu}
              historyQ={historyQ}
            />
          )}

          {d && profile && (
            <>
              <Section icon="📋" titleZh="概况" titleEn="Summary">
                <Bilingual lang={lang} zh={profile.summary.zh} en={profile.summary.en} />
              </Section>

              <Section icon="📜" titleZh="策略 & 哲学" titleEn="Strategy & Philosophy">
                <Bilingual lang={lang} zh={profile.strategy.zh} en={profile.strategy.en} multiline />
              </Section>

              {profile.wins.length > 0 && (
                <Section
                  icon={<TrendingUp className="w-3.5 h-3.5 text-[var(--color-green,#7ed98c)]" />}
                  titleZh="成功 / 成名战"
                  titleEn="Wins / Defining trades"
                >
                  <div className="space-y-3">
                    {profile.wins.map((ev, i) => (
                      <EventCard key={`win-${i}`} ev={ev} lang={lang} accent="green" />
                    ))}
                  </div>
                </Section>
              )}

              {profile.losses.length > 0 && (
                <Section
                  icon={<TrendingDown className="w-3.5 h-3.5 text-[var(--color-red,#e07070)]" />}
                  titleZh="失败 / 教训"
                  titleEn="Losses / Lessons"
                >
                  <div className="space-y-3">
                    {profile.losses.map((ev, i) => (
                      <EventCard key={`loss-${i}`} ev={ev} lang={lang} accent="red" />
                    ))}
                  </div>
                </Section>
              )}

              {profile.must_know.length > 0 && (
                <Section
                  icon={<AlertTriangle className="w-3.5 h-3.5 text-[var(--color-amber,#e5a200)]" />}
                  titleZh="你必须知道的"
                  titleEn="Must-know quirks"
                >
                  <div className="space-y-2">
                    {profile.must_know.map((q, i) => (
                      <QuirkCard key={`q-${i}`} q={q} lang={lang} />
                    ))}
                  </div>
                </Section>
              )}
            </>
          )}

          {/* Live 13F moves — always show regardless of curation status */}
          {d && d.recent_moves.length > 0 && (
            <Section icon="📊" titleZh={`最近 13F 动作 · ${d.n_recent_moves} 条`} titleEn={`Recent 13F moves · ${d.n_recent_moves}`}>
              <RecentMovesList moves={d.recent_moves.slice(0, 12)} />
            </Section>
          )}

          {/* Live news — Tavily-backed */}
          {d && (
            <Section icon={<Newspaper className="w-3.5 h-3.5 text-[var(--color-text)]" />} titleZh="最新新闻 · 实时搜索" titleEn="Latest news · live search">
              <NewsList q={newsQ} />
            </Section>
          )}

          {/* Links — always show */}
          {profile && profile.links.length > 0 && (
            <Section icon="🔗" titleZh="资源 / 链接" titleEn="Resources / Links">
              <LinksList links={profile.links} />
            </Section>
          )}

          {/* Derivative exposure warning if applicable */}
          {d?.derivative_note && (
            <div className="text-[10px] italic text-[var(--color-dim)] border-l-2 border-[var(--color-amber,#e5a200)]/60 pl-2 py-1 bg-[var(--color-amber,#e5a200)]/5">
              ⚠️ 13F 暴露提示: {d.derivative_note}
            </div>
          )}
        </div>
      </aside>
    </>
  )
}


// ── Components ──────────────────────────────────────────────────────


function Section({
  icon, titleZh, titleEn, children,
}: { icon: React.ReactNode; titleZh: string; titleEn: string; children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <section className="border border-[var(--color-border)]/40 rounded">
      <button
        onClick={() => setCollapsed(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-[var(--color-border)]/10 text-left"
      >
        <span className="flex items-center justify-center w-4 h-4">{icon}</span>
        <span className="text-[11px] font-semibold text-[var(--color-text)]">{titleZh}</span>
        <span className="text-[9.5px] text-[var(--color-dim)] font-mono">{titleEn}</span>
        <span className="ml-auto text-[var(--color-dim)]">
          {collapsed ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
        </span>
      </button>
      {!collapsed && <div className="px-3 pb-3">{children}</div>}
    </section>
  )
}


function ResearchSummarySection({
  whaleKey, researchQ, regenMu, historyQ,
}: {
  whaleKey: string
  researchQ: ReturnType<typeof useWhaleResearchSummary>
  regenMu:   ReturnType<typeof useRegenWhaleResearch>
  historyQ:  ReturnType<typeof useWhaleResearchHistory>
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const data = researchQ.data
  const isRegen = regenMu.isPending && regenMu.variables === whaleKey

  const summary: ResearchSummary | null = data?.summary ?? null
  const generated_at = data?.generated_at
  const has_summary = data?.exists && summary

  // Format generated_at in the user's LOCAL timezone (matches the global clock)
  const tsLabel = generated_at ? asLocal(generated_at) : '从未生成'

  return (
    <section className="border border-[var(--color-accent,#7ed9d9)]/40 rounded bg-[var(--color-accent,#7ed9d9)]/5">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          onClick={() => setCollapsed(v => !v)}
          className="flex items-center gap-1 text-left flex-1 hover:opacity-80"
        >
          <span>🔬</span>
          <span className="text-[11px] font-semibold text-[var(--color-text)]">
            NeoMind 研究总结
          </span>
          <span className="text-[9.5px] font-mono text-[var(--color-dim)]">
            · {tsLabel}
          </span>
          {has_summary && (data?.n_urls_validated ?? 0) > 0 && (
            <span className="text-[9px] text-[var(--color-dim)] font-mono">
              · {data.n_urls_validated} URL validated
            </span>
          )}
          <span className="ml-auto text-[var(--color-dim)]">
            {collapsed ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          </span>
        </button>
        <button
          onClick={() => regenMu.mutate(whaleKey)}
          disabled={isRegen}
          className={'text-[9.5px] px-2 py-0.5 rounded border ' +
            (isRegen
              ? 'border-[var(--color-amber,#e5a200)] text-[var(--color-amber,#e5a200)] cursor-wait'
              : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent,#7ed9d9)]')}
          title="重新搜索 + LLM 总结. ~30-90 秒"
        >
          {isRegen ? '🔄 生成中…' : '🔄 重新生成'}
        </button>
      </div>

      {!collapsed && (
        <div className="px-3 pb-3 space-y-3 text-[11.5px] leading-[1.6]">
          {researchQ.isLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">Loading…</div>
          )}
          {!researchQ.isLoading && !has_summary && (
            <div className="text-[10.5px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              这个 whale 还没生成过研究总结. 点上面 "🔄 重新生成" 触发 (~30-90 秒).
            </div>
          )}
          {has_summary && summary && (
            <>
              <SubSection title="📊 投资逻辑 · Investment Logic">
                <CitationText text={summary.investment_logic} validated={summary.all_links_validated} />
              </SubSection>
              <SubSection title="💰 AUM / 市场地位 · Market Position">
                <CitationText text={summary.aum_market_position} validated={summary.all_links_validated} />
              </SubSection>
              <SubSection title="📈 最近动作综合 · Recent Moves Synthesis">
                <CitationText text={summary.recent_moves_synthesis} validated={summary.all_links_validated} />
              </SubSection>
              {summary.recent_news.length > 0 && (
                <SubSection title={`📰 相关新闻 · ${summary.recent_news.length} 篇 (URL 已验证)`}>
                  <div className="space-y-2">
                    {summary.recent_news.map((n, i) => (
                      <a
                        key={i}
                        href={n.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block p-2 border border-[var(--color-border)]/40 rounded hover:border-[var(--color-text)]/40 hover:bg-[var(--color-border)]/10"
                      >
                        <div className="text-[11px] font-medium text-[var(--color-text)] mb-0.5">{n.title}</div>
                        {n.summary && (
                          <div className="text-[10px] text-[var(--color-dim)] mb-1">{n.summary}</div>
                        )}
                        {n.relevance && (
                          <div className="text-[10px] text-[var(--color-text)]/85 italic mb-1">
                            relevance: {n.relevance}
                          </div>
                        )}
                        <div className="flex items-center gap-2 text-[9px] font-mono text-[var(--color-dim)]">
                          <span>{n.source}</span>
                          {n.published && <span>· {n.published}</span>}
                          <ExternalLink className="w-2.5 h-2.5 ml-auto" />
                        </div>
                      </a>
                    ))}
                  </div>
                </SubSection>
              )}
              <SubSection title="⚠️ 争议 / 风险 · Controversies & Risks">
                <CitationText text={summary.controversies_risks} validated={summary.all_links_validated} />
              </SubSection>
              {summary.key_things_to_know.length > 0 && (
                <SubSection title="🎯 关键点 · Key Things to Know">
                  <ul className="list-disc ml-4 space-y-0.5">
                    {summary.key_things_to_know.map((k, i) => (
                      <li key={i} className="text-[11px]">
                        <CitationText text={k} validated={summary.all_links_validated} />
                      </li>
                    ))}
                  </ul>
                </SubSection>
              )}
              {/* URL validation report (broken URLs) */}
              {summary.all_links_validated.some(v => !v.ok) && (
                <details className="text-[9.5px] text-[var(--color-dim)] mt-1">
                  <summary className="cursor-pointer hover:text-[var(--color-text)]">
                    ⚠️ {summary.all_links_validated.filter(v => !v.ok).length} 个 URL 验证失败 (从主内容中移除了)
                  </summary>
                  <div className="mt-1 ml-2 space-y-0.5">
                    {summary.all_links_validated.filter(v => !v.ok).map((v, i) => (
                      <div key={i} className="font-mono text-[9px] break-all">
                        {v.http_status ?? 'no response'} · {v.url}
                      </div>
                    ))}
                  </div>
                </details>
              )}
              {/* History expand */}
              <details
                open={showHistory}
                onToggle={(e) => setShowHistory((e.target as HTMLDetailsElement).open)}
                className="text-[9.5px] text-[var(--color-dim)] mt-1"
              >
                <summary className="cursor-pointer hover:text-[var(--color-text)]">
                  📅 历史版本 {historyQ.data ? `(${historyQ.data.n})` : ''}
                </summary>
                {historyQ.data && (
                  <div className="mt-1 ml-2 space-y-0.5">
                    {historyQ.data.history.map(h => (
                      <div key={h.id} className="font-mono text-[9.5px]">
                        {h.is_active ? '★' : ' '} {asLocal(h.generated_at) || '?'}
                        · {h.model_used ?? '?'}
                        · {h.n_urls_validated ?? 0} URLs OK
                        {h.error_message ? <span className="text-[var(--color-red,#e07070)]"> · {h.error_message.slice(0, 50)}</span> : null}
                      </div>
                    ))}
                  </div>
                )}
              </details>
            </>
          )}
        </div>
      )}
    </section>
  )
}


function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10.5px] font-semibold text-[var(--color-text)] mb-1">{title}</div>
      <div className="text-[11px] leading-[1.6] text-[var(--color-text)]/90">{children}</div>
    </div>
  )
}


function CitationText({
  text, validated,
}: { text: string; validated: WhaleResearchRow['summary'] extends infer T ? (T extends { all_links_validated: infer A } ? A : never) : never }) {
  // Convert [source N] citations to subtle superscript indicators.
  // No interactive linking yet — citations refer to indices in the LLM's
  // evidence block which we don't surface 1-to-1 in the UI.
  void validated  // (reserved for future linking)
  const parts = text.split(/(\[source\s+\d+\]|\[\d+\])/g)
  return (
    <span>
      {parts.map((p, i) =>
        /^\[source\s+\d+\]$|^\[\d+\]$/.test(p)
          ? <sup key={i} className="text-[8px] text-[var(--color-accent,#7ed9d9)] mx-0.5">{p}</sup>
          : <span key={i}>{p}</span>
      )}
    </span>
  )
}


function Bilingual({
  lang, zh, en, multiline = false,
}: { lang: Lang; zh?: string; en?: string; multiline?: boolean }) {
  const showZh = (lang === 'both' || lang === 'zh') && zh
  const showEn = (lang === 'both' || lang === 'en') && en

  if (lang === 'both') {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        {showZh && (
          <div className="text-[11.5px] leading-[1.6] text-[var(--color-text)]">
            <MaybeMultiline text={zh!} multiline={multiline} />
          </div>
        )}
        {showEn && (
          <div className="text-[11.5px] leading-[1.6] text-[var(--color-text)]/85 italic">
            <MaybeMultiline text={en!} multiline={multiline} />
          </div>
        )}
      </div>
    )
  }
  return (
    <div className="text-[11.5px] leading-[1.6] text-[var(--color-text)]">
      {showZh && <MaybeMultiline text={zh!} multiline={multiline} />}
      {showEn && <MaybeMultiline text={en!} multiline={multiline} />}
    </div>
  )
}


function MaybeMultiline({ text, multiline }: { text: string; multiline: boolean }) {
  if (!multiline) return <span>{renderBold(text)}</span>
  // Split on \n\n for paragraphs
  return (
    <>
      {text.split(/\n\n+/).map((p, i) => (
        <p key={i} className={i > 0 ? 'mt-2' : ''}>{renderBold(p)}</p>
      ))}
    </>
  )
}


/** Tiny markdown bolder: convert `**word**` → <strong>word</strong>. */
function renderBold(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i} className="font-semibold text-[var(--color-text)]">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>
  )
}


function EventCard({ ev, lang, accent }: { ev: Event; lang: Lang; accent: 'green' | 'red' }) {
  const accentColor = accent === 'green'
    ? 'border-[var(--color-green,#7ed98c)]/40 bg-[var(--color-green,#7ed98c)]/5'
    : 'border-[var(--color-red,#e07070)]/40 bg-[var(--color-red,#e07070)]/5'
  const showBoth = lang === 'both'
  return (
    <div className={`border rounded p-2 ${accentColor}`}>
      <div className="flex items-baseline gap-2 mb-1">
        {ev.year && (
          <span className="text-[9.5px] font-mono text-[var(--color-dim)]">{ev.year}</span>
        )}
        <div className={showBoth ? 'grid md:grid-cols-2 gap-3 flex-1' : 'flex-1'}>
          {(lang === 'both' || lang === 'zh') && ev.title_zh && (
            <span className="text-[11.5px] font-semibold text-[var(--color-text)]">{ev.title_zh}</span>
          )}
          {(lang === 'both' || lang === 'en') && ev.title_en && (
            <span className="text-[11px] font-semibold text-[var(--color-text)]/80 italic">{ev.title_en}</span>
          )}
        </div>
      </div>
      <Bilingual lang={lang} zh={ev.body_zh} en={ev.body_en} multiline={false} />
    </div>
  )
}


function QuirkCard({ q, lang }: { q: Quirk; lang: Lang }) {
  return (
    <div className="border-l-2 border-[var(--color-amber,#e5a200)]/60 pl-2 py-1">
      <div className={lang === 'both' ? 'grid md:grid-cols-2 gap-3' : ''}>
        {(lang === 'both' || lang === 'zh') && q.title_zh && (
          <div className="text-[11.5px] font-semibold text-[var(--color-text)] mb-1">{q.title_zh}</div>
        )}
        {(lang === 'both' || lang === 'en') && q.title_en && (
          <div className="text-[11px] font-semibold text-[var(--color-text)]/85 italic mb-1">{q.title_en}</div>
        )}
      </div>
      <Bilingual lang={lang} zh={q.body_zh} en={q.body_en} />
    </div>
  )
}


function RecentMovesList({ moves }: { moves: RecentMove[] }) {
  const actionColor = (ct?: string) => {
    if (ct === 'new')      return 'text-[var(--color-green,#7ed98c)] border-[var(--color-green,#7ed98c)]/40'
    if (ct === 'increase') return 'text-[var(--color-green,#7ed98c)] border-[var(--color-green,#7ed98c)]/40'
    if (ct === 'decrease') return 'text-[var(--color-amber,#e5a200)] border-[var(--color-amber,#e5a200)]/40'
    if (ct === 'exit')     return 'text-[var(--color-red,#e07070)] border-[var(--color-red,#e07070)]/40'
    return 'text-[var(--color-dim)] border-[var(--color-border)]'
  }
  const actionLabel = (ct?: string) => ({
    new: '新建仓', increase: '加仓', decrease: '减仓', exit: '清仓',
  } as Record<string, string>)[ct ?? ''] ?? ct ?? '?'
  return (
    <div className="space-y-1">
      {moves.map(m => (
        <div key={m.event_id} className="flex items-center gap-2 text-[10.5px] py-0.5">
          <span className={`px-1 py-0 rounded border text-[9px] font-mono flex-shrink-0 ${actionColor(m.change_type)}`}>
            {actionLabel(m.change_type)}
          </span>
          <span className="font-mono font-medium text-[var(--color-text)] w-14 flex-shrink-0">{m.ticker}</span>
          {typeof m.delta_pct === 'number' && (
            <span className="text-[9.5px] font-mono text-[var(--color-dim)] flex-shrink-0">
              {(m.delta_pct * 100).toFixed(0)}%
            </span>
          )}
          <span className="ml-auto text-[9px] font-mono text-[var(--color-dim)]">
            {m.filing_date}
          </span>
          {m.source_url && (
            <a
              href={m.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--color-dim)] hover:text-[var(--color-text)]"
              title="View SEC filing"
            >
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      ))}
    </div>
  )
}


function NewsList({
  q,
}: { q: ReturnType<typeof useQuery<WhaleNews>> }) {
  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 text-[10.5px] text-[var(--color-dim)] py-2">
        <Loader2 className="w-3 h-3 animate-spin" />
        正在搜索最新新闻 (Tavily)...
      </div>
    )
  }
  if (q.error || !q.data) {
    return (
      <div className="text-[10.5px] text-[var(--color-dim)] italic">
        新闻搜索失败. 试试 <a href={`https://news.google.com/search?q=${encodeURIComponent(String(q.data?.query ?? ''))}`} target="_blank" rel="noopener noreferrer" className="text-[var(--color-text)] underline">Google News</a>
      </div>
    )
  }
  const items = q.data.items ?? []
  if (items.length === 0) {
    return (
      <div className="text-[10.5px] text-[var(--color-dim)] italic">
        没找到相关新闻. 试试 <a href={q.data.fallback_url} target="_blank" rel="noopener noreferrer" className="text-[var(--color-text)] underline">Google News</a>
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {items.map((it, i) => (
        <a
          key={i}
          href={it.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block p-2 border border-[var(--color-border)]/40 rounded hover:border-[var(--color-text)]/40 hover:bg-[var(--color-border)]/10"
        >
          <div className="text-[11px] font-medium text-[var(--color-text)] mb-0.5 leading-[1.4]">{it.title}</div>
          {it.snippet && (
            <div className="text-[10px] text-[var(--color-dim)] leading-[1.4] mb-1">{it.snippet}</div>
          )}
          <div className="flex items-center gap-1.5 text-[9px] font-mono text-[var(--color-dim)]">
            {it.source && <span>{it.source}</span>}
            {it.published && <span>· {new Date(it.published).toISOString().slice(0, 10)}</span>}
            <ExternalLink className="w-2.5 h-2.5 ml-auto" />
          </div>
        </a>
      ))}
      <a
        href={q.data.fallback_url}
        target="_blank"
        rel="noopener noreferrer"
        className="block text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] mt-1"
      >
        看更多 → Google News
      </a>
    </div>
  )
}


function LinksList({ links }: { links: Link[] }) {
  const iconFor = (t: string) => {
    if (t === 'letters')   return <FileText className="w-3 h-3" />
    if (t === 'book')      return <BookOpen className="w-3 h-3" />
    if (t === 'podcast')   return <Mic className="w-3 h-3" />
    if (t === 'interview') return <Mic className="w-3 h-3" />
    if (t === 'x')         return <AtSign className="w-3 h-3" />
    if (t === 'wiki')      return <Globe className="w-3 h-3" />
    if (t === 'paper')     return <FileText className="w-3 h-3" />
    return <ExternalLink className="w-3 h-3" />
  }
  return (
    <div className="space-y-1">
      {links.map((l, i) => (
        <a
          key={i}
          href={l.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-[10.5px] text-[var(--color-text)] hover:text-[var(--color-accent,#7ed9d9)] py-0.5"
        >
          <span className="text-[var(--color-dim)]">{iconFor(l.type)}</span>
          <span className="flex-1 truncate">{l.label}</span>
          <span className="text-[9px] font-mono text-[var(--color-dim)] uppercase">{l.type}</span>
          <ExternalLink className="w-2.5 h-2.5 text-[var(--color-dim)]" />
        </a>
      ))}
    </div>
  )
}


function NoCurationNotice({
  name, philosophy, famousFor,
}: { name: string; philosophy?: string; famousFor?: string }) {
  return (
    <div className="border border-[var(--color-amber,#e5a200)]/40 bg-[var(--color-amber,#e5a200)]/5 rounded p-3 text-[11px] leading-[1.5]">
      <div className="font-semibold text-[var(--color-text)] mb-1">
        {name} 暂无中英双语详细档案
      </div>
      <div className="text-[var(--color-dim)]">
        Detailed bilingual profile not yet curated for this whale.
      </div>
      {philosophy && (
        <div className="mt-2">
          <span className="text-[9.5px] uppercase font-mono text-[var(--color-dim)]">Philosophy </span>
          <div className="text-[10.5px] mt-1 text-[var(--color-text)]/85">{philosophy}</div>
        </div>
      )}
      {famousFor && (
        <div className="mt-2">
          <span className="text-[9.5px] uppercase font-mono text-[var(--color-dim)]">Famous for </span>
          <div className="text-[10.5px] mt-1 text-[var(--color-text)]/85">{famousFor}</div>
        </div>
      )}
      <div className="mt-2 text-[9.5px] text-[var(--color-dim)] italic">
        Live 13F moves + news below are unaffected.
      </div>
    </div>
  )
}


function Loading() {
  return (
    <div className="flex items-center gap-2 text-[11px] text-[var(--color-dim)] py-4">
      <Loader2 className="w-3.5 h-3.5 animate-spin" />
      Loading whale profile...
    </div>
  )
}
