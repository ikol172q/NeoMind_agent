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
	$(PYTEST) \
		tests/test_lattice_spec_contract.py \
		tests/test_lattice_formulas.py \
		tests/test_lattice_graph_builder.py \
		tests/test_lattice_drift.py \
		tests/test_lattice_bilingual.py \
		tests/test_lattice_trace.py \
		tests/test_lattice_budgets.py \
		-m "lattice_fast and not lattice_drift and not lattice_slow" -v

# V1 + V2 scope: + endpoint coherence + graph-algorithm recompute.
# Requires a live backend on 127.0.0.1:8001.
validate-lattice:
	$(PYTEST) \
		tests/test_lattice_spec_contract.py \
		tests/test_lattice_formulas.py \
		tests/test_lattice_graph_builder.py \
		tests/test_lattice_endpoint_coherence.py \
		-v

# V1 + V2 + V3 + V4 scope: + fixture drift + judge baseline.
# Nightly or on demand; takes several minutes (runs live judge).
validate-lattice-full:
	$(PYTEST) \
		tests/test_lattice_spec_contract.py \
		tests/test_lattice_formulas.py \
		tests/test_lattice_graph_builder.py \
		tests/test_lattice_endpoint_coherence.py \
		tests/test_lattice_drift.py \
		tests/test_web_lattice_viz.py \
		-v
	$(PY) tools/eval/lattice_judge.py --layer all --n 3 \
		--report /tmp/lattice_judge_latest.md

# Just the drift fixtures + judge baseline regression.
# Use after pulling changes or before releases.
validate-lattice-drift:
	$(PYTEST) tests/test_lattice_drift.py -v

# UI-only subset (V3 onwards)
validate-viz-only:
	$(PYTEST) tests/test_web_lattice_viz.py -v

.DEFAULT_GOAL := validate-algorithm-only
