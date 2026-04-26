"""CLI for the integrity check.

    python -m agent.finance.integrity.runner
    python -m agent.finance.integrity.runner --layer data
    python -m agent.finance.integrity.runner --json
    python -m agent.finance.integrity.runner --fail-on-error  # exit 1 if any check fails

Designed to be hookable from pre-commit, CI, and a local make target.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from agent.finance.integrity import run_integrity_check


_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _format_terminal(report: Dict[str, Any]) -> str:
    lines = []
    summary = report["summary"]
    color = _GREEN if report["all_pass"] else _RED
    lines.append(f"{color}{summary}{_RESET}  ({report['timestamp']})")
    lines.append("")

    for c in report["checks"]:
        if c.get("error"):
            mark = f"{_RED}✗{_RESET}"
            tail = f"  {_RED}{c['error']}{_RESET}"
        elif c["pass"]:
            mark = f"{_GREEN}✓{_RESET}"
            tail = ""
        else:
            mark = f"{_YELLOW}⚠{_RESET}"
            tail = ""

        layer = f"{_DIM}[{c['layer']:10s}]{_RESET}"
        lines.append(f"  {mark} {layer} {c['label']}")
        lines.append(f"    {_DIM}{c['detail']}{_RESET}{tail}")

        if c.get("offenders") and not c["pass"]:
            for off in c["offenders"][:5]:
                lines.append(f"      {_DIM}↳ {off}{_RESET}")
            if len(c["offenders"]) > 5:
                lines.append(f"      {_DIM}↳ ... {len(c['offenders']) - 5} more{_RESET}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="neomind-fin-integrity")
    p.add_argument("--layer", choices=["data", "compute", "compliance", "viz"],
                   help="run only checks in this layer")
    p.add_argument("--json", action="store_true",
                   help="emit a JSON report instead of human-readable text")
    p.add_argument("--fail-on-error", action="store_true",
                   help="exit 1 if any check fails (for pre-commit / CI)")
    args = p.parse_args(argv)

    report = run_integrity_check(layer_filter=args.layer)

    if args.json:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(_format_terminal(report))

    if args.fail_on_error and not report["all_pass"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
