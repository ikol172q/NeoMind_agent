"""Per-lattice runtime overrides — settings that can be flipped by
the UI without editing YAML or restarting.

Currently just holds the active output_language. Simpler than
threading context through every generate_narrative() / generate_calls()
call. The dashboard is single-user single-process so a module-level
dict is fine; if we ever run multi-tenant this moves to Redis.
"""
from __future__ import annotations

import threading
from typing import Optional

from agent.finance.lattice import spec
from agent.finance.lattice.taxonomy import load_taxonomy


_lock = threading.Lock()
_language_override: Optional[str] = None


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
