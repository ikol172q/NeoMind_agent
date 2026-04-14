"""Phase 5.1-5.3 + CLI routing helper tests.

Covers fleet/session.py (FleetSession state + focus + event buffer +
mention parser + task dispatch wrappers) and the input-routing helper
methods on cli/neomind_interface.py that don't require a live
prompt_toolkit session (those land in Phase 5.10 live smoke).

Zero real LLM calls — every worker is driven by a mocked
_default_llm_call via monkeypatch.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

import fleet.worker_turn as worker_turn
from fleet.project_schema import MemberConfig, ProjectConfig, load_project_config
from fleet.session import (
    FleetEvent,
    FleetSession,
    FleetSessionError,
    LEADER_FOCUS,
    parse_mention,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_config(members_spec):
    """Build a minimal ProjectConfig for tests.

    members_spec is a list of (name, persona, role) tuples.
    """
    members = [
        MemberConfig(name=n, persona=p, role=r) for n, p, r in members_spec
    ]
    return ProjectConfig(
        project_id="test-proj",
        description="test",
        leader=next((m.name for m in members if m.role == "leader"), "chair"),
        members=members,
        settings={},
    )


# ── parse_mention ──────────────────────────────────────────────────────


def test_parse_mention_valid():
    assert parse_mention("@fin-rt analyze AAPL") == ("fin-rt", "analyze AAPL")
    assert parse_mention("@coder_1 refactor this") == ("coder_1", "refactor this")
    assert parse_mention("@a1 x") == ("a1", "x")


def test_parse_mention_no_at_prefix():
    assert parse_mention("hello @fin-rt") is None
    assert parse_mention("just text") is None


def test_parse_mention_empty_rest():
    assert parse_mention("@fin-rt") is None
    assert parse_mention("@fin-rt ") is None


def test_parse_mention_non_alpha_start():
    assert parse_mention("@123 foo") is None
    assert parse_mention("@-name foo") is None


def test_parse_mention_non_string():
    assert parse_mention(None) is None
    assert parse_mention(42) is None


def test_parse_mention_multiline_rest():
    assert parse_mention("@fin-rt line1\nline2") == ("fin-rt", "line1\nline2")


# ── FleetSession construction + basic introspection ───────────────────


def test_session_member_names_excludes_leader():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
        ("w2", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    assert s.member_names() == ["w1", "w2"]
    assert "chair" not in s.member_names()
    assert s.all_member_names() == ["chair", "w1", "w2"]


def test_session_initial_focus_is_leader():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
    ])
    s = FleetSession(cfg)
    assert s.focus == LEADER_FOCUS
    assert s.is_focused_on_leader() is True
    assert s.focused_member_name() is None


def test_session_not_running_before_start():
    cfg = _make_config([("chair", "chat", "leader")])
    s = FleetSession(cfg)
    assert s.running is False
    assert s.uptime == 0.0


# ── Focus cycling ──────────────────────────────────────────────────────


def test_cycle_focus_forward_through_all_targets_then_wraps():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
        ("w2", "fin", "worker"),
        ("w3", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    seq = [s.focus]
    for _ in range(6):
        seq.append(s.cycle_focus(+1))
    # Sequence: leader → w1 → w2 → w3 → leader → w1 → w2
    assert seq == [
        LEADER_FOCUS, "w1", "w2", "w3", LEADER_FOCUS, "w1", "w2",
    ]


def test_cycle_focus_backward():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
        ("w2", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    # Start at leader
    assert s.cycle_focus(-1) == "w2"
    assert s.cycle_focus(-1) == "w1"
    assert s.cycle_focus(-1) == LEADER_FOCUS


def test_set_focus_valid_target():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
    ])
    s = FleetSession(cfg)
    assert s.set_focus("w1") is True
    assert s.focus == "w1"
    assert s.focused_member_name() == "w1"


def test_set_focus_same_target_returns_false():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    s.set_focus("w1")
    assert s.set_focus("w1") is False  # already there


def test_set_focus_unknown_rejects():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    assert s.set_focus("nonexistent") is False
    assert s.focus == LEADER_FOCUS


def test_set_focus_cannot_target_leader_member_by_name():
    """Leader is the leader slot, not a focusable sub-agent.
    Setting focus to the leader's name should be rejected — use
    LEADER_FOCUS sentinel instead."""
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    s.set_focus("w1")
    assert s.set_focus("chair") is False  # leader name is not a tag
    assert s.focus == "w1"  # unchanged


def test_set_focus_leader_sentinel():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    s.set_focus("w1")
    assert s.set_focus(LEADER_FOCUS) is True
    assert s.focus == LEADER_FOCUS


# ── Event ring buffer ──────────────────────────────────────────────────


def test_record_event_appends_to_ring_buffer():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    s._record_event("w1", {"kind": "task_received", "content": "refactor x"})
    s._record_event("w1", {"kind": "llm_call_start", "content": "deepseek"})
    events = s.recent_events("w1")
    assert len(events) == 2
    assert [e.kind for e in events] == ["task_received", "llm_call_start"]


def test_record_event_ring_buffer_caps_at_200():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    for i in range(300):
        s._record_event("w1", {"kind": "tick", "content": f"{i}"})
    assert len(s._event_buffers["w1"]) == 200  # deque maxlen
    # Oldest 100 dropped, keeping 100..299
    kinds = list(s._event_buffers["w1"])
    assert kinds[0].content == "100"
    assert kinds[-1].content == "299"


def test_record_event_unknown_member_silently_drops():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    # Should not raise
    s._record_event("nonexistent", {"kind": "x", "content": "y"})
    assert len(s._event_buffers["w1"]) == 0


def test_recent_events_limit():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    for i in range(10):
        s._record_event("w1", {"kind": "tick", "content": str(i)})
    last5 = s.recent_events("w1", limit=5)
    assert len(last5) == 5
    assert [e.content for e in last5] == ["5", "6", "7", "8", "9"]


def test_recent_events_leader_returns_empty():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    assert s.recent_events(LEADER_FOCUS) == []


def test_record_user_event_public_api():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    s.record_user_event("w1", "user_message", "hi from the leader")
    events = s.recent_events("w1")
    assert len(events) == 1
    assert events[0].kind == "user_message"


def test_record_user_event_unknown_member_raises():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    with pytest.raises(FleetSessionError):
        s.record_user_event("nonexistent", "user_message", "x")


# ── Input history ─────────────────────────────────────────────────────


def test_input_history_per_member_isolated():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
        ("w2", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    s.record_input("w1", "refactor this file")
    s.record_input("w1", "now test it")
    s.record_input("w2", "analyze AAPL")
    assert s.input_history("w1") == ["refactor this file", "now test it"]
    assert s.input_history("w2") == ["analyze AAPL"]
    assert s.input_history(LEADER_FOCUS) == []


def test_input_history_caps_at_50():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    for i in range(75):
        s.record_input("w1", f"cmd{i}")
    hist = s.input_history("w1")
    assert len(hist) == 50
    assert hist[0] == "cmd25"
    assert hist[-1] == "cmd74"


# ── Leader @mention preprocessing ─────────────────────────────────────


def test_handle_leader_input_valid_mention():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    result = s.handle_leader_input("@fin-rt analyze AAPL")
    assert result == ("fin-rt", "analyze AAPL")


def test_handle_leader_input_unknown_member_falls_through():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    # @no-such is syntactically valid but the member doesn't exist —
    # should return None so the CLI falls through to normal LLM
    # handling (don't block the user on a typo).
    assert s.handle_leader_input("@no-such foo") is None


def test_handle_leader_input_empty_rest_falls_through():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    assert s.handle_leader_input("@fin-rt") is None


def test_handle_leader_input_no_mention():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    assert s.handle_leader_input("regular chat message") is None


def test_handle_leader_input_cannot_mention_leader():
    """Leader name is not a focusable tag — mentioning it falls through."""
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)
    assert s.handle_leader_input("@chair something") is None


# ── Status snapshot ───────────────────────────────────────────────────


def test_status_snapshot_without_launcher():
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
        ("w2", "fin", "worker"),
    ])
    s = FleetSession(cfg)
    snap = s.status_snapshot()
    assert snap["project_id"] == "test-proj"
    assert snap["running"] is False
    assert snap["focus"] == LEADER_FOCUS
    member_names = [m["name"] for m in snap["members"]]
    assert member_names == ["w1", "w2"]  # leader excluded


# ── End-to-end with mocked LLM ────────────────────────────────────────


class _MockLlm:
    def __init__(self, response="done"):
        self.response = response
        self.calls = []

    async def __call__(self, model, system_prompt, user_prompt):
        self.calls.append({
            "model": model,
            "prompt": user_prompt,
        })
        return self.response


def test_end_to_end_submit_to_member_with_events(tmp_path, monkeypatch):
    """Start a session with a mocked LLM, submit a task to a specific
    member, verify events flow through the ring buffer."""
    mock = _MockLlm(
        '{"signal":"hold","confidence":5,"reason":"test","sources":["mock"]}'
    )
    monkeypatch.setattr(worker_turn, "_default_llm_call", mock)

    cfg = load_project_config("projects/coding-smoke/project.yaml")
    s = FleetSession(cfg, base_dir=str(tmp_path / "fleet"))

    async def go():
        await s.start()
        task_id = await s.submit_to_member("coder-1", "add a comment")
        assert isinstance(task_id, str)
        # Wait for events to flow
        for _ in range(40):
            events = s.recent_events("coder-1")
            kinds = [e.kind for e in events]
            if "task_completed" in kinds or "task_failed" in kinds:
                break
            await asyncio.sleep(0.1)
        await s.stop()

    asyncio.run(go())

    events = s.recent_events("coder-1", limit=20)
    kinds = [e.kind for e in events]
    # Must include the lifecycle markers
    assert "spawned" in kinds
    assert "task_received" in kinds
    assert "llm_call_start" in kinds
    assert "llm_call_end" in kinds
    assert "task_completed" in kinds
    # LLM was called exactly once
    assert len(mock.calls) == 1


def test_submit_to_member_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_turn, "_default_llm_call", _MockLlm())
    cfg = load_project_config("projects/coding-smoke/project.yaml")
    s = FleetSession(cfg, base_dir=str(tmp_path / "fleet"))

    async def go():
        await s.start()
        try:
            with pytest.raises(FleetSessionError):
                await s.submit_to_member("nonexistent", "task")
        finally:
            await s.stop()

    asyncio.run(go())


def test_submit_without_start_raises():
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)

    async def go():
        with pytest.raises(FleetSessionError):
            await s.submit_to_member("w1", "task")

    asyncio.run(go())


def test_stop_is_idempotent():
    """Calling stop() before start() or twice must not crash."""
    cfg = _make_config([("chair", "chat", "leader"), ("w1", "coding", "worker")])
    s = FleetSession(cfg)

    async def go():
        await s.stop()  # before start — no-op
        await s.stop()  # again — no-op

    asyncio.run(go())
    assert s.running is False


def test_start_idempotent_warns_but_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_turn, "_default_llm_call", _MockLlm())
    cfg = load_project_config("projects/coding-smoke/project.yaml")
    s = FleetSession(cfg, base_dir=str(tmp_path / "fleet"))

    async def go():
        await s.start()
        await s.start()  # second call should be a no-op
        assert s.running is True
        await s.stop()

    asyncio.run(go())


# ── CLI helper smoke (indirect) ───────────────────────────────────────


def test_fleet_event_color_mapping():
    """The CLI renderer uses _fleet_event_color to pick tag colors
    by event kind. Verify the mapping is sane."""
    from cli.neomind_interface import NeoMindInterface
    assert NeoMindInterface._fleet_event_color("task_completed") == "bold green"
    assert NeoMindInterface._fleet_event_color("task_failed") == "bold red"
    assert NeoMindInterface._fleet_event_color("llm_call_start") == "yellow"
    assert NeoMindInterface._fleet_event_color("llm_call_end") == "green"
    assert NeoMindInterface._fleet_event_color("unknown_kind") == "white"


def test_fleet_toolbar_line_empty_when_no_session():
    """No FleetSession → toolbar line is empty string, keeping the
    bottom bar identical to legacy single-session behavior."""
    from cli.neomind_interface import NeoMindInterface

    class Stub:
        _fleet_session = None
        _fleet_tag_nav_active = False
        _fleet_tag_cursor = 0

    line = NeoMindInterface._fleet_toolbar_line(Stub())
    assert line == ""


def test_fleet_toolbar_line_renders_tags_with_focus_marker():
    """Phase 5.12: when focus is on a sub-agent, that tag renders in
    bold magenta (session.focus highlight). The leader slot is
    bracketed. When tag-nav mode is not active, no reverse-video
    cursor is shown."""
    from cli.neomind_interface import NeoMindInterface

    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
        ("dev-1", "coding", "worker"),
    ])
    session = FleetSession(cfg)
    session.set_focus("fin-rt")

    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = False
        _fleet_tag_cursor = 0

    line = NeoMindInterface._fleet_toolbar_line(Stub())
    assert "@fin-rt" in line
    assert "@dev-1" in line
    assert "[chair]" in line  # leader slot bracket label
    # Focused tag is bold + underlined
    assert "<b><u>@fin-rt</u></b>" in line
    # Navigation hint at end (tag-nav not active)
    assert "navigate" in line


def test_fleet_toolbar_line_tag_nav_cursor_highlight():
    """When tag-nav is active, the cursor position is reverse-video
    highlighted, independent of which tag is currently the session
    focus."""
    from cli.neomind_interface import NeoMindInterface

    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
        ("dev-1", "coding", "worker"),
    ])
    session = FleetSession(cfg)
    # focus = leader, but cursor moved to @dev-1 (index 2)
    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = True
        _fleet_tag_cursor = 2  # points at @dev-1

    line = NeoMindInterface._fleet_toolbar_line(Stub())
    # The dev-1 tag should be wrapped in bg="ansiyellow" for cursor highlight
    assert 'bg="ansiyellow"' in line
    assert "dev-1" in line
    # Navigation hint reflects tag-nav mode
    assert "Enter" in line or "Esc" in line


# ── Phase 5.12 regression guards — added after full UX audit ────────

def test_cursor_highlight_uses_explicit_bg_not_reverse():
    """Phase 5.12: the tag-nav cursor highlight must use an explicit
    `bg="ansiyellow"` + `fg="ansiblack"` style, NOT `<reverse>`.

    Why this guard exists: an earlier implementation used `<reverse>`,
    which double-cancels against prompt_toolkit's already-reversed
    bottom_toolbar style. The cursor rendered as green / gray / invisible
    depending on the tag's current event color. The user rejected that
    flaky rendering ("有时候绿色，有时候灰色有时候看不清"). The explicit
    bg+fg style renders consistently regardless of context.
    """
    from cli.neomind_interface import NeoMindInterface
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
    ])
    session = FleetSession(cfg)

    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = True
        _fleet_tag_cursor = 1
    line = NeoMindInterface._fleet_toolbar_line(Stub())
    assert "<reverse>" not in line, (
        "cursor highlight regressed to <reverse>; must use explicit "
        "bg/fg style so it renders consistently"
    )
    assert 'bg="ansiyellow"' in line
    assert 'fg="ansiblack"' in line


def test_toolbar_has_no_background_rainbow():
    """Phase 5.12: status-based tag colors must use FOREGROUND only
    (ansired/ansiyellow/ansibrightblack). No `bg=` backgrounds except
    the tag-nav cursor itself. User complaint that triggered this:
    "颜色过多，分不清哪里是哪里" — the previous event-based background
    coloring (red/yellow/green/magenta backgrounds) was visually noisy.
    """
    from cli.neomind_interface import NeoMindInterface
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
        ("dev-1", "coding", "worker"),
    ])
    session = FleetSession(cfg)
    # NOT in tag-nav mode — only status colors should apply
    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = False
        _fleet_tag_cursor = 0
    line = NeoMindInterface._fleet_toolbar_line(Stub())
    # No bg= attributes when tag-nav is off (no cursor to highlight)
    assert "bg=" not in line, (
        "toolbar uses background colors in non-nav state; the user "
        "rejected the background-color rainbow — use fg only"
    )


def test_compute_prompt_str_reflects_mode_switch():
    """Phase 5.12: after /mode coding, the prompt prefix must become
    `> ` (no `[fin]`). Regression guard for the mode-switch discussion
    where the user saw stale `[fin] > ` in scrollback and thought the
    switch had silently failed.
    """
    from cli.neomind_interface import NeoMindInterface
    from agent.core import NeoMindAgent

    agent = NeoMindAgent()
    agent.switch_mode("fin", persist=False)
    iface = NeoMindInterface(agent)
    assert iface._compute_prompt_str() == "[fin] > "

    agent.switch_mode("coding", persist=False)
    assert iface._compute_prompt_str() == "> "

    agent.switch_mode("chat", persist=False)
    assert iface._compute_prompt_str() == "[chat] > "


def test_compute_prompt_str_sub_agent_focus_prefix():
    """Phase 5.12: when a fleet is running AND focus is on a worker,
    the prompt must be `[@<name> <persona>] > ` so the user knows
    exactly where their typed input will land.
    """
    from cli.neomind_interface import NeoMindInterface
    from agent.core import NeoMindAgent

    agent = NeoMindAgent()
    iface = NeoMindInterface(agent)

    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
        ("dev-1", "coding", "worker"),
    ])
    session = FleetSession(cfg)
    iface._fleet_session = session

    session.set_focus("fin-rt")
    assert iface._compute_prompt_str() == "[@fin-rt fin] > "

    session.set_focus("dev-1")
    assert iface._compute_prompt_str() == "[@dev-1 coding] > "

    # Back to leader — prompt reflects main agent mode
    from fleet.session import LEADER_FOCUS
    session.set_focus(LEADER_FOCUS)
    agent.switch_mode("fin", persist=False)
    assert iface._compute_prompt_str() == "[fin] > "


def test_toolbar_hint_says_down_not_up():
    """Phase 5.12: the navigation hint text must direct the user to
    press Down (not Up), because the fleet tag row sits BELOW the
    input — pressing Down to reach it is the natural direction.
    """
    from cli.neomind_interface import NeoMindInterface
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
    ])
    session = FleetSession(cfg)

    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = False
        _fleet_tag_cursor = 0
    line = NeoMindInterface._fleet_toolbar_line(Stub())
    assert "↓" in line, "hint should show ↓ (Down) as tag-nav entry"
    assert "↑ to navigate" not in line, (
        "stale Up hint — the user rejected Up because tags are BELOW"
    )


def test_no_ctrl_arrow_bindings_in_key_bindings_source():
    """Phase 5.12: user explicitly rejected Ctrl+arrow shortcuts
    ("和系统有冲突而且很难看"). Guard the neomind_interface source so
    no one accidentally re-adds `c-left` / `c-right` / `c-up` / `c-down`
    key bindings for fleet tag navigation.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "cli" / "neomind_interface.py"
    text = src.read_text(encoding="utf-8")

    for banned in ('"c-left"', '"c-right"', '"c-up"', '"c-down"'):
        assert banned not in text, (
            f"Ctrl+arrow binding regressed: {banned} found in "
            f"neomind_interface.py — user rejected Ctrl+arrow for "
            f"system-conflict + aesthetic reasons; use plain arrows "
            f"(filtered by Condition) instead"
        )


def test_unread_completion_badge_renders_in_toolbar():
    """Phase 5.12 task #67: when a worker completes a task while the
    user was focused on a different agent, the toolbar renders a
    bright-green ● badge on that worker's tag so the user can see
    at-a-glance that there is an unacknowledged reply waiting."""
    from cli.neomind_interface import NeoMindInterface
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
        ("fin-rsrch", "fin", "worker"),
    ])
    session = FleetSession(cfg)
    session.set_focus("fin-rt")

    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = False
        _fleet_tag_cursor = 0
        _fleet_unread_completion = {"fin-rsrch"}  # rsrch finished while user was on rt

    line = NeoMindInterface._fleet_toolbar_line(Stub())
    # fin-rsrch should have the badge; fin-rt (currently focused) should NOT
    assert "fin-rsrch" in line
    assert 'fg="ansibrightgreen"' in line
    assert "●" in line
    # Badge must be attached to the rsrch tag, not the rt tag
    rt_segment = line.split("@fin-rsrch")[0]
    assert "●" not in rt_segment, (
        "unread badge should only attach to the agent with the unread "
        "completion, not the currently-focused one"
    )


def test_unread_completion_badge_absent_by_default():
    """Guard: when no agent has an unread completion, the toolbar
    contains no ● badge at all."""
    from cli.neomind_interface import NeoMindInterface
    cfg = _make_config([
        ("chair", "chat", "leader"),
        ("fin-rt", "fin", "worker"),
    ])
    session = FleetSession(cfg)

    class Stub:
        _fleet_session = session
        _fleet_tag_nav_active = False
        _fleet_tag_cursor = 0
        _fleet_unread_completion = set()
    line = NeoMindInterface._fleet_toolbar_line(Stub())
    assert "●" not in line
    assert "ansibrightgreen" not in line
