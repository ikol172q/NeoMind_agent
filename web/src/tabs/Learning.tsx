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
  type LearningCase,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import {
  ExternalLink, Loader2, Search, Sparkles, Clock, X,
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
      <div className="p-4 max-w-6xl mx-auto space-y-3">
        {/* Today */}
        <Card>
          <CardHeader
            title="📚 Today"
            subtitle={`${fresh.length} 条 fresh + 1 经典轮换 · 最近 7 天 fetch 的为 fresh`}
          />
          <CardBody>
            <div className="flex items-center gap-2 mb-3 text-[10px] text-[var(--color-dim)]">
              <button
                data-testid="learning-refresh"
                onClick={() => refreshMu.mutate()}
                disabled={refreshMu.isPending}
                className="px-2 py-1 rounded border border-emerald-500/40 hover:border-emerald-300 text-emerald-300 flex items-center gap-1 disabled:opacity-50"
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

        {/* Library */}
        <Card>
          <CardHeader
            title="📖 Library"
            subtitle={`${libraryQ.data?.total ?? 0} 条全部案例 · 按 fetched_at 倒序`}
          />
          <CardBody>
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-2 mb-3 text-[11px]">
              <div className="relative flex-1 min-w-[200px]">
                <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--color-dim)]" />
                <input
                  type="text"
                  placeholder="搜标题 / 摘要…"
                  value={searchQ}
                  onChange={e => setSearchQ(e.target.value)}
                  className="w-full pl-7 pr-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px] outline-none focus:border-[var(--color-accent)]"
                />
              </div>
              <select
                value={filterTheme}
                onChange={e => setFilterTheme(e.target.value)}
                className="px-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px]"
              >
                <option value="">全部主题</option>
                {(themesQ.data?.themes ?? []).map(t => (
                  <option key={t.theme} value={t.theme}>{t.theme} ({t.count})</option>
                ))}
              </select>
              <select
                value={filterEra}
                onChange={e => setFilterEra(e.target.value)}
                className="px-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px]"
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
                className="px-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[11px]"
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
      <h3 className="text-[12px] font-semibold text-[var(--color-text)] mb-1 leading-snug">
        {c.title_zh}
      </h3>
      <p className="text-[10.5px] text-[var(--color-text)]/75 leading-snug line-clamp-3">
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
      <div className="fixed top-[5vh] left-1/2 -translate-x-1/2 w-[820px] max-w-[92vw] max-h-[90vh] bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-2xl z-50 flex flex-col">
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

        <div className="flex-1 overflow-y-auto p-4 text-[12px] leading-[1.7] text-[var(--color-text)]/90">
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
