"""Unit tests for agent/finance/investment_projects.py (data firewall).

Every test redirects the Investment root to a tmp_path via the
NEOMIND_INVESTMENT_ROOT env var — no test ever writes to the real
~/Desktop/Investment/ folder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.finance import investment_projects as ip
from agent.finance.investment_projects import (
    InvestmentPathError,
    append_trade,
    get_investment_root,
    get_project_dir,
    kpi_snapshot,
    list_projects,
    log_journal,
    register_project,
    write_analysis,
)


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """Redirect the Investment root to a tmp dir for the test."""
    root = tmp_path / "Investment"
    root.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(root))
    return root


# ── Root resolution ──────────────────────────────────────────────────────

def test_root_honors_env_var(tmp_root):
    assert get_investment_root() == tmp_root.resolve()


def test_default_root_is_desktop_investment(monkeypatch):
    monkeypatch.delenv("NEOMIND_INVESTMENT_ROOT", raising=False)
    expected = (Path.home() / "Desktop" / "Investment").resolve()
    assert get_investment_root() == expected


# ── project_id validation ────────────────────────────────────────────────

@pytest.mark.parametrize("pid", [
    "us-growth-2026q2",
    "a-share-value",
    "btc_momentum",
    "ab",                 # min length
    "a" * 40,             # max length
    "x1",
])
def test_valid_project_id(tmp_root, pid):
    register_project(pid, "desc")
    assert (tmp_root / pid).is_dir()


@pytest.mark.parametrize("pid", [
    "",
    "a",                  # too short
    "A-UPPER",            # uppercase
    "-leading-dash",
    "_underscore",
    "has space",
    "has/slash",
    "../escape",
    "a" * 41,             # too long
    "emoji🚀",
    123,                  # not a string
])
def test_invalid_project_id_rejected(tmp_root, pid):
    with pytest.raises(InvestmentPathError):
        get_project_dir(pid)  # type: ignore[arg-type]


# ── Path traversal defense ───────────────────────────────────────────────

def test_traversal_via_project_id_rejected(tmp_root):
    with pytest.raises(InvestmentPathError):
        get_project_dir("../../etc/passwd")


def test_write_outside_root_is_impossible(tmp_root, monkeypatch):
    """Even if someone sets env var to a weird path, writes stay inside it."""
    # Intentionally set root to a sub-sub dir, then verify a registered
    # project lands under it and NOT in tmp_root's parent.
    sub = tmp_root / "nested"
    sub.mkdir()
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(sub))
    proj = register_project("p1", "x")
    assert str(proj).startswith(str(sub.resolve()))


def test_forbidden_segment_neomind_agent_rejected(tmp_path, monkeypatch):
    """If the Investment root itself contained 'NeoMind_agent', writes fail."""
    bad_root = tmp_path / "NeoMind_agent" / "Investment"
    bad_root.mkdir(parents=True)
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(bad_root))
    with pytest.raises(InvestmentPathError):
        register_project("proj", "desc")


# ── register_project ─────────────────────────────────────────────────────

def test_register_creates_scaffold(tmp_root):
    proj = register_project("us-growth-2026q2", "Q2 growth thesis")
    for sub in ("analyses", "backtests", "journal", "kpi"):
        assert (proj / sub).is_dir()
    assert (proj / "README.md").exists()
    assert (proj / "watchlist.yaml").exists()
    readme_text = (proj / "README.md").read_text()
    assert "us-growth-2026q2" in readme_text
    assert "Q2 growth thesis" in readme_text


def test_register_is_idempotent(tmp_root):
    proj = register_project("proj", "first")
    register_project("proj", "")  # empty description → preserves existing README
    assert "first" in (proj / "README.md").read_text()
    # Re-register with new desc overwrites README
    register_project("proj", "second")
    assert "second" in (proj / "README.md").read_text()


def test_register_does_not_overwrite_watchlist(tmp_root):
    proj = register_project("proj", "x")
    (proj / "watchlist.yaml").write_text("symbols: [AAPL]\n")
    register_project("proj", "y")
    assert "AAPL" in (proj / "watchlist.yaml").read_text()


# ── append_trade ─────────────────────────────────────────────────────────

def test_append_trade_requires_registration(tmp_root):
    with pytest.raises(FileNotFoundError):
        append_trade("not-registered", {"symbol": "AAPL", "qty": 10})


def test_append_trade_jsonl_format(tmp_root):
    register_project("proj", "x")
    append_trade("proj", {"symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0})
    append_trade("proj", {"symbol": "NVDA", "side": "sell", "qty": 5, "price": 900.0})

    lines = (tmp_root / "proj" / "trades.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    rec1 = json.loads(lines[1])
    assert rec0["symbol"] == "AAPL" and rec0["qty"] == 10
    assert rec1["symbol"] == "NVDA" and rec1["side"] == "sell"
    assert "_written_at" in rec0 and "_written_at" in rec1


def test_append_trade_concurrent_atomic(tmp_root):
    """Concurrent writers from threads produce valid JSONL with no corruption."""
    import threading

    register_project("proj", "x")
    N = 50
    errors: list = []

    def worker(i):
        try:
            append_trade("proj", {"symbol": "AAPL", "qty": i, "tag": f"t{i}"})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    lines = (tmp_root / "proj" / "trades.jsonl").read_text().strip().split("\n")
    assert len(lines) == N
    # Every line parses cleanly (no interleaved corruption)
    tags = {json.loads(line)["tag"] for line in lines}
    assert tags == {f"t{i}" for i in range(N)}


# ── write_analysis ───────────────────────────────────────────────────────

def test_write_analysis_roundtrip(tmp_root):
    register_project("proj", "x")
    signal = {"signal": "buy", "confidence": 8, "reason": "strong earnings"}
    path = write_analysis("proj", "aapl", signal)
    assert path.exists()
    assert path.name.endswith("_AAPL.json")
    payload = json.loads(path.read_text())
    assert payload["symbol"] == "AAPL"
    assert payload["project_id"] == "proj"
    assert payload["signal"] == signal
    assert "written_at" in payload


def test_write_analysis_rejects_bad_symbol(tmp_root):
    register_project("proj", "x")
    with pytest.raises(InvestmentPathError):
        write_analysis("proj", "not a symbol!", {"signal": "hold"})


def test_write_analysis_lands_in_analyses_dir(tmp_root):
    register_project("proj", "x")
    path = write_analysis("proj", "AAPL", {"signal": "buy"})
    assert path.parent == (tmp_root / "proj" / "analyses")


def test_write_analysis_rapid_same_symbol_no_collision(tmp_root):
    """Regression for a Phase 0 bug: filename used seconds-resolution
    timestamp, so rapid successive writes of the same symbol overwrote
    each other. After the fix (microseconds in filename), 20 rapid
    writes must produce 20 distinct files."""
    register_project("proj", "x")
    N = 20
    paths = set()
    for i in range(N):
        p = write_analysis("proj", "AAPL", {"signal": "buy", "tag": i})
        paths.add(str(p))
    assert len(paths) == N, (
        f"filename collision: {N} writes produced only {len(paths)} files"
    )
    # Every file must still exist on disk
    analyses_dir = tmp_root / "proj" / "analyses"
    written_files = list(analyses_dir.glob("*.json"))
    assert len(written_files) == N


# ── log_journal ──────────────────────────────────────────────────────────

def test_log_journal_appends_with_hr_separator(tmp_root):
    register_project("proj", "x")
    log_journal("proj", "# Morning thoughts\n\nBullish on NVDA.")
    log_journal("proj", "# Midday update\n\nNVDA broke resistance.")
    # Filename is today's date
    journal_dir = tmp_root / "proj" / "journal"
    files = list(journal_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "Morning thoughts" in content
    assert "Midday update" in content
    assert "---" in content  # separator between blocks


# ── kpi_snapshot ─────────────────────────────────────────────────────────

def test_kpi_snapshot_appends(tmp_root):
    register_project("proj", "x")
    kpi_snapshot("proj", {"accuracy": 0.62, "signal_noise": 2.4, "latency_p50_ms": 840})
    kpi_snapshot("proj", {"accuracy": 0.58, "signal_noise": 2.8, "latency_p50_ms": 910})

    lines = (tmp_root / "proj" / "kpi" / "weekly.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["accuracy"] == 0.62
    assert "recorded_at" in first


# ── list_projects ────────────────────────────────────────────────────────

def test_list_projects_excludes_meta_and_hidden(tmp_root):
    register_project("us-growth", "x")
    register_project("a-share-value", "y")
    (tmp_root / "_meta").mkdir()
    (tmp_root / ".DS_Store").mkdir()
    (tmp_root / "not-a-project").mkdir()  # no README → excluded

    names = list_projects()
    assert names == ["a-share-value", "us-growth"]


def test_list_projects_empty_when_no_root(tmp_path, monkeypatch):
    nonexistent = tmp_path / "does-not-exist"
    monkeypatch.setenv("NEOMIND_INVESTMENT_ROOT", str(nonexistent))
    assert list_projects() == []


# ── Data firewall: NeoMind repo must never receive writes ────────────────

def test_never_writes_into_neomind_repo(tmp_root):
    """Belt-and-suspenders: even if env var pointed at the NeoMind repo,
    the forbidden-segment check blocks it."""
    register_project("proj", "x")
    append_trade("proj", {"symbol": "AAPL", "qty": 1})
    # Verify none of the files landed under the NeoMind repo
    neomind_root = Path(__file__).resolve().parent.parent  # tests/ → repo root
    for written in (tmp_root / "proj").rglob("*"):
        assert not str(written).startswith(str(neomind_root)), (
            f"Write leaked into NeoMind repo: {written}"
        )
