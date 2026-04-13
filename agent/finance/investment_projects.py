"""
Investment project tracking + data firewall.

All real investment data (trade logs, analyses, journals, KPI snapshots,
backtest outputs) for fin persona projects lives under
``~/Desktop/Investment/<project_id>/`` — NEVER inside the NeoMind repo.
This module is the single write path; it validates every destination is
under the Investment root and rejects anything else.

Directory layout (per project):

    ~/Desktop/Investment/<project_id>/
    ├── README.md          hypothesis + success criteria + stop conditions
    ├── watchlist.yaml     symbols tracked under this project
    ├── trades.jsonl       append-only trade log
    ├── analyses/          one JSON file per agent analysis call
    ├── backtests/         historical backtest outputs
    ├── journal/           daily markdown reflections
    └── kpi/               rolling KPI snapshots (weekly.jsonl)

Root override for tests: set env var ``NEOMIND_INVESTMENT_ROOT`` to redirect
all writes to a tmp path. Fleet runtime MUST NOT set this — production code
must always write to the user's Desktop/Investment folder.

Contract: plans/2026-04-12_fin_deepening_fusion_plan.md §3 (data firewall).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "get_investment_root",
    "get_project_dir",
    "register_project",
    "append_trade",
    "write_analysis",
    "log_journal",
    "kpi_snapshot",
    "list_projects",
    "InvestmentPathError",
]

# project_id must start with an alphanumeric, then 1-39 of [a-z0-9_-]
_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
# Ticker-style symbols for analysis filenames
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
# Forbidden substrings anywhere in the resolved destination path
_FORBIDDEN_SEGMENTS = (".git", "__pycache__", "NeoMind_agent")


class InvestmentPathError(ValueError):
    """Raised when a write target escapes the Investment root or is forbidden."""


def get_investment_root() -> Path:
    """Return the Investment root directory (resolved, absolute).

    Honors ``NEOMIND_INVESTMENT_ROOT`` env var for tests; defaults to
    ``~/Desktop/Investment`` otherwise.
    """
    env = os.environ.get("NEOMIND_INVESTMENT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / "Desktop" / "Investment").resolve()


def _validate_project_id(project_id: str) -> None:
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.match(project_id):
        raise InvestmentPathError(
            f"Invalid project_id {project_id!r}. "
            f"Must match {_PROJECT_ID_RE.pattern} (2-40 chars, starts alnum, "
            f"then a-z/0-9/_/-)."
        )


def _validate_destination(target: Path, root: Path) -> Path:
    """Ensure ``target`` resolves under ``root`` and contains no forbidden segments.

    Returns the resolved target. Raises ``InvestmentPathError`` otherwise.
    """
    resolved = target.resolve() if target.exists() else (
        target.parent.resolve() / target.name
    )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise InvestmentPathError(
            f"Path {resolved} escapes Investment root {root}"
        ) from exc
    resolved_str = str(resolved)
    for bad in _FORBIDDEN_SEGMENTS:
        if bad in resolved_str:
            raise InvestmentPathError(
                f"Forbidden path segment {bad!r} in {resolved}"
            )
    return resolved


def get_project_dir(project_id: str) -> Path:
    """Return the absolute path of a project directory. Does NOT create it."""
    _validate_project_id(project_id)
    root = get_investment_root()
    return _validate_destination(root / project_id, root)


def register_project(project_id: str, description: str = "") -> Path:
    """Create (idempotently) the scaffold for an investment project.

    On first call: creates the directory tree, README.md, and watchlist.yaml.
    On subsequent calls with a non-empty description: overwrites README.md.
    """
    proj = get_project_dir(project_id)
    proj.mkdir(parents=True, exist_ok=True)
    for sub in ("analyses", "backtests", "journal", "kpi"):
        (proj / sub).mkdir(exist_ok=True)

    readme = proj / "README.md"
    if description or not readme.exists():
        body = description.strip() if description else "_No description yet._"
        readme.write_text(
            f"# {project_id}\n\n"
            f"**Registered:** {datetime.now(timezone.utc).isoformat()}\n\n"
            f"## Hypothesis\n\n{body}\n\n"
            f"## Success criteria\n\n_TBD_\n\n"
            f"## Stop conditions\n\n_TBD_\n",
            encoding="utf-8",
        )

    watchlist = proj / "watchlist.yaml"
    if not watchlist.exists():
        watchlist.write_text(
            "# Symbols tracked under this project.\n"
            "# Edit by hand or via the fin persona /watchlist command.\n"
            "symbols: []\n",
            encoding="utf-8",
        )
    return proj


def _require_registered(project_id: str) -> Path:
    proj = get_project_dir(project_id)
    if not proj.exists():
        raise FileNotFoundError(
            f"Project {project_id!r} is not registered. "
            f"Call register_project({project_id!r}) first."
        )
    return proj


def _atomic_append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    """Append one JSON object as a line, with POSIX advisory file lock."""
    root = get_investment_root()
    _validate_destination(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def append_trade(project_id: str, trade: Dict[str, Any]) -> None:
    """Append a trade record to ``<project>/trades.jsonl``.

    Adds ``_written_at`` (UTC ISO8601) to every record. The caller owns the
    rest of the schema (symbol / side / qty / price / strategy / ...).
    """
    proj = _require_registered(project_id)
    record = {**trade, "_written_at": datetime.now(timezone.utc).isoformat()}
    _atomic_append_jsonl(proj / "trades.jsonl", record)


def write_analysis(
    project_id: str, symbol: str, signal: Dict[str, Any]
) -> Path:
    """Write a single agent-analysis JSON file under ``<project>/analyses/``.

    Filename: ``YYYY-MM-DD_HHMMSS_<SYMBOL>.json``.
    """
    proj = _require_registered(project_id)
    symbol_upper = symbol.upper().strip()
    if not _SYMBOL_RE.match(symbol_upper):
        raise InvestmentPathError(f"Invalid symbol {symbol!r}")

    now = datetime.now()
    # Include microseconds so rapid successive writes of the same symbol
    # (e.g. a fin worker batch-analyzing) don't collide on a 1-second
    # filename. Format: YYYY-MM-DD_HHMMSS_microseconds_SYMBOL.json
    filename = (
        f"{now.strftime('%Y-%m-%d_%H%M%S')}_"
        f"{now.microsecond:06d}_{symbol_upper}.json"
    )
    target = _validate_destination(proj / "analyses" / filename, get_investment_root())
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_id": project_id,
        "symbol": symbol_upper,
        "written_at": now.isoformat(),
        "signal": signal,
    }
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def log_journal(project_id: str, markdown: str) -> Path:
    """Append a markdown block to ``<project>/journal/<YYYY-MM-DD>.md``.

    Successive blocks on the same day are separated by a horizontal rule.
    """
    proj = _require_registered(project_id)
    today = datetime.now().strftime("%Y-%m-%d")
    target = _validate_destination(
        proj / "journal" / f"{today}.md", get_investment_root()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = "\n---\n\n" if target.exists() and target.stat().st_size > 0 else ""
    with open(target, "a", encoding="utf-8") as f:
        f.write(prefix + markdown.rstrip() + "\n")
    return target


def kpi_snapshot(project_id: str, metrics: Dict[str, Any]) -> None:
    """Append a KPI snapshot to ``<project>/kpi/weekly.jsonl``."""
    proj = _require_registered(project_id)
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **metrics,
    }
    _atomic_append_jsonl(proj / "kpi" / "weekly.jsonl", record)


def list_projects() -> List[str]:
    """List registered project IDs (excluding ``_meta`` and hidden dirs)."""
    root = get_investment_root()
    if not root.exists():
        return []
    out: List[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        if not (entry / "README.md").exists():
            continue
        # Also enforce the id regex — stray dirs are not "registered projects"
        if _PROJECT_ID_RE.match(entry.name):
            out.append(entry.name)
    return out
