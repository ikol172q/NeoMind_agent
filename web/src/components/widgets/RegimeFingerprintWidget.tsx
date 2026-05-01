/**
 * RegimeFingerprintWidget — 5 colored bars showing today's regime
 * across the 5 user-friendly buckets, per design doc v2 §1.
 *
 * Each bar:
 *   • 0–100 score (or "no data" when fingerprint isn't available yet)
 *   • Tooltip explaining what the bucket means in plain language
 *   • Click → expand to see component metrics + 5-window percentiles
 *
 * Sits at the top of the Strategies tab (and ideally at the top of
 * Research tab too) so the user can SEE today's regime at a glance
 * and trace why a strategy was recommended.
 */
import { useState } from 'react'
import { useRegimeFingerprint } from '@/lib/api'


interface BucketDef {
  key:     'risk_appetite' | 'volatility_regime' | 'breadth' | 'event_density' | 'flow'
  scoreKey: 'risk_appetite_score' | 'volatility_regime_score' | 'breadth_score' | 'event_density_score' | 'flow_score'
  emoji:   string
  zhLabel: string
  enLabel: string
  tooltip: string                                    // plain-language meaning
  highSide: string                                   // what "high score" means (text)
  lowSide:  string                                   // what "low score" means
}


const BUCKETS: BucketDef[] = [
  {
    key:      'risk_appetite',
    scoreKey: 'risk_appetite_score',
    emoji:    '🌡️',
    zhLabel:  '市场情绪',
    enLabel:  'Risk Appetite',
    tooltip:
      '今天市场是恐慌还是贪婪？基于 VIX 百分位、SPY RSI 等。\n' +
      '决定 保守 vs 激进策略偏好。',
    highSide: '贪婪 / Greed',
    lowSide:  '恐慌 / Fear',
  },
  {
    key:      'volatility_regime',
    scoreKey: 'volatility_regime_score',
    emoji:    '📈',
    zhLabel:  '波动幅度',
    enLabel:  'Volatility',
    tooltip:
      '股票每天跳多大？基于 SPY 30d 实际波动、VIX-RV 差、波动期限结构。\n' +
      '决定 卖期权（高IV）vs 买期权（低IV）。',
    highSide: '高波 / Stretched',
    lowSide:  '低波 / Compressed',
  },
  {
    key:      'breadth',
    scoreKey: 'breadth_score',
    emoji:    '🌐',
    zhLabel:  '市场广度',
    enLabel:  'Breadth',
    tooltip:
      '是少数大盘股领涨还是普涨？基于 S&P500 站50日均线占比、板块离散度。\n' +
      '决定 指数 vs 个股、板块轮动。',
    highSide: '宽 / Broad',
    lowSide:  '窄 / Narrow',
  },
  {
    key:      'event_density',
    scoreKey: 'event_density_score',
    emoji:    '📅',
    zhLabel:  '事件密度',
    enLabel:  'Event Density',
    tooltip:
      '未来几天有多少大事件？基于到 OPEX 距离、未来5日财报数、FOMC 距离。\n' +
      '决定 hedge / 套利 / 等待时机。',
    highSide: '事件密集',
    lowSide:  '平静',
  },
  {
    key:      'flow',
    scoreKey: 'flow_score',
    emoji:    '💸',
    zhLabel:  '资金流向',
    enLabel:  'Flow',
    tooltip:
      '钱往哪里跑？基于收益率曲线、USD 强弱、信用利差(HYG/IEF)。\n' +
      '决定 risk-on / risk-off、跨资产配置。',
    highSide: 'Risk-on',
    lowSide:  'Risk-off',
  },
]


function colorForScore(score: number | null): string {
  if (score == null) return 'var(--color-dim)'
  if (score < 30)  return 'var(--color-red, #e07070)'      // low side — caution
  if (score < 70)  return 'var(--color-amber,#e5a200)'     // neutral
  return 'var(--color-green)'                              // high side
}


function labelForScore(b: BucketDef, score: number | null): string {
  if (score == null) return '—'
  if (score < 30)  return b.lowSide
  if (score < 70)  return '中性 / Neutral'
  return b.highSide
}


export interface RegimeFingerprintWidgetProps {
  asOf?: string                                            // 'live' or 'YYYY-MM-DD'
  /** When true, show a compact horizontal layout (5 bars on one row).
   *  When false, vertical layout with extra detail per bar. */
  compact?: boolean
}


export function RegimeFingerprintWidget({
  asOf,
  compact = true,
}: RegimeFingerprintWidgetProps) {
  const q = useRegimeFingerprint(asOf)
  const [expanded, setExpanded] = useState<string | null>(null)

  const fp = q.data
  const isLoading = q.isLoading
  const isError = q.isError

  if (isError) {
    return (
      <div
        data-testid="regime-fingerprint-widget"
        className="mb-3 rounded border border-[var(--color-amber,#e5a200)]/40 bg-[var(--color-amber,#e5a200)]/[0.05] p-2 text-[10px] text-[var(--color-dim)]"
      >
        ⚠ 5-bucket regime fingerprint 不可用（可能是 raw_market_data
        还没 backfill）— 双击桌面 <code>regime_backfill.command</code>
        拉 1 年 yfinance 数据。
      </div>
    )
  }

  // Even when loading or with empty fingerprint, render the bars (with
  // "—" placeholders) so the user can see the surface and won't think
  // it's a layout bug.
  return (
    <div
      data-testid="regime-fingerprint-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5"
    >
      <div className="flex items-center gap-2 mb-1.5 text-[10px] text-[var(--color-dim)]">
        <span className="font-semibold text-[var(--color-text)]">
          🎯 今日市场状态 / Today's Regime
        </span>
        <span className="font-mono">
          {fp?.fingerprint_date ?? (isLoading ? 'loading…' : '—')}
        </span>
        {!fp && !isLoading && (
          <span className="text-[var(--color-amber,#e5a200)]">
            (no fingerprint yet — run regime_backfill.command)
          </span>
        )}
      </div>

      <div className={
        compact
          ? 'grid grid-cols-5 gap-1.5'
          : 'flex flex-col gap-1.5'
      }>
        {BUCKETS.map(b => {
          const score = fp?.[b.scoreKey] ?? null
          const isExpanded = expanded === b.key
          const fillPct = score == null ? 0 : score
          const color = colorForScore(score)
          const components = fp?.components?.[b.key] as
            Record<string, Record<string, number | null> | { value?: number }> | undefined

          return (
            <div key={b.key} className="text-[10px]">
              <button
                data-testid={`regime-bucket-${b.key}`}
                onClick={() => setExpanded(isExpanded ? null : b.key)}
                className="w-full text-left px-1.5 py-1 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 transition"
                title={b.tooltip}
              >
                <div className="flex items-center gap-1 mb-1">
                  <span>{b.emoji}</span>
                  <span className="text-[var(--color-text)] font-medium truncate">
                    {b.zhLabel}
                  </span>
                  <span className="ml-auto font-mono text-[9.5px]" style={{ color }}>
                    {score == null ? '—' : score.toFixed(0)}
                  </span>
                </div>
                {/* bar */}
                <div className="h-1.5 rounded bg-[var(--color-border)]/40 overflow-hidden">
                  <div
                    className="h-full transition-all"
                    style={{
                      width: `${fillPct}%`,
                      backgroundColor: color,
                    }}
                  />
                </div>
                <div className="mt-0.5 text-[8.5px] text-[var(--color-dim)] truncate">
                  {labelForScore(b, score)}
                </div>
              </button>

              {isExpanded && (
                <div
                  data-testid={`regime-bucket-${b.key}-detail`}
                  className="mt-1 px-1.5 py-1 rounded bg-[var(--color-panel)] border border-[var(--color-border)] text-[9.5px] leading-[1.4]"
                >
                  <div className="font-semibold text-[var(--color-text)] mb-0.5">
                    {b.enLabel}
                  </div>
                  <div className="text-[var(--color-dim)] whitespace-pre-line mb-1.5">
                    {b.tooltip}
                  </div>
                  {components && Object.keys(components).length > 0 ? (
                    <>
                      <div className="text-[var(--color-dim)] uppercase tracking-wider text-[8.5px] mb-0.5">
                        components
                      </div>
                      {Object.entries(components).map(([k, v]) => {
                        // Multi-window percentile? (object with 1w/1m/3m/6m/1y keys)
                        if (v && typeof v === 'object' && '3m' in (v as object)) {
                          const win = v as Record<string, number | null>
                          return (
                            <div key={k} className="font-mono text-[9px] flex items-center gap-2">
                              <span className="text-[var(--color-text)]">{k}</span>
                              <span className="text-[var(--color-dim)]">
                                3m: {fmt(win['3m'])}
                                {' · '}1m: {fmt(win['1m'])}
                                {' · '}1y: {fmt(win['1y'])}
                              </span>
                            </div>
                          )
                        }
                        // Single-value component
                        const val = (v as { value?: number }).value
                        return (
                          <div key={k} className="font-mono text-[9px]">
                            <span className="text-[var(--color-text)]">{k}</span>
                            {' '}<span className="text-[var(--color-dim)]">{val?.toFixed?.(1) ?? '—'}</span>
                          </div>
                        )
                      })}
                    </>
                  ) : (
                    <div className="italic text-[var(--color-dim)]">
                      no component data (fingerprint may be empty)
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-1.5 text-[8.5px] text-[var(--color-dim)] italic leading-[1.4]">
        Click 任一块看详情 + 5 个窗口百分位（1w/1m/3m/6m/1y）。每个数字
        都源自 raw_market_data SQLite 表（双击桌面 regime_backfill.command
        来拉 1 年 yfinance 数据）。每天的 regime 不一样 → 推荐策略也不一样。
      </div>
    </div>
  )
}


function fmt(p: number | null | undefined): string {
  if (p == null) return '—'
  return `${(p * 100).toFixed(0)}%`
}
