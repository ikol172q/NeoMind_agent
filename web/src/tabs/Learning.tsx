/**
 * Learning tab — investing case-study library.
 *
 * Two sections:
 *   - Today  → 1-N fresh items (last 7d) + 1 classic on rotation
 *   - Library → full archive with theme / era / language / search filters
 *
 * Click any case → modal with full body + source link. No personal
 * note-taking surface — per user spec the system is consume-only;
 * material is cached locally so reads are fast and offline-friendly.
 */
import { useEffect, useState } from 'react'
import {
  useLearningToday,
  useLearningLibrary,
  useLearningThemes,
  useLearningCase,
  useRefreshLearning,
  useMarkLearningSeen,
  useLearningBooks,
  type LearningCase,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import {
  ExternalLink, Loader2, Search, Sparkles, Clock, X, BookOpen, ShoppingCart, Globe,
} from 'lucide-react'

const ERA_LABEL: Record<string, string> = {
  'modern_cn':    '现代中国',
  'classic_intl': '国际经典',
  'classic_cn':   '中文经典',
  'recent_2024':  '2024',
  'recent_2025':  '2025',
  'recent_2026':  '2026',
}

const ERA_COLOR: Record<string, string> = {
  'modern_cn':    'border-amber-500/40 text-amber-300',
  'classic_intl': 'border-emerald-500/40 text-emerald-300',
  'classic_cn':   'border-emerald-500/40 text-emerald-300',
  'recent_2024':  'border-blue-500/40 text-blue-300',
  'recent_2025':  'border-blue-500/40 text-blue-300',
  'recent_2026':  'border-violet-500/40 text-violet-300',
}

const DIFFICULTY_LABEL: Record<string, string> = {
  'beginner':     '入门',
  'intermediate': '中级',
  'advanced':     '高阶',
}

export function LearningTab() {
  const todayQ = useLearningToday()
  const themesQ = useLearningThemes()
  const refreshMu = useRefreshLearning()
  const [openSlug, setOpenSlug] = useState<string | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [filterTheme, setFilterTheme] = useState<string>('')
  const [filterEra, setFilterEra] = useState<string>('')
  const [filterLang, setFilterLang] = useState<string>('')

  const libraryQ = useLearningLibrary({
    theme: filterTheme || undefined,
    era: filterEra || undefined,
    language: filterLang || undefined,
    q: searchQ.trim() || undefined,
    limit: 100,
  })

  const fresh = todayQ.data?.fresh ?? []
  const classic = todayQ.data?.classic ?? null

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-2 md:p-4 max-w-6xl mx-auto space-y-3">
        {/* Today */}
        <Card>
          <CardHeader
            title="📚 Today"
            subtitle={`${fresh.length} 条 fresh + 1 经典轮换 · 最近 7 天 fetch 的为 fresh`}
          />
          <CardBody>
            <div className="flex flex-wrap items-center gap-2 mb-3 text-[11px] md:text-[10px] text-[var(--color-dim)]">
              <button
                data-testid="learning-refresh"
                onClick={() => refreshMu.mutate()}
                disabled={refreshMu.isPending}
                className="px-2.5 md:px-2 py-1.5 md:py-1 rounded border border-emerald-500/40 hover:border-emerald-300 text-emerald-300 flex items-center gap-1 disabled:opacity-50"
                title="拉一批新案例 (调用 Tavily + miniflux + LLM gate, ~30-60s, ~$0.01)"
              >
                {refreshMu.isPending
                  ? <><Loader2 size={11} className="animate-spin" /> 抓取中…</>
                  : <><Sparkles size={11} /> 立刻 fetch 新内容</>}
              </button>
              {refreshMu.data && (
                <span className="text-emerald-300">
                  ↳ 加了 {refreshMu.data.new_slugs?.length ?? 0} 条新 case
                </span>
              )}
              {refreshMu.error && (
                <span className="text-red-400">✗ {(refreshMu.error as Error).message}</span>
              )}
            </div>

            {todayQ.isLoading && <div className="text-[11px] italic text-[var(--color-dim)]">loading…</div>}

            {fresh.length === 0 && !todayQ.isLoading && (
              <div className="text-[11px] text-[var(--color-dim)] mb-3 italic">
                目前没有 fresh case (是新装的？或最近 7 天 daily fetcher 没跑过)。
                点上面 ✨ 立刻拉一批 — 大约 30-60 秒。或者下方 Today's Classic 先看着。
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
              {fresh.map(c => (
                <CaseCard key={c.slug} c={c} onOpen={setOpenSlug} freshBadge />
              ))}
            </div>

            {classic && (
              <div>
                <div className="text-[10px] text-[var(--color-dim)] mb-1.5 flex items-center gap-1">
                  <Clock size={10} /> 今日经典 (轮换中)
                </div>
                <CaseCard c={classic} onOpen={setOpenSlug} />
              </div>
            )}
          </CardBody>
        </Card>

        {/* Books — dedicated section grouped by availability */}
        <BooksSection onOpen={setOpenSlug} />

        {/* Library */}
        <Card>
          <CardHeader
            title="📖 Library"
            subtitle={`${libraryQ.data?.total ?? 0} 条全部案例 · 按 fetched_at 倒序`}
          />
          <CardBody>
            {/* Filters — wrap on mobile; search takes full row, dropdowns wrap below */}
            <div className="flex flex-wrap items-center gap-2 mb-3 text-[12px] md:text-[11px]">
              <div className="relative w-full md:flex-1 md:min-w-[200px] md:w-auto">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--color-dim)]" />
                <input
                  type="text"
                  placeholder="搜标题 / 摘要…"
                  value={searchQ}
                  onChange={e => setSearchQ(e.target.value)}
                  className="w-full pl-7 pr-2 py-1.5 md:py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[12px] md:text-[11px] outline-none focus:border-[var(--color-accent)]"
                />
              </div>
              <select
                value={filterTheme}
                onChange={e => setFilterTheme(e.target.value)}
                className="px-2 py-1.5 md:py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[12px] md:text-[11px]"
              >
                <option value="">全部主题</option>
                {(themesQ.data?.themes ?? []).map(t => (
                  <option key={t.theme} value={t.theme}>{t.theme} ({t.count})</option>
                ))}
              </select>
              <select
                value={filterEra}
                onChange={e => setFilterEra(e.target.value)}
                className="px-2 py-1.5 md:py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[12px] md:text-[11px]"
              >
                <option value="">全部时代</option>
                <option value="modern_cn">现代中国</option>
                <option value="classic_intl">国际经典</option>
                <option value="classic_cn">中文经典</option>
                <option value="recent_2024">2024</option>
                <option value="recent_2025">2025</option>
                <option value="recent_2026">2026</option>
              </select>
              <select
                value={filterLang}
                onChange={e => setFilterLang(e.target.value)}
                className="px-2 py-1.5 md:py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[12px] md:text-[11px]"
              >
                <option value="">全部语言</option>
                <option value="zh">中文原生</option>
                <option value="en">英文原文</option>
                <option value="mix">混合</option>
              </select>
              {(searchQ || filterTheme || filterEra || filterLang) && (
                <button
                  onClick={() => { setSearchQ(''); setFilterTheme(''); setFilterEra(''); setFilterLang('') }}
                  className="text-[10px] text-[var(--color-dim)] hover:text-[var(--color-accent)]"
                >
                  清空筛选
                </button>
              )}
            </div>

            {libraryQ.isLoading && <div className="text-[11px] italic text-[var(--color-dim)]">loading…</div>}

            {!libraryQ.isLoading && (libraryQ.data?.cases.length ?? 0) === 0 && (
              <div className="text-[11px] italic text-[var(--color-dim)] py-3">
                没有匹配的 case。试试清空筛选，或者上面 Today 区点 ✨ 拉一批新内容。
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {(libraryQ.data?.cases ?? []).map(c => (
                <CaseCard key={c.slug} c={c} onOpen={setOpenSlug} />
              ))}
            </div>
          </CardBody>
        </Card>
      </div>

      {/* Modal */}
      {openSlug && (
        <CaseModal slug={openSlug} onClose={() => setOpenSlug(null)} />
      )}
    </div>
  )
}


function CaseCard({
  c, onOpen, freshBadge = false,
}: { c: LearningCase; onOpen: (slug: string) => void; freshBadge?: boolean }) {
  const eraColor = ERA_COLOR[c.era || ''] || 'border-[var(--color-border)] text-[var(--color-dim)]'
  return (
    <button
      onClick={() => onOpen(c.slug)}
      data-testid={`learning-case-${c.slug}`}
      className="text-left p-2.5 rounded border border-[var(--color-border)]/50 hover:border-[var(--color-accent)] bg-[var(--color-panel)]/30 hover:bg-[var(--color-panel)]/60 transition"
    >
      <div className="flex items-start gap-2 mb-1">
        {freshBadge && (
          <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex-shrink-0">
            FRESH
          </span>
        )}
        {c.era && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${eraColor} flex-shrink-0`}>
            {ERA_LABEL[c.era] || c.era}
          </span>
        )}
        {c.difficulty && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-dim)] flex-shrink-0">
            {DIFFICULTY_LABEL[c.difficulty] || c.difficulty}
          </span>
        )}
        {c.language === 'en' && (
          <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-dim)] flex-shrink-0">
            原 EN
          </span>
        )}
      </div>
      <h3 className="text-[14px] md:text-[12px] font-semibold text-[var(--color-text)] mb-1 leading-snug">
        {c.title_zh}
      </h3>
      <p className="text-[12px] md:text-[10.5px] text-[var(--color-text)]/75 leading-snug line-clamp-3">
        {c.summary_zh}
      </p>
      <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
        {c.themes.slice(0, 4).map(t => (
          <span key={t} className="text-[8.5px] px-1 py-0.5 rounded bg-[var(--color-bg)] text-[var(--color-dim)]">
            {t}
          </span>
        ))}
        {c.source_name && (
          <span className="text-[8.5px] text-[var(--color-dim)] ml-auto italic truncate max-w-[180px]">
            {c.source_name}
          </span>
        )}
      </div>
    </button>
  )
}


function CaseModal({ slug, onClose }: { slug: string; onClose: () => void }) {
  const caseQ = useLearningCase(slug)
  const seenMu = useMarkLearningSeen()

  // Fire-and-forget: bump shown_count once the modal opens. Used by
  // the "today's classic" rotation to avoid showing the same case
  // every day.
  useEffect(() => {
    seenMu.mutate(slug)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  // ESC closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const c = caseQ.data

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      {/* Mobile: near-fullscreen with 8px margin (avoids the iOS
          URL bar / notch eating the bottom). Desktop: original
          centered 820px modal. dvh > vh on iOS so the modal sizes
          to the *visible* viewport, not the full-screen viewport. */}
      <div className="fixed inset-x-2 top-2 bottom-2 md:inset-auto md:top-[5vh] md:left-1/2 md:-translate-x-1/2 md:w-[820px] md:max-w-[92vw] md:max-h-[90dvh] bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-2xl z-50 flex flex-col">
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <div className="flex-1 min-w-0">
            {caseQ.isLoading && <div className="text-[12px] italic text-[var(--color-dim)]">loading…</div>}
            {c && (
              <>
                <h2 className="text-[15px] font-bold text-[var(--color-text)] mb-1">{c.title_zh}</h2>
                {c.title !== c.title_zh && (
                  <div className="text-[10px] text-[var(--color-dim)] italic">原标题: {c.title}</div>
                )}
                <div className="mt-1 flex items-center gap-2 text-[10px] flex-wrap">
                  {c.era && (
                    <span className={`px-1.5 py-0.5 rounded border ${ERA_COLOR[c.era] || 'border-[var(--color-border)] text-[var(--color-dim)]'}`}>
                      {ERA_LABEL[c.era] || c.era}
                    </span>
                  )}
                  {c.difficulty && (
                    <span className="px-1.5 py-0.5 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-dim)]">
                      {DIFFICULTY_LABEL[c.difficulty] || c.difficulty}
                    </span>
                  )}
                  {c.themes.map(t => (
                    <span key={t} className="px-1.5 py-0.5 rounded bg-[var(--color-bg)] text-[var(--color-dim)]">{t}</span>
                  ))}
                </div>
              </>
            )}
          </div>
          <button onClick={onClose} className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1">
            <X size={16} />
          </button>
        </div>

        {/* min-h-0 lets flex-1 actually shrink so overflow-y-auto
            kicks in (without it, content can blow past the parent
            on iOS). overscroll-contain keeps swipes from leaking to
            the underlying page. -webkit-overflow-scrolling for older
            iOS Safari momentum-scroll. touch-action: pan-y blocks
            iOS pull-to-refresh interfering. */}
        <div
          className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-3 md:p-4 text-[13px] md:text-[12px] leading-[1.7] text-[var(--color-text)]/90"
          style={{
            WebkitOverflowScrolling: 'touch',
            touchAction: 'pan-y',
          }}
        >
          {c?.body
            ? <pre className="whitespace-pre-wrap font-sans">{c.body}</pre>
            : c
              ? <p>{c.summary_zh}</p>
              : null}
        </div>

        {c?.source_url && (
          <div className="px-4 py-2.5 border-t border-[var(--color-border)] bg-[var(--color-panel)]/60 flex items-center gap-2">
            <a
              href={c.source_url}
              target="_blank" rel="noopener noreferrer"
              className="text-[11px] px-2 py-1 rounded border border-[var(--color-accent)]/40 hover:border-[var(--color-accent)] text-[var(--color-accent)] flex items-center gap-1"
            >
              🔗 阅读原文 (打开 {c.source_name || '源站'}) <ExternalLink size={10} />
            </a>
            {c.tickers.length > 0 && (
              <span className="ml-auto text-[10px] text-[var(--color-dim)]">
                相关 ticker: {c.tickers.join(', ')}
              </span>
            )}
          </div>
        )}
      </div>
    </>
  )
}


// ── Books section — grouped by availability ────────────────────
//
// Per user request: "把书单单独理出来 — 如果有网上的 PDF 或相关
// web 你可以加上, 否则我得去买". This section makes the book list
// clearly separate from the case/memo timeline. Free books (PD or
// publisher's free web edition) get a green 📖 button; paid books
// get an amber 🛒 button labelled with where to buy.
function BooksSection({ onOpen }: { onOpen: (slug: string) => void }) {
  const booksQ = useLearningBooks()
  const grouped = booksQ.data?.grouped ?? {}
  const free = [...(grouped.public_domain || []), ...(grouped.free_web || [])]
  const paid = grouped.paid || []

  // User asked: 中译本和英文原版混在一起看着像复读 — split paid by
  // language so 中文 (originals + translations) stack on top, then
  // 英文原版 below. Free section stays flat (only 1 zh entry there;
  // splitting would look silly).
  const paidZh = paid.filter(b => b.language === 'zh')
  const paidEn = paid.filter(b => b.language !== 'zh')

  return (
    <Card>
      <CardHeader
        title="📚 Books"
        subtitle={`${booksQ.data?.total ?? 0} 本经典投资书 · 免费的可直接读, 付费的标了去哪买`}
      />
      <CardBody>
        {booksQ.isLoading && (
          <div className="text-[11px] italic text-[var(--color-dim)]">loading…</div>
        )}

        {/* Free section — flat, mostly EN */}
        {free.length > 0 && (
          <>
            <div className="text-[10px] uppercase tracking-wider text-emerald-300 mb-1.5 flex items-center gap-1">
              <Globe size={11} /> 免费可读 ({free.length})
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
              {free.map(b => <BookCard key={b.slug} b={b} onOpen={onOpen} />)}
            </div>
          </>
        )}

        {/* Paid section — split by language */}
        {paid.length > 0 && (
          <>
            <div className="text-[10px] uppercase tracking-wider text-amber-300 mb-1.5 flex items-center gap-1">
              <ShoppingCart size={11} /> 需要购买 ({paid.length})
            </div>

            {paidZh.length > 0 && (
              <>
                <div className="text-[10px] text-[var(--color-text)]/60 mb-1.5 ml-1 flex items-center gap-1">
                  <span>🇨🇳</span> 中文版 ({paidZh.length})
                  <span className="text-[var(--color-dim)] italic">— 中文原创 + 中译本</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                  {paidZh.map(b => <BookCard key={b.slug} b={b} onOpen={onOpen} />)}
                </div>
              </>
            )}

            {paidEn.length > 0 && (
              <>
                <div className="text-[10px] text-[var(--color-text)]/60 mb-1.5 ml-1 flex items-center gap-1">
                  <span>🇺🇸</span> 英文原版 ({paidEn.length})
                  <span className="text-[var(--color-dim)] italic">— 没有官方中译本或想读原文</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {paidEn.map(b => <BookCard key={b.slug} b={b} onOpen={onOpen} />)}
                </div>
              </>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}


function BookCard({
  b, onOpen,
}: { b: LearningCase; onOpen: (slug: string) => void }) {
  const isFree = b.availability === 'public_domain' || b.availability === 'free_web'
  const availLabel = b.availability === 'public_domain' ? 'Public Domain'
                  : b.availability === 'free_web'      ? '免费在线'
                  : '需购买'
  const availColor = isFree
    ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10'
    : 'border-amber-500/40 text-amber-300 bg-amber-500/10'
  return (
    <div className="p-2.5 rounded border border-[var(--color-border)]/50 bg-[var(--color-panel)]/30 flex flex-col gap-2">
      <div>
        <div className="flex items-start gap-1.5 mb-1 flex-wrap">
          <span
            className="text-[10px] flex-shrink-0"
            title={b.language === 'zh' ? '中文版' : '英文原版'}
          >
            {b.language === 'zh' ? '🇨🇳' : '🇺🇸'}
          </span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${availColor} flex-shrink-0`}>
            {availLabel}
          </span>
          {b.era && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded border ${
              ERA_COLOR[b.era] || 'border-[var(--color-border)] text-[var(--color-dim)]'
            } flex-shrink-0`}>
              {ERA_LABEL[b.era] || b.era}
            </span>
          )}
        </div>
        <h3 className="text-[14px] md:text-[12px] font-semibold text-[var(--color-text)] leading-snug mb-1">
          {b.title_zh}
        </h3>
        <p className="text-[12px] md:text-[10.5px] text-[var(--color-text)]/75 leading-snug line-clamp-3">
          {b.summary_zh}
        </p>
      </div>
      <div className="flex items-center gap-1.5 mt-auto flex-wrap">
        <button
          onClick={() => onOpen(b.slug)}
          className="text-[12px] md:text-[10px] px-2.5 md:px-2 py-1 md:py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)]"
        >
          📋 看简介
        </button>
        {b.purchase_url && (
          <a
            href={b.purchase_url}
            target="_blank" rel="noopener noreferrer"
            className={`text-[12px] md:text-[10px] px-2.5 md:px-2 py-1 md:py-0.5 rounded border flex items-center gap-1 ${
              isFree
                ? 'border-emerald-500/40 hover:border-emerald-300 text-emerald-300'
                : 'border-amber-500/40 hover:border-amber-300 text-amber-300'
            }`}
          >
            {isFree
              ? <><BookOpen size={10} /> 免费读</>
              : <><ShoppingCart size={10} /> 去购买</>}
            <ExternalLink size={9} />
          </a>
        )}
        {b.source_name && (
          <span className="text-[8.5px] text-[var(--color-dim)] italic ml-auto truncate max-w-[140px]">
            {b.source_name}
          </span>
        )}
      </div>
    </div>
  )
}
