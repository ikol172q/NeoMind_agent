"""Resolve free-text ``data_requirements`` strings → widget_registry ids.

Phase 6 Step 3 of the design doc. The catalog's free-text
``data_requirements`` (e.g., ``"options chain"``, ``"IV rank"``) are
human-readable but unauditable. This module maps each known phrase
to one or more widget ids from ``widget_registry.WIDGET_REGISTRY``.

The mapping is **explicit** (not LLM-inferred): every entry below is
either (a) a verbatim phrase from today's 36 strategies × 100
data_requirement entries, or (b) a near-synonym for one of those.

Adding a new phrase: append below and re-run
``audit_strategies_yaml`` to refresh the controlled field.
"""

from __future__ import annotations

from typing import Dict, List, Set

from agent.finance.lattice.widget_registry import WIDGET_REGISTRY


# Verbatim phrases as they appear in docs/strategies/strategies.yaml,
# mapped to one or more widget ids. Multiple ids = the requirement
# spans multiple widgets (rare but legitimate).
FREE_TEXT_TO_WIDGETS: Dict[str, List[str]] = {
    # ── chart / price-action ──
    "12-month and 1-month price data per symbol": ["chart"],
    "200-day MA filter":                            ["chart"],
    "52w high":                                     ["chart"],
    "ATR":                                          ["chart"],
    "average daily volume":                         ["chart"],
    "daily OHLCV":                                  ["chart"],
    "weekly close":                                 ["chart"],
    "monthly NAV":                                  ["chart"],
    "support levels":                               ["chart"],
    "resistance levels":                            ["chart"],
    "support/resistance":                           ["chart"],
    "volume":                                       ["chart"],
    "realized volatility":                          ["chart"],
    "intraday SPY/QQQ":                             ["chart"],

    # ── earnings ──
    "earnings calendar":                            ["earnings"],
    "SUE (standardized unexpected earnings)":       ["earnings"],
    "historical earnings move":                     ["earnings"],
    "post-announcement gap":                        ["earnings", "news"],

    # ── options ──
    "options chain":                                ["options_chain"],
    "delta":                                        ["options_chain"],
    "delta of LEAPS":                               ["options_chain"],
    "LEAPS quote (1-2 yr)":                         ["options_chain"],
    "monthly call chain":                           ["options_chain"],
    "FXI options chain":                            ["options_chain"],
    "open interest concentration":                  ["options_chain"],
    "bid-ask spread":                               ["options_chain"],
    "expected move":                                ["iv_rank", "options_chain"],
    "implied move from options":                    ["iv_rank", "options_chain"],
    "implied volatility":                           ["iv_rank"],
    "IV rank":                                      ["iv_rank"],
    "term structure of IV":                         ["iv_rank"],
    "VIX":                                          ["sentiment"],
    "VIX term structure":                           ["sentiment"],

    # ── mean reversion / momentum ──
    "RSI(2)":                                       ["mean_reversion_z"],
    "3-month relative strength":                    ["relative_strength"],
    "3-month relative strength SOXX vs KWEB vs MCHI": ["relative_strength"],
    "sector relative strength":                     ["sectors", "relative_strength"],

    # ── fundamentals ──
    "P/E":                                          ["fundamentals_value"],
    "P/B":                                          ["fundamentals_value"],
    "ROE":                                          ["fundamentals_value"],
    "debt/equity":                                  ["fundamentals_value"],
    "earnings stability":                           ["fundamentals_value"],
    "beta":                                         ["factor_exposure"],
    "factor exposure":                              ["factor_exposure"],
    "currency exposure":                            ["factor_exposure"],
    "USD/CNY":                                      ["factor_exposure"],

    # ── dividends ──
    "dividend history":                             ["dividend_schedule"],
    "dividend schedule":                            ["dividend_schedule"],
    "yield-on-cost":                                ["dividend_schedule"],

    # ── treasury / yield ──
    "yield curve":                                  ["yield_curve"],
    "auction calendar":                             ["yield_curve"],

    # ── macro / news ──
    "macro indicators (PMI, yield curve)":          ["macro_pmi_inflation", "yield_curve"],
    "macro/policy news":                            ["news", "macro_pmi_inflation"],
    "macro China data":                             ["macro_pmi_inflation"],
    "China policy / stimulus calendar":             ["news", "event_calendar_ipo_russell_fomc"],
    "China policy news flow":                       ["news"],

    # ── allocation / fund metadata ──
    "expense ratio":                                ["expense_ratio"],
    "allocation %":                                 ["allocation_state"],
    "rebalance bands":                              ["allocation_state"],
    "glidepath":                                    ["allocation_state"],
    "monthly rebalance":                            ["allocation_state"],
    "country weights":                              ["allocation_state"],
    "holdings concentration":                       ["allocation_state"],

    # ── events / calendars ──
    "FOMC calendar (8 meetings/yr)":                ["event_calendar_ipo_russell_fomc"],
    "FTSE Russell preliminary lists (May)":         ["event_calendar_ipo_russell_fomc"],
    "additions/deletions":                          ["event_calendar_ipo_russell_fomc"],
    "regulatory calendar":                          ["event_calendar_ipo_russell_fomc", "news"],
    "IPO calendar":                                 ["event_calendar_ipo_russell_fomc"],
    "lockup date (typ. 180d post-IPO)":             ["event_calendar_ipo_russell_fomc"],
    "quarterly quad-witch dates (3rd Fri Mar/Jun/Sep/Dec)": ["event_calendar_ipo_russell_fomc"],
    "float vs lockup share count":                  ["short_interest",
                                                     "event_calendar_ipo_russell_fomc"],

    # ── M&A ──
    "deal docs (S-4)":                              ["merger_arbitrage_universe", "news"],
    "spread vs deal price":                         ["merger_arbitrage_universe"],

    # ── crypto / exchange ──
    "exchange ACH ramp":                            ["crypto_ohlcv"],
    "exchange access":                              ["crypto_ohlcv"],

    # ── lots / portfolio ──
    "underlying cost basis":                        ["portfolio",
                                                     "fin_db.holding_period_tracker"],
}


# Sanity: every widget id we map to MUST exist in the registry.
def _self_check() -> None:
    """Module-load assertion that every right-hand side is a real widget."""
    referenced: Set[str] = set()
    for _phrase, widgets in FREE_TEXT_TO_WIDGETS.items():
        referenced.update(widgets)
    missing = referenced - set(WIDGET_REGISTRY.keys())
    if missing:
        raise AssertionError(
            f"strategy_widget_resolver references widgets not in WIDGET_REGISTRY: {sorted(missing)}"
        )


_self_check()


# ── Public helpers ───────────────────────────────────────────────────


def resolve_phrase(free_text: str) -> List[str]:
    """Return the list of widget ids for a free-text data-requirement phrase.
    Returns an empty list when the phrase is unknown — caller decides
    whether to flag that as a hard error or a soft warning.
    """
    return list(FREE_TEXT_TO_WIDGETS.get(free_text, []))


def resolve_strategy_data_requirements(
    free_text_list: List[str],
) -> Dict[str, List[str]]:
    """Resolve every free-text in a strategy's data_requirements.

    Returns:
        {
          "widget_ids":   [...]   # de-duped union of resolved widgets
          "unresolved":   [...]   # phrases the mapping doesn't cover
        }
    """
    widgets: List[str] = []
    seen: Set[str] = set()
    unresolved: List[str] = []
    for phrase in free_text_list:
        ws = FREE_TEXT_TO_WIDGETS.get(phrase)
        if not ws:
            unresolved.append(phrase)
            continue
        for w in ws:
            if w not in seen:
                widgets.append(w)
                seen.add(w)
    return {"widget_ids": widgets, "unresolved": unresolved}
