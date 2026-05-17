"""
PhaseRunner — executes spec-kit phases wired to NeoMind's existing systems.

Integrates with:
- SpecManager (artifact CRUD)
- SprintManager (phase tracking)
- Coordinator (multi-agent research/implementation)
- TaskManager (session-level task tracking)
- PlanModeManager (read-only toggle during planning)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.coding.speckit.spec_manager import SpecManager
from agent.coding.speckit.constitution import ConstitutionManager

logger = logging.getLogger(__name__)


class PhaseResult:
    """Result from a single spec-kit phase execution."""

    def __init__(self, phase: str, success: bool, message: str,
                 artifact_path: Optional[str] = None,
                 data: Optional[Dict[str, Any]] = None):
        self.phase = phase
        self.success = success
        self.message = message
        self.artifact_path = artifact_path
        self.data = data or {}

    def __repr__(self):
        return f"PhaseResult({self.phase}, ok={self.success})"


class PhaseRunner:
    """Executes spec-kit phases, producing persistent artifacts.

    LLM calls are delegated through ``llm_fn`` — an async callable
    ``(system_prompt, user_prompt) -> str``. This keeps PhaseRunner
    provider-agnostic (works with any LLM backend).

    Coordinator integration:
        When available (``coordinator`` and ``worker_fn`` are both set),
        the plan and implement phases use parallel multi-agent execution.
        Otherwise they fall back to sequential LLM calls.
    """

    def __init__(
        self,
        spec_manager: SpecManager,
        llm_fn: Optional[callable] = None,
        sprint_manager: Optional[Any] = None,
        task_manager: Optional[Any] = None,
        coordinator: Optional[Any] = None,
        worker_fn: Optional[callable] = None,
        plan_mode_manager: Optional[Any] = None,
    ):
        self.spec = spec_manager
        self.llm_fn = llm_fn
        self.sprints = sprint_manager
        self.tasks = task_manager
        self.coordinator = coordinator
        self.worker_fn = worker_fn
        self.plan_mode = plan_mode_manager

    # ── Phase: constitution ───────────────────────────────────────

    async def run_constitution(self, project_name: str) -> PhaseResult:
        """Scaffold .specify/memory/constitution.md from template.

        User should review and edit the result. No LLM call needed —
        just template instantiation.
        """
        try:
            path = self.spec.init_constitution(project_name)
            return PhaseResult(
                "constitution", True,
                f"Constitution scaffolded at {path}. Review and edit before proceeding.",
                artifact_path=str(path),
            )
        except Exception as exc:
            return PhaseResult("constitution", False, f"Failed: {exc}")

    # ── Phase: specify ────────────────────────────────────────────

    async def run_specify(self, feature_name: str, description: str) -> PhaseResult:
        """Create a feature spec from user description.

        1. Scaffolds spec.md from template
        2. Optionally calls LLM to fill in user stories / requirements
        3. Creates a Sprint for phase tracking
        """
        try:
            spec_path = self.spec.create_spec(feature_name, description)

            # If LLM is available, enrich the spec from the description
            if self.llm_fn and description.strip():
                slug = _slugify(feature_name)
                template_content = self.spec.load_spec(slug)
                enriched = await self._llm_enrich_spec(feature_name, description, template_content)
                if enriched:
                    self.spec.update_spec(slug, enriched)

            # Create a Sprint for phase tracking
            sprint = None
            if self.sprints:
                try:
                    sprint = self.sprints.create(
                        goal=f"[spec-kit] {feature_name}: {description or 'New feature'}",
                        mode="coding",
                    )
                except Exception:
                    pass

            return PhaseResult(
                "specify", True,
                f"Spec created: {spec_path}",
                artifact_path=str(spec_path),
                data={"feature_slug": _slugify(feature_name), "sprint_id": sprint.id if sprint else None},
            )
        except Exception as exc:
            return PhaseResult("specify", False, f"Failed: {exc}")

    # ── Phase: clarify ────────────────────────────────────────────

    async def run_clarify(self, feature_slug: str) -> PhaseResult:
        """Identify and resolve [NEEDS CLARIFICATION] markers in a spec.

        Returns a list of questions for the user. Does NOT modify the spec
        automatically — the caller should present questions and feed answers
        back via a follow-up call or manual editing.
        """
        try:
            spec_text = self.spec.load_spec(feature_slug)
            if not spec_text:
                return PhaseResult("clarify", False, f"Spec '{feature_slug}' not found.")

            markers = _extract_clarification_markers(spec_text)
            if not markers:
                return PhaseResult("clarify", True, "No [NEEDS CLARIFICATION] markers found.")

            # If LLM is available, generate suggested answers
            suggestions = {}
            if self.llm_fn:
                suggestions = await self._llm_suggest_clarifications(feature_slug, markers)

            return PhaseResult(
                "clarify", True,
                f"Found {len(markers)} clarification questions.",
                data={
                    "feature_slug": feature_slug,
                    "questions": markers,
                    "suggestions": suggestions,
                    "n_markers": len(markers),
                },
            )
        except Exception as exc:
            return PhaseResult("clarify", False, f"Failed: {exc}")

    # ── Phase: plan ───────────────────────────────────────────────

    async def run_plan(self, feature_slug: str) -> PhaseResult:
        """Produce an implementation plan anchored to spec + constitution.

        Strategy:
        - If Coordinator is available: RESEARCH (explore codebase) → SYNTHESIS (produce plan)
        - Otherwise: direct LLM call with spec as context
        """
        try:
            spec_text = self.spec.load_spec(feature_slug)
            if not spec_text:
                return PhaseResult("plan", False, f"Spec '{feature_slug}' not found.")

            const_text = self.spec.load_constitution() or ""

            # Create plan.md from template
            plan_path = self.spec.create_plan(feature_slug)

            # Enrich plan using Coordinator or direct LLM
            plan_content = None
            if self.coordinator and self.worker_fn:
                try:
                    plan_content = await self._coordinator_plan(feature_slug, spec_text, const_text)
                except Exception as exc:
                    logger.warning("Coordinator plan failed, falling back to LLM: %s", exc)

            if plan_content is None and self.llm_fn:
                plan_content = await self._llm_plan(feature_slug, spec_text, const_text)

            if plan_content:
                # Write enriched plan over the template
                Path(plan_path).write_text(plan_content)

            return PhaseResult(
                "plan", True,
                f"Plan created: {plan_path}",
                artifact_path=str(plan_path),
                data={"feature_slug": feature_slug},
            )
        except Exception as exc:
            return PhaseResult("plan", False, f"Failed: {exc}")

    # ── Phase: tasks ──────────────────────────────────────────────

    async def run_tasks(self, feature_slug: str) -> PhaseResult:
        """Break plan into user-story-grouped tasks, syncing to TaskManager."""
        try:
            plan_text = self.spec.load_plan(feature_slug)
            if not plan_text:
                return PhaseResult("tasks", False, f"Plan '{feature_slug}' not found.")

            # Create tasks.md from template
            tasks_path = self.spec.create_tasks(feature_slug)

            # Enrich tasks via LLM
            if self.llm_fn:
                tasks_content = await self._llm_tasks(feature_slug, plan_text)
                if tasks_content:
                    Path(tasks_path).write_text(tasks_content)

            # Sync into TaskManager
            parsed = self.spec.parse_tasks(feature_slug)
            synced = 0
            failed = 0
            if self.tasks:
                for t in parsed:
                    try:
                        self.tasks.create(
                            subject=f"[{feature_slug}] {t['description'][:80]}",
                            description=t['description'],
                            metadata={
                                "feature": feature_slug,
                                "user_story": t.get("user_story", ""),
                                "spec_kit_id": t["id"],
                            },
                        )
                        synced += 1
                    except Exception as exc:
                        failed += 1
                        logger.warning(
                            "TaskManager sync failed for %s/%s: %s",
                            feature_slug, t.get("id"), exc,
                        )

            msg = f"Tasks created: {tasks_path} ({synced} synced to TaskManager"
            if failed:
                msg += f", {failed} failed"
            msg += ")"
            return PhaseResult(
                "tasks", True,
                msg,
                artifact_path=str(tasks_path),
                data={
                    "feature_slug": feature_slug,
                    "n_tasks": len(parsed),
                    "n_synced": synced,
                    "n_sync_failed": failed,
                },
            )
        except Exception as exc:
            return PhaseResult("tasks", False, f"Failed: {exc}")

    # ── Phase: analyze ────────────────────────────────────────────

    async def run_analyze(self, feature_slug: str) -> PhaseResult:
        """Cross-artifact consistency and constitution compliance check.

        Reads spec.md, plan.md, tasks.md and produces:
        - checklist.md (filled in)
        - Gate decision (PASS / FAIL with reasons)
        """
        try:
            const_mgr = ConstitutionManager(self.spec)
            violations: List[str] = []

            # Constitution checks
            const_violations = const_mgr.validate_spec_against_constitution(feature_slug)
            violations.extend(const_violations)

            plan_violations = const_mgr.validate_plan_against_constitution(feature_slug)
            violations.extend(plan_violations)

            # Cross-artifact checks
            spec_text = self.spec.load_spec(feature_slug)
            plan_text = self.spec.load_plan(feature_slug)
            tasks_text = self.spec.load_tasks(feature_slug)

            if spec_text and plan_text:
                cross = _cross_artifact_check(spec_text, plan_text, tasks_text or "")
                violations.extend(cross)

            # Create/fill checklist
            checklist_path = self.spec.create_checklist(feature_slug)

            gate_passed = len(violations) == 0

            return PhaseResult(
                "analyze", gate_passed,
                "All checks passed." if gate_passed else f"{len(violations)} issue(s) found.",
                artifact_path=str(checklist_path),
                data={
                    "feature_slug": feature_slug,
                    "gate": "PASS" if gate_passed else "FAIL",
                    "violations": violations,
                },
            )
        except Exception as exc:
            return PhaseResult("analyze", False, f"Failed: {exc}")

    # ── Phase: implement ──────────────────────────────────────────

    async def run_implement(self, feature_slug: str) -> PhaseResult:
        """Execute the implementation plan.

        Uses Coordinator for parallel multi-agent execution when available,
        otherwise reports that implementation requires an active agent loop.
        """
        try:
            plan_text = self.spec.load_plan(feature_slug)
            tasks_text = self.spec.load_tasks(feature_slug)

            if not plan_text:
                return PhaseResult("implement", False, f"Plan '{feature_slug}' not found. Run /speckit.plan first.")

            # Extract implementation tasks
            impl_tasks = _extract_implementation_steps(plan_text)
            if not impl_tasks:
                impl_tasks = [f"Implement {feature_slug} per plan.md"]

            if self.coordinator and self.worker_fn:
                result = await self._coordinator_implement(feature_slug, impl_tasks)
                return result

            # No coordinator — return tasks for manual/session execution
            task_list = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(impl_tasks))
            return PhaseResult(
                "implement", True,
                f"Implementation tasks ready:\n{task_list}\n\n"
                "Run these tasks in the current session or use Coordinator mode.",
                data={"feature_slug": feature_slug, "implementation_tasks": impl_tasks},
            )
        except Exception as exc:
            return PhaseResult("implement", False, f"Failed: {exc}")

    # ── Phase: checklist ──────────────────────────────────────────

    async def run_checklist(self, feature_slug: str) -> PhaseResult:
        """Generate quality checklist for a feature."""
        try:
            path = self.spec.create_checklist(feature_slug)
            return PhaseResult(
                "checklist", True,
                f"Checklist created: {path}",
                artifact_path=str(path),
                data={"feature_slug": feature_slug},
            )
        except Exception as exc:
            return PhaseResult("checklist", False, f"Failed: {exc}")

    # ── Phase: status ─────────────────────────────────────────────

    async def run_status(self, feature_slug: Optional[str] = None) -> PhaseResult:
        """Report on spec-kit state: list specs or show one feature's status."""
        try:
            if feature_slug:
                return self._feature_status(feature_slug)

            specs = self.spec.list_specs()
            if not specs:
                const_ok = self.spec.has_constitution()
                msg = "No feature specs yet."
                if not const_ok:
                    msg += " Run /speckit.constitution first."
                return PhaseResult("status", True, msg, data={"specs": [], "has_constitution": const_ok})

            lines = [f"{len(specs)} feature spec(s):"]
            for s in specs:
                lines.append(f"  {s['slug']} — {s['status']} ({s['created']})")
            return PhaseResult("status", True, "\n".join(lines), data={"specs": specs})
        except Exception as exc:
            return PhaseResult("status", False, f"Failed: {exc}")

    def _feature_status(self, feature_slug: str) -> PhaseResult:
        spec_path = self.spec.get_feature_dir(feature_slug)
        artifacts = []
        for fname in ["spec.md", "plan.md", "tasks.md", "research.md", "checklist.md"]:
            p = spec_path / fname
            if p.exists():
                artifacts.append(f"  {'✅' if _is_complete(p) else '📝'} {fname}")
            else:
                artifacts.append(f"  ⬜ {fname}")

        checklist_stats = self.spec.get_checklist_stats(feature_slug)
        lines = [f"Feature: {feature_slug}", ""] + artifacts
        if checklist_stats["total"] > 0:
            lines.append(f"\nChecklist: {checklist_stats['completed']}/{checklist_stats['total']} completed")

        return PhaseResult("status", True, "\n".join(lines), data={
            "feature_slug": feature_slug,
            "checklist_stats": checklist_stats,
        })

    # ── LLM helpers ───────────────────────────────────────────────

    async def _llm_enrich_spec(self, name: str, desc: str, template: str) -> Optional[str]:
        """Use LLM to fill the spec template with real content."""
        if not self.llm_fn:
            return None
        prompt = (
            f"Fill in this feature specification template for: {name}\n"
            f"Description: {desc}\n\n"
            f"Template:\n{template}\n\n"
            "Keep all template structure. Add user stories, requirements, success criteria. "
            "Use [NEEDS CLARIFICATION] for things you're unsure about (max 3). "
            "Include <epistemic-status> on each requirement."
        )
        try:
            return await self.llm_fn("You are a product engineer writing feature specs.", prompt)
        except Exception as exc:
            logger.warning("LLM enrich spec failed: %s", exc)
            return None

    async def _llm_suggest_clarifications(self, slug: str, markers: List[str]) -> Dict[str, str]:
        """Generate suggested answers for clarification markers."""
        if not self.llm_fn:
            return {}
        suggestions = {}
        for marker in markers[:5]:  # Limit to avoid runaway
            try:
                result = await self.llm_fn(
                    "You are a technical analyst helping clarify feature requirements.",
                    f"Question from spec '{slug}': {marker}\n"
                    "Suggest a reasonable answer based on common patterns. Be concise."
                )
                suggestions[marker] = result.strip()
            except Exception:
                suggestions[marker] = "(could not generate suggestion)"
        return suggestions

    async def _llm_plan(self, slug: str, spec_text: str, const_text: str) -> Optional[str]:
        if not self.llm_fn:
            return None
        # The section list below MUST stay aligned with
        # ConstitutionManager.validate_plan_against_constitution
        # (constitution.py:96-101) — every header that validator looks
        # for must appear in this prompt verbatim.
        prompt = (
            f"Create an implementation plan for feature '{slug}'.\n\n"
            f"## Constitution\n{const_text[:2000]}\n\n"
            f"## Specification\n{spec_text[:4000]}\n\n"
            "Produce an implementation plan in markdown with EXACTLY these "
            "H2 sections, in this order:\n"
            "  ## Summary\n"
            "  ## Constitution Check  (table of constitutional principles vs PASS/VIOLATION)\n"
            "  ## Source Graph  (files to change, marked [NEW]/[MODIFIED]/[DELETED], ordered by dependency)\n"
            "  ## Architecture Overview\n"
            "  ## Implementation Steps  (use `### Step N: Title` headers; each step lists File, Change, Rollback, Test)\n"
            "  ## Verification Plan\n"
            "Do NOT omit any of these section headers — they are required for the analyze phase to pass."
        )
        try:
            return await self.llm_fn("You are a senior software architect.", prompt)
        except Exception as exc:
            logger.warning("LLM plan failed: %s", exc)
            return None

    async def _llm_tasks(self, slug: str, plan_text: str) -> Optional[str]:
        if not self.llm_fn:
            return None
        # Task ID prefix (`T001`, `T002`, ...) is REQUIRED by
        # spec_manager.parse_tasks (spec_manager.py:248-265) — without
        # it, parse_tasks returns 0 tasks and TaskManager sync is a no-op.
        # `[P]` and `[US1]` tags are bare brackets (no backticks), in any
        # order — parse_tasks searches for them as literal substrings.
        prompt = (
            f"Break this plan into user-story-grouped tasks for feature '{slug}'.\n\n"
            f"{plan_text[:5000]}\n\n"
            "Output a markdown task list with this EXACT line shape:\n"
            "    - [ ] T001 [P] [US1] Description of the task\n"
            "Rules:\n"
            "1. Every task line MUST start with `- [ ] T###` (zero-padded sequential id).\n"
            "2. Use literal bare brackets `[P]` (do NOT wrap in backticks) for parallelizable tasks.\n"
            "3. Use `[US1]`, `[US2]`, ... to tag the owning user story.\n"
            "4. Group tasks under `## Phase N: User Story N — <title> (Priority: P#)` headers.\n"
            "5. Tag order `[P]` vs `[USx]` does not matter; both must appear when applicable.\n"
            "Include dependency markers and checkpoints between phases."
        )
        try:
            return await self.llm_fn("You are a technical project manager.", prompt)
        except Exception as exc:
            logger.warning("LLM tasks failed: %s", exc)
            return None

    # ── Coordinator helpers ──────────────────────────────────────

    async def _coordinator_plan(self, slug: str, spec_text: str, const_text: str) -> Optional[str]:
        """Use Coordinator for research → synthesis → plan."""
        research_tasks = [
            f"Read the specification for '{slug}' and identify all code locations that will be affected",
            "Search for existing patterns, conventions, and tests in the codebase that this feature must follow",
        ]
        try:
            result = await self.coordinator.coordinate(
                objective=f"Create an implementation plan for: {slug}",
                research_tasks=research_tasks,
                implementation_tasks=None,  # Plan only — no implementation in this phase
                verification_tasks=None,
            )
            # Extract synthesis as plan content
            for pr in result.phases:
                if pr.phase.value == "synthesis":
                    return pr.summary
            return result.final_summary
        except Exception as exc:
            logger.warning("Coordinator plan failed: %s", exc)
            return None

    async def _coordinator_implement(
        self, slug: str, impl_tasks: List[str]
    ) -> PhaseResult:
        """Use Coordinator for implementation → verification."""
        try:
            result = await self.coordinator.coordinate(
                objective=f"Implement feature: {slug}",
                research_tasks=[f"Read plan.md and tasks.md for '{slug}' to confirm scope"],
                implementation_tasks=impl_tasks,
                verification_tasks=[
                    "Run tests for changed modules",
                    "Check for regressions",
                ],
            )
            return PhaseResult(
                "implement", result.success,
                result.final_summary,
                data={
                    "feature_slug": slug,
                    "files_changed": result.files_changed,
                    "tests_passed": result.tests_passed,
                    "phases": [p.phase.value for p in result.phases],
                },
            )
        except Exception as exc:
            return PhaseResult("implement", False, f"Coordinator implementation failed: {exc}")


# ── Helpers ───────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    import re
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "feature"


def _extract_clarification_markers(text: str) -> List[str]:
    import re
    markers = []
    for match in re.finditer(r"\[NEEDS CLARIFICATION\]\s*:?\s*(.+?)(?:\n|$)", text):
        markers.append(match.group(1).strip() or match.group(0))
    return markers


def _cross_artifact_check(spec: str, plan: str, tasks: str) -> List[str]:
    """Basic cross-artifact consistency checks."""
    issues = []

    # Count user stories in spec
    import re
    spec_stories = len(re.findall(r"###\s+User Story\s+\d+", spec))
    plan_steps = len(re.findall(r"###\s+Step\s+\d+", plan))
    task_items = len(re.findall(r"- \[[ x]\]\s+T\d+", tasks))

    if spec_stories == 0:
        issues.append("Spec has no user stories.")
    if plan_steps == 0:
        issues.append("Plan has no implementation steps.")
    if task_items == 0:
        issues.append("Tasks list is empty.")

    # Check for unresolved markers
    if "[NEEDS CLARIFICATION]" in spec:
        issues.append("Spec still has [NEEDS CLARIFICATION] markers. Run /speckit.clarify.")
    if "[NEEDS CLARIFICATION]" in plan:
        issues.append("Plan still has [NEEDS CLARIFICATION] markers.")

    return issues


def _extract_implementation_steps(plan_text: str) -> List[str]:
    """Extract implementation step descriptions from plan.md.

    Recognizes, in order of preference:
        1. ``### Step N: Title``  (spec-kit canonical form)
        2. ``## Step N: Title``   (h2 variant, LLM-common)
        3. Numbered bullets ``1. Title`` under an "Implementation Steps" /
           "Steps" header (also LLM-common)
    Returns step titles in order.
    """
    import re
    # 1) ### Step N:
    steps = [
        m.group(1).strip().split("\n")[0]
        for m in re.finditer(r"###\s+Step\s+\d+:\s*(.+?)(?=\n###|\Z)", plan_text, re.DOTALL)
    ]
    if steps:
        return steps
    # 2) ## Step N:
    steps = [
        m.group(1).strip().split("\n")[0]
        for m in re.finditer(r"##\s+Step\s+\d+:\s*(.+?)(?=\n##|\Z)", plan_text, re.DOTALL)
    ]
    if steps:
        return steps
    # 3) Numbered bullets under an Implementation Steps / Steps header
    section_match = re.search(
        r"^##\s+(?:Implementation\s+)?Steps\s*$(.*?)(?=^##\s+|\Z)",
        plan_text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if section_match:
        body = section_match.group(1)
        for m in re.finditer(r"^\s*\d+\.\s+(.+?)$", body, re.MULTILINE):
            steps.append(m.group(1).strip())
    return steps


def _is_complete(path: Path) -> bool:
    """Heuristic: check if a template still has placeholders."""
    try:
        text = path.read_text()
        return "[FEATURE_NAME]" not in text and "[PROJECT_NAME]" not in text
    except Exception:
        return False


__all__ = ["PhaseRunner", "PhaseResult"]
