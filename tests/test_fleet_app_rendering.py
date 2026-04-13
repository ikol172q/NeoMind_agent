"""Tests for cli/fleet_app.py — pure render-function tests that don't
require running the full prompt_toolkit Application.

The critical Phase 5.11 property these tests lock in: **switching
focus preserves each view's content** because the renderer reads
from independent persistent lists, not a shared ring buffer.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

# prompt_toolkit's FormattedText is just a list subclass of tuples,
# so we can inspect it directly.
try:
    from prompt_toolkit.formatted_text import FormattedText
except ImportError:
    FormattedText = None  # type: ignore

from fleet.project_schema import MemberConfig, ProjectConfig
from fleet.session import FleetSession, LEADER_FOCUS
from fleet.transcripts import AgentTurn


# Skip every test if prompt_toolkit isn't available
pytestmark = pytest.mark.skipif(
    FormattedText is None, reason="prompt_toolkit not installed"
)


def _make_cfg(member_specs):
    members = [
        MemberConfig(name=n, persona=p, role=r) for n, p, r in member_specs
    ]
    return ProjectConfig(
        project_id="test-proj",
        description="",
        leader=next((m.name for m in members if m.role == "leader"), "chair"),
        members=members,
        settings={},
    )


@pytest.fixture
def stock_session(tmp_path):
    """Fresh session with 1 leader + 2 sub-agents, in a tmp base dir
    so transcripts don't clobber real ones."""
    cfg = _make_cfg([
        ("chair", "chat", "leader"),
        ("w1", "coding", "worker"),
        ("w2", "fin", "worker"),
    ])
    return FleetSession(cfg, base_dir=str(tmp_path / "fleet"))


@pytest.fixture
def mock_leader_chat():
    """A minimal object that imitates NeoMindAgent just enough for
    the leader-view renderer to inspect conversation_history."""

    class MockAgent:
        conversation_history = [
            {"role": "system", "content": "you are a helpful assistant"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    return MockAgent()


def _flatten_text(ft) -> str:
    """Return the concatenated plain text from a FormattedText list."""
    if ft is None:
        return ""
    return "".join(text for (_style, text) in ft)


# ── Status bar ─────────────────────────────────────────────────────────


def test_status_bar_shows_project_and_leader_bracket(stock_session):
    from cli.fleet_app import FleetApplication
    app = FleetApplication(stock_session)
    ft = app._render_status_bar()
    text = _flatten_text(ft)
    assert "test-proj" in text
    assert "[chair]" in text
    assert "@w1" in text
    assert "@w2" in text
    # Initial focus is leader → no star on any sub-agent tag
    assert "@w1*" not in text
    assert "@w2*" not in text


def test_status_bar_marks_focused_sub_agent(stock_session):
    from cli.fleet_app import FleetApplication
    stock_session.set_focus("w2")
    app = FleetApplication(stock_session)
    ft = app._render_status_bar()
    text = _flatten_text(ft)
    assert "@w2*" in text
    assert "@w1*" not in text


# ── Message area: state-driven source switch (Phase 5.11 CRITICAL) ─────


def test_message_area_leader_view_renders_leader_history(
    stock_session, mock_leader_chat,
):
    """When focused on leader, the message area MUST render the main
    chat history — not any sub-agent's transcript."""
    from cli.fleet_app import FleetApplication
    # Seed a sub-agent transcript so we can tell the two sources apart
    t1 = stock_session.get_transcript("w1")
    t1.append_turn(AgentTurn(role="user", content="agent1-only-content"))

    app = FleetApplication(stock_session, leader_chat=mock_leader_chat)
    ft = app._render_message_area()
    text = _flatten_text(ft)
    # Must include leader's chat history
    assert "hello" in text
    assert "hi there" in text
    # Must NOT include w1's transcript content
    assert "agent1-only-content" not in text


def test_message_area_agent_view_renders_that_agents_transcript(
    stock_session, mock_leader_chat,
):
    """When focused on w1, the message area MUST render w1's
    transcript — not the leader's chat, not w2's transcript."""
    from cli.fleet_app import FleetApplication
    t1 = stock_session.get_transcript("w1")
    t1.append_turn(AgentTurn(role="user", content="agent1-prompt"))
    t1.append_turn(AgentTurn(role="assistant", content="agent1-response"))
    t2 = stock_session.get_transcript("w2")
    t2.append_turn(AgentTurn(role="user", content="agent2-prompt"))

    stock_session.set_focus("w1")
    app = FleetApplication(stock_session, leader_chat=mock_leader_chat)
    ft = app._render_message_area()
    text = _flatten_text(ft)
    # w1's content appears
    assert "agent1-prompt" in text
    assert "agent1-response" in text
    # w2's content and leader's history do NOT appear
    assert "agent2-prompt" not in text
    assert "hi there" not in text  # leader's chat is hidden


def test_message_area_preserved_across_focus_switches(
    stock_session, mock_leader_chat,
):
    """The core user requirement: switching between agents preserves
    each agent's previous conversation. This test exercises a full
    switch cycle and asserts content stays bit-for-bit consistent."""
    from cli.fleet_app import FleetApplication

    # Seed distinct content per agent
    stock_session.get_transcript("w1").append_turn(
        AgentTurn(role="user", content="w1-question-A")
    )
    stock_session.get_transcript("w1").append_turn(
        AgentTurn(role="assistant", content="w1-answer-A")
    )
    stock_session.get_transcript("w2").append_turn(
        AgentTurn(role="user", content="w2-question-B")
    )
    stock_session.get_transcript("w2").append_turn(
        AgentTurn(role="assistant", content="w2-answer-B")
    )

    app = FleetApplication(stock_session, leader_chat=mock_leader_chat)

    # Snapshot w1's view
    stock_session.set_focus("w1")
    w1_text_first = _flatten_text(app._render_message_area())
    assert "w1-question-A" in w1_text_first
    assert "w1-answer-A" in w1_text_first

    # Switch to w2 — its content appears
    stock_session.set_focus("w2")
    w2_text = _flatten_text(app._render_message_area())
    assert "w2-question-B" in w2_text
    assert "w2-answer-B" in w2_text
    # w1's content is NOT in w2's view (isolation)
    assert "w1-question-A" not in w2_text

    # Switch BACK to w1 — content must be bit-for-bit preserved
    stock_session.set_focus("w1")
    w1_text_second = _flatten_text(app._render_message_area())
    assert "w1-question-A" in w1_text_second
    assert "w1-answer-A" in w1_text_second
    # This is the critical assertion:
    assert w1_text_second == w1_text_first, (
        "switching focus away and back must preserve an agent's view "
        "bit-for-bit — if this regresses, the ring-buffer bug is back"
    )


def test_message_area_agent_view_empty_transcript_shows_hint(stock_session):
    from cli.fleet_app import FleetApplication
    stock_session.set_focus("w1")
    app = FleetApplication(stock_session)
    text = _flatten_text(app._render_message_area())
    assert "no conversation yet" in text.lower()


def test_message_area_leader_view_empty_history_still_renders(stock_session):
    from cli.fleet_app import FleetApplication

    class EmptyAgent:
        conversation_history = []

    app = FleetApplication(stock_session, leader_chat=EmptyAgent())
    text = _flatten_text(app._render_message_area())
    # No crash, renders the banner
    assert "Leader" in text or "leader" in text.lower()


def test_message_area_leader_view_without_leader_chat(stock_session):
    """leader_chat=None is a supported configuration (headless use).
    Rendering must not crash."""
    from cli.fleet_app import FleetApplication
    app = FleetApplication(stock_session, leader_chat=None)
    text = _flatten_text(app._render_message_area())
    assert "Leader" in text or "leader" in text.lower()


# ── Prompt hint + help bar ─────────────────────────────────────────────


def test_prompt_hint_leader_says_mention(stock_session):
    from cli.fleet_app import FleetApplication
    app = FleetApplication(stock_session)
    text = _flatten_text(app._render_prompt_hint())
    assert "@agent" in text or "@<agent>" in text or "@<agent_name>" in text


def test_prompt_hint_subagent_says_dispatch(stock_session):
    from cli.fleet_app import FleetApplication
    stock_session.set_focus("w1")
    app = FleetApplication(stock_session)
    text = _flatten_text(app._render_prompt_hint())
    assert "dispatch" in text.lower() or "send task" in text.lower()
    assert "@w1" in text


def test_help_bar_shows_key_reminders(stock_session):
    from cli.fleet_app import FleetApplication
    app = FleetApplication(stock_session)
    text = _flatten_text(app._render_help_bar())
    assert "Ctrl+" in text
    assert "Esc" in text
    assert "exit" in text.lower()


# ── FleetApplication construction ─────────────────────────────────────


def test_fleet_application_requires_session():
    from cli.fleet_app import FleetApplication, FleetAppError
    with pytest.raises(FleetAppError):
        FleetApplication(None)  # type: ignore[arg-type]


def test_fleet_application_constructs_without_leader_chat(stock_session):
    from cli.fleet_app import FleetApplication
    app = FleetApplication(stock_session)
    assert app.app is not None
    assert app.input_buffer is not None
