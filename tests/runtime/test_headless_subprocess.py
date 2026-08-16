"""Phase 3 gate — `neomind -p` as a real process.

The gate asks for real subprocess coverage, not in-process calls: exit codes,
stream separation and signal handling are properties of the process, and an
in-process test cannot observe any of them. Each test here spawns
`python main.py -p ...` and reads what a caller would read.

Network-dependent cases skip without a key rather than mocking the provider —
a mocked provider would only confirm this file's beliefs about the provider.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.py"
HAS_KEY = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
needs_key = pytest.mark.skipif(not HAS_KEY, reason="no DEEPSEEK_API_KEY")


#: Overriding DEEPSEEK_API_KEY alone proves nothing here. `_resolve_provider`
#: gives the local LiteLLM router priority over every other provider, so with
#: LLM_ROUTER_* set — which is the normal state on this machine — a "bad key"
#: run still succeeds through the router. Provider-failure tests have to point
#: the router itself somewhere invalid, or disable it.
#:
#: Disabling means setting these to "" rather than deleting them: main.py calls
#: load_dotenv(), which fills in any name *absent* from the environment, so a
#: deleted variable is simply restored from .env. An empty string is present,
#: so dotenv leaves it alone, and `os.getenv(...) or ""` reads it as off.
ROUTER_VARS = ("LLM_ROUTER_BASE_URL", "LLM_ROUTER_API_KEY", "LITELLM_ENABLED")


def run_headless(prompt, *, extra_args=(), env=None, timeout=180, cwd=None, clear_router=False):
    environment = dict(os.environ)
    if clear_router:
        for var in ROUTER_VARS:
            environment[var] = ""
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, str(MAIN), "-p", prompt, *extra_args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
        cwd=str(cwd or REPO),
    )


class TestSuccess:

    @needs_key
    def test_text_output_goes_to_stdout_with_exit_zero(self):
        proc = run_headless("Reply with exactly: PONG")
        assert proc.returncode == 0, proc.stderr[-500:]
        assert "PONG" in proc.stdout

    @needs_key
    def test_stdout_carries_only_the_answer(self):
        """A caller pipes stdout. Progress and diagnostics belong on stderr."""
        proc = run_headless("Reply with exactly: PONG")
        assert proc.stdout.strip() == "PONG" or proc.stdout.strip().endswith("PONG")
        assert "\x1b[" not in proc.stdout, "ANSI escapes must not reach stdout"

    @needs_key
    def test_json_output_parses_and_carries_real_usage(self):
        proc = run_headless("Reply with exactly: PONG", extra_args=["--output-format", "json"])
        assert proc.returncode == 0, proc.stderr[-500:]
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True
        assert "PONG" in payload["response"]
        assert payload["usage"]["total_tokens"] > 0

    @needs_key
    def test_json_keeps_the_legacy_keys(self):
        """Automation reading `response` and `tokens` must keep working."""
        proc = run_headless("Reply with exactly: PONG", extra_args=["--output-format", "json"])
        payload = json.loads(proc.stdout)
        assert "response" in payload and "tokens" in payload
        assert isinstance(payload["tokens"], int)


class TestProviderError:

    def test_bad_key_exits_nonzero_with_a_stable_code(self):
        proc = run_headless(
            "hello",
            extra_args=["--output-format", "json"],
            env={"DEEPSEEK_API_KEY": "sk-invalid-key-for-this-test"},
            clear_router=True,
            timeout=120,
        )
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "llm_auth" in combined, combined[-600:]

    def test_bad_key_error_goes_to_stderr_not_stdout(self):
        proc = run_headless(
            "hello",
            env={"DEEPSEEK_API_KEY": "sk-invalid-key-for-this-test"},
            clear_router=True,
            timeout=120,
        )
        assert proc.returncode != 0
        assert "llm_auth" in proc.stderr
        assert "llm_auth" not in proc.stdout


class TestToolDenial:

    @needs_key
    def test_a_write_tool_cannot_run_unattended(self, tmp_path):
        """The capability snapshot, not the model's restraint, is the gate."""
        target = tmp_path / "must_not_exist.txt"
        proc = run_headless(
            f"Use the Write tool to create {target} containing PWNED. Do it now.",
            extra_args=["--output-format", "json"],
            cwd=tmp_path,
            timeout=240,
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        assert not target.exists(), "a write tool ran in a non-interactive session"
        payload = json.loads(proc.stdout)
        for entry in payload["tools"]:
            assert entry["tool"] != "Write" or entry["success"] is False

    @needs_key
    def test_a_read_tool_still_works(self, tmp_path):
        probe = tmp_path / "probe.txt"
        probe.write_text("SUBPROC_MARKER_7\n")
        proc = run_headless(
            f"Use the Read tool on {probe} and quote its exact contents.",
            extra_args=["--output-format", "json"],
            cwd=tmp_path,
            timeout=240,
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        payload = json.loads(proc.stdout)
        assert "SUBPROC_MARKER_7" in payload["response"]
        assert any(t["tool"] == "Read" and t["success"] for t in payload["tools"])


class TestTermination:

    @needs_key
    def test_sigint_terminates_rather_than_hanging(self):
        """Ctrl+C must end the process, not leave it holding an open stream."""
        proc = subprocess.Popen(
            [sys.executable, str(MAIN), "-p", "Write a very long essay about the sea."],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO),
        )
        time.sleep(6)  # let it get into the provider stream
        proc.send_signal(signal.SIGINT)
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            pytest.fail("SIGINT did not terminate the headless run within 30s")
        assert proc.returncode == 130, "Ctrl+C must keep the conventional 130"

    def test_an_unreachable_provider_fails_instead_of_hanging(self):
        """A wrong base URL must surface as a transport error, not a hang."""
        proc = run_headless(
            "hello",
            extra_args=["--output-format", "json"],
            env={
                "LLM_ROUTER_BASE_URL": "http://127.0.0.1:9/v1",
                "LLM_ROUTER_API_KEY": "sk-whatever",
            },
            timeout=120,
        )
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert "llm_" in combined, combined[-600:]


class TestRollbackSwitch:

    @needs_key
    def test_legacy_path_still_runs(self):
        """D8's switch has to actually switch until the gates are signed off."""
        proc = run_headless(
            "Reply with exactly: PONG",
            env={"NEOMIND_HEADLESS": "legacy"},
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        assert "PONG" in proc.stdout
