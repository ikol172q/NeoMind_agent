"""Audit script: write controlled `data_requirement_widgets` field into
docs/strategies/strategies.yaml based on FREE_TEXT_TO_WIDGETS mapping.

Run once after adding new strategies or new mapping entries. Non-
destructive — preserves the human-readable `data_requirements` and
adds a parallel `data_requirement_widgets` list.

    python -m agent.finance.scripts.audit_strategy_widgets

Output: rewritten strategies.yaml + a coverage report.

Idempotent: running again on already-audited yaml is a no-op (other
than re-printing the report).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

from agent.finance.lattice.strategy_widget_resolver import (
    resolve_strategy_data_requirements,
)
from agent.finance.lattice.widget_registry import (
    STATUS_AVAILABLE, STATUS_PLANNED, get_widget,
)

_STRATEGIES_YAML = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs" / "strategies" / "strategies.yaml"
)


def main() -> int:
    if not _STRATEGIES_YAML.exists():
        print(f"❌ strategies.yaml not found at {_STRATEGIES_YAML}")
        return 1

    raw = yaml.safe_load(_STRATEGIES_YAML.read_text(encoding="utf-8")) or {}
    strategies = raw.get("strategies", [])

    total_unresolved = 0
    available_count, planned_count = 0, 0
    audit_rows: List[Dict[str, Any]] = []

    for s in strategies:
        free = s.get("data_requirements", []) or []
        result = resolve_strategy_data_requirements(free)
        widget_ids: List[str] = result["widget_ids"]
        unresolved: List[str] = result["unresolved"]

        s["data_requirement_widgets"] = widget_ids

        # Per-strategy availability split
        avail = sum(1 for w in widget_ids
                    if (get_widget(w) or {}).get("status") == STATUS_AVAILABLE)
        plan = sum(1 for w in widget_ids
                   if (get_widget(w) or {}).get("status") == STATUS_PLANNED)
        available_count += avail
        planned_count += plan
        total_unresolved += len(unresolved)

        audit_rows.append({
            "id":        s["id"],
            "free_n":    len(free),
            "widget_n":  len(widget_ids),
            "avail":     avail,
            "planned":   plan,
            "unresolved": unresolved,
        })

    # Re-serialize. yaml.dump preserves order if data is OrderedDict-y;
    # python 3.7+ dict iteration is insertion-ordered which is enough.
    out = yaml.safe_dump(
        raw, sort_keys=False, allow_unicode=True, width=200, indent=2,
    )
    _STRATEGIES_YAML.write_text(out, encoding="utf-8")

    # ── Coverage report ──
    print(f"=== audit complete: wrote {_STRATEGIES_YAML} ===")
    print(f"  {len(strategies)} strategies processed")
    print(f"  total widget references:   "
          f"{available_count + planned_count}  "
          f"(available {available_count} / planned {planned_count})")
    print(f"  unresolved free-text:      {total_unresolved}")
    print()

    # Sort: most-gappy first
    audit_rows.sort(key=lambda r: (-r["planned"], r["id"]))
    print("=== per-strategy widget coverage ===")
    print(f"  {'strategy':32s}  free  widget  avail  planned  unresolved")
    for r in audit_rows:
        un = ",".join(r["unresolved"]) if r["unresolved"] else "-"
        print(f"  {r['id']:32s}  {r['free_n']:>4d}  {r['widget_n']:>6d}  "
              f"{r['avail']:>5d}  {r['planned']:>7d}  {un}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
