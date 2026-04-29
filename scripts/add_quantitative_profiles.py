#!/usr/bin/env python
"""Add ``quantitative_profile`` block to every strategies.yaml entry.

Maps strategy id → payoff_class and per-bucket regime_sensitivity.
Run once; safe to re-run (only adds the block when missing).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import yaml


YAML_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs" / "strategies" / "strategies.yaml"
)


# id → (payoff_class, greeks_template, regime_sensitivity, expected_hold_days, breakeven_RV_pctile)
PROFILES: Dict[str, Dict[str, Any]] = {
    # ── Long-only equity / ETF ──────────────────────────────
    "dollar_cost_averaging_index":  {
        "payoff_class": "dca",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.2, "volatility_regime": -0.5,
            "breadth": +0.6, "event_density": +0.0, "flow": +0.4,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },
    "dividend_growth_etf": {
        "payoff_class": "buy_and_hold",
        "greeks_template": {"delta": 0.85, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.1, "volatility_regime": -0.4,
            "breadth": +0.5, "event_density": +0.0, "flow": +0.3,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.40,
    },
    "target_date_fund": {
        "payoff_class": "target_date_fund",
        "greeks_template": {"delta": 0.7, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": -0.3,
            "breadth": +0.4, "event_density": 0.0, "flow": +0.2,
        },
        "expected_hold_days": 1825,
        "breakeven_RV_pctile": 0.50,
    },
    "lazy_portfolio_three_fund": {
        "payoff_class": "lazy_portfolio_three_fund",
        "greeks_template": {"delta": 0.7, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": -0.3,
            "breadth": +0.4, "event_density": 0.0, "flow": +0.2,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },
    "permanent_portfolio": {
        "payoff_class": "permanent_portfolio",
        "greeks_template": {"delta": 0.5, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": +0.0,
            "breadth": +0.2, "event_density": 0.0, "flow": +0.1,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },
    "bond_ladder_treasury": {
        "payoff_class": "buy_and_hold",
        "greeks_template": {"delta": -0.1, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.3, "volatility_regime": -0.2,
            "breadth": 0.0, "event_density": 0.0, "flow": -0.4,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.30,
    },
    "international_developed_etf": {
        "payoff_class": "buy_and_hold",
        "greeks_template": {"delta": 0.9, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.1, "volatility_regime": -0.3,
            "breadth": +0.3, "event_density": 0.0, "flow": +0.5,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },

    # ── Factor / momentum ────────────────────────────────────
    "sector_rotation": {
        "payoff_class": "sector_rotation_business_cycle",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.2, "volatility_regime": -0.2,
            "breadth": +0.1, "event_density": -0.1, "flow": +0.5,
        },
        "expected_hold_days": 90,
        "breakeven_RV_pctile": 0.50,
    },
    "relative_strength_momentum": {
        "payoff_class": "trend_following",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.4, "volatility_regime": -0.2,
            "breadth": +0.6, "event_density": -0.2, "flow": +0.3,
        },
        "expected_hold_days": 90,
        "breakeven_RV_pctile": 0.50,
    },
    "value_factor_etf": {
        "payoff_class": "value_factor",
        "greeks_template": {"delta": 0.95, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.2, "volatility_regime": +0.2,
            "breadth": +0.2, "event_density": 0.0, "flow": +0.2,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },
    "low_volatility_factor": {
        "payoff_class": "low_volatility_factor",
        "greeks_template": {"delta": 0.7, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.4, "volatility_regime": +0.5,
            "breadth": -0.2, "event_density": +0.2, "flow": -0.3,
        },
        "expected_hold_days": 180,
        "breakeven_RV_pctile": 0.50,
    },
    "small_cap_value": {
        "payoff_class": "value_factor",
        "greeks_template": {"delta": 1.1, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.3, "volatility_regime": -0.2,
            "breadth": +0.5, "event_density": 0.0, "flow": +0.4,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },
    "quality_factor": {
        "payoff_class": "value_factor",
        "greeks_template": {"delta": 0.95, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.1, "volatility_regime": -0.1,
            "breadth": +0.3, "event_density": 0.0, "flow": +0.2,
        },
        "expected_hold_days": 365,
        "breakeven_RV_pctile": 0.50,
    },

    # ── Swing / breakout / mean reversion ────────────────────
    "swing_breakout_52w_high": {
        "payoff_class": "fifty_two_week_high_breakout_swing",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.5, "volatility_regime": -0.3,
            "breadth": +0.6, "event_density": -0.3, "flow": +0.4,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
    },
    "mean_reversion_oversold": {
        "payoff_class": "mean_reversion_oversold_bounce_rsi2",
        "greeks_template": {"delta": 0.95, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.4, "volatility_regime": +0.6,
            "breadth": -0.3, "event_density": +0.0, "flow": -0.2,
        },
        "expected_hold_days": 5,
        "breakeven_RV_pctile": 0.50,
    },
    "post_earnings_drift": {
        "payoff_class": "trend_following",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.2, "volatility_regime": +0.0,
            "breadth": +0.2, "event_density": +0.4, "flow": +0.1,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
    },
    "earnings_announcement_drift": {
        "payoff_class": "trend_following",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.2, "volatility_regime": +0.0,
            "breadth": +0.2, "event_density": +0.5, "flow": 0.0,
        },
        "expected_hold_days": 5,
        "breakeven_RV_pctile": 0.50,
    },

    # ── Event-driven ─────────────────────────────────────────
    "merger_arbitrage": {
        "payoff_class": "merger_arbitrage",
        "greeks_template": {"delta": 0.3, "theta": 0.0, "vega": -0.1, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.1, "volatility_regime": -0.2,
            "breadth": 0.0, "event_density": +0.5, "flow": -0.2,
        },
        "expected_hold_days": 90,
        "breakeven_RV_pctile": 0.50,
    },
    "russell_rebalance": {
        "payoff_class": "trend_following",
        "greeks_template": {"delta": 0.8, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": +0.0,
            "breadth": +0.2, "event_density": +0.6, "flow": 0.0,
        },
        "expected_hold_days": 14,
        "breakeven_RV_pctile": 0.50,
    },
    "fomc_announcement_fade": {
        "payoff_class": "mean_reversion",
        "greeks_template": {"delta": 0.5, "theta": 0.0, "vega": -0.1, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": +0.5,
            "breadth": 0.0, "event_density": +0.7, "flow": 0.0,
        },
        "expected_hold_days": 1,
        "breakeven_RV_pctile": 0.50,
    },
    "ipo_lockup_expiry": {
        "payoff_class": "trend_following",
        "greeks_template": {"delta": -0.7, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": -0.2, "volatility_regime": +0.3,
            "breadth": -0.2, "event_density": +0.5, "flow": -0.1,
        },
        "expected_hold_days": 14,
        "breakeven_RV_pctile": 0.50,
    },

    # ── Options: short-vol ──────────────────────────────────
    "covered_call_etf": {
        "payoff_class": "covered_call_etf",
        "greeks_template": {"delta": 0.5, "theta": +0.05, "vega": -0.18, "gamma": -0.02},
        "regime_sensitivity": {
            "risk_appetite": -0.2, "volatility_regime": +0.6,
            "breadth": +0.1, "event_density": -0.4, "flow": +0.0,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
    },
    "cash_secured_put_etf": {
        "payoff_class": "cash_secured_put",
        "greeks_template": {"delta": 0.4, "theta": +0.05, "vega": -0.18, "gamma": -0.02},
        "regime_sensitivity": {
            "risk_appetite": -0.2, "volatility_regime": +0.5,
            "breadth": -0.1, "event_density": -0.3, "flow": -0.1,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
    },
    "vertical_bull_put_spread": {
        "payoff_class": "vertical_bull_put_spread",
        "greeks_template": {"delta": 0.2, "theta": +0.04, "vega": -0.10, "gamma": -0.01},
        "regime_sensitivity": {
            "risk_appetite": +0.0, "volatility_regime": +0.4,
            "breadth": +0.2, "event_density": -0.4, "flow": +0.1,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
        "max_loss_units": 1.0,
    },
    "vertical_bear_call_spread": {
        "payoff_class": "vertical_bear_call_spread",
        "greeks_template": {"delta": -0.2, "theta": +0.04, "vega": -0.10, "gamma": -0.01},
        "regime_sensitivity": {
            "risk_appetite": -0.2, "volatility_regime": +0.4,
            "breadth": -0.2, "event_density": -0.4, "flow": -0.1,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
        "max_loss_units": 1.0,
    },
    "iron_condor_index": {
        "payoff_class": "iron_condor_index",
        "greeks_template": {"delta": 0.0, "theta": +0.06, "vega": -0.12, "gamma": -0.01},
        "regime_sensitivity": {
            "risk_appetite": -0.1, "volatility_regime": +0.5,
            "breadth": +0.0, "event_density": -0.5, "flow": +0.0,
        },
        "expected_hold_days": 30,
        "breakeven_RV_pctile": 0.50,
        "max_loss_units": 2.0,
    },

    # ── Options: defensive / hedged ────────────────────────
    "collar_protective_put": {
        "payoff_class": "buy_and_hold",
        "greeks_template": {"delta": 0.5, "theta": -0.02, "vega": +0.10, "gamma": +0.01},
        "regime_sensitivity": {
            "risk_appetite": -0.4, "volatility_regime": +0.0,
            "breadth": +0.0, "event_density": +0.3, "flow": -0.2,
        },
        "expected_hold_days": 90,
        "breakeven_RV_pctile": 0.50,
    },
    "calendar_spread": {
        "payoff_class": "calendar_spread",
        "greeks_template": {"delta": 0.0, "theta": +0.02, "vega": +0.05, "gamma": -0.01},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": -0.3,
            "breadth": 0.0, "event_density": +0.2, "flow": 0.0,
        },
        "expected_hold_days": 14,
        "breakeven_RV_pctile": 0.50,
    },
    "poor_mans_covered_call": {
        "payoff_class": "diagonal_spread",
        "greeks_template": {"delta": 0.3, "theta": +0.03, "vega": -0.08, "gamma": -0.01},
        "regime_sensitivity": {
            "risk_appetite": -0.1, "volatility_regime": +0.3,
            "breadth": +0.1, "event_density": -0.3, "flow": +0.0,
        },
        "expected_hold_days": 60,
        "breakeven_RV_pctile": 0.50,
    },
    "quad_witching_volatility": {
        "payoff_class": "long_straddle",
        "greeks_template": {"delta": 0.0, "theta": -0.04, "vega": +0.18, "gamma": +0.02},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": -0.4,
            "breadth": 0.0, "event_density": +0.7, "flow": 0.0,
        },
        "expected_hold_days": 5,
        "breakeven_RV_pctile": 0.50,
    },
    "fxi_volatility_play": {
        "payoff_class": "long_straddle",
        "greeks_template": {"delta": 0.0, "theta": -0.04, "vega": +0.18, "gamma": +0.02},
        "regime_sensitivity": {
            "risk_appetite": 0.0, "volatility_regime": -0.3,
            "breadth": 0.0, "event_density": +0.4, "flow": -0.2,
        },
        "expected_hold_days": 14,
        "breakeven_RV_pctile": 0.50,
    },

    # ── International / Crypto ──────────────────────────────
    "sector_etf_rotation_us_china": {
        "payoff_class": "sector_rotation_business_cycle",
        "greeks_template": {"delta": 0.95, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.2, "volatility_regime": -0.2,
            "breadth": +0.1, "event_density": -0.1, "flow": +0.5,
        },
        "expected_hold_days": 90,
        "breakeven_RV_pctile": 0.50,
    },
    "kweb_momentum": {
        "payoff_class": "trend_following",
        "greeks_template": {"delta": 1.1, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.4, "volatility_regime": -0.2,
            "breadth": +0.3, "event_density": -0.2, "flow": +0.4,
        },
        "expected_hold_days": 60,
        "breakeven_RV_pctile": 0.50,
    },
    "mchi_long_hold": {
        "payoff_class": "buy_and_hold",
        "greeks_template": {"delta": 1.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.3, "volatility_regime": -0.2,
            "breadth": +0.2, "event_density": 0.0, "flow": +0.4,
        },
        "expected_hold_days": 730,
        "breakeven_RV_pctile": 0.50,
    },
    "btc_dca": {
        "payoff_class": "dca",
        "greeks_template": {"delta": 1.5, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.5, "volatility_regime": +0.0,
            "breadth": +0.2, "event_density": -0.1, "flow": +0.5,
        },
        "expected_hold_days": 1095,
        "breakeven_RV_pctile": 0.50,
    },
    "eth_dca": {
        "payoff_class": "dca",
        "greeks_template": {"delta": 1.6, "theta": 0.0, "vega": 0.0, "gamma": 0.0},
        "regime_sensitivity": {
            "risk_appetite": +0.5, "volatility_regime": +0.0,
            "breadth": +0.2, "event_density": -0.1, "flow": +0.5,
        },
        "expected_hold_days": 1095,
        "breakeven_RV_pctile": 0.50,
    },
}


def main() -> int:
    text = YAML_PATH.read_text(encoding="utf-8")
    y = yaml.safe_load(text)
    strategies = y.get("strategies") or []

    added = 0
    skipped = 0
    missing_profile: list = []
    for s in strategies:
        sid = s["id"]
        if "quantitative_profile" in s:
            skipped += 1
            continue
        prof = PROFILES.get(sid)
        if not prof:
            missing_profile.append(sid)
            continue
        s["quantitative_profile"] = prof
        added += 1

    print(f"added {added} profiles, skipped {skipped} (already had one)")
    if missing_profile:
        print(f"⚠ {len(missing_profile)} strategies have no profile in script:")
        for sid in missing_profile:
            print("  -", sid)

    YAML_PATH.write_text(
        yaml.safe_dump(y, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"wrote {YAML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
