"""Phase B4 — strict ``dep_hash`` cache for compute steps.

The compute module sits *between* the raw store (B1-B3) and the
display layer.  Every compute step (observations, themes, calls,
strategy_signals, etc.) is keyed by a content hash of its inputs
(``dep_hash``).  Hits return the stored snapshot; misses re-execute
the step and persist a new ``compute_run``.

Strict cache means: if a single byte of any input changed — a blob,
the prompt template, the model, the sample strategy, the taxonomy,
or the source git sha — the hash differs and we re-execute.  No
fuzzy matching, no "looks similar".  This is by operator design
(see docs/design/2026-04-26_provenance-architecture.md).

Public API
----------
``DepHashInputs``    immutable inputs to one compute step
``compute_dep_hash`` pure hashing function
``diff_inputs``      "what differs between inputs A and B"
``DepCache``         get / put / list backed by ``_dep_index.sqlite``
"""

from .dep_hash import (
    DEP_HASH_SCHEMA,
    DepHashInputs,
    compute_dep_hash,
    diff_inputs,
)
from .cache import (
    DepCache,
    CachedRun,
    open_dep_cache,
)
from .codeversion import get_code_git_sha
from .validation import (
    ValidationCheck,
    ValidationReport,
    ValidationStore,
    VALID_STATES,
    VALID_STEPS,
    passing,
    warn,
    failing,
    unknown,
    aggregate_checks,
    algorithm_checks_for_observations,
    llm_checks_for_themes,
    llm_checks_for_calls,
)

__all__ = [
    "DEP_HASH_SCHEMA",
    "DepHashInputs",
    "compute_dep_hash",
    "diff_inputs",
    "DepCache",
    "CachedRun",
    "open_dep_cache",
    "get_code_git_sha",
    # B7 validation
    "ValidationCheck",
    "ValidationReport",
    "ValidationStore",
    "VALID_STATES",
    "VALID_STEPS",
    "passing",
    "warn",
    "failing",
    "unknown",
    "aggregate_checks",
    "algorithm_checks_for_observations",
    "llm_checks_for_themes",
    "llm_checks_for_calls",
]
