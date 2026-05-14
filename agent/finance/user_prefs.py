"""User preferences — Phase 4 (Decision Context Dimensions thresholds).

Single key/value store for thresholds the chain panel surfaces as
INFORMATION (not enforcement gates — per plan §2 philosophy).

Seeded defaults (only inserted if key absent):
  max_position_pct      = 15      # alert when single ticker > 15% of portfolio
  max_sector_pct        = 50      # alert when sector > 50% of portfolio
  benchmark_ticker      = SPY     # default benchmark for vs-benchmark calc
  review_window_core    = 14      # days; "stale thesis" warning for Core
  review_window_adjacent= 30      # days; same for Adjacent
  review_window_watching= 90      # days; same for Watching

Endpoints:
  GET    /api/preferences          — list all
  PATCH  /api/preferences/{key}    — update one
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


_DEFAULTS: Dict[str, str] = {
    "max_position_pct":         "15",
    "max_sector_pct":           "50",
    "benchmark_ticker":         "SPY",
    "review_window_core":       "14",
    "review_window_adjacent":   "30",
    "review_window_watching":   "90",
}

# Type-coerce keys: str → int / str → str so callers don't have to remember.
_PREF_TYPES: Dict[str, type] = {
    "max_position_pct":         int,
    "max_sector_pct":           int,
    "benchmark_ticker":         str,
    "review_window_core":       int,
    "review_window_adjacent":   int,
    "review_window_watching":   int,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_defaults() -> None:
    """Insert any missing default preferences. Idempotent — safe to
    call at every dashboard startup. Existing values are preserved."""
    ensure_schema()
    now = _now()
    with connect() as conn:
        for k, v in _DEFAULTS.items():
            conn.execute(
                "INSERT INTO user_preferences (pref_key, pref_value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(pref_key) DO NOTHING",
                (k, v, now),
            )


def get_pref(key: str) -> Any:
    """Return typed value for a single preference. Falls back to
    default if missing (defensive — should not happen post-seed)."""
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT pref_value FROM user_preferences WHERE pref_key = ?", (key,)
        ).fetchone()
    raw = row["pref_value"] if row else _DEFAULTS.get(key)
    if raw is None:
        return None
    typ = _PREF_TYPES.get(key, str)
    try:
        if typ is int:
            return int(raw)
        return raw
    except (TypeError, ValueError):
        return raw


def list_prefs() -> Dict[str, Any]:
    """All known prefs (seeded + custom). Returns typed values."""
    ensure_schema()
    out: Dict[str, Any] = {}
    with connect() as conn:
        rows = conn.execute(
            "SELECT pref_key, pref_value FROM user_preferences"
        ).fetchall()
    for r in rows:
        k = r["pref_key"]
        typ = _PREF_TYPES.get(k, str)
        try:
            out[k] = int(r["pref_value"]) if typ is int else r["pref_value"]
        except (TypeError, ValueError):
            out[k] = r["pref_value"]
    # Backfill any defaults that weren't yet seeded
    for k, v in _DEFAULTS.items():
        if k not in out:
            typ = _PREF_TYPES.get(k, str)
            out[k] = int(v) if typ is int else v
    return out


def set_pref(key: str, value: Any) -> Any:
    """Upsert a preference. Returns the typed read-back value."""
    if key not in _DEFAULTS:
        raise HTTPException(400, f"unknown preference key {key!r} (known: {sorted(_DEFAULTS)})")
    # Validate type
    typ = _PREF_TYPES.get(key, str)
    if typ is int:
        try:
            iv = int(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{key} must be an integer; got {value!r}")
        # Sanity bounds for percentage prefs
        if key in ("max_position_pct", "max_sector_pct") and not (0 < iv <= 100):
            raise HTTPException(400, f"{key} must be in (0, 100]; got {iv}")
        if key.startswith("review_window_") and not (1 <= iv <= 365):
            raise HTTPException(400, f"{key} must be in [1, 365] days; got {iv}")
        stored = str(iv)
    else:
        stored = str(value).strip().upper() if key == "benchmark_ticker" else str(value)
    ensure_schema()
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO user_preferences (pref_key, pref_value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(pref_key) DO UPDATE SET "
            "  pref_value = excluded.pref_value, updated_at = excluded.updated_at",
            (key, stored, now),
        )
    return get_pref(key)


# ── Pydantic ────────────────────────────────────────────────────────


class PrefPatchBody(BaseModel):
    value: Any   # int or str depending on key


# ── Router ──────────────────────────────────────────────────────────


def build_user_prefs_router() -> APIRouter:
    router = APIRouter(prefix="/api/preferences", tags=["user-preferences"])

    @router.get("")
    def list_endpoint() -> Dict[str, Any]:
        return {"preferences": list_prefs(), "fetched_at": _now()}

    @router.patch("/{key}")
    def patch_endpoint(key: str, body: PrefPatchBody) -> Dict[str, Any]:
        new_val = set_pref(key, body.value)
        return {"ok": True, "key": key, "value": new_val}

    return router
