"""Tax & compliance detectors for the NeoMind fin platform.

The schema layer in ``agent/finance/persistence/`` already has the
target tables (``wash_sale_events``, ``pdt_round_trips``,
``holding_period_snapshots``). This package fills them by scanning
``tax_lots`` rows and applying the rule logic.

Three detectors:

  - ``wash_sale.detect_wash_sales``   — IRS § 1091 30-day window
  - ``pdt_counter.compute_round_trips`` — FINRA Pattern Day Trader
  - ``holding_period.snapshot_holding_periods`` — short vs long term

A scheduler job wraps all three: see
``agent/finance/scheduler/jobs/compliance_check.py``. The integrity
framework's compliance-layer checks then verify the detector output
is consistent with the source rows (closing the loop).

Cross-references:
  - response_validator.py Rule 4: "Recommendations need confidence +
    time horizon + scenarios". The detectors here surface tax_warning
    text that the signal/recommendation layer can attach to advice
    BEFORE it's shown to the user — so a "buy AAPL" suggestion comes
    pre-flagged with "wash sale risk: closed at loss 12d ago" or
    "would push you to 4 round-trips this week".
"""

from agent.finance.compliance.holding_period import (
    classify_holding_period,
    days_until_long_term,
    snapshot_holding_periods,
)
from agent.finance.compliance.pdt_counter import (
    PDT_LIMIT,
    PDT_WINDOW_TRADING_DAYS,
    compute_pdt_status,
    compute_round_trips,
)
from agent.finance.compliance.wash_sale import (
    WASH_SALE_WINDOW_DAYS,
    detect_wash_sales,
)

__all__ = [
    # wash_sale
    "WASH_SALE_WINDOW_DAYS",
    "detect_wash_sales",
    # pdt
    "PDT_LIMIT",
    "PDT_WINDOW_TRADING_DAYS",
    "compute_pdt_status",
    "compute_round_trips",
    # holding_period
    "classify_holding_period",
    "days_until_long_term",
    "snapshot_holding_periods",
]
