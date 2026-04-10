"""
Comprehensive unit tests for agentic/infrastructure modules.

Covers:
  1. agent.agentic.error_recovery  — ErrorRecoveryPipeline
  2. agent.agentic.stop_hooks      — StopHookPipeline, create_default_pipeline
  3. agent.agentic.swarm            — Mailbox, SharedTaskQueue, TeamManager, format_task_notification
  4. agent.services.compact.context_collapse — ContextCollapser, snip_messages
  5. agent.services.export_service  — export_markdown/json/html, detect_format, export_conversation
"""

import asyncio
import json
import os
import pytest

# ── Module 1 ────────────────────────────────────────────────────────────────
from agent.agentic.error_recovery import ErrorRecoveryPipeline

# ── Module 2 ────────────────────────────────────────────────────────────────
from agent.agentic.stop_hooks import StopHookPipeline, create_default_pipeline

# ── Module 3 ────────────────────────────────────────────────────────────────
from agent.agentic.swarm import (
    Mailbox,
    SharedTaskQueue,
    TeamManager,
    format_task_notification,
    TEAM_COLORS,
)

# ── Module 4 ────────────────────────────────────────────────────────────────
from agent.services.compact.context_collapse import ContextCollapser, snip_messages
from agent.services.compact.context_compactor import (
    CompactMessage,
    MessageRole,
    PreservePolicy,
)

# ── Module 5 ────────────────────────────────────────────────────────────────
from agent.services.export_service import (
    export_markdown,
    export_json,
    export_html,
    detect_format,
    export_conversation,
)


# ============================================================================
# Module 1: ErrorRecoveryPipeline
# ============================================================================

class TestErrorRecoveryPipeline:

    def test_creation(self):
        pipeline = ErrorRecoveryPipeline()
        assert pipeline.recovery_count == 0
        assert pipeline.max_recovery_attempts == 3

    def test_creation_custom_max(self):
        pipeline = ErrorRecoveryPipeline(max_recovery_attempts=5)
        assert pipeline.max_recovery_attempts == 5

    # -- classify_error --

    def test_classify_context_length_exceeded(self):
        p = ErrorRecoveryPipeline()
        assert p.classify_error(Exception("context length exceeded")) == "context_length_exceeded"

    def test_classify_prompt_too_long(self):
        p = ErrorRecoveryPipeline()
        assert p.classify_error(Exception("prompt too long")) == "prompt_too_long"

    def test_classify_rate_limit(self):
        p = ErrorRecoveryPipeline()
        assert p.classify_error(Exception("rate limit reached")) == "rate_limit"

    def test_classify_unknown_error_returns_none(self):
        p = ErrorRecoveryPipeline()
        assert p.classify_error(Exception("random error")) is None

    # -- is_recoverable --

    def test_is_recoverable_true(self):
        p = ErrorRecoveryPipeline()
        assert p.is_recoverable(Exception("context length exceeded")) is True

    def test_is_recoverable_false_for_unknown(self):
        p = ErrorRecoveryPipeline()
        assert p.is_recoverable(Exception("random error")) is False

    def test_is_recoverable_circuit_breaker(self):
        p = ErrorRecoveryPipeline(max_recovery_attempts=3)
        # Simulate 3 recovery attempts by directly incrementing
        p._recovery_count = 3
        # After 3 attempts, should trip the circuit breaker and return False
        assert p.is_recoverable(Exception("context length exceeded")) is False
        assert p._circuit_broken is True
        # Even after circuit is broken, still False
        assert p.is_recoverable(Exception("context length exceeded")) is False

    # -- recover (Stage 3) --

    def test_recover_stage3_trims_messages(self):
        p = ErrorRecoveryPipeline()
        # Build a long message list: 1 system + 10 user/assistant pairs = 21 msgs
        messages = [{"role": "system", "content": "You are helpful."}]
        for i in range(10):
            messages.append({"role": "user", "content": f"User message {i}"})
            messages.append({"role": "assistant", "content": f"Assistant message {i}"})

        assert len(messages) == 21  # > 6

        recovered, result, note = asyncio.get_event_loop().run_until_complete(
            p.recover(Exception("context length exceeded"), messages)
        )
        assert recovered is True
        # Result should be: system msgs + 1 recovery system msg + last 4
        system_count = sum(1 for m in result if m.get("role") == "system")
        assert system_count >= 2  # original system + recovery system
        # Last 4 messages should be preserved
        assert result[-4:] == messages[-4:]
        assert "trimmed" in (note or "").lower()

    # -- reset --

    def test_reset(self):
        p = ErrorRecoveryPipeline()
        p._recovery_count = 5
        p._circuit_broken = True
        p.reset()
        assert p.recovery_count == 0
        assert p._circuit_broken is False


# ============================================================================
# Module 2: StopHookPipeline
# ============================================================================

class TestStopHookPipeline:

    def test_creation(self):
        pipeline = StopHookPipeline()
        assert pipeline.list_hooks() == []

    def test_register_hooks(self):
        pipeline = StopHookPipeline()
        pipeline.register("a", lambda **kw: None, priority=50)
        pipeline.register("b", lambda **kw: None, priority=10)
        hooks = pipeline.list_hooks()
        assert len(hooks) == 2
        # b has lower priority so should be first
        assert hooks[0]["name"] == "b"
        assert hooks[1]["name"] == "a"

    def test_run_all_priority_order(self):
        """Hooks run in ascending priority order (lower number first)."""
        pipeline = StopHookPipeline()
        order = []
        pipeline.register("third", lambda **kw: order.append("third"), priority=30)
        pipeline.register("first", lambda **kw: order.append("first"), priority=10)
        pipeline.register("second", lambda **kw: order.append("second"), priority=20)

        pipeline.run_all()
        assert order == ["first", "second", "third"]

    def test_run_all_failure_isolation(self):
        """One hook failure must not block subsequent hooks."""
        pipeline = StopHookPipeline()
        results_collector = []

        def failing(**kw):
            raise RuntimeError("boom")

        def passing(**kw):
            results_collector.append("ok")

        pipeline.register("fail_hook", failing, priority=10)
        pipeline.register("pass_hook", passing, priority=20)

        results = pipeline.run_all()
        # The passing hook must still have run
        assert results_collector == ["ok"]
        assert results["fail_hook"]["success"] is False
        assert "boom" in results["fail_hook"]["error"]
        assert results["pass_hook"]["success"] is True

    def test_disabled_hooks_skipped(self):
        pipeline = StopHookPipeline()
        called = []
        pipeline.register("enabled", lambda **kw: called.append("e"), priority=10)
        pipeline.register("disabled", lambda **kw: called.append("d"), priority=20, enabled=False)

        results = pipeline.run_all()
        assert called == ["e"]
        assert results["disabled"].get("skipped") is True

    def test_unregister(self):
        pipeline = StopHookPipeline()
        pipeline.register("x", lambda **kw: None)
        pipeline.register("y", lambda **kw: None)
        pipeline.unregister("x")
        names = [h["name"] for h in pipeline.list_hooks()]
        assert "x" not in names
        assert "y" in names

    def test_list_hooks(self):
        pipeline = StopHookPipeline()
        pipeline.register("alpha", lambda **kw: None, priority=5, enabled=False)
        hooks = pipeline.list_hooks()
        assert hooks == [{"name": "alpha", "priority": 5, "enabled": False}]

    def test_create_default_pipeline(self):
        pipeline = create_default_pipeline(services=None)
        hooks = pipeline.list_hooks()
        assert len(hooks) == 3
        names = {h["name"] for h in hooks}
        assert names == {"session_notes", "auto_dream", "evolution"}
        # Should be in priority order
        priorities = [h["priority"] for h in hooks]
        assert priorities == sorted(priorities)


# ============================================================================
# Module 3: Swarm
# ============================================================================

class TestMailbox:

    def test_write_and_read_roundtrip(self, tmp_path):
        mb = Mailbox("test_team", "agent_a", base_dir=str(tmp_path))
        mb.write_message("agent_b", "Hello from B")
        unread = mb.read_unread()
        assert len(unread) == 1
        assert unread[0].sender == "agent_b"
        assert unread[0].content == "Hello from B"
        assert unread[0].msg_type == "text"

    def test_read_marks_as_read(self, tmp_path):
        mb = Mailbox("test_team", "agent_a", base_dir=str(tmp_path))
        mb.write_message("agent_b", "msg1")
        mb.write_message("agent_c", "msg2")

        first_read = mb.read_unread()
        assert len(first_read) == 2

        # Second read should return nothing
        second_read = mb.read_unread()
        assert len(second_read) == 0


class TestSharedTaskQueue:

    def test_add_and_claim(self, tmp_path):
        q = SharedTaskQueue("test_team", base_dir=str(tmp_path))
        task_id = q.add_task("Fix the bug", "leader")
        assert task_id.startswith("task_")

        claimed = q.try_claim_next("worker_1")
        assert claimed is not None
        assert claimed["id"] == task_id
        assert claimed["status"] == "claimed"
        assert claimed["claimed_by"] == "worker_1"

    def test_claimed_task_not_claimable_again(self, tmp_path):
        q = SharedTaskQueue("test_team", base_dir=str(tmp_path))
        q.add_task("Only task", "leader")
        q.try_claim_next("worker_1")

        # No more available tasks
        result = q.try_claim_next("worker_2")
        assert result is None

    def test_complete_task(self, tmp_path):
        q = SharedTaskQueue("test_team", base_dir=str(tmp_path))
        task_id = q.add_task("Do something", "leader")
        q.try_claim_next("worker")
        q.complete_task(task_id, result="done!")

        tasks = q.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["status"] == "completed"
        assert tasks[0]["result"] == "done!"


class TestTeamManager:

    def test_create_and_get_team(self, tmp_path):
        tm = TeamManager(base_dir=str(tmp_path))
        data = tm.create_team("alpha", "leader_1")
        assert data["name"] == "alpha"
        assert data["leader"] == "leader_1"
        assert len(data["members"]) == 1
        assert data["members"][0]["is_leader"] is True

        retrieved = tm.get_team("alpha")
        assert retrieved is not None
        assert retrieved["name"] == "alpha"

    def test_add_member_color_assignment(self, tmp_path):
        tm = TeamManager(base_dir=str(tmp_path))
        tm.create_team("beta", "leader")
        identity = tm.add_member("beta", "worker_1")

        assert identity.agent_name == "worker_1"
        assert identity.team_name == "beta"
        # Leader got TEAM_COLORS[0], worker gets TEAM_COLORS[1]
        assert identity.color == TEAM_COLORS[1]

        team = tm.get_team("beta")
        assert len(team["members"]) == 2

    def test_delete_team(self, tmp_path):
        tm = TeamManager(base_dir=str(tmp_path))
        tm.create_team("doomed", "leader")
        team_dir = tmp_path / "teams" / "doomed"
        assert team_dir.exists()

        tm.delete_team("doomed")
        assert not team_dir.exists()


class TestFormatTaskNotification:

    def test_xml_output_format(self):
        result = format_task_notification(
            task_id="task_123",
            status="completed",
            summary="Fixed the bug",
            result="All tests pass",
            tokens_used=500,
        )
        assert "<task-notification>" in result
        assert "<task-id>task_123</task-id>" in result
        assert "<status>completed</status>" in result
        assert "<summary>Fixed the bug</summary>" in result
        assert "<result>All tests pass</result>" in result
        assert "<tokens-used>500</tokens-used>" in result
        assert "</task-notification>" in result


# ============================================================================
# Module 4: ContextCollapser
# ============================================================================

def _make_msg(role, content, tokens, preserve=PreservePolicy.COMPRESSIBLE):
    return CompactMessage(
        role=role,
        content=content,
        token_count=tokens,
        preserve=preserve,
    )


class TestContextCollapser:

    def test_creation(self):
        c = ContextCollapser(max_tokens=100000, preserve_recent=3)
        assert c.max_tokens == 100000
        assert c.preserve_recent == 3

    def test_should_collapse_below_threshold(self):
        c = ContextCollapser(max_tokens=1000)
        msgs = [_make_msg(MessageRole.USER, "hi", 100)]
        assert c.should_collapse(msgs) is False  # 10% < 85%

    def test_should_collapse_above_threshold(self):
        c = ContextCollapser(max_tokens=1000)
        msgs = [_make_msg(MessageRole.USER, "hi", 900)]
        assert c.should_collapse(msgs) is True  # 90% >= 85%

    def test_collapse_old_tool_results(self):
        """Tool results older than recent window should be collapsed."""
        c = ContextCollapser(max_tokens=1000, preserve_recent=1)
        msgs = [
            _make_msg(MessageRole.USER, "q1", 100),
            _make_msg(
                MessageRole.TOOL_RESULT,
                "A" * 300,  # >200 chars, compressible, old
                400,
            ),
            _make_msg(MessageRole.ASSISTANT, "reply", 100),
            # Recent user message (preserve_recent=1 keeps this one)
            _make_msg(MessageRole.USER, "q2", 100),
            _make_msg(MessageRole.ASSISTANT, "r2", 200),
        ]
        # Total = 900 / 1000 = 90% → should collapse
        result, freed = c.collapse(msgs)
        assert freed > 0
        # The tool result should have been collapsed
        tool_msgs = [m for m in result if m.role == MessageRole.TOOL_RESULT]
        assert len(tool_msgs) == 1
        assert "[Collapsed tool result:" in tool_msgs[0].content

    def test_collapse_preserves_recent(self):
        """Recent messages should not be collapsed."""
        c = ContextCollapser(max_tokens=1000, preserve_recent=2)
        msgs = [
            _make_msg(MessageRole.USER, "old question", 100),
            _make_msg(MessageRole.ASSISTANT, "old answer", 50),
            _make_msg(MessageRole.USER, "recent q1", 300),
            _make_msg(MessageRole.ASSISTANT, "recent a1", 200),
            _make_msg(MessageRole.USER, "recent q2", 200),
            _make_msg(MessageRole.ASSISTANT, "recent a2", 50),
        ]
        # 900/1000 = 90%
        result, freed = c.collapse(msgs)
        # Recent messages preserved — check last 4 messages are unchanged
        assert result[-1].content == "recent a2"
        assert result[-2].content == "recent q2"

    def test_snip_messages(self):
        msgs = [
            _make_msg(MessageRole.USER, "a", 10),
            _make_msg(MessageRole.ASSISTANT, "b", 10),
            _make_msg(MessageRole.USER, "c", 10),
        ]
        result = snip_messages(msgs, [1])
        assert len(result) == 2
        assert result[0].content == "a"
        assert result[1].content == "c"


# ============================================================================
# Module 5: ExportService
# ============================================================================

SAMPLE_HISTORY = [
    {"role": "system", "content": "You are NeoMind."},
    {"role": "user", "content": "Hello, who are you?"},
    {"role": "assistant", "content": "I am NeoMind, your AI assistant."},
]


class TestExportMarkdown:

    def test_contains_user_header(self):
        md = export_markdown(SAMPLE_HISTORY)
        assert "## User" in md

    def test_contains_assistant_header(self):
        md = export_markdown(SAMPLE_HISTORY)
        assert "## Assistant" in md

    def test_skips_system_messages(self):
        md = export_markdown(SAMPLE_HISTORY)
        assert "## System" not in md


class TestExportJson:

    def test_valid_json_with_messages_key(self):
        output = export_json(SAMPLE_HISTORY)
        data = json.loads(output)
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_system_messages_excluded_by_default(self):
        output = export_json(SAMPLE_HISTORY)
        data = json.loads(output)
        roles = [m["role"] for m in data["messages"]]
        assert "system" not in roles

    def test_message_count_field(self):
        output = export_json(SAMPLE_HISTORY)
        data = json.loads(output)
        assert data["message_count"] == len(SAMPLE_HISTORY)


class TestExportHtml:

    def test_contains_html_tag(self):
        html_out = export_html(SAMPLE_HISTORY)
        assert "<html" in html_out

    def test_contains_doctype(self):
        html_out = export_html(SAMPLE_HISTORY)
        assert "<!DOCTYPE html>" in html_out

    def test_user_content_escaped(self):
        history = [{"role": "user", "content": "<script>alert(1)</script>"}]
        html_out = export_html(history)
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out


class TestDetectFormat:

    @pytest.mark.parametrize("filename, expected", [
        ("export.md", "markdown"),
        ("data.json", "json"),
        ("page.html", "html"),
        ("notes.txt", "text"),
        ("readme.markdown", "markdown"),
        ("page.htm", "html"),
    ])
    def test_detect_format(self, filename, expected):
        assert detect_format(filename) == expected

    def test_default_is_markdown(self):
        assert detect_format("noext") == "markdown"


class TestExportConversation:

    def test_markdown_format(self):
        result = export_conversation(SAMPLE_HISTORY, fmt="markdown")
        assert "## User" in result

    def test_json_format(self):
        result = export_conversation(SAMPLE_HISTORY, fmt="json")
        data = json.loads(result)
        assert "messages" in data

    def test_html_format(self):
        result = export_conversation(SAMPLE_HISTORY, fmt="html")
        assert "<html" in result

    def test_text_format_falls_back_to_markdown(self):
        result = export_conversation(SAMPLE_HISTORY, fmt="text")
        assert "## User" in result
