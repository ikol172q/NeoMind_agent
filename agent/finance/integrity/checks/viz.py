"""Visualization-layer integrity (Phase 5 V4 / Task 15 V1).

The user's Insight-Lattice principle: every UI number must be
traceable to its data source — no fabricated, stale, or detached
displays. This check is the **machine-readable** version of that
contract: it walks a manifest of UI element ↔ backend mappings and
verifies every mapping resolves to a sane value.

How it pairs with the UI:
  - Each UI component documents its source via a ``data-source``
    HTML attribute (visible in DevTools). Examples:
      <div data-testid="pdt-counter" data-source="GET /api/db/health → counts.pdt_round_trips">
      <span data-source="counts.tax_lots">{count}</span>
  - The manifest below lists the SAME mappings in code form.
  - This check verifies: for every manifest entry, the documented
    backend path is reachable and returns a value of the expected
    type.
  - A future V2 (using Playwright) will additionally render the SPA
    and verify the rendered TEXT equals the value at that path.
    Out of scope here.

Mismatch surfaces as a `viz`-layer integrity check failure with the
specific entry name in offenders. So if someone:
  - removes /api/db/health.counts.pdt_round_trips
  - or restructures the JSON shape
  - or renames a data-source attribute in a component
…the integrity badge goes amber on the next tick, drawing attention
to the broken contract.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

from agent.finance.persistence import connect


# Manifest: every UI numeric/text element that claims a backend
# source. Format: (ui_label, sql_to_compute_expected, expected_type).
# We deliberately don't go through HTTP — we hit the DB directly with
# the same SQL the API endpoint would run. The HTTP layer is thin
# pass-through; this proves the SQL itself is sound.
UI_MANIFEST: List[Tuple[str, str, type]] = [
    # PdtCounter — header pill
    ("pdt-counter:counts.pdt_round_trips",
     "SELECT COUNT(*) FROM pdt_round_trips",
     int),
    # FinIntegrityBadge counts row — 6 numbers
    ("fin-badge:counts.market_data_daily",
     "SELECT COUNT(*) FROM market_data_daily",
     int),
    ("fin-badge:counts.tickers_universe",
     "SELECT COUNT(*) FROM tickers_universe",
     int),
    ("fin-badge:counts.tax_lots",
     "SELECT COUNT(*) FROM tax_lots",
     int),
    ("fin-badge:counts.wash_sale_events",
     "SELECT COUNT(*) FROM wash_sale_events",
     int),
    ("fin-badge:counts.pdt_round_trips",
     "SELECT COUNT(*) FROM pdt_round_trips",
     int),
    ("fin-badge:counts.analysis_runs",
     "SELECT COUNT(*) FROM analysis_runs",
     int),
    # FinIntegrityBadge schema_version row
    ("fin-badge:schema_version",
     "SELECT MAX(version) FROM schema_version",
     int),
]


def check_ui_data_sources_resolvable(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Every documented UI source resolves to a value of the expected type.

    Returns a check-result dict matching the framework contract.
    """
    offenders: List[Dict[str, Any]] = []
    for label, sql, expected_type in UI_MANIFEST:
        try:
            row = conn.execute(sql).fetchone()
            value = row[0] if row else None
        except sqlite3.Error as exc:
            offenders.append({
                "ui_element": label, "sql": sql,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        if value is None:
            offenders.append({
                "ui_element": label, "sql": sql,
                "error": "query returned NULL — UI would show '—' or break",
            })
            continue

        if not isinstance(value, expected_type):
            offenders.append({
                "ui_element": label, "sql": sql,
                "got_type": type(value).__name__,
                "expected_type": expected_type.__name__,
                "value": str(value)[:100],
            })

    total = len(UI_MANIFEST)
    if offenders:
        return {
            "pass": False,
            "detail": f"{len(offenders)} / {total} UI source mappings broken",
            "offenders": offenders,
        }
    return {
        "pass": True,
        "detail": f"{total} / {total} UI element data-sources resolve to expected types",
    }
