"""The harness that refuses vacuous passes — tested against the real failures.

Each test here replays something that actually happened in this repository and
reported green. If the harness cannot catch these, it is decoration.
"""

from __future__ import annotations

import pytest

from tests.integration.evidence import (
    Evidence,
    VacuousEvidence,
    WitnessMissing,
    collect,
    require_path_marker,
)


class TestEmptyCapture:
    """2026-08-16: a terminal gate wrote three dumps, two of them zero bytes,
    then asserted 'the sentinel is not on screen' against empty strings and
    reported three passes."""

    def test_an_empty_capture_is_rejected_at_construction(self):
        with pytest.raises(VacuousEvidence):
            Evidence(label="exit", body="")

    def test_whitespace_is_not_an_observation(self):
        with pytest.raises(VacuousEvidence):
            Evidence(label="exit", body="   \n\n  \t ")

    def test_a_few_stray_characters_are_not_an_observation(self):
        """A redraw artefact is not a capture."""
        with pytest.raises(VacuousEvidence):
            Evidence(label="exit", body="> ")

    def test_the_error_says_why_absence_proves_nothing(self):
        with pytest.raises(VacuousEvidence) as caught:
            Evidence(label="exit", body="")
        assert "absent" in str(caught.value).lower()


class TestWitnessRequired:
    """The load-bearing rule: an absence assertion is worthless unless the
    instrument is known to have been aimed at the right target."""

    def test_absent_refuses_to_run_before_a_witness(self):
        ev = Evidence(label="exit", body="some unrelated terminal noise here")
        with pytest.raises(WitnessMissing):
            ev.absent("__EXIT__")

    def test_contains_also_requires_a_witness(self):
        ev = Evidence(label="exit", body="some unrelated terminal noise here")
        with pytest.raises(WitnessMissing):
            ev.contains("Goodbye")

    def test_a_witness_that_is_not_present_fails_loudly(self):
        ev = Evidence(label="exit", body="a screen that shows something else")
        with pytest.raises(WitnessMissing) as caught:
            ev.witness("> /exit")
        assert "pointed at" in str(caught.value)

    def test_the_full_sequence_passes_when_it_really_looked(self):
        ev = Evidence(label="exit", body="> /exit\nGoodbye!\n$ ")
        ev.witness("> /exit").contains("Goodbye").absent("__EXIT__")
        assert ev.summary()["witnessed_by"] == ["> /exit"]
        assert len(ev.summary()["checks"]) == 2

    def test_all_of_mode_requires_every_marker(self):
        ev = Evidence(label="switch", body="Switched from chat to coding mode.")
        with pytest.raises(WitnessMissing):
            ev.witness("Switched", "Tools (52)", any_of=False)


class TestCodePathMarker:
    """2026-08-16: a Telethon plan passed 6 steps against the live bot while
    exercising `_handle_dashboard_agent` — a path the change never touched.
    Every reply was real; none of them came from the code under test."""

    def test_a_missing_new_marker_fails(self):
        log = "fin route: intent=lookup → deepseek-v4-flash/low\n"
        with pytest.raises(WitnessMissing) as caught:
            require_path_marker(log, "[session]", label="telegram turn")
        assert "different code path" in str(caught.value)

    def test_the_new_marker_alone_passes(self):
        log = "[session] ✅ deepseek:deepseek-v4-flash (203 chars)\n"
        require_path_marker(log, "[session]", "[llm-stream]")

    def test_both_markers_present_is_also_a_failure(self):
        """A run that exercised both paths proves neither."""
        log = "[session] ok\n[llm-stream] ok\n"
        with pytest.raises(AssertionError) as caught:
            require_path_marker(log, "[session]", "[llm-stream]")
        assert "proves neither" in str(caught.value)


class TestReporting:

    def test_the_summary_names_the_witness_so_a_reader_can_audit_it(self):
        """A reported pass should show *why* it counted, not just that it did."""
        a = Evidence(label="one", body="> /mode coding\nSwitched to coding")
        a.witness("> /mode coding").contains("Switched")
        b = Evidence(label="two", body="> /exit\nGoodbye!")
        b.witness("> /exit").absent("__EXIT__")

        report = collect([a, b])
        assert report["total_checks"] == 2
        assert all(o["witnessed_by"] for o in report["observations"])
