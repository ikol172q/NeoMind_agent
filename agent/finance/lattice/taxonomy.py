"""Tag taxonomy loader + validator.

Reads agent/config/lattice_taxonomy.yaml and exposes the allowed
tag set + the configured L2 theme signatures. This is the only
module that knows the tag grammar — observation generators import
helpers from here to stay schema-safe.

The YAML is the source of truth. Never hardcode a tag string in a
generator without also updating the taxonomy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from agent.finance.lattice import spec

import yaml

logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "lattice_taxonomy.yaml"

# Dimensions that don't enumerate values (free-form identifiers).
# `symbol:AAPL`, `sector:Consumer Discretionary`, `position:NVDA` —
# the value is inherited from the world, not a closed enum.
_OPEN_DIMENSIONS = {"symbol", "sector", "position"}


@dataclass(frozen=True)
class ThemeSignature:
    id: str
    title: str
    any_of: frozenset[str] = field(default_factory=frozenset)
    all_of: frozenset[str] = field(default_factory=frozenset)
    min_members: int = 1

    def matches(self, tags: Iterable[str]) -> bool:
        """Does this signature match an observation's tags?"""
        tagset = set(tags)
        if self.all_of and not self.all_of.issubset(tagset):
            return False
        if self.any_of and tagset.isdisjoint(self.any_of):
            return False
        return True


@dataclass(frozen=True)
class Taxonomy:
    version: int
    dimensions: Dict[str, Optional[frozenset[str]]]   # None = open (symbol, sector, position)
    themes: List[ThemeSignature]
    # Optional L1.5 layer between observations and themes. Empty list
    # means n=3 (the default). A non-empty list engages n=4 — the
    # lattice pipeline picks the config up automatically; no code
    # change is needed (D6 gate: YAML switch).
    sub_themes: List[ThemeSignature] = field(default_factory=list)
    # Output language for LLM-authored narratives / calls. V5.
    # Must be one of spec.OUTPUT_LANGUAGES; falls back to default
    # on unknown input. Edit the YAML's top-level `output_language`
    # field to switch.
    output_language: str = spec.OUTPUT_LANGUAGE_DEFAULT

    def is_valid_tag(self, tag: str) -> bool:
        """True if `tag` matches a declared dimension + its enum."""
        if ":" not in tag:
            return False
        key, _, value = tag.partition(":")
        if key not in self.dimensions:
            return False
        allowed = self.dimensions[key]
        if allowed is None:
            return bool(value.strip())
        return value in allowed

    def reject_invalid(self, tags: Iterable[str]) -> List[str]:
        """Return the subset of tags that pass the taxonomy check, and
        log anything rejected. We prefer 'silently drop invalid' over
        'raise', so a taxonomy drift doesn't break the entire layer —
        but log loudly."""
        out: List[str] = []
        for t in tags:
            if self.is_valid_tag(t):
                out.append(t)
            else:
                logger.warning("lattice taxonomy: rejected invalid tag %r", t)
        return out


def _freeze_values(raw_dim: Dict[str, Any]) -> Optional[frozenset[str]]:
    if "valid_values" not in raw_dim:
        return None
    return frozenset(str(v) for v in raw_dim["valid_values"])


_cached_taxonomy: Optional[Taxonomy] = None


def load_taxonomy(path: Optional[Path] = None) -> Taxonomy:
    """Load the taxonomy YAML. Cached after first call — reload requires
    process restart. Testing can pass a different path."""
    global _cached_taxonomy
    if _cached_taxonomy is not None and path is None:
        return _cached_taxonomy

    target = path or _TAXONOMY_PATH
    with target.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "version" not in raw:
        raise ValueError(f"taxonomy at {target} is malformed (missing version)")

    version = int(raw["version"])
    dims_raw = raw.get("dimensions") or {}
    dimensions: Dict[str, Optional[frozenset[str]]] = {}
    for name, body in dims_raw.items():
        if name in _OPEN_DIMENSIONS:
            dimensions[name] = None
        else:
            dimensions[name] = _freeze_values(body)

    def _parse_sigs(raw_list) -> List[ThemeSignature]:
        sigs: List[ThemeSignature] = []
        for t in raw_list or []:
            sig_raw = t.get("signature") or {}
            sigs.append(ThemeSignature(
                id=t["id"],
                title=t["title"],
                any_of=frozenset(sig_raw.get("any_of") or []),
                all_of=frozenset(sig_raw.get("all_of") or []),
                min_members=int(t.get("min_members", 1)),
            ))
        return sigs

    themes = _parse_sigs(raw.get("themes"))
    sub_themes = _parse_sigs(raw.get("sub_themes"))

    raw_lang = str(raw.get("output_language") or spec.OUTPUT_LANGUAGE_DEFAULT).strip()
    if raw_lang not in spec.OUTPUT_LANGUAGES:
        logger.warning(
            "lattice taxonomy: unknown output_language %r; falling back to %r",
            raw_lang, spec.OUTPUT_LANGUAGE_DEFAULT,
        )
        raw_lang = spec.OUTPUT_LANGUAGE_DEFAULT

    tax = Taxonomy(
        version=version,
        dimensions=dimensions,
        themes=themes,
        sub_themes=sub_themes,
        output_language=raw_lang,
    )
    if path is None:
        _cached_taxonomy = tax
    return tax


# ── Tag-building helpers (observation generators use these) ────

def tag_symbol(sym: str) -> str:
    return f"symbol:{sym.upper()}"


def tag_market(market: str) -> str:
    return f"market:{market.upper()}"


def tag_sector(sector_name: str) -> str:
    return f"sector:{sector_name}"


def tag_position(sym: str) -> str:
    return f"position:{sym.upper()}"


def tag_kv(key: str, value: str) -> str:
    return f"{key}:{value}"
