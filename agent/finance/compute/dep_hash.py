"""``dep_hash`` — content-hash composition for one compute step.

Recipe (matches docs/design/2026-04-26_provenance-architecture.md §
"dep_hash composition"):

    dep_hash = sha256_hex(
        "v1|"
      + sorted_join(blob.sha256 for blob in inputs)
      + "|" + prompt_template_version
      + "|" + llm_model_id + "@" + temperature
      + "|" + sample_strategy_serialized
      + "|" + taxonomy_version
      + "|" + code_git_sha
      + "|" + sorted_join(extra k=v)
    )

Every component is a string serialised the same way every time, so
two structurally identical ``DepHashInputs`` always produce the same
hash.  Any one-byte difference produces a different hash.  This is
strict by design — the operator explicitly accepted the LLM-cost
trade-off.

The ``diff_inputs`` helper exists so a "why did the cache miss?" CLI
or UI can answer "code_git_sha changed: aabbccdd → eeff0011" without
re-hashing the whole structure.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


# Bump when the composition recipe itself changes.  Stored
# inside the hash so "v1" hashes can never collide with "v2" hashes.
DEP_HASH_SCHEMA = "v1"


@dataclass(frozen=True)
class DepHashInputs:
    """Immutable bundle of every byte that influences one compute
    step's output.  Add fields here only when the composition recipe
    changes — and bump ``DEP_HASH_SCHEMA`` when you do.

    All string fields default to ``""`` so a step that doesn't use
    LLMs (e.g. a pure deterministic detector) can pass just
    ``blob_hashes`` + ``code_git_sha``.
    """

    # Sorted hex SHA-256s of every raw blob this step reads.  The
    # caller must canonicalise — we sort defensively but won't
    # de-duplicate (duplicates indicate a bug in the caller).
    blob_hashes:             Tuple[str, ...] = ()
    prompt_template_version: str             = ""
    llm_model_id:            str             = ""
    llm_temperature:         float           = 0.0
    sample_strategy:         str             = ""   # e.g. "top_n_relevance:30:seed=4711"
    taxonomy_version:        str             = ""
    code_git_sha:            str             = ""   # short ok (≥8 chars)
    # Open extension slot: any ``(key, value)`` pair the step wants
    # baked into the hash.  Use sparingly — every distinct key is a
    # cache-key dimension.  Values must be string-coercible.
    extra:                   Tuple[Tuple[str, str], ...] = ()

    def canonical(self) -> str:
        """Return the deterministic input string that's hashed.
        Exposed for debugging / "what got hashed?" diagnostics.
        """
        # Always sort blob hashes — order shouldn't matter (a step
        # that reads {A, B} reads the same data as one reading
        # {B, A}).  Sorted tuple normalisation is part of the
        # canonical form.
        sorted_blobs = "|".join(sorted(self.blob_hashes))
        sorted_extra = ",".join(
            f"{k}={v}" for k, v in sorted(self.extra)
        )
        # Format temperature with fixed precision so 0.3 vs 0.30
        # don't accidentally produce different hashes.
        temp_str = f"{float(self.llm_temperature):.6f}"
        parts = [
            DEP_HASH_SCHEMA,
            sorted_blobs,
            self.prompt_template_version,
            f"{self.llm_model_id}@{temp_str}",
            self.sample_strategy,
            self.taxonomy_version,
            self.code_git_sha,
            sorted_extra,
        ]
        return "|".join(parts)


def compute_dep_hash(inputs: DepHashInputs) -> str:
    """Pure SHA-256 of the canonical input string.  Always 64 chars."""
    raw = inputs.canonical().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── Diff diagnostics ──────────────────────────────────────────────


# Which fields we surface in diff output, in display order.  "extra"
# is rendered as a per-key diff so the message stays readable.
_FIELD_ORDER: Sequence[str] = (
    "blob_hashes",
    "prompt_template_version",
    "llm_model_id",
    "llm_temperature",
    "sample_strategy",
    "taxonomy_version",
    "code_git_sha",
)


def _format_blob_hashes(hashes: Tuple[str, ...]) -> str:
    """Compact rendering for blob-hash diffs: '<n> blobs: aabbcc..., ...'"""
    short = [h[:8] + "…" for h in sorted(hashes)[:5]]
    suffix = f", +{max(0, len(hashes) - 5)} more" if len(hashes) > 5 else ""
    if not hashes:
        return "(empty)"
    return f"{len(hashes)} blob(s): {', '.join(short)}{suffix}"


def diff_inputs(a: DepHashInputs, b: DepHashInputs) -> List[str]:
    """Human-readable bullet list of fields where ``a`` and ``b`` differ.

    Returns an empty list when ``a == b`` (the cache would hit).  If
    they only differ in ``extra``, lists each differing key separately
    so "why did this miss?" answers like ``extra[seed]: 4711 → 4712``
    are visible without re-reading the design doc.
    """
    if a == b:
        return []

    out: List[str] = []
    for fname in _FIELD_ORDER:
        av, bv = getattr(a, fname), getattr(b, fname)
        if av == bv:
            continue
        if fname == "blob_hashes":
            # Collapse blob_hashes diff: count + symmetric difference
            sa, sb = set(av), set(bv)
            added   = sorted(sb - sa)
            removed = sorted(sa - sb)
            parts: List[str] = []
            if removed:
                parts.append(f"-{len(removed)} ({', '.join(h[:8]+'…' for h in removed[:3])}{'…' if len(removed)>3 else ''})")
            if added:
                parts.append(f"+{len(added)} ({', '.join(h[:8]+'…' for h in added[:3])}{'…' if len(added)>3 else ''})")
            out.append(f"blob_hashes: {_format_blob_hashes(av)} → {_format_blob_hashes(bv)} [{'; '.join(parts)}]")
        else:
            out.append(f"{fname}: {av!r} → {bv!r}")

    # extra (treated as dict for per-key diff)
    da = dict(a.extra)
    db = dict(b.extra)
    keys = sorted(set(da) | set(db))
    for k in keys:
        if da.get(k) != db.get(k):
            out.append(f"extra[{k}]: {da.get(k)!r} → {db.get(k)!r}")

    return out


# ── Convenience: snapshot inputs for serialisation ────────────────


def inputs_to_dict(inputs: DepHashInputs) -> dict:
    """Convert to JSON-serialisable dict (used by the cache when
    storing ``params_json``)."""
    d = dataclasses.asdict(inputs)
    # asdict turns the tuple-of-tuples ``extra`` into a list-of-lists,
    # which round-trips fine but loses the dict semantics. Normalise
    # to a plain dict in JSON for human inspection.
    d["extra"] = {k: v for k, v in inputs.extra}
    d["blob_hashes"] = list(inputs.blob_hashes)
    return d


def inputs_from_dict(d: dict) -> DepHashInputs:
    """Inverse of ``inputs_to_dict``."""
    extra_d = d.get("extra") or {}
    if isinstance(extra_d, list):
        # Legacy: list-of-pairs — accept both shapes.
        extra_t = tuple((str(k), str(v)) for k, v in extra_d)
    else:
        extra_t = tuple((str(k), str(v)) for k, v in extra_d.items())
    return DepHashInputs(
        blob_hashes=             tuple(d.get("blob_hashes") or ()),
        prompt_template_version= str(d.get("prompt_template_version") or ""),
        llm_model_id=            str(d.get("llm_model_id") or ""),
        llm_temperature=         float(d.get("llm_temperature") or 0.0),
        sample_strategy=         str(d.get("sample_strategy") or ""),
        taxonomy_version=        str(d.get("taxonomy_version") or ""),
        code_git_sha=            str(d.get("code_git_sha") or ""),
        extra=                   extra_t,
    )
