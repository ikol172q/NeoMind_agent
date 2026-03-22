# agent/workflow/sprint.py
"""
Sprint Framework — Think → Plan → Build → Review → Test → Ship → Reflect.

Provides structured task execution for all 3 personalities:
- chat: Think → Plan → Execute → Review (simpler)
- coding: Full 7-phase sprint
- fin: Think → Plan → Review → Test (paper trade) → Execute

The framework doesn't force a linear flow — it provides phase-aware
context and ensures nothing important is skipped.
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone
import os


@dataclass
class SprintPhase:
    name: str
    status: str = "pending"  # pending, active, completed, skipped
    started_at: str = ""
    completed_at: str = ""
    output: str = ""         # key output of this phase (file path or summary)
    notes: str = ""


@dataclass
class Sprint:
    """A structured task execution with phases."""
    id: str
    goal: str
    mode: str = "coding"  # which personality initiated this
    phases: List[SprintPhase] = field(default_factory=list)
    created_at: str = ""
    completed_at: str = ""
    status: str = "active"  # active, completed, abandoned

    @property
    def current_phase(self) -> Optional[SprintPhase]:
        for phase in self.phases:
            if phase.status == "active":
                return phase
        return None

    @property
    def next_phase(self) -> Optional[SprintPhase]:
        for phase in self.phases:
            if phase.status == "pending":
                return phase
        return None

    @property
    def progress(self) -> str:
        done = sum(1 for p in self.phases if p.status in ("completed", "skipped"))
        total = len(self.phases)
        return f"{done}/{total}"


# Phase templates per mode
PHASE_TEMPLATES = {
    "coding": [
        SprintPhase(name="think"),    # understand the problem
        SprintPhase(name="plan"),     # design the solution
        SprintPhase(name="build"),    # write the code
        SprintPhase(name="review"),   # self-review
        SprintPhase(name="test"),     # run tests
        SprintPhase(name="ship"),     # commit + push
        SprintPhase(name="reflect"), # what did we learn
    ],
    "fin": [
        SprintPhase(name="think"),    # understand the opportunity
        SprintPhase(name="plan"),     # design the trade/allocation
        SprintPhase(name="review"),   # trade-review validation
        SprintPhase(name="test"),     # paper trade
        SprintPhase(name="execute"),  # live execution (with confirmation)
        SprintPhase(name="reflect"), # track outcome
    ],
    "chat": [
        SprintPhase(name="think"),    # understand the question
        SprintPhase(name="plan"),     # structure the approach
        SprintPhase(name="execute"),  # do the work
        SprintPhase(name="review"),   # verify accuracy
    ],
}


class SprintManager:
    """Manages sprint lifecycle — create, advance, complete.

    Usage:
        mgr = SprintManager()
        sprint = mgr.create("Fix login bug", mode="coding")
        mgr.advance(sprint.id)           # move to next phase
        mgr.complete_phase(sprint.id, output="Fixed in auth.py")
        mgr.advance(sprint.id)           # next phase
    """

    SPRINTS_DIR = Path(os.getenv("HOME", "/data")) / ".neomind" / "sprints"

    def __init__(self):
        self.SPRINTS_DIR.mkdir(parents=True, exist_ok=True)
        self._active_sprints: Dict[str, Sprint] = {}

    def create(self, goal: str, mode: str = "coding") -> Sprint:
        """Create a new sprint with mode-appropriate phases."""
        sprint_id = f"sprint-{int(time.time())}"
        now = datetime.now(timezone.utc).isoformat()

        # Deep copy phase template
        template = PHASE_TEMPLATES.get(mode, PHASE_TEMPLATES["chat"])
        phases = [SprintPhase(name=p.name) for p in template]

        sprint = Sprint(
            id=sprint_id,
            goal=goal,
            mode=mode,
            phases=phases,
            created_at=now,
        )

        # Start first phase
        if phases:
            phases[0].status = "active"
            phases[0].started_at = now

        self._active_sprints[sprint_id] = sprint
        self._save(sprint)
        return sprint

    def get(self, sprint_id: str) -> Optional[Sprint]:
        return self._active_sprints.get(sprint_id)

    def advance(self, sprint_id: str) -> Optional[SprintPhase]:
        """Complete current phase and advance to next. Returns new active phase."""
        sprint = self._active_sprints.get(sprint_id)
        if not sprint:
            return None

        now = datetime.now(timezone.utc).isoformat()

        # Complete current phase
        current = sprint.current_phase
        if current:
            current.status = "completed"
            current.completed_at = now

        # Start next phase
        next_phase = sprint.next_phase
        if next_phase:
            next_phase.status = "active"
            next_phase.started_at = now
            self._save(sprint)
            return next_phase

        # No more phases — sprint complete
        sprint.status = "completed"
        sprint.completed_at = now
        self._save(sprint)
        return None

    def skip_phase(self, sprint_id: str) -> Optional[SprintPhase]:
        """Skip current phase and move to next."""
        sprint = self._active_sprints.get(sprint_id)
        if not sprint:
            return None

        current = sprint.current_phase
        if current:
            current.status = "skipped"

        return self.advance(sprint_id)

    def complete_phase(self, sprint_id: str, output: str = "", notes: str = ""):
        """Add output/notes to current phase."""
        sprint = self._active_sprints.get(sprint_id)
        if not sprint:
            return
        current = sprint.current_phase
        if current:
            current.output = output
            current.notes = notes
            self._save(sprint)

    def get_sprint_prompt(self, sprint_id: str) -> str:
        """Generate context prompt for current sprint state.

        This is injected into the LLM context so it knows
        where in the sprint it is and what to do next.
        """
        sprint = self._active_sprints.get(sprint_id)
        if not sprint:
            return ""

        lines = [
            f"## Active Sprint: {sprint.goal}",
            f"Mode: {sprint.mode} | Progress: {sprint.progress}",
            "",
        ]

        for phase in sprint.phases:
            icon = {
                "completed": "✅",
                "active": "▶️",
                "skipped": "⏭️",
                "pending": "⬜",
            }.get(phase.status, "⬜")
            lines.append(f"{icon} {phase.name}")
            if phase.output:
                lines.append(f"   Output: {phase.output[:100]}")

        current = sprint.current_phase
        if current:
            lines.append(f"\nCurrent phase: **{current.name}**")
            lines.append(f"Focus on completing the {current.name} phase before moving on.")

        return "\n".join(lines)

    def format_status(self, sprint_id: str) -> str:
        """Human-readable sprint status."""
        sprint = self._active_sprints.get(sprint_id)
        if not sprint:
            return "No active sprint"

        lines = [f"📋 Sprint: {sprint.goal}", f"   Progress: {sprint.progress}\n"]
        for phase in sprint.phases:
            icon = {"completed": "✅", "active": "▶️", "skipped": "⏭️", "pending": "⬜"}.get(phase.status, "⬜")
            lines.append(f"   {icon} {phase.name}")
        return "\n".join(lines)

    def _save(self, sprint: Sprint):
        path = Path(self.SPRINTS_DIR) / f"{sprint.id}.json"
        data = {
            "id": sprint.id,
            "goal": sprint.goal,
            "mode": sprint.mode,
            "status": sprint.status,
            "created_at": sprint.created_at,
            "completed_at": sprint.completed_at,
            "phases": [
                {"name": p.name, "status": p.status, "started_at": p.started_at,
                 "completed_at": p.completed_at, "output": p.output, "notes": p.notes}
                for p in sprint.phases
            ],
        }
        path.write_text(json.dumps(data, indent=2))
