"""Phase 7 — the ACP entry point a client spawns.

This is the piece that makes NeoMind usable by DeepSeek Harness *today*: its
`subagent-acp` provider spawns a configured command and speaks ACP over that
process's stdio. Verified end to end against a real model by
`tools/protocol/drive_with_acp_client.py`; these cover the parts that would
break silently.

Stdout discipline is the whole risk. Stdout **is** the wire, so anything that
prints lands inside a JSON-RPC frame and the client reports a parse error
naming nothing — no traceback, no origin, just a broken stream.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


class TestStdoutStaysClean:

    def test_importing_the_entry_point_prints_nothing(self):
        """An import that prints has already corrupted the stream by the time
        the agent exists."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import agent.integration.acp_stdio as m; print('MARKER', end='')"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr[-400:]
        assert result.stdout == "MARKER", (
            f"something printed during import: {result.stdout[:200]!r}"
        )

    def test_logging_is_pinned_to_stderr(self):
        """`logging.basicConfig` is a no-op once a handler exists, so a module
        that configured logging at import time would keep its stdout handler."""
        code = (
            "import logging, sys;"
            "logging.basicConfig(stream=sys.stdout);"
            "import agent.integration.acp_stdio as m;"
            "m._silence_stdout();"
            "logging.getLogger('x').warning('to-stderr');"
            "print('CLEAN', end='')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO,
            capture_output=True, text=True, timeout=120,
        )
        assert result.stdout == "CLEAN", f"a log reached stdout: {result.stdout!r}"
        assert "to-stderr" in result.stderr


class TestCommandLine:
    """A client's config points at this command; a broken argument surface
    means the spawn fails with nothing useful on stderr."""

    def test_help_works_without_starting_a_server(self):
        result = subprocess.run(
            [sys.executable, "-m", "agent.integration.acp_stdio", "--help"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0
        assert "Agent Client Protocol" in result.stdout

    def test_an_invalid_mode_is_refused_rather_than_defaulted(self):
        result = subprocess.run(
            [sys.executable, "-m", "agent.integration.acp_stdio", "--mode", "nonsense"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode != 0
        assert "invalid choice" in result.stderr

    @pytest.mark.parametrize("mode", ["chat", "coding", "fin"])
    def test_every_mode_is_accepted(self, mode):
        """Parsed, not started: the server would block on stdin forever."""
        from agent.integration.acp_stdio import main
        import argparse
        from unittest import mock

        with mock.patch("asyncio.run") as run:
            assert main(["--mode", mode]) == 0
        assert run.called


class TestShutdown:
    """`subagent-acp` closes stdin and waits a grace period before SIGTERM.
    A child that treats EOF as a crash makes every ordinary teardown look
    like a failure in the parent's logs."""

    def test_closed_stdin_exits_zero(self):
        proc = subprocess.Popen(
            [sys.executable, "-m", "agent.integration.acp_stdio"],
            cwd=REPO, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("did not exit after stdin closed")
        assert proc.returncode == 0, proc.stderr.read()[-400:]
