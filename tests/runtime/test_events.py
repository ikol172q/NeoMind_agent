"""Events must be immutable and ordered.

Immutability is the structural fix for the approval defect: the old loop
yielded a mutable event and re-read `.approved` from it afterwards, so consent
was whatever the object happened to hold by then. If an event cannot be
written to, that whole class of bug is unrepresentable.
"""

import dataclasses

import pytest

from agent.runtime.events import (
    TERMINAL_EVENT_TYPES,
    PermissionRequested,
    SequenceGenerator,
    TextDelta,
    ToolFinished,
    TurnFailed,
    TurnFinished,
    TurnStarted,
    new_call_id,
    new_request_id,
    new_session_id,
    new_turn_id,
)

ENVELOPE = {"session_id": "s1", "turn_id": "t1", "sequence": 0}


def test_events_are_frozen():
    ev = TextDelta(**ENVELOPE, text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.text = "tampered"


def test_permission_event_cannot_be_answered_by_mutation():
    """There is no `approved` field to set — that is the point.

    A surface answers through resolve_permission(request_id, decision); it can
    never grant consent by writing to an object the runtime will read again.
    """
    ev = PermissionRequested(**ENVELOPE, request_id="r1", tool_name="Write")

    assert not hasattr(ev, "approved")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.tool_name = "Read"


def test_every_event_carries_the_envelope():
    for ev in (
        TurnStarted(**ENVELOPE),
        TextDelta(**ENVELOPE, text="x"),
        ToolFinished(**ENVELOPE, call_id="c", tool_name="Read", success=True),
        TurnFinished(**ENVELOPE, response="done"),
    ):
        assert ev.session_id and ev.turn_id
        assert ev.sequence == 0
        assert ev.timestamp > 0
        assert ev.type, "every event needs a stable wire name"


def test_wire_names_are_stable_snake_case():
    """Renderers and replay fixtures key on these strings, not class names."""
    assert TextDelta(**ENVELOPE).type == "text_delta"
    assert TurnFinished(**ENVELOPE).type == "turn_finished"
    assert PermissionRequested(**ENVELOPE).type == "permission_requested"


def test_sequence_is_monotonic_within_a_turn():
    seq = SequenceGenerator()
    values = [seq.next() for _ in range(5)]
    assert values == sorted(values) == [0, 1, 2, 3, 4]


def test_separate_turns_get_independent_sequences():
    """Per-turn, so a consumer checking for gaps need not model interleaving."""
    a, b = SequenceGenerator(), SequenceGenerator()
    assert a.next() == 0 and b.next() == 0
    assert a.next() == 1


def test_terminal_event_set_is_exactly_finish_and_fail():
    assert TERMINAL_EVENT_TYPES == {"turn_finished", "turn_failed"}
    assert TurnFinished(**ENVELOPE).type in TERMINAL_EVENT_TYPES
    assert TurnFailed(**ENVELOPE).type in TERMINAL_EVENT_TYPES
    assert TextDelta(**ENVELOPE).type not in TERMINAL_EVENT_TYPES


def test_ids_are_unique_and_prefixed():
    for factory, prefix in (
        (new_session_id, "ses_"),
        (new_turn_id, "trn_"),
        (new_call_id, "cal_"),
        (new_request_id, "req_"),
    ):
        ids = {factory() for _ in range(200)}
        assert len(ids) == 200, f"{prefix} ids collided"
        assert all(i.startswith(prefix) for i in ids)
