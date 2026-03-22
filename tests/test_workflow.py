"""
Tests for workflow modules: guards, sprint, evidence, review.

Run: pytest tests/test_workflow.py -v
"""
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSafetyGuards:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from agent.workflow.guards import SafetyGuard, GuardState
        self.guard = SafetyGuard()
        self.guard.state._state_path = tmp_path / "guard.json"
        self.guard.enable_careful()

    def test_detects_rm_rf(self):
        blocked, msg = self.guard.check_command("rm -rf /important/data")
        assert blocked is True
        assert "deletion" in msg.lower() or "CRITICAL" in msg

    def test_detects_force_push(self):
        blocked, msg = self.guard.check_command("git push --force origin main")
        assert blocked is True
        assert "force" in msg.lower() or "Force push" in msg

    def test_detects_hard_reset(self):
        blocked, msg = self.guard.check_command("git reset --hard HEAD~5")
        assert blocked is True

    def test_detects_drop_table(self):
        blocked, msg = self.guard.check_command("DROP TABLE users;")
        assert blocked is True

    def test_detects_delete_no_where(self):
        blocked, msg = self.guard.check_command("DELETE FROM orders;")
        assert blocked is True

    def test_safe_commands_pass(self):
        safe_commands = [
            "ls -la",
            "git status",
            "cat README.md",
            "python test.py",
            "pip install --user requests",
        ]
        for cmd in safe_commands:
            blocked, msg = self.guard.check_command(cmd)
            assert blocked is False, f"Safe command blocked: {cmd}"

    def test_careful_disabled_allows_all(self):
        self.guard.disable_careful()
        blocked, msg = self.guard.check_command("rm -rf /")
        assert blocked is False  # careful is off

    def test_freeze_blocks_outside(self):
        self.guard.enable_freeze("/home/user/project/src")
        blocked, msg = self.guard.check_file_edit("/home/user/project/README.md")
        assert blocked is True
        assert "FROZEN" in msg

    def test_freeze_allows_inside(self):
        self.guard.enable_freeze("/home/user/project/src")
        blocked, msg = self.guard.check_file_edit("/home/user/project/src/main.py")
        assert blocked is False

    def test_unfreeze(self):
        self.guard.enable_freeze("/some/dir")
        self.guard.disable_freeze()
        blocked, msg = self.guard.check_file_edit("/anywhere/file.py")
        assert blocked is False

    def test_guard_enables_both(self):
        self.guard.disable_guard()
        assert not self.guard.state.careful_enabled
        assert not self.guard.state.freeze_enabled

        self.guard.enable_guard("/some/dir")
        assert self.guard.state.careful_enabled
        assert self.guard.state.freeze_enabled


class TestSprintFramework:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        self.mgr = SprintManager()
        self.mgr.SPRINTS_DIR = tmp_path / "sprints"
        self.mgr.SPRINTS_DIR.mkdir()

    def test_create_coding_sprint(self):
        sprint = self.mgr.create("Fix login bug", mode="coding")
        assert sprint.goal == "Fix login bug"
        assert sprint.mode == "coding"
        assert len(sprint.phases) == 7
        assert sprint.phases[0].name == "think"
        assert sprint.phases[0].status == "active"

    def test_create_fin_sprint(self):
        sprint = self.mgr.create("Buy AAPL", mode="fin")
        assert len(sprint.phases) == 6
        phase_names = [p.name for p in sprint.phases]
        assert "review" in phase_names
        assert "test" in phase_names

    def test_create_chat_sprint(self):
        sprint = self.mgr.create("Research AI trends", mode="chat")
        assert len(sprint.phases) == 4

    def test_advance_phases(self):
        sprint = self.mgr.create("Test", mode="chat")
        assert sprint.current_phase.name == "think"

        self.mgr.advance(sprint.id)
        assert sprint.current_phase.name == "plan"

        self.mgr.advance(sprint.id)
        assert sprint.current_phase.name == "execute"

        self.mgr.advance(sprint.id)
        assert sprint.current_phase.name == "review"

        result = self.mgr.advance(sprint.id)
        assert result is None  # completed
        assert sprint.status == "completed"

    def test_skip_phase(self):
        sprint = self.mgr.create("Quick fix", mode="coding")
        self.mgr.skip_phase(sprint.id)  # skip think
        assert sprint.current_phase.name == "plan"
        assert sprint.phases[0].status == "skipped"

    def test_progress_tracking(self):
        sprint = self.mgr.create("Test", mode="chat")
        assert sprint.progress == "0/4"
        self.mgr.advance(sprint.id)
        assert sprint.progress == "1/4"

    def test_sprint_prompt(self):
        sprint = self.mgr.create("Fix bug", mode="coding")
        prompt = self.mgr.get_sprint_prompt(sprint.id)
        assert "Fix bug" in prompt
        assert "think" in prompt
        assert "▶️" in prompt  # active phase indicator


class TestEvidenceTrail:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        from agent.workflow.evidence import EvidenceTrail
        self.trail = EvidenceTrail()
        self.trail.LOG_DIR = tmp_path / "evidence"
        self.trail.LOG_DIR.mkdir()
        self.trail._log_path = self.trail.LOG_DIR / "audit.jsonl"

    def test_log_and_retrieve(self):
        self.trail.log("command", "ls -la", "listed 42 files", mode="coding")
        entries = self.trail.get_recent(10)
        assert len(entries) == 1
        assert entries[0]["action"] == "command"
        assert entries[0]["input"] == "ls -la"

    def test_multiple_entries(self):
        for i in range(5):
            self.trail.log("test", f"input {i}", f"output {i}")
        assert len(self.trail.get_recent(10)) == 5

    def test_filter_by_action(self):
        self.trail.log("command", "ls", "ok")
        self.trail.log("trade", "BUY AAPL", "submitted")
        self.trail.log("command", "cat file", "ok")
        trades = self.trail.get_by_action("trade")
        assert len(trades) == 1
        assert trades[0]["input"] == "BUY AAPL"

    def test_filter_by_sprint(self):
        self.trail.log("build", "wrote code", "ok", sprint_id="sprint-1")
        self.trail.log("test", "ran tests", "pass", sprint_id="sprint-1")
        self.trail.log("build", "other", "ok", sprint_id="sprint-2")
        s1 = self.trail.get_by_sprint("sprint-1")
        assert len(s1) == 2

    def test_severity(self):
        self.trail.log("trade", "SELL ALL", "executed", severity="critical")
        entries = self.trail.get_recent(1)
        assert entries[0]["severity"] == "critical"

    def test_evidence_path(self):
        self.trail.log("screenshot", "took screenshot", "saved", evidence_path="/tmp/shot.png")
        entries = self.trail.get_recent(1)
        assert entries[0]["evidence"] == "/tmp/shot.png"

    def test_stats(self):
        for i in range(10):
            self.trail.log("command", f"cmd {i}", "ok")
        self.trail.log("trade", "buy", "ok")
        stats = self.trail.get_stats()
        assert stats["total"] == 11
        assert stats["by_action"]["command"] == 10
        assert stats["by_action"]["trade"] == 1

    def test_format_recent(self):
        self.trail.log("command", "ls", "ok", severity="info")
        output = self.trail.format_recent(5)
        assert "Evidence Trail" in output
        assert "command" in output


class TestReviewDispatcher:

    def test_coding_gets_eng_review(self):
        from agent.workflow.review import ReviewDispatcher
        d = ReviewDispatcher()
        prompt = d.get_review_prompt("coding")
        assert prompt is not None
        assert len(prompt) > 50

    def test_fin_gets_trade_review(self):
        from agent.workflow.review import ReviewDispatcher
        d = ReviewDispatcher()
        prompt = d.get_review_prompt("fin")
        assert prompt is not None

    def test_chat_gets_default(self):
        from agent.workflow.review import ReviewDispatcher
        d = ReviewDispatcher()
        prompt = d.get_review_prompt("chat")
        assert "Self-Review" in prompt

    def test_should_review(self):
        from agent.workflow.review import ReviewDispatcher
        d = ReviewDispatcher()
        assert d.should_review("coding", "file_edit") is True
        assert d.should_review("coding", "read_file") is False
        assert d.should_review("fin", "trade") is True
        assert d.should_review("fin", "search") is False
