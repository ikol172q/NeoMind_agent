/**
 * AlgorithmAppendix — Strategies tab 底部的 GROUND TRUTH 文档.
 *
 * 这个 component 列出 Strategies tab 上每个可视化背后的：
 *   - 算法名 + 论文 / 出处
 *   - 公式（数学符号）
 *   - 实现的代码位置（可点击）
 *   - 输入 / 输出
 *   - 期望解释 + 阈值
 *
 * 这是 dashboard 数字的对照表 — 用户可以拿任意一个数字查回到这里
 * 验证它是否符合既定算法。
 *
 * 严谨性要求:
 *   - 公式必须跟代码完全一致（否则就是 bug）
 *   - 论文引用要精确到年份 + 作者 + title
 *   - 代码路径要 exact 当前 repo
 *   - 没有遗漏的算法 — 看到 dashboard 上的数字应该能找到对应条目
 *
 * 折叠默认隐藏（节省视觉空间），用户主动点开看。
 */
import { useState } from 'react'


export function AlgorithmAppendix() {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpanded(next)
  }

  return (
    <div
      data-testid="algorithm-appendix"
      className="mt-4 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40"
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-2 hover:bg-[var(--color-panel)]/30 transition flex items-center gap-2"
      >
        <span className="text-[10px] font-semibold text-[var(--color-text)]">
          📚 Algorithm Appendix · Ground Truth — 所有可视化背后的算法 / 论文 / 公式 / 代码
        </span>
        <span className="text-[8.5px] text-[var(--color-dim)] italic ml-auto">
          {open ? '▾ 折叠' : '▸ 展开 (用来对照 dashboard 数字)'}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-2 text-[10px]">
          <div className="text-[8.5px] text-[var(--color-dim)] italic mb-2 leading-[1.5]">
            目的：dashboard 上每个数字可以追溯回这里。任何不一致 = bug。
            <span className="text-[var(--color-text)]"> 严谨为先</span>。
          </div>

          {SECTIONS.map((section) => (
            <AppendixSection
              key={section.id}
              section={section}
              isOpen={expanded.has(section.id)}
              onToggle={() => toggle(section.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}


function AppendixSection({
  section, isOpen, onToggle,
}: {
  section: SectionDef
  isOpen: boolean
  onToggle: () => void
}) {
  return (
    <div className="rounded border border-[var(--color-border)] bg-[var(--color-panel)]/40">
      <button
        onClick={onToggle}
        className="w-full text-left px-2.5 py-1.5 hover:bg-[var(--color-panel)] flex items-center gap-2"
      >
        <span className="text-[9.5px] font-medium text-[var(--color-text)]">
          {section.id}. {section.title}
        </span>
        <span className="text-[8.5px] text-[var(--color-dim)] italic ml-auto truncate max-w-[60%]">
          {section.subtitle}
        </span>
        <span className="text-[8px] text-[var(--color-dim)]">{isOpen ? '▾' : '▸'}</span>
      </button>
      {isOpen && (
        <div className="px-2.5 pb-2.5 space-y-1.5">
          {section.entries.map((entry, i) => (
            <div
              key={i}
              className="rounded border border-[var(--color-border)] bg-[var(--color-bg)]/30 p-2 space-y-1"
            >
              <div className="flex items-baseline gap-2">
                <span className="font-semibold text-[var(--color-text)] text-[10px]">
                  {entry.name}
                </span>
                {entry.citation && (
                  <span className="text-[8.5px] italic text-[var(--color-dim)]">
                    — {entry.citation}
                  </span>
                )}
              </div>
              {entry.formula && (
                <div className="font-mono text-[9.5px] bg-[var(--color-panel)]/60 rounded px-2 py-1 text-[var(--color-text)] whitespace-pre-wrap">
                  {entry.formula}
                </div>
              )}
              {entry.symbols && (
                <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
                  <strong className="text-[var(--color-text)]">符号</strong>: {entry.symbols}
                </div>
              )}
              {entry.interpretation && (
                <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
                  <strong className="text-[var(--color-text)]">解释</strong>: {entry.interpretation}
                </div>
              )}
              {entry.thresholds && (
                <div className="text-[9px] text-[var(--color-dim)] leading-[1.5]">
                  <strong className="text-[var(--color-text)]">阈值</strong>: {entry.thresholds}
                </div>
              )}
              {entry.code && (
                <div className="text-[8.5px] font-mono text-[var(--color-dim)]">
                  📄 {entry.code}
                </div>
              )}
              {entry.dashboard_field && (
                <div className="text-[8.5px] text-[var(--color-dim)] italic">
                  ↑ 对应 dashboard 字段：<span className="font-mono text-[var(--color-text)]">{entry.dashboard_field}</span>
                </div>
              )}
              {entry.caveat && (
                <div className="text-[9px] text-[var(--color-amber,#e5a200)] leading-[1.5]">
                  ⚠ {entry.caveat}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


// ── Ground truth definitions ──────────────────────────────────────


interface AppendixEntry {
  name:               string
  citation?:          string
  formula?:           string
  symbols?:           string
  interpretation?:    string
  thresholds?:        string
  code?:              string
  dashboard_field?:   string
  caveat?:            string
}


interface SectionDef {
  id:        string
  title:     string
  subtitle:  string
  entries:   AppendixEntry[]
}


const SECTIONS: SectionDef[] = [
  // ── 1. Regime Fingerprint ───────────────────────────────────────
  {
    id: '1',
    title: 'Regime Fingerprint (5 buckets)',
    subtitle: '5 个 regime bucket 的计算方法 — Strategies tab 顶部的彩色 bar',
    entries: [
      {
        name: 'Risk Appetite Score',
        citation: 'percentile rank (Galton 1885); RSI (Wilder 1978, "New Concepts in Technical Trading Systems")',
        formula:
          'risk_appetite = avg(\n' +
          '  100 × (1 − vix_pct_rank_1y),     # VIX low percentile → high risk appetite\n' +
          '  spy_rsi_14                        # SPY 14-day RSI\n' +
          ')',
        symbols: 'vix_pct_rank_1y = ECDF of VIX over last 252 trading days; spy_rsi_14 = Wilder\'s RSI',
        interpretation: '0-100 分数。> 70 贪婪/Greed；< 30 恐慌/Fear；50 ± 中性',
        code: 'agent/finance/regime/fingerprint.py:_bucket_risk_appetite',
        dashboard_field: 'fingerprint.risk_appetite_score (顶部 🌡️ 市场情绪 bar)',
      },
      {
        name: 'Volatility Regime Score',
        citation: 'realized volatility (Andersen-Bollerslev 1998 RV literature); VIX term structure',
        formula:
          'volatility_regime = avg(\n' +
          '  spy_30d_rv_pct_rank_1y × 100,    # SPY annualised 30d realized vol percentile\n' +
          '  vix_minus_rv_score,              # (VIX − RV) — vol risk premium\n' +
          '  vol_term_score                   # VIX9D − VIX (negative = backwardation)\n' +
          ')',
        symbols: 'rv_30d = √252 × stdev(log returns over 30d); vix_minus_rv = (VIX/100 − rv_30d)',
        interpretation: '> 70 高波 / Stretched；< 30 低波 / Compressed',
        code: 'agent/finance/regime/fingerprint.py:_bucket_volatility_regime',
        dashboard_field: 'fingerprint.volatility_regime_score (顶部 📈 波动幅度 bar)',
      },
      {
        name: 'Breadth Score',
        citation: 'market breadth indicators (Lowry 1933); sector dispersion',
        formula:
          'breadth = avg(\n' +
          '  pct_sp500_above_50d_ma,          # % of S&P500 above their 50-day MA\n' +
          '  100 × (1 − sector_dispersion_5d_normalized)\n' +
          ')',
        symbols: 'pct_sp500_above_50d_ma uses ~454 S&P500 tickers; sector_dispersion = stdev of 5d returns across 11 SPDR sector ETFs',
        interpretation: '> 70 普涨 (Broad)；< 30 少数股推动 (Narrow concentrated leadership)',
        code: 'agent/finance/regime/fingerprint.py:_bucket_breadth',
        dashboard_field: 'fingerprint.breadth_score (顶部 🌐 市场广度 bar)',
      },
      {
        name: 'Event Density Score',
        citation: 'OPEX cycle (CBOE), FOMC schedule (FRB)',
        formula:
          'event_density = clip(\n' +
          '  100 × (1 − days_to_OPEX / 30) × 0.5\n' +
          '  + 100 × (1 − days_to_FOMC / 60) × 0.5,\n' +
          '  0, 100\n' +
          ')',
        symbols: 'OPEX = third Friday of month; FOMC = Federal Reserve meeting calendar',
        interpretation: '> 70 事件密集 (近 OPEX / FOMC)；< 30 平静 (远期)',
        code: 'agent/finance/regime/fingerprint.py:_bucket_event_density',
        dashboard_field: 'fingerprint.event_density_score (顶部 📅 事件密度 bar)',
      },
      {
        name: 'Flow Score',
        citation: 'yield curve research (Estrella-Mishkin 1998); credit spread (Gilchrist-Zakrajšek 2012)',
        formula:
          'flow = avg(\n' +
          '  yield_curve_score,               # ^TNX − ^IRX (10y − 13w T-bill, 2y proxy)\n' +
          '  usd_index_score,                 # 1 − pct_rank(DX-Y.NYB) — weak USD = risk-on\n' +
          '  hyg_ief_ratio_pct_rank × 100     # HYG/IEF (high yield / treasury) — tight credit = risk-on\n' +
          ')',
        symbols: 'HYG = iShares iBoxx $ High Yield Corporate Bond ETF; IEF = 7-10y treasury ETF',
        interpretation: '> 70 Risk-on (信用宽松)；< 30 Risk-off (避险资金)',
        code: 'agent/finance/regime/fingerprint.py:_bucket_flow',
        dashboard_field: 'fingerprint.flow_score (顶部 💸 资金流向 bar)',
      },
      {
        name: 'Multi-window Percentile (1w / 1m / 3m / 6m / 1y)',
        citation: 'empirical CDF / rank-based normalization',
        formula: 'pct_rank(x; window) = (#{x_t < x : t ∈ window}) / |window|',
        interpretation: '点击任一 bucket 展开看 5 个时间窗口的百分位。多窗口一致 → 信号 robust；分歧 → 短/长期不一致',
        code: 'agent/finance/regime/fingerprint.py:_multi_window_pct_rank',
        dashboard_field: 'components.{bucket}.{indicator}.{1w|1m|3m|6m|1y}',
      },
    ],
  },

  // ── 2. Portfolio Selection (MMR) ───────────────────────────────
  {
    id: '2',
    title: 'Portfolio Selection — MMR (Maximal Marginal Relevance)',
    subtitle: 'Top + Alternatives widget 上方的 1 个最推荐 + 3-8 个替代',
    entries: [
      {
        name: 'Maximal Marginal Relevance',
        citation: 'Carbonell & Goldstein (1998) "The use of MMR, diversity-based reranking for reordering documents and producing summaries", SIGIR \'98',
        formula:
          'MMR(c) = λ · relevance(c) − (1 − λ) · max_{s ∈ Selected} similarity(c, s)\n' +
          '\n' +
          'algorithm:\n' +
          '  1. selected = [argmax(relevance)]\n' +
          '  2. while |selected| < n+1:\n' +
          '       next = argmax_{c ∉ selected} MMR(c)\n' +
          '       selected.append(next)',
        symbols: 'relevance(c) = score / max_score (0..1); λ ∈ [0,1] (默认 0.65 = 偏 relevance)',
        interpretation: '"和已选差异越大 + 相关性越高 → MMR 越大"。λ=1 → 纯按 relevance 排；λ=0 → 纯按差异排',
        code: 'agent/finance/regime/scorer.py:select_diversified_portfolio',
        dashboard_field: 'PortfolioWidget.alternatives — _mmr_score, _diversity_from_top',
      },
      {
        name: 'Strategy Similarity',
        citation: 'cosine sim (Salton 1971); category match (custom)',
        formula:
          'similarity(a, b) = 0.40 · payoff_class_match(a, b)\n' +
          '                 + 0.20 · asset_class_match(a, b)\n' +
          '                 + 0.40 · cosine(regime_sensitivity_a, regime_sensitivity_b)',
        symbols: 'payoff_class_match: 1.0 if identical; 0.5 if same family prefix; 0 otherwise',
        interpretation: 'similarity 越大 = 两个 strategy 在 payoff 形态 + asset class + 对 regime 的敏感方向 上越接近',
        code: 'agent/finance/regime/scorer.py:_strategy_similarity',
        dashboard_field: 'PortfolioWidget alternatives 中的 div: 42% (= 1 − similarity)',
      },
    ],
  },

  // ── 3. k-NN Bayesian Prior ────────────────────────────────────
  {
    id: '3',
    title: 'k-NN Bayesian Shrinkage Prior (Step E)',
    subtitle: 'v2 scorer 用历史相似日的实际 P&L 校正模型预测',
    entries: [
      {
        name: 'k-Nearest Neighbors over Regime Space',
        citation: 'Cover & Hart (1967) "Nearest Neighbor Pattern Classification"',
        formula:
          'distance(today, day_j) = √(Σ_{k=1..5} (regime_score_k_today − regime_score_k_j)²)\n' +
          'similarity = max(0, 1 − distance / 111.8)         # 111.8 = √(5×100²)',
        symbols: '5 个 bucket score 都是 0-100，所以最大距离 = √5 × 100 = 223.6，归一化',
        interpretation: 'k=5 个最相似的历史日子',
        code: 'agent/finance/regime/scorer.py:_knn_regime_neighbors',
      },
      {
        name: 'Empirical Bayes Shrinkage',
        citation: 'Robbins (1956) "An Empirical Bayes Approach to Statistics"; Stein (1956)',
        formula:
          'prior_mean = Σ_i (similarity_i · realized_score_i) / Σ_i similarity_i\n' +
          'β = min(0.40, n / (n + 5))                       # adaptive shrinkage\n' +
          'blended = (1 − β) · model_score + β · prior_mean',
        symbols: 'n = number of neighbors with historical data; β capped at 0.4 = 不超过 40% 权重给 prior',
        interpretation: '历史邻居越多 → β 越大 → 越信 prior；neighbors=0 → β=0 → 纯模型分',
        code: 'agent/finance/regime/scorer.py:score_all_strategies (apply_knn_prior=True path)',
        dashboard_field: 'decision_traces.breakdown.knn_prior',
      },
    ],
  },

  // ── 4. Risk Dashboard 6 dimensions ────────────────────────────
  {
    id: '4',
    title: 'Risk Dashboard — 6 维度风险量化',
    subtitle: '点开任一 strategy 卡片看 6 个 section + walk-forward',
    entries: [
      {
        name: '4.1 Return Distribution (k-NN regime analogs)',
        citation: 'k-NN density estimation (Loftsgaarden-Quesenberry 1965)',
        formula:
          '1. find K=30 historical dates closest to today\'s regime by Euclidean distance\n' +
          '2. pull realized 30d P&L of THIS strategy on those dates\n' +
          '3. report: median, p10, p25, p75, p90, mean, std',
        interpretation: '"过去类似 regime 下，这个 strategy 30 天后赚多少"的经验分布',
        code: 'agent/finance/regime/risk.py:return_distribution',
        dashboard_field: 'return_distribution.{median, p10, p90, mean, std}',
      },
      {
        name: '4.2 VaR (Value at Risk)',
        citation: 'Markowitz (1959); Jorion (2007) "Value at Risk: The New Benchmark"',
        formula:
          'VaR_α = − inf{x : P(L ≤ x) ≥ 1 − α}\n' +
          'historical: VaR_95 = 5th percentile of full historical loss distribution',
        symbols: 'L = loss (negative return); α = 0.95 confidence; 也可写作 5% tail percentile',
        interpretation: '"5% 的概率会损失到 VaR 以下" — 历史最差 5% 那批的边界',
        thresholds: '|VaR_95| > 5%/月 = 高风险；> 10% = 极端',
        code: 'agent/finance/regime/risk.py:tail_risk',
        dashboard_field: 'tail_risk.var',
        caveat: 'VaR 不是 coherent risk measure (Artzner 1999)，不满足次可加性。优先看 CVaR。',
      },
      {
        name: '4.3 CVaR (Conditional Value at Risk / Expected Shortfall)',
        citation: 'Rockafellar & Uryasev (2002) "Conditional value-at-risk for general loss distributions", J. Banking & Finance, 26(7), 1443–1471',
        formula:
          'CVaR_α = E[L | L ≥ VaR_α]\n' +
          '       = (1 / (1−α)) ∫_VaR_α^∞ x · f_L(x) dx',
        symbols: '在最坏 (1−α) 的 tail 里，平均损失多少',
        interpretation: '"最坏 5% 的情况下，平均亏 CVaR" — 比 VaR 严格，convex 可优化',
        thresholds: 'CVaR > 2 × VaR 表明 fat tail；CVaR_95 > 8% 极端',
        code: 'agent/finance/regime/risk.py:tail_risk (R-U method)',
        dashboard_field: 'tail_risk.cvar',
      },
      {
        name: '4.4 Maximum Drawdown',
        citation: 'Magdon-Ismail-Atiya (2004) "Maximum Drawdown" — Risk magazine',
        formula:
          'MaxDD = min_t(realized_return_t)             # in 5y backtest\n' +
          '(单期最差 — 因为 backtest_results 每行是独立 30d sample，不是连续 PnL 路径)',
        interpretation: '"5 年里最惨那次 30 天后跌多少" + 那是哪一天',
        thresholds: 'individual: 可承受 10-20%；25%+ 触发策略复盘',
        code: 'agent/finance/regime/risk.py:tail_risk',
        dashboard_field: 'tail_risk.max_drawdown, max_drawdown_date',
      },
      {
        name: '4.5 Kelly Criterion + Half-Kelly',
        citation: 'Kelly (1956) "A New Interpretation of Information Rate", Bell System Technical Journal, 35(4), 917–926. Half-Kelly: MacLean-Ziemba (1985).',
        formula:
          'Kelly: f* = (b · p − q) / b\n' +
          '  其中 b = avg_win / |avg_loss| (gain/loss ratio)\n' +
          '       p = win rate; q = 1 − p\n' +
          '\n' +
          'Half-Kelly: f_½ = 0.5 · f*\n' +
          '\n' +
          '理论：长期 expected log wealth growth 在 f = f* 处最大化',
        symbols: 'f* = optimal capital fraction; clipped to [0, 1]',
        interpretation: '"数学上最优的下注比例"。但 f* 是 upper bound — 实际用 Half-Kelly 安全得多 (drawdown 减半，growth ~75%)',
        thresholds: 'Half-Kelly > 5% = 值得做；= 0 = 不要 trade；< 0 = 反着做（理论上）',
        code: 'agent/finance/regime/risk.py:position_sizing',
        dashboard_field: 'position_sizing.{kelly, half_kelly, gain_loss_ratio}',
        caveat: 'Kelly 对 win_rate / avg_win / avg_loss 估计的误差非常敏感 — 5% 估计误差可能导致 50% 仓位偏差',
      },
      {
        name: '4.6 Markowitz Hedge Ratio',
        citation: 'Markowitz (1952) "Portfolio Selection", Journal of Finance, 7(1), 77–91',
        formula:
          'optimal hedge ratio: h* = − cov(target, hedge) / var(hedge)\n' +
          '                       = − ρ · σ_target / σ_hedge\n' +
          '\n' +
          'portfolio variance:  var(target + h · hedge)\n' +
          '                   = σ²_target + h² · σ²_hedge + 2h · ρ · σ_target · σ_hedge\n' +
          '取导数 = 0 得 h*',
        symbols: 'ρ = Pearson correlation between target & candidate hedge return series',
        interpretation: '"持 1 单位 target 加 h 单位 hedge，组合方差最小" — Markowitz 1952 的特殊化',
        code: 'agent/finance/regime/risk.py:hedge_candidates',
        dashboard_field: 'hedge_candidates.top[].{correlation, size_ratio}',
        caveat: 'Top 3 candidates 显示 ρ ≈ -0.91 完全相同 — 是 proxy P&L 的伪相关。真 broker 数据后会分散。',
      },
      {
        name: '4.7 ATR Stop-Loss',
        citation: 'Wilder (1978) "New Concepts in Technical Trading Systems"',
        formula:
          'TR_t = max(high − low, |high − prev_close|, |prev_close − low|)\n' +
          'ATR(n)_t = (1/n) · Σ_{i=t-n+1}^{t} TR_i        # Wilder 用 EMA 平滑\n' +
          '\n' +
          'suggested_stop = − atr_multiple · σ_strategy\n' +
          'time_stop = 1.5 × hold_days',
        symbols: 'atr_multiple = 1.0 (默认 1σ)；σ_strategy = stdev(realized_pnl_pct in 5y)',
        interpretation: '"~70% 的历史路径都不会跌破 stop"，剩 30% 触发止损保护本金',
        thresholds: 'coverage = % paths NOT triggering stop (希望 ≥ 80%)',
        code: 'agent/finance/regime/risk.py:stop_loss',
        dashboard_field: 'stop_loss.{suggested_stop, time_stop_days, sigma, coverage}',
      },
      {
        name: '4.8 Regime Fit Score',
        citation: 'rule-based; not from a paper',
        formula:
          '对 5 个 bucket 各自:\n' +
          '  pref = "high" if sensitivity > +0.3\n' +
          '         "low"  if sensitivity < −0.3\n' +
          '         "neutral" else\n' +
          '  today = "high" if score > 66; "low" if < 33; "neutral" else\n' +
          '  fit = "good" if pref == today\n' +
          '        "bad"  if opposite\n' +
          '        "warning" else\n' +
          '\n' +
          'fit_score = (n_good − n_bad) / n_active        # range -1..+1',
        interpretation: '+1 = 5/5 buckets 都对得上；−1 = 全相反；0 = 中性',
        thresholds: '> 0.4 = strong fit；< -0.4 = bad fit',
        code: 'agent/finance/regime/risk.py:regime_fit',
        dashboard_field: 'regime_fit.fit_score',
        caveat: 'sensitivity 来自 strategies.yaml，是子 agent 调研出来的（标记 ⚠ unverified）— 不一定准',
      },
    ],
  },

  // ── 5. Walk-forward + Deflated Sharpe ─────────────────────────
  {
    id: '5',
    title: 'Walk-Forward + Deflated Sharpe Ratio (Phase K1)',
    subtitle: '多重检验校正 — 这是真金白银决策的最后一道关',
    entries: [
      {
        name: 'Walk-Forward Validation (IS/OOS split)',
        citation: 'Pardo (1992) "Design, Testing, and Optimization of Trading Systems"; Kaastra-Boyd (1996)',
        formula:
          '1. sort backtest_results by fingerprint_date\n' +
          '2. is_end = floor(N · 0.80)                   # 80/20 default\n' +
          '3. IS = rows[:is_end]; OOS = rows[is_end:]\n' +
          '4. compute Sharpe on each:\n' +
          '   SR_per_period = mean(rels) / stdev(rels)\n' +
          '   SR_annual = SR_per_period × √(252 / hold_days)\n' +
          '5. report IS-OOS gap',
        thresholds: 'gap > 1.5 = overfit; gap ≈ 0 = robust; OOS < 0 with IS >> 0 = pure overfit',
        interpretation: 'IS Sharpe 高、OOS 低 = 模型只是拟合了 in-sample noise',
        code: 'agent/finance/regime/walk_forward.py:walk_forward_sharpe',
        dashboard_field: 'walk_forward.{is_sharpe_ann, oos_sharpe_ann, is_oos_gap, overfitting_ratio}',
      },
      {
        name: 'Sharpe Ratio (per-period)',
        citation: 'Sharpe (1966) "Mutual Fund Performance", Journal of Business, 39(1)',
        formula:
          'SR = (E[R] − R_f) / σ(R)\n' +
          '我们用 R_f = 0 (per-period basis)，因为 per-30d 的无风险利率 ≈ 0.3% 噪声 < 标的 σ 数倍',
        symbols: 'E[R] = mean realized; σ(R) = stdev; R_f = risk-free rate',
        thresholds: '> 1 good，> 2 excellent (annualized)',
        interpretation: '单位 σ 里换多少超额收益。但对 fat-tail 不友好 — 优先看 Sortino',
        code: 'agent/finance/regime/walk_forward.py:walk_forward_sharpe',
      },
      {
        name: 'Deflated Sharpe Ratio (DSR)',
        citation: 'Bailey & López de Prado (2014) "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality", Journal of Portfolio Management, 40(5), 94–107',
        formula:
          'DSR = Φ(z)\n' +
          '其中 z = (SR_obs − E[max SR | null]) / σ_SR\n' +
          '\n' +
          'expected max SR under null (eq.7):\n' +
          '  E[max SR_N] = σ_SR · ((1 − γ) · Φ⁻¹(1 − 1/N)\n' +
          '                       + γ · Φ⁻¹(1 − 1/(N·e)))\n' +
          '其中 γ ≈ 0.5772 (Euler-Mascheroni)\n' +
          '\n' +
          'SR estimator variance (Mertens 2002, eq.4):\n' +
          '  V[SR] = (1 − γ₃ · SR + (γ₄ − 1)/4 · SR²) / (T − 1)\n' +
          '其中 γ₃ = skewness, γ₄ = kurtosis (Pearson, NOT excess)',
        symbols: 'N = number of trials (我们 N=36 = catalog size); T = OOS sample size; Φ = standard normal CDF',
        interpretation: '"在 N 个候选里挑出 SR_obs 这么高，true SR > 0 的概率"。校正了 multiple testing',
        thresholds: 'DSR > 0.95 = ship; > 0.80 = promising; ≈ 0.50 = noise; < 0.50 = 比随机 null 还差',
        code: 'agent/finance/regime/walk_forward.py:deflated_sharpe',
        dashboard_field: 'walk_forward.deflated_sharpe.{dsr_prob, sr_max_expected, z_score}',
      },
      {
        name: 'Why N=36 trials matters',
        citation: 'Bailey-López de Prado (2014) §3; Harvey-Liu-Zhu (2016) "...and the Cross-Section of Expected Returns"',
        formula:
          'expected max SR ≈ √(2 · ln(N))   (asymptotically)\n' +
          'for N=36: √(2 · ln 36) ≈ 2.68 standard errors',
        interpretation: '36 个候选里挑最佳，纯噪声也会显得"+2.7σ 显著"。这就是 PBO (Probability of Backtest Overfitting) 结构上 > 50% 的原因',
        thresholds: 'DSR < 0.50 ↔ observed SR 比 expected max under null 还低',
      },
    ],
  },

  // ── 6. Backtest validation methods (Phase D) ──────────────────
  {
    id: '6',
    title: 'Backtest Validation Methods (Audit tab)',
    subtitle: '6 种独立验证方法 — Audit tab 的 Backtest Recall + regime_validate.command',
    entries: [
      {
        name: '6.1 Information Coefficient (Spearman 排序相关)',
        citation: 'Spearman (1904) "The proof and measurement of association between two things"; Grinold-Kahn (1999) "Active Portfolio Management" §13',
        formula:
          'IC = Spearman(predicted_score, realized_pnl)\n' +
          '   = Pearson(rank_x, rank_y)\n' +
          '   = 1 − 6 · Σ d² / (n · (n² − 1))    # for non-tied data\n' +
          '其中 d_i = rank(x_i) − rank(y_i)',
        thresholds: 'IC > 0.05 sustained (per-day mean) = real alpha; ≈ 0 = random; < 0 = anti-predictive',
        interpretation: '"模型给的分数排序 vs 真实收益排序 一致吗"。不依赖分布，对 outliers robust',
        code: 'agent/finance/regime/backtest.py:_spearman, recall_summary',
      },
      {
        name: '6.2 Decile Monotonicity',
        citation: 'standard quant practice; Lakonishok-Shleifer-Vishny (1994) decile sorts',
        formula:
          '1. sort all (date, strategy) rows by predicted score\n' +
          '2. split into 10 deciles\n' +
          '3. compute mean(realized) per decile\n' +
          '4. decile_rho = Spearman(decile_idx, mean_realized)',
        thresholds: 'decile_rho > 0.7 = monotonically increasing → real signal；U-shape → memorization；flat → no edge',
        interpretation: '希望最低分 decile 收益最低、最高分 decile 收益最高',
        code: 'agent/finance/regime/backtest.py:_model_summary, validation_report',
      },
      {
        name: '6.3 Long-Short Spread',
        citation: 'Fama-French (1992) factor construction; Sharpe (1966)',
        formula:
          'daily_spread = mean(top decile realized) − mean(bottom decile realized)\n' +
          'spread Sharpe (annualized) = mean(daily_spread) / stdev × √252',
        thresholds: 'Sharpe > 0.5 = good；> 1 = excellent；< 0 = ranking 反向',
        interpretation: '"做多 top 10% / 做空 bottom 10%"的合成组合年化 Sharpe',
        code: 'agent/finance/regime/backtest.py:validation_report',
        caveat: '当前看到的 1.77 Sharpe 是 proxy P&L 伪信号；切到真数据后会大幅下降',
      },
      {
        name: '6.4 Permutation Null Test',
        citation: 'Fisher (1935) "Design of Experiments"; non-parametric hypothesis testing',
        formula:
          '1. shuffle predicted scores 200 次\n' +
          '2. for each shuffle: compute IC\n' +
          '3. p-value = #{shuffled_IC ≥ observed_IC} / 200',
        thresholds: 'p < 0.05 = real signal；p ≥ 0.10 = indistinguishable from random',
        interpretation: '"如果完全没信号，模型分数随机分配，会得到比观察更好的结果的概率"',
        code: 'agent/finance/regime/backtest.py:validation_report (permutation_null)',
      },
      {
        name: '6.5 Regime Stratification',
        citation: 'subgroup analysis (Yates 1934); regime conditioning',
        formula:
          'for each risk_appetite bucket (low/mid/high):\n' +
          '  compute IC on rows where today\'s ra_score in bucket\n' +
          'check if IC stable across buckets',
        thresholds: '所有 bucket IC > 0 = robust；某个 bucket IC < -0.05 = 在该 regime 反向',
        interpretation: '"signal 在不同 regime 下是不是一致" — 防止 only-bull-market alpha',
        code: 'agent/finance/regime/backtest.py:validation_report (regime_stratification)',
      },
      {
        name: '6.6 Within-Strategy IC vs Cross-Strategy IC',
        citation: 'Grinold-Kahn fundamental law: IR = IC · √breadth',
        formula:
          'within-strategy IC: 对每个 strategy 算它自己时间序列的 (predicted, realized) 相关\n' +
          'cross-strategy IC: 对每天，算当天 36 个 strategy 的 (predicted, realized) 排序相关\n' +
          '\n' +
          'if cross-strategy IC ≫ within-strategy IC：\n' +
          '  模型只是"按 strategy 历史均值排序"，没真在用 regime 信号',
        thresholds: 'within ≈ cross = real signal；within ≈ 0, cross > 0 = memorization',
        interpretation: 'v3 当前显示 within=0.008, cross=0.31 → 纯 memorization。这就是为啥 v3 没 ship',
        code: 'agent/finance/regime/scorer_v3.py:diagnose_v3',
        caveat: 'Phase G 已确认 v3 是 memorization；v3 没 ship 到 lattice-fit endpoint',
      },
    ],
  },

  // ── 7. Data quality classification ────────────────────────────
  {
    id: '7',
    title: 'Data Quality — REAL vs PROXY 分类',
    subtitle: '决定哪些 strategy 的 backtest 数字真金白银可用',
    entries: [
      {
        name: 'REAL data path',
        formula:
          'is_real_data(strategy) = (payoff_class ∈ REAL_PAYOFF_CLASSES)\n' +
          '\n' +
          'REAL_PAYOFF_CLASSES = {\n' +
          '  "dca", "buy_and_hold",\n' +
          '  "lazy_portfolio_three_fund", "target_date_fund",\n' +
          '  "permanent_portfolio", "dollar_cost_averaging_index",\n' +
          '  "dividend_growth_etf",\n' +
          '  "low_volatility_factor", "value_factor",\n' +
          '}',
        interpretation: '这些 strategy 的"realized P&L" = anchor 资产真实 forward return。你买入持有就这个收益',
        code: 'agent/finance/regime/risk.py:REAL_PAYOFF_CLASSES, is_real_data',
        dashboard_field: 'data_quality = "real" 的 9 个长持类',
      },
      {
        name: 'PROXY data path',
        formula:
          '其他全部 payoff_class:\n' +
          '  options (covered_call, iron_condor, long_vol, ...)\n' +
          '  active trading (momentum, mean_reversion, ...)\n' +
          '  hedges (tail_risk_hedge, bear_market_hedge)\n' +
          '  events (event_fade, event_drift)\n' +
          '\n' +
          '_proxy_pnl(payoff_class, forward_return, hold_days) → 简化估值',
        interpretation: '需要真实期权链 / 真实成交价 / 真实 IV 数据才能算。当前 proxy 不可信',
        code: 'agent/finance/regime/backtest.py:_proxy_pnl',
        dashboard_field: 'data_quality = "proxy_only" 的 27 个 (期权/动量/对冲/事件)',
        caveat: 'PROXY 行只显示 regime fit；其他风险维度全部隐藏。需要 paper trade 几个月才能填充真数据',
      },
    ],
  },

  // ── 8. Anchors used per strategy ──────────────────────────────
  {
    id: '8',
    title: 'Anchor Symbols — 每个 strategy 用哪个标的算 forward return',
    subtitle: '决定 backtest_results.realized_pnl 是从谁的价格算的',
    entries: [
      {
        name: 'Per-strategy anchor mapping',
        formula:
          'priority:\n' +
          '  1. strategy id 在 OVERRIDES 表里 → 用 override\n' +
          '  2. asset_class == "crypto" → "BTC-USD"\n' +
          '  3. default → "SPY"\n' +
          '\n' +
          'overrides:\n' +
          '  btc_dca → BTC-USD\n' +
          '  eth_dca → ETH-USD\n' +
          '  mchi_long_hold → MCHI\n' +
          '  kweb_momentum → KWEB\n' +
          '  fxi_china_vol / fxi_options_china_vol → FXI\n' +
          '  qqq_iron_condor → QQQ\n' +
          '  spy_iron_condor / spy_long_vol → SPY\n' +
          '  intl_developed_etf → VEA\n' +
          '  small_cap_value_etf → AVUV\n' +
          '  low_volatility_etf → USMV\n' +
          '  value_factor_etf → VLUE\n' +
          '  quality_factor_etf → QUAL\n' +
          '  dividend_growth_etf → DGRO\n' +
          '  total_market_index_dca → VTI',
        code: 'agent/finance/regime/backtest.py:_anchor_symbol',
        caveat: 'For PROXY strategies, anchor return is NOT the strategy return — proxy 公式才是。但 anchor 给一个"市场环境"参考',
      },
      {
        name: 'Forward return formula',
        formula:
          'forward_return(symbol, start_date, hold_days):\n' +
          '  e0 = close at-or-after start_date\n' +
          '  e1 = close at-or-after start_date + hold_days\n' +
          '  return e1 / e0 − 1',
        interpretation: '简单点对点收益 — 不含分红、不含借贷成本、不含 slippage',
        code: 'agent/finance/regime/backtest.py:_forward_return',
        caveat: '没有分红再投 — 对 dividend_growth_etf 会低估 ~1.5-3% / 年',
      },
    ],
  },
]
