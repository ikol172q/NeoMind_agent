"""NeoMind Golden Dataset Regression Testing

Maintains a "golden dataset" of known-good input/output pairs.
Before any self-edit is applied, the agent must pass >80% of
golden dataset tests to ensure no regression.

Research: Round 4 — golden dataset regression testing provides
a concrete quality floor for self-modifying agents.

No external dependencies — stdlib only.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

GOLDEN_DIR = Path("/data/neomind/golden_dataset")


class GoldenCase:
    """A single golden test case."""

    def __init__(self, case_id: str, category: str,
                 input_data: Dict[str, Any],
                 expected: Dict[str, Any],
                 validator: Optional[Callable] = None,
                 weight: float = 1.0):
        """
        Args:
            case_id: Unique identifier
            category: Test category (learning, cost, safety, prompt, etc.)
            input_data: Input to the function under test
            expected: Expected output (for comparison)
            validator: Custom validation function(actual, expected) -> bool
            weight: How much this case counts (default 1.0)
        """
        self.case_id = case_id
        self.category = category
        self.input_data = input_data
        self.expected = expected
        self.validator = validator
        self.weight = weight


class GoldenDataset:
    """Manages golden test cases for regression testing.

    Usage:
        dataset = GoldenDataset()

        # Add golden cases
        dataset.add(GoldenCase(
            case_id="cost_001",
            category="cost",
            input_data={"model": "deepseek-chat", "input_tokens": 1000, "output_tokens": 500},
            expected={"cost_min": 0, "cost_max": 0.001},
        ))

        # Run regression test
        results = dataset.run_regression(test_function)
        if results["pass_rate"] < 0.80:
            reject_self_edit()
    """

    def __init__(self, golden_dir: Optional[Path] = None):
        self.golden_dir = golden_dir or GOLDEN_DIR
        self._cases: List[GoldenCase] = []
        self._results_history: List[Dict] = []
        self._load_builtin_cases()

    def add(self, case: GoldenCase) -> None:
        """Add a golden test case."""
        # Check for duplicates
        existing_ids = {c.case_id for c in self._cases}
        if case.case_id in existing_ids:
            self._cases = [c for c in self._cases if c.case_id != case.case_id]
        self._cases.append(case)

    def run_regression(self, test_fn: Callable[[Dict], Dict],
                       category: Optional[str] = None) -> Dict[str, Any]:
        """Run golden dataset regression test.

        Args:
            test_fn: Function that takes input_data and returns actual output
            category: Optional filter by category

        Returns:
            Dict with pass_rate, passed, failed, details
        """
        cases = self._cases
        if category:
            cases = [c for c in cases if c.category == category]

        if not cases:
            return {"pass_rate": 1.0, "passed": 0, "failed": 0, "total": 0}

        results = []
        total_weight = 0
        passed_weight = 0

        for case in cases:
            try:
                actual = test_fn(case.input_data)

                if case.validator:
                    passed = case.validator(actual, case.expected)
                else:
                    passed = self._default_validate(actual, case.expected)

                results.append({
                    "case_id": case.case_id,
                    "category": case.category,
                    "passed": passed,
                    "actual": str(actual)[:200],
                    "expected": str(case.expected)[:200],
                })

                total_weight += case.weight
                if passed:
                    passed_weight += case.weight

            except Exception as e:
                results.append({
                    "case_id": case.case_id,
                    "category": case.category,
                    "passed": False,
                    "error": str(e),
                })
                total_weight += case.weight

        pass_rate = passed_weight / total_weight if total_weight > 0 else 0

        report = {
            "pass_rate": round(pass_rate, 3),
            "passed": sum(1 for r in results if r.get("passed")),
            "failed": sum(1 for r in results if not r.get("passed")),
            "total": len(results),
            "details": results,
            "ts": datetime.now(timezone.utc).isoformat(),
            "threshold": 0.80,
            "meets_threshold": pass_rate >= 0.80,
        }

        self._results_history.append(report)
        if len(self._results_history) > 100:
            self._results_history = self._results_history[-50:]

        return report

    @staticmethod
    def _default_validate(actual: Any, expected: Dict) -> bool:
        """Default validation: check that actual values fall within expected bounds."""
        if isinstance(expected, dict):
            for key, exp_val in expected.items():
                if key.endswith("_min"):
                    base_key = key[:-4]
                    if base_key in actual and actual[base_key] < exp_val:
                        return False
                elif key.endswith("_max"):
                    base_key = key[:-4]
                    if base_key in actual and actual[base_key] > exp_val:
                        return False
                elif key in actual:
                    if actual[key] != exp_val:
                        return False
            return True
        return actual == expected

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get recent regression test results."""
        return [
            {
                "pass_rate": r["pass_rate"],
                "passed": r["passed"],
                "failed": r["failed"],
                "total": r["total"],
                "meets_threshold": r["meets_threshold"],
                "ts": r["ts"],
            }
            for r in self._results_history[-limit:]
        ]

    def save_to_disk(self) -> bool:
        """Persist golden cases to disk."""
        try:
            self.golden_dir.mkdir(parents=True, exist_ok=True)
            cases_data = [
                {
                    "case_id": c.case_id,
                    "category": c.category,
                    "input_data": c.input_data,
                    "expected": c.expected,
                    "weight": c.weight,
                }
                for c in self._cases
            ]
            filepath = self.golden_dir / "golden_cases.json"
            filepath.write_text(json.dumps(cases_data, indent=2, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Failed to save golden dataset: {e}")
            return False

    def load_from_disk(self) -> int:
        """Load golden cases from disk. Returns count loaded."""
        filepath = self.golden_dir / "golden_cases.json"
        if not filepath.exists():
            return 0
        try:
            cases_data = json.loads(filepath.read_text())
            for cd in cases_data:
                self.add(GoldenCase(
                    case_id=cd["case_id"],
                    category=cd["category"],
                    input_data=cd["input_data"],
                    expected=cd["expected"],
                    weight=cd.get("weight", 1.0),
                ))
            return len(cases_data)
        except Exception as e:
            logger.error(f"Failed to load golden dataset: {e}")
            return 0

    # ── Built-in Golden Cases ──────────────────────────

    def _load_builtin_cases(self) -> None:
        """Load NeoMind's standard golden test cases."""

        # Cost calculation cases
        self.add(GoldenCase(
            case_id="cost_001",
            category="cost",
            input_data={
                "model": "deepseek-chat",
                "input_tokens": 10000,
                "output_tokens": 5000,
            },
            expected={
                "cost_min": 0.0,
                "cost_max": 0.01,  # $0.01 max for 15K tokens on cheap model
            },
        ))

        self.add(GoldenCase(
            case_id="cost_002",
            category="cost",
            input_data={
                "model": "deepseek-chat",
                "input_tokens": 0,
                "output_tokens": 0,
            },
            expected={
                "cost": 0.0,
            },
        ))

        # Output token limit cases
        self.add(GoldenCase(
            case_id="token_limit_001",
            category="token_limits",
            input_data={"mode": "chat"},
            expected={"limit": 2000},
        ))

        self.add(GoldenCase(
            case_id="token_limit_002",
            category="token_limits",
            input_data={"mode": "coding"},
            expected={"limit": 4000},
        ))

        self.add(GoldenCase(
            case_id="token_limit_003",
            category="token_limits",
            input_data={"mode": "fin"},
            expected={"limit": 1500},
        ))

        # Model routing cases
        self.add(GoldenCase(
            case_id="routing_001",
            category="routing",
            input_data={
                "complexity": "simple",
                "budget_ok": True,
            },
            expected={
                "model": "deepseek-chat",
            },
        ))

        self.add(GoldenCase(
            case_id="routing_002",
            category="routing",
            input_data={
                "complexity": "complex",
                "budget_ok": True,
            },
            expected={
                "model": "deepseek-reasoner",
            },
        ))

        # Safety cases
        self.add(GoldenCase(
            case_id="safety_001",
            category="safety",
            input_data={
                "target_file": "self_edit.py",
                "action": "modify",
            },
            expected={
                "allowed": False,
            },
        ))

        self.add(GoldenCase(
            case_id="safety_002",
            category="safety",
            input_data={
                "target_file": "learnings.py",
                "action": "add_method",
            },
            expected={
                "allowed": True,
            },
        ))

        # Degradation cases
        self.add(GoldenCase(
            case_id="degradation_001",
            category="degradation",
            input_data={
                "memory_pct": 96,
                "api_failure_rate": 0.0,
            },
            expected={
                "tier": "static",
            },
        ))

        self.add(GoldenCase(
            case_id="degradation_002",
            category="degradation",
            input_data={
                "memory_pct": 50,
                "api_failure_rate": 0.0,
            },
            expected={
                "tier": "live",
            },
        ))

        logger.debug(f"Loaded {len(self._cases)} built-in golden cases")


if __name__ == "__main__":
    # Quick self-test
    ds = GoldenDataset()
    print(f"Loaded {len(ds._cases)} golden cases")

    # Example regression test with a simple test function
    def mock_test(input_data):
        if "model" in input_data and "input_tokens" in input_data:
            cost = (input_data["input_tokens"] * 0.14 +
                    input_data["output_tokens"] * 0.28) / 1_000_000
            return {"cost": cost}
        if "mode" in input_data:
            limits = {"chat": 2000, "coding": 4000, "fin": 1500}
            return {"limit": limits.get(input_data["mode"], 2000)}
        return input_data

    results = ds.run_regression(mock_test, category="cost")
    print(f"Cost tests: {results['pass_rate']*100:.0f}% pass rate")

    results = ds.run_regression(mock_test, category="token_limits")
    print(f"Token limit tests: {results['pass_rate']*100:.0f}% pass rate")
