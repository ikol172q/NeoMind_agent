"""
Extended comprehensive tests for agent/workflow modules:
- audit.py (AuditEngine, AuditFinding, AuditCycleReport)
- guards.py (SafetyGuard, GuardState, DANGEROUS_PATTERNS)
- sprint.py (SprintManager, Sprint, SprintPhase)
- evidence.py (EvidenceTrail, EvidenceEntry)
- review.py (ReviewDispatcher)

This file extends and complements tests/test_workflow.py with comprehensive coverage
of all edge cases, error paths, and additional functionality.

Run: pytest tests/test_workflow_full.py -v
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# AUDIT ENGINE TESTS
# ============================================================================

class TestAuditFinding:
    """Test AuditFinding dataclass."""

    def test_init(self):
        from agent.workflow.audit import AuditFinding
        finding = AuditFinding(
            severity="critical",
            module="auth.py",
            issue="SQL injection vulnerability"
        )

        assert finding.severity == "critical"
        assert finding.module == "auth.py"
        assert finding.issue == "SQL injection vulnerability"
        assert finding.status == "open"
        assert finding.fix == ""
        assert finding.test == ""

    def test_init_with_all_fields(self):
        from agent.workflow.audit import AuditFinding
        finding = AuditFinding(
            severity="high",
            module="api.py",
            issue="Unvalidated input",
            status="fixed",
            fix="Added input validation",
            test="test_input_validation"
        )

        assert finding.status == "fixed"
        assert finding.fix == "Added input validation"


class TestAuditCycleReport:
    """Test AuditCycleReport dataclass and properties."""

    def test_init(self):
        from agent.workflow.audit import AuditCycleReport
        report = AuditCycleReport(cycle=1, scope="core", date="2024-01-01")

        assert report.cycle == 1
        assert report.scope == "core"
        assert report.date == "2024-01-01"
        assert report.findings == []
        assert report.tests_run == {}
        assert report.skipped == []

    def test_critical_count(self):
        from agent.workflow.audit import AuditCycleReport, AuditFinding
        report = AuditCycleReport(cycle=1, scope="test", date="2024-01-01")

        report.findings = [
            AuditFinding("critical", "mod1", "issue1"),
            AuditFinding("critical", "mod2", "issue2"),
            AuditFinding("high", "mod3", "issue3"),
        ]

        assert report.critical_count == 2

    def test_fixed_count(self):
        from agent.workflow.audit import AuditCycleReport, AuditFinding
        report = AuditCycleReport(cycle=1, scope="test", date="2024-01-01")

        report.findings = [
            AuditFinding("critical", "mod1", "issue1", status="fixed"),
            AuditFinding("high", "mod2", "issue2", status="fixed"),
            AuditFinding("medium", "mod3", "issue3", status="open"),
        ]

        assert report.fixed_count == 2

    def test_open_count(self):
        from agent.workflow.audit import AuditCycleReport, AuditFinding
        report = AuditCycleReport(cycle=1, scope="test", date="2024-01-01")

        report.findings = [
            AuditFinding("critical", "mod1", "issue1", status="open"),
            AuditFinding("high", "mod2", "issue2", status="fixed"),
            AuditFinding("medium", "mod3", "issue3", status="open"),
        ]

        assert report.open_count == 2


class TestAuditEngine:
    """Test AuditEngine class."""

    def test_init(self, tmp_path):
        from agent.workflow.audit import AuditEngine
        engine = AuditEngine(project_root=str(tmp_path))

        assert engine.project_root == tmp_path
        assert (tmp_path / "plans" / "audit").exists()

    def test_run_cycle_creates_findings(self, tmp_path):
        from agent.workflow.audit import AuditEngine
        engine = AuditEngine(project_root=str(tmp_path))

        with patch.object(engine, '_run_check') as mock_check:
            mock_check.return_value = [Mock(severity="info", status="open")]
            report = engine.run_cycle(1, "core")

        assert report.cycle == 1
        assert report.scope == "core"

    def test_run_full_audit(self, tmp_path):
        from agent.workflow.audit import AuditEngine
        engine = AuditEngine(project_root=str(tmp_path))

        with patch.object(engine, 'run_cycle') as mock_cycle:
            with patch.object(engine, '_save_report'):
                with patch.object(engine, '_run_full_regression') as mock_regress:
                    mock_cycle.return_value = Mock(findings=[])
                    mock_regress.return_value = Mock(findings=[])

                    reports = engine.run_full_audit("test goal", cycles=2)

                    # Should run 2 cycles + 1 regression
                    assert mock_cycle.call_count == 2
                    assert mock_regress.called

    def test_format_summary(self, tmp_path):
        from agent.workflow.audit import AuditEngine, AuditCycleReport, AuditFinding
        engine = AuditEngine(project_root=str(tmp_path))

        report1 = AuditCycleReport(cycle=1, scope="core", date="2024-01-01")
        report1.findings = [
            AuditFinding("critical", "m1", "i1"),
            AuditFinding("high", "m2", "i2"),
        ]

        report2 = AuditCycleReport(cycle=2, scope="edge", date="2024-01-02")
        report2.findings = [
            AuditFinding("critical", "m3", "i3"),
        ]

        summary = engine.format_summary([report1, report2])

        assert "Audit Summary" in summary
        assert "critical" in summary.lower() or "2" in summary


# ============================================================================
# GUARDS TESTS (Extended)
# ============================================================================

class TestGuardStateExtended:
    """Extended tests for GuardState."""

    def test_state_persistence(self, tmp_path):
        from agent.workflow.guards import GuardState
        state_file = tmp_path / "guard_state.json"

        state1 = GuardState()
        state1._state_path = state_file
        state1.careful_enabled = True
        state1.freeze_enabled = True
        state1.freeze_directory = "/home/user"
        state1.save()

        state2 = GuardState()
        state2._state_path = state_file
        state2.load()

        assert state2.careful_enabled is True
        assert state2.freeze_enabled is True
        assert state2.freeze_directory == "/home/user"

    def test_load_nonexistent_file(self):
        from agent.workflow.guards import GuardState
        state = GuardState()
        state._state_path = Path("/nonexistent/path/guard.json")

        # Should not raise
        state.load()
        assert state.careful_enabled is False

    def test_save_creates_parent_dir(self, tmp_path):
        from agent.workflow.guards import GuardState
        state_file = tmp_path / "deep" / "nested" / "guard.json"

        state = GuardState()
        state._state_path = state_file
        state.careful_enabled = True
        state.save()

        assert state_file.exists()


class TestSafetyGuardExtended:
    """Extended tests for SafetyGuard."""

    def test_multiple_dangerous_patterns_found(self):
        from agent.workflow.guards import SafetyGuard
        guard = SafetyGuard()
        guard.enable_careful()

        blocked, msg = guard.check_command("rm -rf / && git push --force")

        assert blocked is True
        assert msg.count("\n") > 0  # Multiple warnings

    def test_freeze_with_relative_path(self):
        from agent.workflow.guards import SafetyGuard
        guard = SafetyGuard()

        guard.enable_freeze("./relative/path")
        abs_path = guard.state.freeze_directory

        assert os.path.isabs(abs_path)

    def test_freeze_blocks_symlinks_outside(self):
        from agent.workflow.guards import SafetyGuard
        guard = SafetyGuard()

        guard.enable_freeze("/home/user/allowed")
        blocked, msg = guard.check_file_edit("/home/user/notallowed/file.py")

        assert blocked is True

    def test_get_status_output(self):
        from agent.workflow.guards import SafetyGuard
        guard = SafetyGuard()

        status = guard.get_status()

        assert "Safety Guard" in status
        assert "/careful" in status
        assert "/freeze" in status

    def test_chmod_patterns_detected(self):
        from agent.workflow.guards import SafetyGuard
        guard = SafetyGuard()
        guard.enable_careful()

        cases = [
            "chmod 777 /etc/passwd",
            "chmod -R 666 /var",
            "chmod a+rwx /sensitive",
        ]

        for cmd in cases:
            blocked, msg = guard.check_command(cmd)
            assert blocked is True, f"Should block: {cmd}"

    def test_database_patterns_detected(self):
        from agent.workflow.guards import SafetyGuard
        guard = SafetyGuard()
        guard.enable_careful()

        cases = [
            "DROP TABLE users;",
            "DROP DATABASE production;",
            "DELETE FROM accounts;",
            "TRUNCATE TABLE logs;",
        ]

        for cmd in cases:
            blocked, msg = guard.check_command(cmd)
            assert blocked is True, f"Should block: {cmd}"


# ============================================================================
# SPRINT TESTS (Extended)
# ============================================================================

class TestSprintPhase:
    """Test SprintPhase dataclass."""

    def test_init_defaults(self):
        from agent.workflow.sprint import SprintPhase
        phase = SprintPhase(name="think")

        assert phase.name == "think"
        assert phase.status == "pending"
        assert phase.started_at == ""
        assert phase.completed_at == ""
        assert phase.output == ""
        assert phase.notes == ""


class TestSprintExtended:
    """Extended tests for Sprint class."""

    def test_sprint_properties(self):
        from agent.workflow.sprint import Sprint, SprintPhase
        sprint = Sprint(
            id="sprint-1",
            goal="Test goal",
            mode="coding",
        )
        phase1 = SprintPhase(name="think", status="completed")
        phase2 = SprintPhase(name="plan", status="active")
        phase3 = SprintPhase(name="build", status="pending")

        sprint.phases = [phase1, phase2, phase3]

        assert sprint.current_phase.name == "plan"
        assert sprint.next_phase.name == "build"
        assert sprint.progress == "1/3"


class TestSprintManagerExtended:
    """Extended tests for SprintManager."""

    def test_create_with_all_modes(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        coding_sprint = mgr.create("Code task", mode="coding")
        fin_sprint = mgr.create("Trade", mode="fin")
        chat_sprint = mgr.create("Chat", mode="chat")

        assert len(coding_sprint.phases) == 7
        assert len(fin_sprint.phases) == 6
        assert len(chat_sprint.phases) == 4

    def test_sprint_persistence(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        sprint = mgr.create("Test", mode="chat")
        mgr.advance(sprint.id)

        # Verify saved to disk
        sprint_file = tmp_path / f"{sprint.id}.json"
        assert sprint_file.exists()

    def test_complete_phase_with_output(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        sprint = mgr.create("Test", mode="chat")
        mgr.complete_phase(sprint.id, output="output data", notes="notes here")

        assert sprint.current_phase.output == "output data"
        assert sprint.current_phase.notes == "notes here"

    def test_skip_then_advance(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        sprint = mgr.create("Test", mode="coding")
        assert sprint.current_phase.name == "think"

        mgr.skip_phase(sprint.id)
        assert sprint.current_phase.name == "plan"
        assert sprint.phases[0].status == "skipped"

    def test_format_status_output(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        sprint = mgr.create("Example task", mode="coding")
        status = mgr.format_status(sprint.id)

        assert "Example task" in status
        assert "Progress" in status
        assert "think" in status

    def test_get_nonexistent_sprint(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        sprint = mgr.get("nonexistent-sprint")
        assert sprint is None

    def test_advance_completed_sprint_returns_none(self, tmp_path):
        from agent.workflow.sprint import SprintManager
        mgr = SprintManager()
        mgr.SPRINTS_DIR = tmp_path

        sprint = mgr.create("Test", mode="chat")
        # Advance through all 4 phases
        mgr.advance(sprint.id)  # plan
        mgr.advance(sprint.id)  # execute
        mgr.advance(sprint.id)  # review
        result = mgr.advance(sprint.id)  # completed

        assert result is None
        assert sprint.status == "completed"


# ============================================================================
# EVIDENCE TESTS (Extended)
# ============================================================================

class TestEvidenceEntryExtended:
    """Extended tests for EvidenceEntry."""

    def test_all_fields(self):
        from agent.workflow.evidence import EvidenceEntry
        entry = EvidenceEntry(
            timestamp="2024-01-01T12:00:00Z",
            action="trade",
            input_data="BUY AAPL 100",
            output_data="Order #12345 placed",
            mode="fin",
            evidence_path="/tmp/trade.png",
            sprint_id="sprint-1",
            severity="critical"
        )

        assert entry.timestamp == "2024-01-01T12:00:00Z"
        assert entry.action == "trade"
        assert entry.severity == "critical"


class TestEvidenceTrailExtended:
    """Extended tests for EvidenceTrail."""

    def test_log_truncates_long_input(self, tmp_path):
        from agent.workflow.evidence import EvidenceTrail
        trail = EvidenceTrail()
        trail.LOG_DIR = tmp_path
        trail._log_path = tmp_path / "audit.jsonl"

        long_input = "x" * 1000
        trail.log("test", long_input, "output")

        entries = trail.get_recent(1)
        assert len(entries[0]["input"]) <= 500

    def test_malformed_json_handling(self, tmp_path):
        from agent.workflow.evidence import EvidenceTrail
        trail = EvidenceTrail()
        trail.LOG_DIR = tmp_path
        trail._log_path = tmp_path / "audit.jsonl"

        # Write some valid and invalid entries
        with open(trail._log_path, "w") as f:
            f.write('{"valid": true}\n')
            f.write('INVALID JSON\n')
            f.write('{"valid": true}\n')

        entries = trail.get_recent(10)
        assert len(entries) == 2  # Only valid entries

    def test_get_stats_empty(self, tmp_path):
        from agent.workflow.evidence import EvidenceTrail
        trail = EvidenceTrail()
        trail.LOG_DIR = tmp_path
        trail._log_path = tmp_path / "audit.jsonl"

        stats = trail.get_stats()
        assert stats["total"] == 0

    def test_format_recent_output(self, tmp_path):
        from agent.workflow.evidence import EvidenceTrail
        trail = EvidenceTrail()
        trail.LOG_DIR = tmp_path
        trail._log_path = tmp_path / "audit.jsonl"

        trail.log("command", "ls -la", "listed files", severity="info")
        trail.log("trade", "BUY", "order placed", severity="critical", evidence_path="/tmp/proof.png")

        formatted = trail.format_recent(10)

        assert "Evidence Trail" in formatted
        assert "command" in formatted
        assert "trade" in formatted
        assert "proof.png" in formatted

    def test_get_by_action_limits(self, tmp_path):
        from agent.workflow.evidence import EvidenceTrail
        trail = EvidenceTrail()
        trail.LOG_DIR = tmp_path
        trail._log_path = tmp_path / "audit.jsonl"

        for i in range(30):
            trail.log("command", f"cmd {i}", "ok")

        # Limit to 10
        commands = trail.get_by_action("command", limit=10)
        assert len(commands) == 10


class TestEvidenceTrailSingleton:
    """Test EvidenceTrail singleton."""

    def test_get_evidence_trail_singleton(self):
        from agent.workflow.evidence import get_evidence_trail
        trail1 = get_evidence_trail()
        trail2 = get_evidence_trail()

        assert trail1 is trail2


# ============================================================================
# REVIEW TESTS (Extended)
# ============================================================================

class TestReviewDispatcherExtended:
    """Extended tests for ReviewDispatcher."""

    def test_unknown_mode_default(self):
        from agent.workflow.review import ReviewDispatcher
        d = ReviewDispatcher()

        prompt = d.get_review_prompt("unknown_mode")
        assert prompt is not None
        assert "Self-Review" in prompt

    def test_should_review_coverage(self):
        from agent.workflow.review import ReviewDispatcher
        d = ReviewDispatcher()

        # Coding mode
        assert d.should_review("coding", "file_edit") is True
        assert d.should_review("coding", "code_write") is True
        assert d.should_review("coding", "build") is True
        assert d.should_review("coding", "read_file") is False

        # Fin mode
        assert d.should_review("fin", "trade") is True
        assert d.should_review("fin", "execute") is True
        assert d.should_review("fin", "search") is False

        # Chat mode
        assert d.should_review("chat", "factual_claim") is True
        assert d.should_review("chat", "recommendation") is True
        assert d.should_review("chat", "greet") is False

        # Unknown mode
        assert d.should_review("unknown", "anything") is False
