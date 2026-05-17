"""Tests for the slash-command wiring in agent/coding/speckit/commands.py.

Focus: the sync→async bridge (_run_async) and the project_root resolution
for the PhaseRunner builder.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.coding.speckit import commands as speckit_commands


class TestRunAsync:
    """_run_async must survive: (a) a clean sync caller, (b) a running
    event loop, (c) Python 3.9 policy state after a prior asyncio.run."""

    def test_simple_sync_call(self):
        async def hello():
            return "hi"
        assert speckit_commands._run_async(hello()) == "hi"

    def test_falls_back_when_asyncio_run_raises(self, monkeypatch):
        """If asyncio.run raises RuntimeError (e.g. inside a running loop)
        the fallback must still complete the coroutine."""
        real_new_event_loop = asyncio.new_event_loop

        def boom(_coro):
            raise RuntimeError("asyncio.run() cannot be called from a running event loop")

        monkeypatch.setattr(
            speckit_commands.asyncio, "run", boom
        )

        async def work():
            return 42

        assert speckit_commands._run_async(work()) == 42

    def test_after_prior_asyncio_run(self):
        """Real-world Python 3.9 scenario: a previous asyncio.run() leaves
        the policy state such that future get_event_loop() raises.
        Two back-to-back _run_async calls should both succeed."""
        async def first():
            return "first"

        async def second():
            return "second"

        assert speckit_commands._run_async(first()) == "first"
        assert speckit_commands._run_async(second()) == "second"


class TestGetPhaseRunner:
    """_get_phase_runner must handle missing workspace_manager gracefully."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_falls_back_to_cwd_when_no_workspace_manager(self, monkeypatch):
        """When core has no workspace_manager attribute, project_root
        should fall back to os.getcwd() (not a silent '.' string)."""
        monkeypatch.chdir(self.tmpdir)
        core = MagicMock(spec=[])  # no workspace_manager attribute

        runner = speckit_commands._get_phase_runner(core)
        assert str(runner.spec.workspace_root) == str(Path(self.tmpdir).resolve())

    def test_falls_back_to_cwd_when_project_root_is_none(self, monkeypatch):
        """workspace_manager exists but project_root is None."""
        monkeypatch.chdir(self.tmpdir)
        core = MagicMock(spec=["workspace_manager"])
        core.workspace_manager = MagicMock(spec=["project_root"])
        core.workspace_manager.project_root = None

        runner = speckit_commands._get_phase_runner(core)
        assert str(runner.spec.workspace_root) == str(Path(self.tmpdir).resolve())

    def test_uses_workspace_project_root_when_available(self, monkeypatch):
        core = MagicMock(spec=["workspace_manager", "generate_completion_async"])
        core.workspace_manager = MagicMock()
        core.workspace_manager.project_root = self.tmpdir

        runner = speckit_commands._get_phase_runner(core)
        assert str(runner.spec.workspace_root) == str(Path(self.tmpdir).resolve())
        # LLM fn should be wired since core has generate_completion_async
        assert runner.llm_fn is not None

    def test_llm_fn_wires_sync_generate_completion(self, monkeypatch):
        """Regression: core has only sync generate_completion (no _async
        variant) — historically commands.py disabled LLM enrichment in
        this case. The thread-wrap path must now fire."""
        monkeypatch.chdir(self.tmpdir)
        core = MagicMock(spec=["generate_completion"])
        # Make it return a known sentinel synchronously
        core.generate_completion = MagicMock(return_value="LLM_OUTPUT")

        runner = speckit_commands._get_phase_runner(core)
        assert runner.llm_fn is not None
        # Drive it through the async wrapper and confirm round-trip
        result = asyncio.run(runner.llm_fn("sys prompt", "user prompt"))
        assert result == "LLM_OUTPUT"
        # And that the sync impl was actually called with messages
        call_args = core.generate_completion.call_args
        assert call_args is not None
        msgs = call_args[0][0]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "sys prompt"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "user prompt"

    def test_llm_fn_none_when_neither_method_present(self, monkeypatch):
        """If core has no completion method at all, llm_fn must be None
        so PhaseRunner falls back to template-only behavior."""
        monkeypatch.chdir(self.tmpdir)
        core = MagicMock(spec=[])
        runner = speckit_commands._get_phase_runner(core)
        assert runner.llm_fn is None
