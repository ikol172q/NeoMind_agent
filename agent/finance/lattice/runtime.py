"""Per-lattice runtime overrides — settings that can be flipped by
the UI without editing YAML or restarting.

Currently:
  - output_language (V6): 'en' or 'zh-CN-mixed'
  - layer budgets (V9):   per-layer max_items / min_members / max_candidates /
                          mmr_lambda, for live experimentation without
                          touching YAML.

Module-level dict is fine for single-user single-process; if we ever
run multi-tenant, this moves to Redis.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from typing import Any, Dict, Optional

from agent.finance.lattice import spec
from agent.finance.lattice.taxonomy import load_taxonomy


_lock = threading.Lock()
_language_override: Optional[str] = None
_budget_override: Optional[spec.LayerBudgets] = None


def get_effective_language() -> str:
    """Return the currently effective output language: the runtime
    override if set, otherwise the value from the YAML. Always a
    valid member of spec.OUTPUT_LANGUAGES (falls back to default on
    unknown input)."""
    with _lock:
        override = _language_override
    if override and override in spec.OUTPUT_LANGUAGES:
        return override
    lang = load_taxonomy().output_language
    return lang if lang in spec.OUTPUT_LANGUAGES else spec.OUTPUT_LANGUAGE_DEFAULT


def set_language_override(lang: Optional[str]) -> str:
    """Set (or clear) the runtime language override. Returns the
    now-effective language so the caller can echo it in an API
    response. Clearing (lang=None or 'clear') falls back to YAML."""
    global _language_override
    with _lock:
        if lang is None or lang in ("clear", "reset", "default", ""):
            _language_override = None
        elif lang in spec.OUTPUT_LANGUAGES:
            _language_override = lang
        else:
            raise ValueError(
                f"language {lang!r} not in spec.OUTPUT_LANGUAGES={spec.OUTPUT_LANGUAGES}"
            )
    return get_effective_language()


def get_language_override() -> Optional[str]:
    """Introspection helper — returns the raw override (may be None)."""
    with _lock:
        return _language_override


# ── V9 layer-budget override ───────────────────────────

def get_effective_budgets() -> spec.LayerBudgets:
    """Return currently-effective layer budgets: runtime override if
    set, otherwise the YAML-derived defaults."""
    with _lock:
        override = _budget_override
    if override is not None:
        return override
    return load_taxonomy().layer_budgets


def set_budget_override(raw: Optional[Dict[str, Any]]) -> spec.LayerBudgets:
    """Set (or clear) the runtime budget override.

    `raw` is the same shape the YAML `layer_budgets:` block expects,
    e.g. {"themes": {"max_items": 7}, "calls": {"max_candidates": 6}}.
    Pass None / {} to clear the override (falls back to YAML).

    Returns the now-effective budgets so the caller can echo them.
    Raises ValueError on invalid values (delegates to spec.parse_layer_budgets).
    """
    global _budget_override
    if raw is None or raw == {}:
        with _lock:
            _budget_override = None
        return get_effective_budgets()
    # Merge onto YAML-loaded defaults so partial overrides (e.g. only
    # `themes.max_items`) don't nuke unrelated layers.
    yaml_defaults = load_taxonomy().layer_budgets
    merged = _merge_budgets_dict(yaml_defaults, raw)
    # Validate via the same parser that handles YAML — consistent error
    # messages and bounds.
    parsed = spec.parse_layer_budgets(merged)
    with _lock:
        _budget_override = parsed
    return parsed


def get_budget_override() -> Optional[spec.LayerBudgets]:
    """Raw override (may be None). For introspection endpoints."""
    with _lock:
        return _budget_override


def budget_hash(budgets: spec.LayerBudgets) -> str:
    """Short stable hash of a LayerBudgets instance. Used as a cache-
    key component so different runtime budgets coexist in memory
    instead of busting on every change."""
    d = asdict(budgets)
    blob = json.dumps(d, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:10]


def _merge_budgets_dict(
    base: spec.LayerBudgets, override: Dict[str, Any],
) -> Dict[str, Any]:
    """Produce a dict in parse_layer_budgets' expected shape that is
    the base budgets with `override`'s explicit fields on top. This
    lets a POST specify only `{"themes": {"max_items": 8}}` without
    wiping `calls` / `sub_themes` / `observations`.
    """
    out: Dict[str, Any] = {}
    for layer in ("observations", "sub_themes", "themes", "calls"):
        existing = asdict(getattr(base, layer))
        # Drop None-valued keys so the parser sees only explicit values
        existing = {k: v for k, v in existing.items() if v is not None}
        ov = override.get(layer) or {}
        if not isinstance(ov, dict):
            raise ValueError(f"layer_budgets.{layer} must be a dict")
        merged = {**existing, **{k: v for k, v in ov.items() if v is not None}}
        if merged:
            out[layer] = merged
    return out
