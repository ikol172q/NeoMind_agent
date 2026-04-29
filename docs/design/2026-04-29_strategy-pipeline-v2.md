# Strategy Distillation Pipeline — v2 Implementation Blueprint

**Date**: 2026-04-29  
**Supersedes**: `2026-04-29_strategy-distillation-pipeline.md` (v1, the
diagnosis doc) — this v2 incorporates the user's answers to A-F and is
the doc to implement against.

---

## 0. Goals locked in

> **每个 strategy 推荐都是 1 个端到端可追溯的科学过程**，从 raw 市场数据（原始字节）→ 多层归类总结（lattice）→ 5-维 regime 指纹 → 解析或经验的期望效用 → 约束过滤 → 组合选择，最终落到 Strategies tab 的一张可点击卡片上。**点任何一个数字都能往回看到它是怎么算出来的、用了哪条原始数据。**

**Non-goals (v2)**:
- 实时期权链接入（先用 RV proxy；标记 TODO）
- 实盘下单（继续 paper trading）
- 跨账户 / 多用户支持
- 港股 / A 股扩展（先美股）

---

## 1. The 5 regime buckets (替代散布的 20 维)

每个 bucket 是 0–100 分数 + 方向（↑/↓ 表示是高侧还是低侧）。每个 bucket 由 3-4 个 component metrics 平均而来。**在 UI 默认显示 3-month percentile**，hover 能切换到 1w/1m/3m/6m/1y 五个窗口对比。

### 1.1 🌡️ Risk Appetite （市场情绪）
**一句话**: 今天市场是恐慌还是贪婪？  
**决定**: 保守 vs 激进策略的偏向。

| Component | 数据源 | 公式 |
|---|---|---|
| VIX 百分位 | `^VIX` daily close | `pct_rank(VIX, window)` |
| Put/Call ratio | CBOE PCRATIO via yfinance proxy | `pct_rank(PCR, window)` |
| AAII 牛熊调查 | AAII weekly survey (manual feed for now, mark TODO) | `bull% - bear%` |
| SPY RSI(14) | `SPY` daily close | `100 - 100/(1+RS)` |

**展示**: 红 (恐慌, score < 30) / 黄 (中性, 30-70) / 绿 (贪婪, > 70) + 箭头方向。

### 1.2 📈 Volatility Regime （波动幅度）
**一句话**: 股票每天跳多大？  
**决定**: 卖期权（高 IV）vs 买期权（低 IV）vs 仓位规模缩放。

| Component | 数据源 | 公式 |
|---|---|---|
| SPY 30d RV 百分位 | `SPY` close → log returns | `pct_rank(stdev_30d × √252)` |
| VIX-RV gap | VIX − SPY 30d RV | 直接相减，正值代表 IV 偏贵 |
| Vol term slope | VIX9D − VIX | 近 < 远 = contango (低风险预期), 反之 = backwardation |
| QQQ 60d RV | `QQQ` close → log returns | 类似 SPY |

**展示**: 0–100 + "压缩 / 拉伸" 标签。

**TODO**: 用真实 IV 替代 SPY 30d RV proxy。需 ORATS / IBKR / Tradier feed。

### 1.3 🌐 Breadth （市场广度）
**一句话**: 是少数大盘股领涨，还是普涨？  
**决定**: 指数策略 vs 个股策略 vs 板块轮动。

| Component | 数据源 | 公式 |
|---|---|---|
| % S&P 500 above 50d MA | Tier 3 全部成分股 | `count(close > MA50) / 503` |
| Top10 / Bottom10 5d return ratio | S&P 500 5-day returns | `mean(top10) / |mean(bottom10)|` |
| Sector dispersion | 11 个 sector ETF 5d returns | `stdev(sector_5d)` |
| Adv/Decl line | NYSE adv−decl daily (yfinance) | 累计差分 |

**展示**: 0–100 + "窄 / 宽" 标签。

### 1.4 📅 Event Density （事件密度）
**一句话**: 未来几天有多少大事件？  
**决定**: 卖期权 / hedge / 套利策略的时机。

| Component | 数据源 | 公式 |
|---|---|---|
| Earnings count next 5d | yfinance earnings calendar (Tier 1 + S&P 500) | 简单计数 |
| Days to next FOMC | FRED economic calendar | 整数 |
| Days to next OPEX | 月第三个周五（确定性） | 整数 |
| Days to next major holiday | NYSE calendar | 整数 |

**展示**: 0–100 + 列出未来 5 天具体事件清单。

### 1.5 💸 Flow （资金流向）
**一句话**: 钱往哪个方向跑？  
**决定**: sector rotation、跨资产配置。

| Component | 数据源 | 公式 |
|---|---|---|
| 10y-2y yield slope | `^TNX` − `^TYX` daily | 直接相减 |
| USD index | `DX-Y.NYB` / `UUP` | pct_rank |
| Sector relative strength | 11 sector ETFs vs SPY 30d | 排序 |
| HYG OAS | `HYG` yield - `IEF` yield | 直接相减 |

**展示**: 0–100 + 箭头方向 (risk-on / risk-off)。

---

## 2. 三层 Watchlist

### Tier 1: Personal watchlist
- **现在**: 6 ticker (AAPL/AMD/ARM/META/MSFT/TSLA)
- **可改**: Settings → Watchlist 编辑
- **在 UI**: Strategies tab 给出针对这些 ticker 的具体建议（covered call on AAPL 等）

### Tier 2: Market anchors
- **15 个 ticker**: SPY / QQQ / IWM / DIA + ^VIX + ^VIX9D + ^TNX + ^TYX + DX-Y.NYB + HYG + IEF + GLD + USO + XLE / XLF / XLK / XLY / XLP / XLV / XLI / XLB / XLU / XLRE / XLC (11 sector ETFs)
- **用户看不到列表**（隐藏在 regime 计算后台），但每个 regime metric 旁有 ❓ 能 drill 看到「这个 metric 的输入是 SPY 30d close，最新拉取时间是 X」
- **目的**: 算 regime fingerprint 的输入

### Tier 3: Breadth pool
- **503 个 ticker**: S&P 500 全部成分股
- **完全后台**，用户根本看不到
- **目的**: 算 breadth、sector dispersion、Top10/Bottom10
- **更新**: 每天 ~30 秒 yfinance bulk pull

---

## 3. SQLite tables (新增)

### 3.1 `raw_market_data`
```sql
CREATE TABLE raw_market_data (
    symbol         TEXT NOT NULL,
    trade_date     TEXT NOT NULL,            -- 'YYYY-MM-DD' UTC
    open           REAL,
    high           REAL,
    low            REAL,
    close          REAL,
    adjusted_close REAL,
    volume         INTEGER,
    source         TEXT NOT NULL,            -- 'yfinance' / 'manual' / 'alpha_vantage'
    fetched_at     TEXT NOT NULL,
    raw_blob_sha   TEXT,                     -- raw://<sha256> if from RawStore
    PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX idx_rmd_date ON raw_market_data(trade_date);
```

### 3.2 `regime_fingerprints`
每天 1 行，永久保留。用于 k-NN 历史相似日查找 + UI 展示。

```sql
CREATE TABLE regime_fingerprints (
    fingerprint_date TEXT PRIMARY KEY,    -- 'YYYY-MM-DD' UTC
    -- 5 buckets (0-100 scores)
    risk_appetite_score      REAL,
    volatility_regime_score  REAL,
    breadth_score            REAL,
    event_density_score      REAL,
    flow_score               REAL,
    -- 5 windows for each component (jsonb-style)
    components_json TEXT,                  -- {"vix_pct_rank": {"1w": 0.35, "1m": 0.42, ...}, ...}
    -- raw input refs (for traceability)
    inputs_json     TEXT,                  -- {"vix_close": 14.2, "spy_close": 478.5, ...}
    sources_json    TEXT,                  -- {"vix": "yfinance@2026-04-29T20:30Z", ...}
    computed_at     TEXT NOT NULL
);
```

### 3.3 `decision_traces`
每次 strategy 推荐 1 行。审计入口。

```sql
CREATE TABLE decision_traces (
    trace_id           TEXT PRIMARY KEY,        -- uuid
    fingerprint_date   TEXT NOT NULL,
    strategy_id        TEXT NOT NULL,
    score              REAL NOT NULL,           -- final posterior score 0-10
    rank               INTEGER NOT NULL,        -- 1 = primary, 2-8 = alternatives
    -- decomposition
    breakdown_json     TEXT NOT NULL,           -- {"E_pnl": 245, "P_profit": 0.71, "VaR_95": -2050, ...}
    formula            TEXT NOT NULL,           -- "closed_form_BS" or "empirical_kNN" or "hybrid_β=0.62"
    -- traceability
    lattice_node_refs  TEXT NOT NULL,           -- ["L1:obs_xxx", "L2:theme_yyy", ...]
    knn_neighbor_dates TEXT,                    -- ["2024-11-03", "2024-12-15", ...] for empirical
    constraint_check_json TEXT NOT NULL,        -- {"min_capital": "pass", "PDT": "pass", "options_level": "warn", ...}
    portfolio_fit_json TEXT,                    -- {"delta_after": -0.30, "vega_after": -0.18, ...}
    computed_at        TEXT NOT NULL,
    FOREIGN KEY (fingerprint_date) REFERENCES regime_fingerprints(fingerprint_date)
);
CREATE INDEX idx_dt_date ON decision_traces(fingerprint_date);
CREATE INDEX idx_dt_strategy ON decision_traces(strategy_id);
```

### 3.4 `knn_lookups`
每次 Bayesian k-NN 查找的邻居记录。

```sql
CREATE TABLE knn_lookups (
    lookup_id          TEXT PRIMARY KEY,
    target_date        TEXT NOT NULL,
    neighbor_date      TEXT NOT NULL,
    similarity_score   REAL NOT NULL,           -- cosine / Mahalanobis (0-1)
    weight_in_prior    REAL NOT NULL,           -- normalized weight after softmax
    used_for_strategy  TEXT NOT NULL,
    FOREIGN KEY (target_date) REFERENCES regime_fingerprints(fingerprint_date),
    FOREIGN KEY (neighbor_date) REFERENCES regime_fingerprints(fingerprint_date)
);
CREATE INDEX idx_knn_target ON knn_lookups(target_date, used_for_strategy);
```

---

## 4. Strategy YAML quantitative_profile (Step C)

每个 `docs/strategies/<id>.md` 对应的 yaml entry 加：

```yaml
quantitative_profile:
  payoff_class: covered_call | iron_condor | vertical_spread | DCA | buy_and_hold | ...
  greeks_template:
    delta: -0.4    # 标准 1-contract 方向暴露
    theta: 0.05    # 每日衰减 USD/contract
    vega:  -0.18   # IV 1% 变化下的 PnL USD
    gamma: -0.02
  expected_hold_days: 30
  breakeven_RV_pctile: 0.50   # 当 RV 低于这个 pctile 时策略获利
  # 5 regime bucket 偏好（[-1, 1] 区间）
  regime_sensitivity:
    risk_appetite:     -0.3   # 喜欢中低风险偏好（卖权类）
    volatility_regime: +0.6   # 喜欢高 IV
    breadth:           +0.1   # 略好的 breadth
    event_density:     -0.4   # 不喜欢密集事件期
    flow:               0.0   # 中性
  payoff_function: cc_short_call_long_underlying  # 引用 lib/payoffs.py
  monte_carlo_template_id: cc_atm_30d
```

**填这些** = Step C 的全部内容。36 个 strategy 大概 1 天工作量（参考 Hull 教科书 + Investopedia + 各 strategy 的 .md 现有描述）。

---

## 5. Scoring 算法（Step D）

```python
def expected_utility(strategy_profile, regime_vector, account_state):
    # ── 1) 解析 payoff 分布 ────────────────────────────
    p_underlying = forecast_distribution(
        regime_vector, 
        horizon=strategy_profile["expected_hold_days"],
    )  # Black-Scholes lognormal calibrated by IV-or-RV-proxy
    
    payoff_pdf = analytic_payoff_distribution(
        strategy_profile["payoff_function"],
        underlying_dist=p_underlying,
        greeks=strategy_profile["greeks_template"],
    )
    
    # ── 2) 期望效用分量 ─────────────────────────────────
    E_pnl    = integrate(payoff_pdf, x → x · p(x))
    P_profit = integrate(payoff_pdf, x | x > 0)
    VaR_95   = inverse_cdf(payoff_pdf, 0.05)
    expected_max_dd = regime_conditional_drawdown(regime_vector, payoff_pdf)
    
    # ── 3) Regime 偏好 dot product ─────────────────────
    regime_match = (
        strategy_profile["regime_sensitivity"]["risk_appetite"]     * normalize(regime_vector.risk_appetite_score) +
        strategy_profile["regime_sensitivity"]["volatility_regime"] * normalize(regime_vector.volatility_regime_score) +
        strategy_profile["regime_sensitivity"]["breadth"]           * normalize(regime_vector.breadth_score) +
        strategy_profile["regime_sensitivity"]["event_density"]     * normalize(regime_vector.event_density_score) +
        strategy_profile["regime_sensitivity"]["flow"]              * normalize(regime_vector.flow_score)
    )  # ∈ [-5, 5]
    
    # ── 4) 多目标 utility ──────────────────────────────
    # 权重来自 user prefs (Settings) 或默认
    utility = (
        w_pnl       * standardize(E_pnl) +
        w_profit    * P_profit +
        w_drawdown  * (1 - max(0, expected_max_dd / account_state.max_drawdown_tolerance)) +
        w_regime    * regime_match
    )
    
    return {
        "score": clip(utility * 10 / 5, 0, 10),  # 标准化到 0-10
        "breakdown": {
            "E_pnl": E_pnl, "P_profit": P_profit, "VaR_95": VaR_95,
            "expected_max_dd": expected_max_dd, "regime_match": regime_match,
        },
        "formula": "closed_form_BS_v1",
    }
```

---

## 6. Bayesian shrinkage 用 k-NN（Step E）

```python
def posterior_score(strategy_id, today_regime, model_score):
    # 1. 找历史相似日
    neighbors = sql("""
        SELECT fingerprint_date,
               mahalanobis_distance(components, :today_regime) AS dist
        FROM regime_fingerprints
        WHERE fingerprint_date < :today
        ORDER BY dist ASC
        LIMIT 30
    """)
    similar = [n for n in neighbors if n.dist < ε_threshold]
    
    if len(similar) < 3:
        return model_score, "model_only_no_history"
    
    # 2. 从历史 decision_traces 拉那些天对应 strategy 的 P&L 实绩
    historical_pnls = sql("""
        SELECT fingerprint_date, breakdown_json->>'realized_pnl_30d' AS pnl
        FROM decision_traces
        WHERE strategy_id = :sid
          AND fingerprint_date IN :similar_dates
    """)
    
    if not historical_pnls:
        return model_score, "model_only_no_realized_pnl"
    
    # 3. 加权平均（按相似度权重）
    weights = softmax(-distances / temperature)
    empirical_score = weighted_mean(historical_pnls, weights)
    
    # 4. Bayesian shrinkage — 邻居越多 / 越接近，越信任经验值
    n = len(similar)
    avg_dist = mean(distances)
    β = 1 / (1 + n / 5 * (1 - avg_dist))   # n=5 + 完美匹配 → β = 0.5
    
    posterior = β * model_score + (1 - β) * empirical_score
    
    # 5. 写 knn_lookups 留痕
    insert_knn_lookups(target=today, neighbors=similar, weights=weights)
    
    return posterior, f"hybrid_β={β:.2f}_n={n}"
```

**注意**: backtest harness 是写 `realized_pnl_30d` 进 `decision_traces` 的来源 — 这是 Step E 的**长杆**。在它出来前，empirical fallback 是 0，β=1。

---

## 7. 约束层（Step E 之后）

硬过滤，**下面任一条违反就 drop**：

| 约束 | 条件 | 数据源 |
|---|---|---|
| min_capital | `strategy.min_capital > account.equity` | account state |
| PDT | `strategy.PDT_relevant AND account.equity < 25000 AND account.PDT_count > 2` | trades 表 |
| wash_sale | `strategy.wash_sale_risk='high' AND has_recent_loss(strategy.target_underlyings, days=30)` | tax_lots 表 |
| options_level | `strategy.required_options_level > user.options_level` | Settings |
| holding_period | `strategy.min_hold_days > today + horizon_window` | calendar |

每个约束的检查结果都写到 `decision_traces.constraint_check_json`，UI 卡片上显示「✓ 4/5 通过 · ⚠ 1 警告」，点开看哪条警告。

---

## 8. 组合选择（Step F）

输入: 通过约束层的策略 + 它们的 score
输出: **Top 1 主推 + 3-8 个替代**（按权重排序）

```python
def select_portfolio(scored_strategies, current_portfolio, k_top=1, k_alts=8):
    # MMR (Maximal Marginal Relevance) 选 top + alternatives
    selected = []
    
    # 1. Top 1: 直接选 score 最高的
    best = max(scored_strategies, key=lambda s: s.score)
    selected.append(best)
    
    # 2. Alternatives: 每次选 score - λ * max_similarity_to_already_selected
    remaining = scored_strategies - {best}
    while len(selected) < k_top + k_alts and remaining:
        next_pick = max(remaining, key=lambda s:
            s.score - λ * max(strategy_similarity(s, t) for t in selected)
        )
        selected.append(next_pick)
        remaining.remove(next_pick)
    
    # 3. 给每个加 alternative_weight (相对于 top 的）
    for i, s in enumerate(selected):
        s.rank = i + 1
        s.alternative_weight = s.score / selected[0].score  # 0-1, top is always 1
    
    return selected
```

`strategy_similarity` 基于 `payoff_class` + `regime_sensitivity` cosine + `target_underlying` overlap。两个 covered call 类策略相似度高，就不会同时进 top 5。

---

## 9. UI 整合

### 9.1 Research tab — Lattice diagram 加 L0 锚（regime fingerprint）

```
[Regime fingerprint at top — 5 colored bars]
🌡️ Risk Appetite  ████████░░  72  (greed-side, ↑)
📈 Volatility     ████░░░░░░  41  (compressed)
🌐 Breadth        ███████░░░  68  (broad)
📅 Event Density  ██████░░░░  55  (3 earnings in 5d)
💸 Flow           █████████░  80  (risk-on, USD weak)

[Click any bar → expand 3-4 components + 5 windows + raw data link]

──── L0 SOURCE ──────  
[anomaly detector] [chart] [earnings calendar] [sector heatmap] [vix widget] ...

──── L1 OBS ──────
22 atomic observations (each clickable to see raw data)

──── L1.5 / L2 / L3 ──── 
(unchanged from current)
```

### 9.2 Strategies tab — Card 上的 traceback drawer

每张卡片上 fit 数字旁边加 ❓ 图标，点击 → 抽屉滑出：

```
covered_call_etf — fit 7.2 / 10
─────────────────────────────────────
posterior_score: 7.2
  formula: hybrid_β=0.62  (n=12 historical neighbors)
  
breakdown:
  E[PnL]      $245 / 30d            ← 点 → 看 B-S 公式 + IV 假设
  P(profit)   71%
  VaR_95      −$2050
  regime_match +0.42                ← 点 → 看 sensitivity dot product
  
inputs (lattice trace):
  L0 raw      [SPY close: 478.5] [VIX: 14.2] [SPY 30d RV: 0.18]
              ↓ 点击任一 → Data Lake → raw://<sha256> 验证
  L1 obs      4 个 obs               ← 点 → Research tab 高亮那 4 个
  L2 themes   [Earnings risk] [Macro regime]   ← 点 → Research tab 高亮
  
historical neighbors (k-NN):
  2024-11-03 (sim 0.94) → 这个策略当时 P&L: +$210
  2024-12-15 (sim 0.91) → +$180
  2025-01-22 (sim 0.88) → +$245
  ...其余 9 天 (展开)    ← 点 → Data Lake 看那天完整 lattice
  
constraint check:
  ✓ min_capital $5000 ≤ $98,632
  ✓ PDT_relevant = false
  ✓ wash_sale_risk = low (no recent loss in SPY)
  ⚠ options_level = unknown — 在 Settings 设置后准确
  
portfolio fit:
  current  delta: −0.12  vega: −0.05  theta: +0.08
  +after this: delta: −0.30  vega: −0.18  theta: +0.13
  ✓ 全部在 budget 内
  
alternatives (会被这个 top 1 显示后)：
  rank 2 cash_secured_put_etf  weight 0.92    ← 类似但不同 underlyings
  rank 3 vertical_bull_put_spread  weight 0.78
  ...
```

每一行都是 clickable，跳到对应的 raw / lattice / database row。

### 9.3 Audit tab — 加 sub-pane "Decision traces"

在现有 "PAST RUNS (SCHEDULER + MANUAL)" 下面加一个 collapsible sub-pane：

```
DECISION TRACES (3,628 over 252 days)
filter: date / strategy_id / formula
─────────────────────────────────────────
2026-04-29 covered_call_etf rank=1 score=7.2 formula=hybrid_β=0.62
2026-04-29 cash_secured_put_etf rank=2 score=6.6 formula=hybrid_β=0.62
... (展开任一行 → 完整 breakdown_json + 跳到 Strategies tab 看卡片)
```

### 9.4 Settings tab — "Investment preferences" 4 题问卷

新区块，可跳过用默认。

---

## 10. 默认配置（你不答问卷的话）

```yaml
default_user_prefs:
  options_level: 0           # 不允许期权
  max_drawdown_tolerance: 0.15
  income_vs_growth: 0.5      # balanced
  max_position_concentration: 0.25
  utility_weights:
    w_pnl: 1.0
    w_profit: 0.5
    w_drawdown: 1.5          # beginner: 厌恶 drawdown 强
    w_regime: 0.8
  difficulty_filter:
    show_difficulty_le: 2    # 默认只显示 ★★ 及以下
  # 用户可以手动 toggle 看全部 36
```

新手 onboard 默认行为：
- 36 个策略筛掉 → 6-8 个适合的
- Strategies tab 顶部「显示了 8/36 适合你的策略 · [Show all 36]」按钮
- 点「Show all 36」→ 每个超难卡片右上角 ⚠「这个对你太难，先做完前面再回来」

---

## 11. TODO 清单（不偷懒，明确标记）

| TODO | Why | 触发条件 | 替代方案 |
|---|---|---|---|
| **真实 IV feed** | 现在用 SPY 30d RV proxy，对短期 IV 误差 5-15% | 用户升级到付费数据 | ORATS / IBKR / Tradier |
| **AAII 牛熊调查** | 现在没有自动 feed | 找到稳定 RSS / scraping | Manual weekly entry |
| **Backtest harness** | 现在 `realized_pnl_30d` 是 0 → β=1 → 没有 empirical prior | Step E 完整实现 | 简单的 vectorized bar replay |
| **盘中数据** | 现在只 daily | 用户需要日内决策 | yfinance 1m bars (15min delay)  |
| **A股 / 港股扩展** | 现在只美股 | 用户明确需求 | yfinance + akshare |
| **多账户 / 多用户** | 单一用户 / 单账户 | 真实部署 | Auth + per-user state |

每个 TODO 在 UI 触发的地方都加 ⚠️ 小标记，hover 看上面的解释。

---

## 12. 实施顺序（dependencies）

```
                  Step 1: yfinance ingestion + raw_market_data
                         (Tier 2 + 3, backfill 1 year)
                                    │
                                    ▼
                  Step 2: regime_fingerprint computation 
                         (5 buckets × 5 windows + components)
                                    │
                                    ▼
              Step 3: backfill 252 历史 fingerprints  
                     (一次性 yfinance + compute)
                                    │
                  ┌─────────────────┴────────────────┐
                  ▼                                   ▼
     Step 4: UI surface          Step 5: quantitative_profile
            regime in Research          (yaml for 36 strategies)
                  │                                   │
                  └────────────┬──────────────────────┘
                               ▼
                  Step 6: closed-form scorer
                         (replaces _score_strategy)
                               │
                               ▼
                  Step 7: 约束层 + 组合选择
                         (top 1 + 3-8 alternatives)
                               │
                               ▼
                  Step 8: decision_traces + UI traceback
                         (drawer on each card)
                               │
                               ▼
                  Step 9: k-NN Bayesian shrinkage 
                         (long pole — needs backtest harness)
                               │
                               ▼
                  Step 10: Settings 4-question onboarding
                          + difficulty filter UI
```

Step 1-3 是单一日工作（yfinance 一次跑数小时内完成 backfill）。Step 4-8 是核心新功能。Step 9-10 是 polish。

---

## 13. Acceptance criteria — 怎么知道做对了

每个 step 完成时验证：

- **Step 1-2**: SQL `SELECT * FROM regime_fingerprints WHERE fingerprint_date = '2026-04-29'` 返回 5 个 score + components。
- **Step 3**: SQL `SELECT count(*) FROM regime_fingerprints` ≥ 252。  
- **Step 4**: Research tab 看到 5 个 colored bars，2026-04-23 和 2026-04-28 的数字真的不同。
- **Step 5**: 36 个 yaml 都有 quantitative_profile 块。
- **Step 6**: 切日期，Strategies tab 卡片 fit 数字真的变（不只是因为没数据）。
- **Step 7**: Top 1 + 3-8 alternatives 是不同 payoff_class 的（不全是短 vol）。
- **Step 8**: 卡片点 ❓ 图标 → drawer 显示完整 breakdown + 每个数字跳转生效。
- **Step 9**: Audit → decision_traces 看到 hybrid_β=0.X 而不是 model_only。
- **Step 10**: 答 4 题 → 推荐显著变化（看到不同的 top 1）。

---

## 14. 已锁定的设计选择（不再改）

来自用户 A-F 答复：

- A: 5 个百分位窗口（1w/1m/3m/6m/1y）UI 全显，默认 3m 选中
- B: top 1 + 3-8 alternatives 按 alternative_weight 排序
- C: SPY 30d RV 当 IV proxy（标记 TODO，等付费数据升级）
- D: 1 年 yfinance backfill (~5 min, ~50 MB)
- E: 默认稳健配置 + 4 题 opt-in 问卷
- F: 默认按用户 level 过滤难度，可手动切回 36 全开

---

## 15. 实施期间的硬测试规则（用户明确要求）

**每个 UI-touching commit，必须在浏览器里像真用户一样跑完一轮**才算 done:

1. **不能只跑 tsc / Python ast — 必须 rebuild SPA + 重启 uvicorn + 浏览器手动验**
2. **像真用户一样点击**:
   - 切换 Today / Single Day / Range scope
   - 切日期到至少 2 个不同的过去日期对比
   - 切 Difficulty filter 1★ / 3★ / 5★
   - 切 Sort 选项（today_fit / horizon / difficulty_asc / ...）
   - 点 ↻ fresh，等完成
   - 点 fin badge / check / budgets popover, click-away 关闭
   - 点 Strategy 卡片 expand → 看 traceback drawer 的每个 clickable 字段
3. **跨日期对比**: 选 2026-04-23 vs 2026-04-28，**top 1 推荐必须不同**（或者 score 必须有可见差异）。如果还一样 = bug 没修干净。
4. **跨权限对比**: 切 options_level 0 vs 3，可见的策略数量必须变化。
5. **Audit traceability**: 推一个新 decision，立刻去 Audit tab → decision_traces 找到刚才那行，breakdown_json 字段全要有内容。
6. **数据真实性 spot check**: 任意一张卡片，点开 ❓ → "raw inputs" 行 → "SPY close 478.5" → 跳到 Data Lake 找到这条 row → fetched_at 时间合理。

**违反规则的反例（之前犯过）**:
- ❌ "tsc 通过 + commit 推 PR" — 没真的开浏览器
- ❌ "看一眼 screenshot 就说工作了" — 没切日期 / 没点 filter
- ❌ "API 返回 200 就当对" — 没看 UI 渲染
- ❌ "只测了一个日期就过了" — 没做 cross-day diff

**写 Acceptance criteria 时永远是「在浏览器里看到 X」而不是「API 返回 Y」**。

---

## 实施承诺

我从 Step 1 开始按顺序做。每个 step 完成 commit 一次，UI surface（Step 4 起）每次都拉到 browser 真测一遍 (cross-day diff 真的视觉化看到才算 done)。

不再有"你看不到差异"的兜底借口 — 每个 step 都有上面的 acceptance criteria。
