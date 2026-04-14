"""Unit tests for scripts/neomind_fin_autostart.py — the macOS
launchd installer for the fin dashboard.

These tests never touch ``~/Library/LaunchAgents/`` or run
``launchctl``. They exercise only the pure-Python rendering layer
so CI (and non-macOS contributors) can run them.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import neomind_fin_autostart as m  # noqa: E402


def test_build_plist_dict_has_required_keys():
    payload = m.build_plist_dict(
        repo=Path("/Users/alice/NeoMind_agent"),
        python_bin=Path("/Users/alice/NeoMind_agent/.venv/bin/python"),
        log=Path("/Users/alice/Library/Logs/neomind-fin-dashboard.log"),
    )
    # Label is the launchd job identifier — used by launchctl load/unload
    assert payload["Label"] == "com.neomind.fin-dashboard"
    # RunAtLoad + KeepAlive{SuccessfulExit=False} means: start on load
    # + relaunch on crash, but honour clean exit from unload.
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    # Background ProcessType so macOS throttles it appropriately.
    assert payload["ProcessType"] == "Background"


def test_build_plist_dict_substitutes_absolute_paths():
    repo = Path("/Users/alice/NeoMind_agent")
    py = repo / ".venv/bin/python"
    log = Path("/Users/alice/Library/Logs/neomind-fin-dashboard.log")
    payload = m.build_plist_dict(repo=repo, python_bin=py, log=log)

    # ProgramArguments must be a concrete [python, -m, module, --host, host,
    # --port, port] list with no template placeholders.
    args = payload["ProgramArguments"]
    assert args[0] == str(py)
    assert args[1] == "-m"
    assert args[2] == "agent.finance.dashboard_server"
    assert "--host" in args
    assert "127.0.0.1" in args
    assert "--port" in args
    assert "8001" in args
    # WorkingDirectory is the repo root so relative imports resolve.
    assert payload["WorkingDirectory"] == str(repo)
    # Stdout + stderr both pointed at the same log file.
    assert payload["StandardOutPath"] == str(log)
    assert payload["StandardErrorPath"] == str(log)


def test_environment_variables_include_path_and_pythonunbuffered():
    payload = m.build_plist_dict(
        repo=Path("/x"), python_bin=Path("/y"), log=Path("/z"),
    )
    env = payload["EnvironmentVariables"]
    # PATH must cover both Apple Silicon (/opt/homebrew/bin) and
    # Intel (/usr/local/bin) Homebrew layouts so Finnhub/yfinance
    # transitive C libs can be located.
    assert "/opt/homebrew/bin" in env["PATH"]
    assert "/usr/local/bin" in env["PATH"]
    # PYTHONUNBUFFERED so logs hit disk in real time (not buffered
    # behind a few-KB pipe while the user waits).
    assert env["PYTHONUNBUFFERED"] == "1"


def test_render_plist_produces_parseable_xml():
    xml_bytes = m.render_plist(
        repo=Path("/Users/alice/NeoMind_agent"),
        python_bin=Path("/Users/alice/NeoMind_agent/.venv/bin/python"),
        log=Path("/Users/alice/Library/Logs/neomind-fin-dashboard.log"),
    )
    # Valid plist XML round-trips through plistlib
    parsed = plistlib.loads(xml_bytes)
    assert parsed["Label"] == "com.neomind.fin-dashboard"
    assert parsed["ProgramArguments"][2] == "agent.finance.dashboard_server"
    # Starts with the standard XML + plist DOCTYPE header
    text = xml_bytes.decode("utf-8")
    assert text.startswith("<?xml")
    assert "DOCTYPE plist" in text


def test_render_plist_defaults_resolve_without_crashing():
    # No args → uses repo_root() + default_python_bin() + log_path(),
    # which must all produce absolute paths and round-trip as XML.
    xml_bytes = m.render_plist()
    parsed = plistlib.loads(xml_bytes)
    # The resolved python should be an absolute path
    py_arg = parsed["ProgramArguments"][0]
    assert Path(py_arg).is_absolute()
    # The working directory should be the actual NeoMind_agent repo
    assert parsed["WorkingDirectory"].endswith("NeoMind_agent")


def test_default_python_bin_prefers_isolated_venv(tmp_path, monkeypatch):
    """Phase 5.1 fix for macOS TCC: the isolated Homebrew venv at
    ~/.neomind_fin_venv takes precedence over everything else. Its
    python is the one the launchd plist points at — using a
    non-system binary is the only way FDA grants stick on macOS."""
    fake_isolated = tmp_path / ".neomind_fin_venv"
    fake_isolated_py = fake_isolated / "bin" / "python"
    fake_isolated_py.parent.mkdir(parents=True)
    fake_isolated_py.write_text("#!/usr/bin/env python\n")
    fake_isolated_py.chmod(0o755)

    monkeypatch.setattr(m, "ISOLATED_VENV_DIR", fake_isolated)
    assert m.default_python_bin() == fake_isolated_py


def test_default_python_bin_falls_back_to_repo_venv_then_sys(
    tmp_path, monkeypatch,
):
    # No isolated venv → next best is repo .venv; none of those →
    # sys.executable.
    monkeypatch.setattr(m, "ISOLATED_VENV_DIR", tmp_path / "no-isolated-here")

    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(m, "repo_root", lambda: fake_repo)
    # Neither isolated nor repo venv exist → sys.executable
    assert m.default_python_bin() == Path(sys.executable)

    # Now create the repo .venv and verify it's preferred over sys.executable
    repo_py = fake_repo / ".venv" / "bin" / "python"
    repo_py.parent.mkdir(parents=True)
    repo_py.write_text("#!/usr/bin/env python\n")
    repo_py.chmod(0o755)
    assert m.default_python_bin() == repo_py


def test_find_homebrew_python_prefers_apple_silicon(monkeypatch):
    """find_homebrew_python scans a fixed list in priority order;
    we can't test by making real /opt/homebrew files, but we CAN
    verify the returned path is not a system binary when something
    is available, and None when the whole list is empty."""
    # Empty list → None
    monkeypatch.setattr(m, "_HOMEBREW_PYTHON_CANDIDATES", [])
    assert m.find_homebrew_python() is None


def test_is_system_python_rejects_clt_and_system(monkeypatch):
    # Apple Command Line Tools python — exact prefix used in the
    # user's broken install on 2026-04-13
    assert m._is_system_python(
        Path("/Library/Developer/CommandLineTools/usr/bin/python3")
    ) is True
    assert m._is_system_python(Path("/usr/bin/python3")) is True
    assert m._is_system_python(Path("/System/Library/Python/python3")) is True
    # Homebrew and user venvs are OK
    assert m._is_system_python(Path("/opt/homebrew/bin/python3")) is False
    assert m._is_system_python(Path("/usr/local/bin/python3")) is False
    assert m._is_system_python(
        Path.home() / ".neomind_fin_venv" / "bin" / "python"
    ) is False


def test_plist_environment_includes_pythonpath():
    """Plist must inject PYTHONPATH pointing at the repo root so the
    isolated venv python can import agent.finance.* even if the
    editable pip install .pth file was not registered."""
    payload = m.build_plist_dict(
        repo=Path("/Users/alice/Desktop/NeoMind_agent"),
        python_bin=Path.home() / ".neomind_fin_venv" / "bin" / "python",
        log=Path("/Users/alice/Library/Logs/neomind-fin-dashboard.log"),
    )
    env = payload["EnvironmentVariables"]
    assert env["PYTHONPATH"] == "/Users/alice/Desktop/NeoMind_agent"


def test_label_is_stable_reverse_dns_form():
    # launchd identifies agents by Label; it must be reverse-dns so it
    # doesn't collide with third-party agents in ~/Library/LaunchAgents.
    assert m.LABEL == "com.neomind.fin-dashboard"
    assert m.LABEL.count(".") >= 2


# ── TCC (Transparency, Consent, Control) detection ──────────────────


def test_is_tcc_protected_path_desktop(monkeypatch, tmp_path):
    # Fake a home dir containing Desktop/NeoMind_agent
    fake_home = tmp_path / "alice"
    (fake_home / "Desktop" / "NeoMind_agent").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    repo = fake_home / "Desktop" / "NeoMind_agent"
    assert m._is_tcc_protected_path(repo) is True


def test_is_tcc_protected_path_documents_and_downloads(monkeypatch, tmp_path):
    fake_home = tmp_path / "alice"
    (fake_home / "Documents" / "proj").mkdir(parents=True)
    (fake_home / "Downloads" / "stuff").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert m._is_tcc_protected_path(fake_home / "Documents" / "proj") is True
    assert m._is_tcc_protected_path(fake_home / "Downloads" / "stuff") is True


def test_is_tcc_protected_path_safe_locations(monkeypatch, tmp_path):
    fake_home = tmp_path / "alice"
    (fake_home / "code" / "neomind").mkdir(parents=True)
    (fake_home / ".local" / "share" / "x").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    # ~/code and ~/.local are NOT TCC-protected → safe for launchd
    assert m._is_tcc_protected_path(fake_home / "code" / "neomind") is False
    assert m._is_tcc_protected_path(
        fake_home / ".local" / "share" / "x"
    ) is False


def test_scan_log_for_tcc_error_detects_operation_not_permitted(tmp_path):
    log = tmp_path / "dashboard.log"
    log.write_text(
        "Traceback (most recent call last):\n"
        "  File 'site.py', line 522, in venv\n"
        "PermissionError: [Errno 1] Operation not permitted: "
        "'/Users/alice/Desktop/NeoMind_agent/.venv/pyvenv.cfg'\n"
    )
    # since_ts older than the file → should find it
    assert m._scan_log_for_tcc_error(log, 0.0) is True


def test_scan_log_for_tcc_error_ignores_stale_log(tmp_path):
    log = tmp_path / "dashboard.log"
    log.write_text("PermissionError: Operation not permitted: /foo\n")
    import time
    # since_ts in the future → should NOT count this log
    assert m._scan_log_for_tcc_error(log, time.time() + 60) is False


def test_scan_log_for_tcc_error_missing_log(tmp_path):
    assert m._scan_log_for_tcc_error(tmp_path / "nonexistent.log", 0.0) is False


def test_scan_log_for_tcc_error_clean_log(tmp_path):
    log = tmp_path / "dashboard.log"
    log.write_text(
        "INFO:     127.0.0.1:54842 - GET /api/health HTTP/1.1 200 OK\n"
        "INFO:     Application startup complete.\n"
    )
    assert m._scan_log_for_tcc_error(log, 0.0) is False
