"""Unit tests for agent.evolution.transaction.EvolutionTransaction.

Covers:
  - Lock acquisition + release (single + concurrent)
  - Apply → smoke → commit happy path
  - Apply failure → automatic rollback
  - Smoke failure → automatic rollback (when raised inside with-block)
  - Manual rollback
  - Stale lock cleanup
  - Intent file lifecycle
  - File-count guardrail

Does NOT touch the real /app or /data/neomind paths — uses tmp_path with
monkeypatching of REPO_DIR/DATA_DIR.

These tests must run in this checkout (not inside Docker), so they monkey-patch
SelfEditor.REPO_DIR and the transaction module's DATA_DIR/LOCK_FILE/INTENT_FILE
to point at a temporary directory.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Tuple

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a tiny git repo in tmp_path and point SelfEditor at it.

    Yields:
        Path: the repo directory
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    # Initialize a fresh git repo with one commit
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)

    # Patch SelfEditor and transaction module to use this temp space
    from agent.evolution import self_edit, transaction

    monkeypatch.setattr(self_edit.SelfEditor, "REPO_DIR", repo)
    monkeypatch.setattr(self_edit.SelfEditor, "DATA_DIR", data / "selfedit")
    # Disable the daily limit during tests
    monkeypatch.setattr(self_edit.SelfEditor, "MAX_EDITS_PER_DAY", 100)
    # Disable the safe-mode env var if user has it set
    monkeypatch.delenv("NEOMIND_SAFE_MODE", raising=False)

    monkeypatch.setattr(transaction, "REPO_DIR", repo)
    monkeypatch.setattr(transaction, "DATA_DIR", data / "evolution")
    monkeypatch.setattr(transaction, "LOCK_FILE", data / "evolution" / "transaction.lock")
    monkeypatch.setattr(transaction, "INTENT_FILE", data / "evolution" / "evolution_intent.json")
    monkeypatch.setattr(transaction, "TXN_LOG", data / "evolution" / "transactions.jsonl")

    yield repo


# ── Helper: a minimal valid Python file ──────────────────────────────


SAFE_MODULE_TEMPLATE = '''"""Test module {n}."""
import logging

logger = logging.getLogger(__name__)


def hello_{n}():
    """Return a greeting."""
    try:
        return "hello {n}"
    except Exception:
        logger.exception("hello_{n} failed")
        return None
'''


def _make_module(n: int) -> str:
    return SAFE_MODULE_TEMPLATE.format(n=n)


# ── Tests ────────────────────────────────────────────────────────────


def test_imports():
    """Sanity: both modules import without error."""
    from agent.evolution import transaction, post_restart_verify  # noqa
    assert hasattr(transaction, "EvolutionTransaction")
    assert hasattr(post_restart_verify, "verify_pending_evolution")


def test_lock_acquired_and_released(tmp_repo):
    from agent.evolution.transaction import EvolutionTransaction, LOCK_FILE
    assert not LOCK_FILE.exists()
    with EvolutionTransaction(reason="test lock") as txn:
        assert LOCK_FILE.exists()
    assert not LOCK_FILE.exists()


def test_apply_smoke_commit_happy_path(tmp_repo):
    from agent.evolution.transaction import EvolutionTransaction, INTENT_FILE

    # Need to create the package directory first since SelfEditor only edits
    # files inside the repo (and we're testing via a fake repo)
    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add fake_pkg"], cwd=str(tmp_repo), check=True)

    with EvolutionTransaction(reason="happy path") as txn:
        ok, msg = txn.apply("fake_pkg/mod_a.py", _make_module(1))
        assert ok, msg
        ok, msg = txn.apply("fake_pkg/mod_b.py", _make_module(2))
        assert ok, msg

        # Disable regression + telegram gates here — the tmp repo has no
        # pytest targets and the host venv has no python-telegram-bot.
        # Both gates are exercised by their dedicated tests below.
        ok, msg = txn.smoke_test(run_regression=False, run_telegram_dry_run=False)
        # smoke uses subprocess that imports modules — fake_pkg.mod_a should
        # work because the file exists on disk and PYTHONPATH includes the
        # tmp repo. Note: this requires the subprocess's cwd to be the repo
        # (which transaction.smoke_test does) and PYTHONPATH including it.
        assert ok, f"smoke failed: {msg}"

        ok, msg = txn.commit()
        assert ok, msg

    # Intent file should still exist (commit writes it; only rollback removes)
    assert INTENT_FILE.exists()
    intent = INTENT_FILE.read_text()
    assert "happy path" in intent
    assert "fake_pkg/mod_a.py" in intent
    assert "fake_pkg/mod_b.py" in intent


def test_apply_invalid_python_rolls_back(tmp_repo):
    from agent.evolution.transaction import EvolutionTransaction, INTENT_FILE

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(tmp_repo), check=True)

    with pytest.raises(RuntimeError, match="invalid"):
        with EvolutionTransaction(reason="invalid python test") as txn:
            ok, msg = txn.apply("fake_pkg/mod_a.py", _make_module(1))
            assert ok

            # Apply something with a syntax error → SelfEditor rejects
            ok, msg = txn.apply("fake_pkg/mod_bad.py", "def broken(:\n  pass\n")
            assert not ok
            raise RuntimeError("invalid python encountered")

    # After rollback, intent file should NOT exist
    assert not INTENT_FILE.exists()
    # And mod_a.py should NOT exist (git reset wiped it)
    assert not (tmp_repo / "fake_pkg" / "mod_a.py").exists()
    assert not (tmp_repo / "fake_pkg" / "mod_bad.py").exists()


def test_concurrent_lock_blocks_second_transaction(tmp_repo):
    from agent.evolution.transaction import EvolutionTransaction

    txn1 = EvolutionTransaction(reason="first").__enter__()
    try:
        with pytest.raises(BlockingIOError, match="Another evolution"):
            EvolutionTransaction(reason="second").__enter__()
    finally:
        txn1.__exit__(None, None, None)

    # After release, a new transaction can start
    with EvolutionTransaction(reason="third") as t3:
        assert t3.tag.startswith("evolve-")


def test_max_files_per_transaction(tmp_repo, monkeypatch):
    from agent.evolution.transaction import EvolutionTransaction, MAX_FILES_PER_TRANSACTION

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(tmp_repo), check=True)

    with pytest.raises(RuntimeError, match="limit reached"):
        with EvolutionTransaction(reason="too many files") as txn:
            for i in range(MAX_FILES_PER_TRANSACTION):
                ok, _ = txn.apply(f"fake_pkg/mod_{i}.py", _make_module(i))
                assert ok
            # The N+1 apply must be rejected
            ok, msg = txn.apply("fake_pkg/mod_extra.py", _make_module(99))
            assert not ok
            assert "limit reached" in msg
            raise RuntimeError("limit reached")


def test_rollback_clears_intent_file(tmp_repo):
    from agent.evolution.transaction import EvolutionTransaction, INTENT_FILE

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(tmp_repo), check=True)

    txn = EvolutionTransaction(reason="manual rollback")
    txn.__enter__()
    try:
        txn.apply("fake_pkg/mod_a.py", _make_module(1))
        txn.commit()
        assert INTENT_FILE.exists()

        ok, msg = txn.rollback(reason="test")
        assert ok, msg
        assert not INTENT_FILE.exists()
    finally:
        txn.__exit__(None, None, None)


def test_get_pending_intent_returns_none_when_no_file(tmp_repo):
    from agent.evolution.transaction import get_pending_intent
    assert get_pending_intent() is None


def test_post_restart_verify_no_pending(tmp_repo):
    from agent.evolution.post_restart_verify import verify_pending_evolution
    intent, status = verify_pending_evolution()
    assert intent is None
    assert status == "no_pending"


def test_format_user_notification():
    from agent.evolution.post_restart_verify import format_user_notification
    intent = {
        "tag": "evolve-test-123",
        "reason": "add foo",
        "applied_files": ["a.py", "b.py"],
        "verification_message": "all good",
    }
    msg = format_user_notification(intent, "verified")
    assert "evolve-test-123" in msg
    assert "add foo" in msg
    assert "a.py" in msg
    assert "b.py" in msg
    assert "✅" in msg

    msg2 = format_user_notification({**intent, "verification_error": "ImportError: foo"}, "rolled_back")
    assert "⚠️" in msg2
    assert "ImportError" in msg2


# ── Regression gate tests ────────────────────────────────────────────

PASSING_TEST_BODY = (
    "def test_always_passes():\n"
    "    assert 1 + 1 == 2\n"
    "\n"
    "def test_another_pass():\n"
    "    assert 'foo' in 'foobar'\n"
)

FAILING_TEST_BODY = (
    "def test_will_fail():\n"
    "    assert 1 == 2, 'deliberate fail for regression gate test'\n"
)


def _seed_passing_test_file(tmp_repo) -> str:
    """Write tests/test_regression_stub.py into the tmp repo and commit it."""
    tests_dir = tmp_repo / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    target = "tests/test_regression_stub.py"
    (tmp_repo / target).write_text(PASSING_TEST_BODY)
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed regression stub"], cwd=str(tmp_repo), check=True)
    return target


def test_regression_test_passes(tmp_repo):
    """regression_test() returns ok=True when all targets pass."""
    from agent.evolution.transaction import EvolutionTransaction

    target = _seed_passing_test_file(tmp_repo)
    txn = EvolutionTransaction(
        reason="regression-passes",
        regression_targets=[target],
    )
    txn.__enter__()
    try:
        ok, msg = txn.regression_test()
        assert ok, f"expected pass, got: {msg}"
        assert "pytest OK" in msg or "passed" in msg
    finally:
        txn.__exit__(None, None, None)


def test_regression_test_fails_on_broken_target(tmp_repo):
    """regression_test() returns ok=False when a target has failures."""
    from agent.evolution.transaction import EvolutionTransaction

    tests_dir = tmp_repo / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    (tmp_repo / "tests/test_will_fail.py").write_text(FAILING_TEST_BODY)
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed failing"], cwd=str(tmp_repo), check=True)

    txn = EvolutionTransaction(
        reason="regression-fails",
        regression_targets=["tests/test_will_fail.py"],
    )
    txn.__enter__()
    try:
        ok, msg = txn.regression_test()
        assert not ok
        assert "exit=" in msg or "fail" in msg.lower()
    finally:
        txn.__exit__(None, None, None)


def test_regression_test_missing_target_fails(tmp_repo):
    """A missing test file is a hard failure — not silently skipped."""
    from agent.evolution.transaction import EvolutionTransaction

    txn = EvolutionTransaction(
        reason="missing-target",
        regression_targets=["tests/nonexistent.py"],
    )
    txn.__enter__()
    try:
        ok, msg = txn.regression_test()
        assert not ok
        assert "missing" in msg
    finally:
        txn.__exit__(None, None, None)


def test_regression_test_empty_targets_is_ok(tmp_repo):
    """Empty regression target list short-circuits to ok=True."""
    from agent.evolution.transaction import EvolutionTransaction

    txn = EvolutionTransaction(reason="no-targets", regression_targets=[])
    txn.__enter__()
    try:
        ok, msg = txn.regression_test()
        assert ok
        assert "no regression targets" in msg
    finally:
        txn.__exit__(None, None, None)


def test_smoke_test_runs_regression_by_default(tmp_repo):
    """smoke_test() chains import-smoke + regression unless opted out.

    The telegram dry-run gate is opt-out here because the host venv doesn't
    carry python-telegram-bot; it has its own dedicated test below.
    """
    from agent.evolution.transaction import EvolutionTransaction

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add pkg"], cwd=str(tmp_repo), check=True)

    target = _seed_passing_test_file(tmp_repo)

    with EvolutionTransaction(
        reason="smoke+regression",
        regression_targets=[target],
    ) as txn:
        ok, _ = txn.apply("fake_pkg/mod_a.py", _make_module(1))
        assert ok
        ok, msg = txn.smoke_test(run_telegram_dry_run=False)
        assert ok, f"expected smoke+regression to pass: {msg}"
        assert "pytest OK" in msg or "passed" in msg


def test_telegram_dry_run_missing_deps_fails_cleanly(tmp_repo):
    """Dry-run gate returns a clean failure when python-telegram-bot is
    not installed in the calling venv (which is the case for the host
    unit-test environment). This is the gate's job: if the bot cannot
    boot, fail loudly with a parseable error message.
    """
    from agent.evolution.transaction import EvolutionTransaction

    txn = EvolutionTransaction(reason="telegram-dryrun-nodeps")
    txn.__enter__()
    try:
        ok, msg = txn.telegram_dry_run()
        # On a host without python-telegram-bot, the dry-run fails with
        # ImportError inside the subprocess — and that is exactly what we
        # want the evolution gate to do.
        # On a host that DOES have it, the gate may pass (if the components
        # dict is tolerated) or fail (if something requires actual init),
        # either way the return is a well-formed (bool, str) tuple.
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        if not ok:
            assert "telegram dry-run" in msg
    finally:
        txn.__exit__(None, None, None)


def test_smoke_test_skips_telegram_when_opted_out(tmp_repo):
    """smoke_test(run_telegram_dry_run=False) must not invoke the gate."""
    from agent.evolution.transaction import EvolutionTransaction

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add pkg"], cwd=str(tmp_repo), check=True)

    target = _seed_passing_test_file(tmp_repo)

    with EvolutionTransaction(
        reason="smoke-no-telegram",
        regression_targets=[target],
    ) as txn:
        ok, _ = txn.apply("fake_pkg/mod_a.py", _make_module(1))
        assert ok
        ok, msg = txn.smoke_test(run_telegram_dry_run=False)
        assert ok, f"expected smoke+regression (no telegram) to pass: {msg}"
        # Should NOT mention the telegram gate at all when opted out
        assert "telegram dry-run" not in msg


def test_stage_timings_recorded(tmp_repo):
    """Every stage (apply/smoke/regression/commit) writes into stage_timings."""
    from agent.evolution.transaction import EvolutionTransaction, INTENT_FILE
    import json as _json

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add pkg"], cwd=str(tmp_repo), check=True)
    target = _seed_passing_test_file(tmp_repo)

    with EvolutionTransaction(
        reason="timing coverage",
        regression_targets=[target],
    ) as txn:
        ok, _ = txn.apply("fake_pkg/mod_a.py", _make_module(1))
        assert ok
        ok, _ = txn.apply("fake_pkg/mod_b.py", _make_module(2))
        assert ok
        ok, msg = txn.smoke_test(run_telegram_dry_run=False)
        assert ok, msg
        ok, _ = txn.commit()
        assert ok

        timings = txn.record.stage_timings
        # Each of these stages must be recorded with a positive float
        for stage in ("apply", "smoke", "regression", "commit"):
            assert stage in timings, f"missing timing for {stage}: {timings}"
            assert isinstance(timings[stage], float)
            assert timings[stage] >= 0.0
        # apply was called twice — timing should be the sum
        # (we can't assert exact values, but it should be >= either single run)
        assert timings["apply"] > 0.0

    # Timings survive through the persisted intent file
    intent_data = _json.loads(INTENT_FILE.read_text())
    assert "stage_timings" in intent_data
    persisted = intent_data["stage_timings"]
    assert set(persisted.keys()) >= {"apply", "smoke", "regression", "commit"}


def test_rollback_stage_timed(tmp_repo):
    """rollback() writes a 'rollback' entry into stage_timings even on error."""
    from agent.evolution.transaction import EvolutionTransaction

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add"], cwd=str(tmp_repo), check=True)

    txn = EvolutionTransaction(reason="rollback timing")
    txn.__enter__()
    try:
        ok, _ = txn.apply("fake_pkg/mod_a.py", _make_module(1))
        assert ok
        ok, _ = txn.rollback(reason="test timing")
        assert ok
        assert "rollback" in txn.record.stage_timings
        assert txn.record.stage_timings["rollback"] >= 0.0
    finally:
        txn.__exit__(None, None, None)


def test_smoke_test_fails_when_regression_fails(tmp_repo):
    """If regression gate fails, smoke_test() returns False and blocks commit."""
    from agent.evolution.transaction import EvolutionTransaction

    pkg = tmp_repo / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    tests_dir = tmp_repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tmp_repo / "tests/test_broken.py").write_text(FAILING_TEST_BODY)
    subprocess.run(["git", "add", "."], cwd=str(tmp_repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(tmp_repo), check=True)

    with pytest.raises(RuntimeError, match="regression"):
        with EvolutionTransaction(
            reason="break-regression",
            regression_targets=["tests/test_broken.py"],
        ) as txn:
            ok, _ = txn.apply("fake_pkg/mod_a.py", _make_module(1))
            assert ok
            ok, msg = txn.smoke_test(run_telegram_dry_run=False)
            assert not ok, "regression gate should have failed"
            assert "regression failed" in msg
            raise RuntimeError("regression gate blocked commit")
