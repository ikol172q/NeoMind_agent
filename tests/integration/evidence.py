"""Refuse to let a verification pass without proving it measured something.

Twice in one session a gate reported green while measuring nothing:

  * A Telethon plan ran 6 steps against the live bot and passed. It was
    exercising `_handle_dashboard_agent`, a path the change never touched —
    private DMs never reach the migrated code at all. Nothing in the plan
    could have noticed.
  * A terminal gate wrote three dumps, two of which were zero bytes, and then
    asserted "the sentinel is not on screen" against empty strings. Three
    passes, two of them vacuous.

Both were mechanically detectable at the moment of measurement, and both were
"fixed" by writing the lesson down. A lesson that has to be remembered before
it applies is not a fix, so this is the mechanism instead.

The rule it enforces:

    Before asserting anything about an observation, prove the observation
    happened — and that it observed the thing under test.

That proof is a **witness**: a string that can only appear if the instrument
was pointed at the right target. For a terminal, the prompt or an echoed
command. For a migrated code path, a log marker only the new code emits. For a
chat surface, the reply itself.

A negative assertion without a witness is the dangerous case, because absence
is exactly what an empty capture looks like. `assert_absent` therefore refuses
to run at all until a witness has been established.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


class VacuousEvidence(AssertionError):
    """The instrument produced nothing, so no claim about it is supportable."""


class WitnessMissing(AssertionError):
    """The capture is non-empty but does not show the thing under test.

    This is the Telethon failure: a real reply, from real code, that was not
    the code the change touched.
    """


@dataclass
class Evidence:
    """One observation, plus proof that it observed the right thing.

    Construct it with what was captured, then call `witness()` with a marker
    that only the target could produce. Assertions are unavailable until that
    succeeds.
    """

    label: str
    body: str
    #: Minimum bytes before a capture is considered to have happened at all.
    #: A handful of stray characters from a redraw is not an observation.
    min_bytes: int = 8

    _witnessed: bool = field(default=False, init=False)
    _witness_markers: List[str] = field(default_factory=list, init=False)
    _checks: List[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if len(self.body.strip()) < self.min_bytes:
            raise VacuousEvidence(
                f"{self.label}: captured {len(self.body.strip())} bytes "
                f"(minimum {self.min_bytes}). Nothing was measured, so nothing "
                f"can be concluded — including that something is absent."
            )

    # ── establishing that we looked at the right thing ────────────────────

    def witness(self, *markers: str, any_of: bool = True) -> "Evidence":
        """Prove the capture shows the thing under test.

        `any_of` is the default because a single unambiguous marker is the
        usual case; pass `any_of=False` when every marker must be present.
        """
        present = [m for m in markers if m and m in self.body]
        ok = bool(present) if any_of else len(present) == len([m for m in markers if m])
        if not ok:
            raise WitnessMissing(
                f"{self.label}: none of {list(markers)} appear in the capture. "
                f"The instrument ran, but there is no evidence it was pointed "
                f"at the code under test.\n--- captured ---\n{self.body[:600]}"
            )
        self._witnessed = True
        self._witness_markers.extend(present)
        return self

    # ── assertions, unavailable until witnessed ───────────────────────────

    def _require_witness(self, kind: str) -> None:
        if not self._witnessed:
            raise WitnessMissing(
                f"{self.label}: {kind} attempted before witness(). Establish "
                f"that the capture shows the thing under test first — an "
                f"absence proves nothing about an instrument that may have "
                f"been aimed elsewhere."
            )

    def contains(self, *needles: str) -> "Evidence":
        self._require_witness("contains()")
        missing = [n for n in needles if n and n not in self.body]
        if missing:
            raise AssertionError(
                f"{self.label}: expected {missing} in the capture.\n"
                f"--- captured ---\n{self.body[:600]}"
            )
        self._checks.extend(f"contains {n!r}" for n in needles)
        return self

    def absent(self, *needles: str) -> "Evidence":
        """The assertion that is worthless without a witness.

        One caveat when the body came from a terminal recorder: it accumulates
        every line that was ever on screen during the window, so the scrollback
        of *earlier* steps is part of this capture. Asserting the absence of a
        phrase some previous step legitimately printed will fail, and the
        failure will look like the step under test. Keep the needles to strings
        that can mean nothing but "this step broke".
        """
        self._require_witness("absent()")
        found = [n for n in needles if n and n in self.body]
        if found:
            raise AssertionError(
                f"{self.label}: {found} should not appear.\n"
                f"--- captured ---\n{self.body[:600]}"
            )
        self._checks.extend(f"absent {n!r}" for n in needles)
        return self

    # ── reporting ─────────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "label": self.label,
            "bytes": len(self.body),
            "witnessed_by": list(self._witness_markers),
            "checks": list(self._checks),
        }


def collect(evidence: Sequence[Evidence]) -> dict:
    """Fold a run's evidence into something worth printing.

    Reports the witness for each observation, so a reader can tell a real
    pass from a pass that never looked at anything.
    """
    return {
        "observations": [e.summary() for e in evidence],
        "total_checks": sum(len(e.summary()["checks"]) for e in evidence),
    }


def require_path_marker(
    log_text: str,
    new_marker: str,
    old_marker: Optional[str] = None,
    *,
    label: str = "code path",
) -> None:
    """Assert the *new* code ran, not merely that something answered.

    The Telethon case. A surface can reply perfectly while the change under
    test sits untouched behind a router, so the check is not "did it work" but
    "did the thing I changed execute". `new_marker` must be something only the
    new code emits; `old_marker`, when given, must be absent.
    """
    if new_marker not in log_text:
        raise WitnessMissing(
            f"{label}: '{new_marker}' never appeared in the log. The surface "
            f"may have answered from a different code path than the one under "
            f"test — check the routing before trusting any result from this run."
        )
    if old_marker and old_marker in log_text:
        raise AssertionError(
            f"{label}: '{old_marker}' is still present, so the legacy path ran "
            f"too. A run that exercises both proves neither."
        )
