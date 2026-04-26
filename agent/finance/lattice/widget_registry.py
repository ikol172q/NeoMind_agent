"""L0 widget registry — controlled vocabulary for the lattice.

The single source of truth for "what data sources can a strategy
declare it needs?".

Every entry in ``docs/strategies/strategies.yaml``'s
``data_requirements`` field MUST reference a widget id listed here.
This makes the catalog ↔ lattice mapping bidirectional and auditable:

  forward: strategy.data_requirements → [widget_id, ...]
  reverse: widget.id → [strategy_id, ...]  (computed from forward)

Widgets are tagged with one of three statuses:

  "available"  — actively emitting L1 observations into the lattice.
                 The lattice's graph viewer will show this widget as
                 a connected L0 node when build_observations runs.

  "planned"    — referenced by ≥1 catalog strategy but no generator
                 currently emits obs from it. This is a *known gap*:
                 the strategy is documented but the lattice cannot
                 actually power it. UI surfaces this as "⚠ widget
                 not yet implemented".

  "deprecated" — was emitting, no longer is. Strategies still
                 referencing this should be migrated.

Adding a widget:
  1. Add an entry below
  2. Implement the generator (or mark planned)
  3. CI check at startup validates strategies.yaml references
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Status enum, kept as plain strings (not Enum) so YAML manual entry
# stays readable.
STATUS_AVAILABLE = "available"
STATUS_PLANNED = "planned"
STATUS_DEPRECATED = "deprecated"


# ── Registry ─────────────────────────────────────────────────────────


WIDGET_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ──── 现有 (10) — 已经在 emit L1 obs ────

    "chart": {
        "id": "chart",
        "label_en": "Chart (price / technical)",
        "label_zh": "图表（价格 / 技术指标）",
        "status": STATUS_AVAILABLE,
        "fields": ["range_pos_20d_pct", "rsi14", "return_5d_pct",
                   "sma20", "ema20", "bb", "macd"],
        "produces_tags": [
            "technical:near_52w_high", "technical:near_52w_low",
            "technical:overbought", "technical:oversold",
            "technical:breakout", "technical:breakdown",
            "technical:trend_up", "technical:trend_down",
        ],
        "source_module": "agent.finance.lattice.observations.gen_technical_signals",
        "description": "Daily OHLCV-derived signals: RSI, range position, returns, breakouts. The default L0 widget for any technical strategy.",
    },
    "earnings": {
        "id": "earnings",
        "label_en": "Earnings calendar",
        "label_zh": "财报日历",
        "status": STATUS_AVAILABLE,
        "fields": ["days_until", "atm_iv_pct"],
        "produces_tags": ["risk:earnings", "catalyst:earnings", "timescale:short"],
        "source_module": "agent.finance.lattice.observations.gen_earnings_signals",
        "description": "Earnings event proximity + ATM IV around earnings (powers earnings-drift, covered-call-around-earnings, etc.).",
    },
    "portfolio": {
        "id": "portfolio",
        "label_en": "Portfolio positions",
        "label_zh": "持仓",
        "status": STATUS_AVAILABLE,
        "fields": ["unrealized_pnl_pct", "total_pnl", "quantity"],
        "produces_tags": ["pnl:positive", "pnl:negative", "pnl:large_loss",
                          "pnl:large_gain", "risk:drawdown", "risk:concentration"],
        "source_module": "agent.finance.lattice.observations.gen_portfolio_signals",
        "description": "Open position P&L, drawdown thresholds, concentration warnings.",
    },
    "sectors": {
        "id": "sectors",
        "label_en": "Sector heatmap",
        "label_zh": "行业热力",
        "status": STATUS_AVAILABLE,
        "fields": ["change_pct"],
        "produces_tags": ["regime:rotation"],
        "source_module": "agent.finance.lattice.observations.gen_sector_signals",
        "description": "Per-sector daily / weekly change, basis for rotation strategies.",
    },
    "sentiment": {
        "id": "sentiment",
        "label_en": "Market regime",
        "label_zh": "市场体制",
        "status": STATUS_AVAILABLE,
        "fields": ["composite_score", "components.vix", "components.breadth"],
        "produces_tags": ["regime:vix", "regime:breadth", "regime:sentiment"],
        "source_module": "agent.finance.lattice.observations.gen_sentiment_signals",
        "description": "VIX, breadth, fear/greed composite — macro regime context.",
    },
    "anomalies": {
        "id": "anomalies",
        "label_en": "Anomaly detector",
        "label_zh": "异常检测器",
        "status": STATUS_AVAILABLE,
        "fields": ["kind", "message"],
        "produces_tags": ["risk:earnings", "technical:near_52w_high",
                          "technical:oversold", "regime:rotation"],
        "source_module": "agent.finance.lattice.observations.gen_anomaly_signals",
        "description": "Cross-cutting flag store: 'IV rich into earnings', 'oversold watch', etc. Aggregates across other widgets.",
    },
    "news": {
        "id": "news",
        "label_en": "News feed",
        "label_zh": "新闻",
        "status": STATUS_AVAILABLE,
        "fields": ["title", "summary", "salience"],
        "produces_tags": ["catalyst:regulatory", "catalyst:product",
                          "catalyst:merger", "catalyst:data", "catalyst:fed"],
        "source_module": "agent.finance.lattice.observations.gen_news_signals",
        "description": "Salience-scored news: regulatory, M&A, FDA, Fed, product launches.",
    },
    "fin_db.wash_sale_detector": {
        "id": "fin_db.wash_sale_detector",
        "label_en": "Wash sale detector",
        "label_zh": "Wash sale 检测器",
        "status": STATUS_AVAILABLE,
        "fields": ["disallowed_loss", "days_between"],
        "produces_tags": ["risk:wash_sale", "compliance:tax_inefficiency",
                          "pnl:negative"],
        "source_module": "agent.finance.compliance.wash_sale.detect_wash_sales",
        "description": "IRS § 1091: detects sell-at-loss + buy-back-within-30-days. SQLite-backed lot tracking.",
    },
    "fin_db.pdt_counter": {
        "id": "fin_db.pdt_counter",
        "label_en": "PDT round-trip counter",
        "label_zh": "PDT 当日 round-trip 计数",
        "status": STATUS_AVAILABLE,
        "fields": ["trade_date"],
        "produces_tags": ["risk:pdt_breach", "timescale:short"],
        "source_module": "agent.finance.compliance.pdt_counter.compute_round_trips",
        "description": "FINRA PDT (Pattern Day Trader) — count of intraday round-trips in the rolling 5-business-day window.",
    },
    "fin_db.holding_period_tracker": {
        "id": "fin_db.holding_period_tracker",
        "label_en": "Holding period tracker",
        "label_zh": "持有期追踪",
        "status": STATUS_AVAILABLE,
        "fields": ["days_held", "days_to_long_term"],
        "produces_tags": ["compliance:near_long_term", "compliance:holding_long_term",
                          "compliance:holding_short_term"],
        "source_module": "agent.finance.compliance.holding_period.snapshot_holding_periods",
        "description": "IRS short vs long-term: per-lot days held + countdown to LT qualification.",
    },

    # ──── Planned (referenced by ≥1 strategy but no emitter yet) — explicit gaps ────

    "options_chain": {
        "id": "options_chain", "status": STATUS_PLANNED,
        "label_en": "Options chain", "label_zh": "期权链",
        "fields": ["strike", "expiry", "dte", "delta", "iv", "oi", "volume"],
        "description": "Per-symbol option strikes / expiries / IV / OI / volume. Needed by every options strategy (covered call / CSP / verticals / iron condor / collar / calendar / PMCC). Currently no L1 obs emitted.",
    },
    "iv_rank": {
        "id": "iv_rank", "status": STATUS_PLANNED,
        "label_en": "Implied vol rank", "label_zh": "隐含波动率分位",
        "fields": ["iv_rank_pct", "iv_percentile"],
        "description": "IV rank (current IV vs 52-week range). Earnings widget exposes ATM IV but not rank. Needed by sell-volatility strategies.",
    },
    "fundamentals_value": {
        "id": "fundamentals_value", "status": STATUS_PLANNED,
        "label_en": "Fundamentals (P/E, P/B)", "label_zh": "基本面（PE/PB）",
        "fields": ["pe", "pb", "pcf", "ev_ebitda"],
        "description": "Per-symbol fundamentals. Needed by value-factor strategies.",
    },
    "factor_exposure": {
        "id": "factor_exposure", "status": STATUS_PLANNED,
        "label_en": "Factor exposure", "label_zh": "因子暴露",
        "fields": ["beta", "size", "value", "momentum", "quality", "low_vol"],
        "description": "Fama-French / AQR factor loadings per symbol or ETF. Needed by factor-tilt strategies.",
    },
    "dividend_schedule": {
        "id": "dividend_schedule", "status": STATUS_PLANNED,
        "label_en": "Dividend schedule", "label_zh": "分红日历",
        "fields": ["ex_date", "pay_date", "amount", "yield_pct", "growth_5yr_pct"],
        "description": "Per-symbol ex-/pay-date + history. Needed by dividend strategies and §1058 holding-period checks.",
    },
    "yield_curve": {
        "id": "yield_curve", "status": STATUS_PLANNED,
        "label_en": "US Treasury yield curve", "label_zh": "美债收益率曲线",
        "fields": ["1m", "3m", "6m", "1y", "2y", "5y", "10y", "30y", "10y_minus_2y"],
        "description": "USTreasury yields. Needed by bond-ladder + macro-rotation strategies.",
    },
    "expense_ratio": {
        "id": "expense_ratio", "status": STATUS_PLANNED,
        "label_en": "ETF / fund expense ratio", "label_zh": "ETF / 基金费率",
        "fields": ["expense_ratio_pct", "aum"],
        "description": "Static fund metadata. Needed for any ETF strategy when comparing alternatives.",
    },
    "macro_pmi_inflation": {
        "id": "macro_pmi_inflation", "status": STATUS_PLANNED,
        "label_en": "Macro indicators",   "label_zh": "宏观指标",
        "fields": ["pmi", "cpi_yoy", "core_cpi_yoy", "unemployment", "ism"],
        "description": "PMI, CPI, unemployment. Needed by sector-rotation business-cycle strategies.",
    },
    "short_interest": {
        "id": "short_interest", "status": STATUS_PLANNED,
        "label_en": "Short interest", "label_zh": "做空比例",
        "fields": ["short_pct_float", "days_to_cover"],
        "description": "Per-symbol short interest data. Needed by IPO-lockup short bias and squeeze setups.",
    },
    "event_calendar_ipo_russell_fomc": {
        "id": "event_calendar_ipo_russell_fomc", "status": STATUS_PLANNED,
        "label_en": "Event calendar (IPO lockup / Russell rebalance / FOMC)",
        "label_zh": "事件日历（IPO 解锁 / Russell 调仓 / FOMC）",
        "fields": ["ipo_lockup_dates", "russell_rebalance_dates", "fomc_dates"],
        "description": "Scheduled non-earnings events. Needed by ipo_lockup_short_bias / russell_reconstitution / fomc_announcement_fade.",
    },
    "merger_arbitrage_universe": {
        "id": "merger_arbitrage_universe", "status": STATUS_PLANNED,
        "label_en": "M&A universe (cash deals)", "label_zh": "并购池（现金 deal）",
        "fields": ["target", "acquirer", "deal_price", "spread_pct", "expected_close"],
        "description": "Announced M&A deals + spread tracking. Needed by merger_arbitrage strategy.",
    },
    "crypto_ohlcv": {
        "id": "crypto_ohlcv", "status": STATUS_PLANNED,
        "label_en": "Crypto OHLCV", "label_zh": "加密 OHLCV",
        "fields": ["open", "high", "low", "close", "volume"],
        "description": "BTC / ETH / etc. price feed. Needed by btc_dca / eth_dca. Currently market_data_daily handles US stocks only.",
    },
    "allocation_state": {
        "id": "allocation_state", "status": STATUS_PLANNED,
        "label_en": "Portfolio allocation state", "label_zh": "组合配置状态",
        "fields": ["target_weights", "actual_weights", "drift_pct"],
        "description": "Multi-asset allocation drift. Needed by three_fund / permanent_portfolio / target_date_fund.",
    },
    "etf_flow": {
        "id": "etf_flow", "status": STATUS_PLANNED,
        "label_en": "ETF fund flows", "label_zh": "ETF 资金流",
        "fields": ["weekly_flow_usd", "ytd_flow_usd"],
        "description": "ETF inflows / outflows. Useful tilt indicator for sector rotation.",
    },
    "relative_strength": {
        "id": "relative_strength", "status": STATUS_PLANNED,
        "label_en": "Relative strength rank", "label_zh": "相对强弱排名",
        "fields": ["rs_1m", "rs_3m", "rs_12m"],
        "description": "Cross-sectional momentum ranking. Needed by relative_strength_momentum / cross_sectional_momentum strategies.",
    },
    "mean_reversion_z": {
        "id": "mean_reversion_z", "status": STATUS_PLANNED,
        "label_en": "Short-term mean-reversion signal", "label_zh": "短期均值回归信号",
        "fields": ["rsi2", "5d_zscore"],
        "description": "RSI(2) + short-window z-scores. Needed by mean_reversion_oversold + day_volatility_fade.",
    },
}


# ── Public helpers ───────────────────────────────────────────────────


def list_widgets(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all widgets, optionally filtered by status."""
    if status is None:
        return list(WIDGET_REGISTRY.values())
    return [w for w in WIDGET_REGISTRY.values() if w["status"] == status]


def get_widget(widget_id: str) -> Optional[Dict[str, Any]]:
    return WIDGET_REGISTRY.get(widget_id)


def validate_widget_ids(ids: List[str]) -> Dict[str, List[str]]:
    """Partition a list of ids into (registered, unknown).

    Used at strategies.yaml load time to fail loudly on free-text
    `data_requirements` that don't map to any widget.
    """
    registered, unknown = [], []
    for x in ids:
        (registered if x in WIDGET_REGISTRY else unknown).append(x)
    return {"registered": registered, "unknown": unknown}


def widget_status_summary() -> Dict[str, int]:
    """Counts per status — used by integrity check / UI overview."""
    out: Dict[str, int] = {}
    for w in WIDGET_REGISTRY.values():
        out[w["status"]] = out.get(w["status"], 0) + 1
    return out
