PY := .venv/bin/python
PYTEST := $(PY) -m pytest

.PHONY: validate-algorithm-only validate-lattice validate-lattice-full \
        validate-viz-only

# V1 scope: spec contracts + formula-level unit tests + property tests.
# Pure Python, no backend required. Intended for pre-commit.
# Scoped to tests/test_lattice_*.py because two unrelated test files
# (test_search.py, test_token_budget.py) have pre-existing syntax
# errors that break blanket collection; they're tracked separately.
validate-algorithm-only:
	$(PYTEST) tests/test_lattice_spec_contract.py tests/test_lattice_formulas.py -m lattice_fast -v

# V1 + V2 scope: + endpoint coherence + graph-algorithm recompute.
# Requires a live backend.
validate-lattice:
	$(PYTEST) -m "lattice_fast or lattice_slow" -v

# V1 + V2 + V3 + V4 scope: + fixture drift + judge baseline.
# Nightly or on demand; takes several minutes.
validate-lattice-full:
	$(PYTEST) -m "lattice_fast or lattice_slow or lattice_drift" -v
	$(PY) tools/eval/lattice_judge.py --layer all --n 3 \
		--report /tmp/lattice_judge_latest.md

# UI-only subset (V3 onwards)
validate-viz-only:
	$(PYTEST) tests/test_web_lattice_viz.py -v

.DEFAULT_GOAL := validate-algorithm-only
