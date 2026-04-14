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


def test_default_python_bin_prefers_venv_when_present(tmp_path, monkeypatch):
    # Stage a fake repo with a .venv/bin/python that exists
    fake_repo = tmp_path / "fake_repo"
    venv_py = fake_repo / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/usr/bin/env python\n")
    venv_py.chmod(0o755)

    monkeypatch.setattr(m, "repo_root", lambda: fake_repo)
    assert m.default_python_bin() == venv_py


def test_default_python_bin_falls_back_to_sys_executable(tmp_path, monkeypatch):
    fake_repo = tmp_path / "empty_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(m, "repo_root", lambda: fake_repo)
    # No .venv/bin/python → returns sys.executable
    assert m.default_python_bin() == Path(sys.executable)


def test_label_is_stable_reverse_dns_form():
    # launchd identifies agents by Label; it must be reverse-dns so it
    # doesn't collide with third-party agents in ~/Library/LaunchAgents.
    assert m.LABEL == "com.neomind.fin-dashboard"
    assert m.LABEL.count(".") >= 2
