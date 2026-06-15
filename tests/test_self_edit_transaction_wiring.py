"""Verify _exec_self_editor now routes through EvolutionTransaction so a bad
self-edit is rejected AND auto-rolled-back to the git checkpoint.

Needs `python` on PATH + pytest + the project deps → run in the container:
  docker exec neomind-telegram sh -c \
    'cd /app && python -m pytest tests/test_self_edit_transaction_wiring.py -q'
"""
import subprocess

import pytest


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """Fresh throwaway git repo; point SelfEditor + transaction at it so the
    real repo is never touched (git reset --hard happens on the tmp repo)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi\n")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    from agent.evolution import self_edit, transaction

    monkeypatch.setattr(self_edit.SelfEditor, "REPO_DIR", repo)
    monkeypatch.setattr(self_edit.SelfEditor, "DATA_DIR", data / "se")
    monkeypatch.setattr(self_edit.SelfEditor, "MAX_EDITS_PER_DAY", 100)
    monkeypatch.delenv("NEOMIND_SAFE_MODE", raising=False)
    monkeypatch.setattr(transaction, "REPO_DIR", repo)
    monkeypatch.setattr(transaction, "DATA_DIR", data / "ev")
    monkeypatch.setattr(transaction, "LOCK_FILE", data / "ev" / "lock")
    monkeypatch.setattr(transaction, "INTENT_FILE", data / "ev" / "intent.json")
    monkeypatch.setattr(transaction, "TXN_LOG", data / "ev" / "txn.jsonl")
    # tiny repo has no regression targets — disable so the gate can't false-fail
    monkeypatch.setattr(transaction, "DEFAULT_REGRESSION_TARGETS", ())
    yield repo


def _registry():
    from agent.coding.tools import ToolRegistry
    return ToolRegistry()


def test_broken_self_edit_is_rejected_and_rolled_back(isolated_repo):
    """FAULT INJECTION: a syntactically-broken edit must be rejected and the
    working tree restored to the checkpoint (the broken file must not survive)."""
    reg = _registry()
    res = reg._exec_self_editor(
        "pkg/injected_bad.py", "def broken(:\n    pass\n", "fault-injection: bad syntax"
    )
    assert res.success is False, f"broken edit should be rejected, got: {res.output}"
    err = (res.error or "").lower()
    assert "roll" in err or "checkpoint" in err or "reject" in err, res.error
    # The checkpoint rollback (git reset --hard <tag>) wiped the bad file.
    assert not (isolated_repo / "pkg" / "injected_bad.py").exists(), \
        "broken file survived — rollback did not restore the checkpoint"


def test_plan_mode_blocks_self_edit(isolated_repo):
    reg = _registry()
    reg._plan_mode = True
    res = reg._exec_self_editor("pkg/x.py", "x = 1\n", "should be blocked")
    assert res.success is False and "plan mode" in (res.error or "").lower()
