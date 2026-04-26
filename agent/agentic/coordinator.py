"""
Coordinator Mode for NeoMind Agent.

Implements a 4-phase multi-agent orchestration pattern:
1. Research — Parallel workers investigate the codebase/problem
2. Synthesis — Coordinator reads findings, crafts specs
3. Implementation — Workers make targeted changes
4. Verification — Workers test changes

Inspired by Claude Code's coordinator mode.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "CoordinatorPhase",
    "WorkerType",
    "WorkerTask",
    "PhaseResult",
    "CoordinationResult",
    "Coordinator",
    "COORDINATOR_SYSTEM_PROMPT",
]


# ── Coordinator System Prompt ──────────────────────────────────────
# This prompt is injected when NeoMind operates in coordinator mode.
# It teaches the LLM how to orchestrate multi-agent work.

COORDINATOR_SYSTEM_PROMPT = """\
You are operating in COORDINATOR MODE. You orchestrate multiple worker agents \
to accomplish complex tasks efficiently through parallel execution.

## 4-Phase Workflow

1. **RESEARCH** — Spawn parallel workers to investigate the codebase/problem. \
Each worker reads files, searches code, and reports findings.
2. **SYNTHESIS** — Read all research findings (from the scratchpad), identify \
patterns, and produce a concrete implementation spec.
3. **IMPLEMENTATION** — Spawn parallel workers with specific, non-overlapping \
file assignments. Each worker makes targeted changes.
4. **VERIFICATION** — Spawn workers to run tests, check for regressions, and \
validate the implementation.

## Rules

- MAXIMIZE PARALLELISM. If 3 files need changes, spawn 3 workers, not 1.
- Each worker gets a SPECIFIC task description. Never say "figure it out".
- Workers share findings via the scratchpad directory.
- Do NOT delegate understanding. Read the actual findings before synthesizing.
- After implementation, ALWAYS run verification.
- Workers should NOT use: TeamCreate, TeamDelete, SendMessage, SyntheticOutput.

## Scratchpad

Workers can share findings via the scratchpad directory. After each phase:
- Research findings are saved to `research_findings.md`
- Synthesis spec is saved to `synthesis_spec.md`
Workers can read these to understand context from previous phases.

## Example Session

Objective: "Add input validation to the user registration API"

Phase 1 — RESEARCH (3 workers in parallel):
  Worker 1: "Read all files in src/api/auth/ and list the registration endpoints"
  Worker 2: "Search for existing validation patterns: grep for 'validate', 'schema', 'zod'"
  Worker 3: "Read the test files in tests/api/auth/ to understand test patterns"

Phase 2 — SYNTHESIS:
  Read research findings. Produce spec:
  - File: src/api/auth/register.ts — add Zod schema for email, password, name
  - File: src/api/auth/register.test.ts — add validation error test cases
  - Pattern: follow existing validation in src/api/auth/login.ts

Phase 3 — IMPLEMENTATION (2 workers):
  Worker 1: "Edit src/api/auth/register.ts to add the validation schema"
  Worker 2: "Edit tests to add validation error test cases"

Phase 4 — VERIFICATION (1 worker):
  Worker 1: "Run: npm test -- --grep 'registration'"
"""


class CoordinatorPhase(Enum):
    """The four phases of a coordinated multi-agent run."""

    RESEARCH = "research"
    SYNTHESIS = "synthesis"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"


class WorkerType(Enum):
    """Specialized worker classification for tool allowlisting.

    Each worker type gets a specific tool set matching its role:
      - EXPLORE: Read-only investigation (Read, Grep, Glob, LS, WebSearch)
      - PLAN: Architecture planning (same as EXPLORE + Scratchpad writes)
      - IMPLEMENT: Code changes (Read, Write, Edit, Bash, Git)
      - VERIFY: Test/validation (Read, Bash for tests, Grep)
      - GENERAL: Full access minus excluded tools
    """
    EXPLORE = "explore"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    GENERAL = "general"


@dataclass
class WorkerTask:
    """A unit of work dispatched to a worker agent."""

    id: str
    phase: CoordinatorPhase
    description: str
    status: str = "pending"  # pending | running | completed | failed
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class PhaseResult:
    """Aggregated result of one coordinator phase."""

    phase: CoordinatorPhase
    tasks: List[WorkerTask]
    summary: str
    duration_ms: float
    success: bool


@dataclass
class CoordinationResult:
    """Final result of the full 4-phase coordination."""

    phases: List[PhaseResult]
    total_duration_ms: float
    success: bool
    final_summary: str
    files_changed: List[str] = field(default_factory=list)
    tests_passed: Optional[bool] = None


class Coordinator:
    """4-phase multi-agent coordinator.

    Parameters
    ----------
    worker_fn:
        Async callable that executes a single WorkerTask and returns a
        result string.  This is the main integration point — callers
        provide their own worker implementation (e.g. spawn a sub-agent,
        call an LLM with tools, run a shell command).
    llm_fn:
        Optional async callable ``(prompt) -> response`` used during the
        *synthesis* phase to analyse research findings and produce an
        implementation spec.  When ``None`` a simple concatenation of
        findings is used instead.
    max_workers:
        Maximum number of worker tasks that may run concurrently within a
        single phase.
    """

    # ── Per-worker-type tool allowlists ────────────────────────────────
    # Mirrors Claude Code's ASYNC_AGENT_ALLOWED_TOOLS + per-built-in-type sets.

    # Tools that workers CANNOT use (prevents recursion, system destabilization)
    WORKER_EXCLUDED_TOOLS = frozenset({
        'TeamCreate', 'TeamDelete', 'SendMessage', 'SyntheticOutput',
        'SelfEditor', 'EnterPlanMode', 'ExitPlanMode',
        'TaskOutput', 'AskUserQuestion', 'CronCreate', 'CronDelete',
    })

    # Read-only tools for EXPLORE workers
    EXPLORE_TOOLS = frozenset({
        'Read', 'Grep', 'Glob', 'LS', 'WebSearch', 'WebFetch',
        'ListMcpResources', 'ReadMcpResource',
    })

    # Plan workers get explore tools + scratchpad write access
    PLAN_TOOLS = frozenset(EXPLORE_TOOLS | {
        'Write',  # For scratchpad spec writing
    })

    # Implementation workers get full write access
    IMPLEMENT_TOOLS = frozenset(EXPLORE_TOOLS | {
        'Write', 'Edit', 'Bash', 'NotebookEdit', 'Skill',
        'TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet',
    })

    # Verification workers: read + test execution
    VERIFY_TOOLS = frozenset({
        'Read', 'Grep', 'Glob', 'LS', 'Bash', 'WebFetch',
        'TaskCreate', 'TaskUpdate',
    })

    # General workers: all except excluded
    GENERAL_EXCLUDED = WORKER_EXCLUDED_TOOLS

    # Map WorkerType -> tool set
    WORKER_TYPE_TOOLS: Dict[WorkerType, frozenset] = {
        WorkerType.EXPLORE: EXPLORE_TOOLS,
        WorkerType.PLAN: PLAN_TOOLS,
        WorkerType.IMPLEMENT: IMPLEMENT_TOOLS,
        WorkerType.VERIFY: VERIFY_TOOLS,
        WorkerType.GENERAL: None,  # None = all minus WORKER_EXCLUDED_TOOLS
    }

    # Backward compat — legacy simple_mode tool set
    SIMPLE_MODE_TOOLS = frozenset({'Read', 'Write', 'Edit', 'Bash', 'Grep', 'Glob', 'LS'})

    # Max messages per worker to prevent OOM (whale session: 292 agents → 36GB RSS)
    MAX_WORKER_MESSAGES = 500

    def __init__(
        self,
        worker_fn: Callable[[WorkerTask], Awaitable[str]],
        llm_fn: Optional[Callable[[str], Awaitable[str]]] = None,
        max_workers: int = 3,
    ) -> None:
        self.worker_fn = worker_fn
        self.llm_fn = llm_fn
        self.max_workers = max_workers
        self._semaphore = asyncio.Semaphore(max_workers)
        self.phase_results: List[PhaseResult] = []

        # Scratchpad directory for cross-worker knowledge sharing
        self._scratchpad_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # Worker Tool Filtering & Message Caps
    # ------------------------------------------------------------------

    @classmethod
    def get_allowed_tools(cls, worker_type: WorkerType = WorkerType.GENERAL,
                          simple_mode: bool = False) -> Optional[frozenset]:
        """Get the set of tool names a worker of given type is allowed to use.

        Args:
            worker_type: Classification of worker (EXPLORE, PLAN, IMPLEMENT, VERIFY, GENERAL)
            simple_mode: If True, force minimal tool set (Bash + Read + Edit)

        Returns:
            frozenset of tool names, or None if "allow all minus excluded."
        """
        if simple_mode:
            return frozenset({'Read', 'Write', 'Edit', 'Bash', 'Grep', 'Glob', 'LS'})
        allowed = cls.WORKER_TYPE_TOOLS.get(worker_type)
        if allowed is not None:
            return allowed
        # GENERAL or unknown: return None (caller filters via WORKER_EXCLUDED_TOOLS)
        return None

    def get_worker_allowed_tools(self, simple_mode: bool = False) -> Optional[frozenset]:
        """Legacy wrapper — use get_allowed_tools(worker_type) instead."""
        return self.get_allowed_tools(WorkerType.GENERAL, simple_mode=simple_mode)

    @classmethod
    def filter_worker_tools(cls, all_tools: Dict[str, Any],
                            worker_type: WorkerType = WorkerType.GENERAL,
                            simple_mode: bool = False) -> Dict[str, Any]:
        """Filter a tool registry for worker use based on worker type.

        Args:
            all_tools: Dict of tool_name → ToolDefinition
            worker_type: Worker classification determining tool access
            simple_mode: If True, force minimal tool set

        Returns:
            Filtered dict with unauthorized tools removed.
        """
        allowed = cls.get_allowed_tools(worker_type, simple_mode=simple_mode)
        if allowed is not None:
            return {k: v for k, v in all_tools.items() if k in allowed}
        return {k: v for k, v in all_tools.items()
                if k not in cls.WORKER_EXCLUDED_TOOLS}

    @staticmethod
    def cap_worker_messages(messages: List[Dict[str, Any]],
                            max_messages: int = None) -> List[Dict[str, Any]]:
        """Cap a worker's message history to prevent OOM.

        Keeps system messages + most recent messages within the cap.

        Args:
            messages: Worker's conversation history
            max_messages: Cap (defaults to MAX_WORKER_MESSAGES)

        Returns:
            Capped message list
        """
        cap = max_messages or Coordinator.MAX_WORKER_MESSAGES
        if len(messages) <= cap:
            return messages

        # Keep system messages at the start
        system_msgs = [m for m in messages if m.get('role') == 'system']
        non_system = [m for m in messages if m.get('role') != 'system']

        # Keep the most recent non-system messages
        keep_count = cap - len(system_msgs)
        if keep_count <= 0:
            return system_msgs[-cap:]

        trimmed = system_msgs + non_system[-keep_count:]
        logger.warning(
            "Worker messages capped: %d → %d (removed %d old messages)",
            len(messages), len(trimmed), len(messages) - len(trimmed),
        )
        return trimmed

    # ------------------------------------------------------------------
    # Scratchpad — shared temp directory for cross-worker knowledge
    # ------------------------------------------------------------------

    @staticmethod
    def is_scratchpad_gate_enabled() -> bool:
        """Check if the scratchpad feature gate is enabled.

        The scratchpad gate (SCRATCHPAD) controls whether workers can share
        findings via a shared directory. When disabled, workers communicate
        only through the coordinator.
        """
        try:
            from agent.agentic.feature_gate_registry import gates
            return gates.is_enabled('SCRATCHPAD', default=True)
        except ImportError:
            return True  # If registry unavailable, default to enabled

    @classmethod
    def is_coordinator_mode(cls) -> bool:
        """Check if coordinator mode is active (via env var + feature gate)."""
        try:
            from agent.agentic.feature_gate_registry import gates
            if not gates.is_enabled('COORDINATOR_MODE', default=True):
                return False
        except ImportError:
            pass
        return os.environ.get('NEOMIND_COORDINATOR_MODE', '') == '1'

    @classmethod
    def match_session_mode(cls, session_mode: Optional[str]) -> Optional[str]:
        """Ensure coordinator mode matches a resumed session's stored mode.

        If the current coordinator mode doesn't match the session, flip the
        environment variable so is_coordinator_mode() returns the correct value.

        Returns:
            Warning message if mode was switched, or None.
        """
        if session_mode is None:
            return None

        current = cls.is_coordinator_mode()
        session_is_coordinator = session_mode == 'coordinator'

        if current == session_is_coordinator:
            return None

        if session_is_coordinator:
            os.environ['NEOMIND_COORDINATOR_MODE'] = '1'
            return 'Entered coordinator mode to match resumed session.'
        else:
            os.environ.pop('NEOMIND_COORDINATOR_MODE', None)
            return 'Exited coordinator mode to match resumed session.'

    @classmethod
    def get_worker_context(cls, worker_type: WorkerType = WorkerType.GENERAL,
                           scratchpad_dir: Optional[str] = None,
                           mcp_server_names: Optional[List[str]] = None) -> str:
        """Build a context string describing what tools a worker has access to.

        Args:
            worker_type: Worker classification
            scratchpad_dir: If provided and scratchpad gate enabled, include path
            mcp_server_names: If provided, list of MCP server names

        Returns:
            Context string for injection into worker system prompt.
        """
        allowed = cls.get_allowed_tools(worker_type)
        if allowed is not None:
            tool_names = sorted(allowed)
        else:
            tool_names = ['all tools except'] + sorted(cls.WORKER_EXCLUDED_TOOLS)

        parts = [f"Worker ({worker_type.value}) has access to: {', '.join(tool_names)}"]

        if mcp_server_names:
            parts.append(f"MCP servers: {', '.join(mcp_server_names)}")

        if scratchpad_dir and cls.is_scratchpad_gate_enabled():
            parts.append(
                f"Scratchpad directory: {scratchpad_dir} — "
                "workers can read and write here without permission prompts"
            )

        return '\n'.join(parts)

    def _create_scratchpad(self) -> str:
        """Create a temporary scratchpad directory for this coordination run.

        Only creates if the scratchpad gate is enabled.
        """
        if not self.is_scratchpad_gate_enabled():
            logger.info("Coordinator: scratchpad gate disabled, skipping creation")
            self._scratchpad_dir = None
            return None
        self._scratchpad_dir = tempfile.mkdtemp(prefix='neomind_scratch_')
        logger.info("Coordinator: scratchpad created at %s", self._scratchpad_dir)
        return self._scratchpad_dir

    def _cleanup_scratchpad(self):
        """Remove the scratchpad directory after coordination completes."""
        if self._scratchpad_dir and os.path.exists(self._scratchpad_dir):
            try:
                shutil.rmtree(self._scratchpad_dir)
                logger.info("Coordinator: scratchpad cleaned up")
            except Exception as e:
                logger.warning("Coordinator: scratchpad cleanup failed: %s", e)
        self._scratchpad_dir = None

    @property
    def scratchpad_dir(self) -> Optional[str]:
        """Path to the current scratchpad directory (None if not active)."""
        return self._scratchpad_dir

    def write_to_scratchpad(self, filename: str, content: str):
        """Write a file to the scratchpad for other workers to read."""
        if not self._scratchpad_dir:
            return
        filepath = os.path.join(self._scratchpad_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def read_from_scratchpad(self, filename: str) -> Optional[str]:
        """Read a file from the scratchpad."""
        if not self._scratchpad_dir:
            return None
        filepath = os.path.join(self._scratchpad_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def list_scratchpad(self) -> List[str]:
        """List all files in the scratchpad."""
        if not self._scratchpad_dir or not os.path.exists(self._scratchpad_dir):
            return []
        return os.listdir(self._scratchpad_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def coordinate(
        self,
        objective: str,
        research_tasks: List[str],
        implementation_tasks: Optional[List[str]] = None,
        verification_tasks: Optional[List[str]] = None,
    ) -> CoordinationResult:
        """Execute the full 4-phase coordination.

        Parameters
        ----------
        objective:
            High-level goal that drives synthesis.
        research_tasks:
            Descriptions for phase-1 parallel research workers.
        implementation_tasks:
            Optional explicit tasks for phase 3.  When ``None`` the
            coordinator derives them from the synthesis output.
        verification_tasks:
            Optional explicit tasks for phase 4.  Defaults to basic
            test / regression checks.

        Returns
        -------
        CoordinationResult with per-phase details and overall summary.
        """
        start = time.time()
        self.phase_results = []
        self._create_scratchpad()

        try:
            return await self._execute_phases(
                objective, research_tasks, implementation_tasks,
                verification_tasks, start
            )
        finally:
            self._cleanup_scratchpad()

    async def _execute_phases(
        self,
        objective: str,
        research_tasks: List[str],
        implementation_tasks: Optional[List[str]],
        verification_tasks: Optional[List[str]],
        start: float,
    ) -> CoordinationResult:
        """Internal: execute all 4 phases with scratchpad active.

        Separated from coordinate() so the try/finally in coordinate()
        guarantees scratchpad cleanup.
        """
        # Phase 1 — Research (parallel)
        logger.info("Coordinator: starting RESEARCH phase (%d tasks)", len(research_tasks))
        research_result = await self._run_phase(
            CoordinatorPhase.RESEARCH, research_tasks
        )
        self.phase_results.append(research_result)

        if not research_result.success:
            logger.warning("Coordinator: RESEARCH phase had failures, continuing anyway")

        # Write research findings to scratchpad for later phases
        self.write_to_scratchpad('research_findings.md', research_result.summary)

        # Phase 2 — Synthesis (coordinator analyses research output)
        logger.info("Coordinator: starting SYNTHESIS phase")
        synthesis_result = await self._synthesize(objective, research_result)
        self.phase_results.append(synthesis_result)

        # Write synthesis spec to scratchpad
        self.write_to_scratchpad('synthesis_spec.md', synthesis_result.summary)

        # Phase 3 — Implementation (parallel)
        impl_descriptions = implementation_tasks or self._extract_impl_tasks(synthesis_result)
        if impl_descriptions:
            logger.info(
                "Coordinator: starting IMPLEMENTATION phase (%d tasks)",
                len(impl_descriptions),
            )
            impl_result = await self._run_phase(
                CoordinatorPhase.IMPLEMENTATION, impl_descriptions
            )
            self.phase_results.append(impl_result)
        else:
            logger.info("Coordinator: no implementation tasks — skipping phase")

        # Phase 4 — Verification (parallel)
        verify_descriptions = verification_tasks or [
            "Run tests and report results",
            "Check for regressions in affected modules",
        ]
        logger.info(
            "Coordinator: starting VERIFICATION phase (%d tasks)",
            len(verify_descriptions),
        )
        verify_result = await self._run_phase(
            CoordinatorPhase.VERIFICATION, verify_descriptions
        )
        self.phase_results.append(verify_result)

        # Assemble final result
        total_ms = (time.time() - start) * 1000
        all_success = all(pr.success for pr in self.phase_results)
        tests_passed = verify_result.success

        files_changed = self._collect_files_changed()
        final_summary = self._build_final_summary(objective, all_success)

        return CoordinationResult(
            phases=list(self.phase_results),
            total_duration_ms=total_ms,
            success=all_success,
            final_summary=final_summary,
            files_changed=files_changed,
            tests_passed=tests_passed,
        )

    # ------------------------------------------------------------------
    # Phase execution helpers
    # ------------------------------------------------------------------

    async def _run_phase(
        self,
        phase: CoordinatorPhase,
        task_descriptions: List[str],
    ) -> PhaseResult:
        """Run a phase with parallel workers (bounded by semaphore)."""
        start = time.time()

        tasks = [
            WorkerTask(
                id=f"{phase.value}-{idx}",
                phase=phase,
                description=desc,
            )
            for idx, desc in enumerate(task_descriptions)
        ]

        completed = await asyncio.gather(
            *(self._run_worker(t) for t in tasks),
            return_exceptions=False,
        )

        duration_ms = (time.time() - start) * 1000
        success = all(t.status == "completed" for t in completed)

        # Build a human-readable summary of the phase
        summary_parts: List[str] = []
        for t in completed:
            status_icon = "OK" if t.status == "completed" else "FAIL"
            snippet = (t.result or t.error or "")[:200]
            summary_parts.append(f"[{status_icon}] {t.id}: {snippet}")
        summary = "\n".join(summary_parts)

        return PhaseResult(
            phase=phase,
            tasks=list(completed),
            summary=summary,
            duration_ms=duration_ms,
            success=success,
        )

    async def _run_worker(self, task: WorkerTask) -> WorkerTask:
        """Run a single worker task under semaphore control."""
        async with self._semaphore:
            task.status = "running"
            start = time.time()
            try:
                result = await self.worker_fn(task)
                task.status = "completed"
                task.result = result
            except Exception as exc:
                task.status = "failed"
                task.error = f"{type(exc).__name__}: {exc}"
                logger.error("Worker %s failed: %s", task.id, task.error)
            finally:
                task.duration_ms = (time.time() - start) * 1000
        return task

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    async def _synthesize(
        self,
        objective: str,
        research_result: PhaseResult,
    ) -> PhaseResult:
        """Synthesize research findings into an implementation spec.

        When *llm_fn* is available the coordinator sends the research
        findings to the LLM and asks it to produce a structured
        implementation plan.  Otherwise a deterministic concatenation is
        used as a fallback.
        """
        start = time.time()

        findings = "\n\n".join(
            f"### {t.id}\n{t.result or '(no result)'}"
            for t in research_result.tasks
        )

        if self.llm_fn is not None:
            prompt = (
                f"You are a senior software architect coordinating a multi-agent "
                f"coding session.\n\n"
                f"## Objective\n{objective}\n\n"
                f"## Research Findings\n{findings}\n\n"
                f"Based on the research above, produce a concise implementation "
                f"plan.  List each discrete change as a numbered task prefixed "
                f'with "TASK:" so they can be parsed programmatically.  '
                f"Keep each task to one clear sentence."
            )
            try:
                synthesis_text = await self.llm_fn(prompt)
                status = "completed"
                error = None
            except Exception as exc:
                synthesis_text = f"LLM synthesis failed, falling back.\n\n{findings}"
                status = "failed"
                error = f"{type(exc).__name__}: {exc}"
                logger.error("Synthesis LLM call failed: %s", error)
        else:
            synthesis_text = (
                f"## Synthesis (no LLM — concatenated findings)\n\n"
                f"Objective: {objective}\n\n{findings}"
            )
            status = "completed"
            error = None

        duration_ms = (time.time() - start) * 1000

        task = WorkerTask(
            id="synthesis-0",
            phase=CoordinatorPhase.SYNTHESIS,
            description="Synthesize research into implementation spec",
            status=status,
            result=synthesis_text,
            error=error,
            duration_ms=duration_ms,
        )

        return PhaseResult(
            phase=CoordinatorPhase.SYNTHESIS,
            tasks=[task],
            summary=synthesis_text,
            duration_ms=duration_ms,
            success=(status == "completed"),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_impl_tasks(self, synthesis_result: PhaseResult) -> List[str]:
        """Extract implementation task descriptions from synthesis output.

        Looks for lines prefixed with ``TASK:`` in the synthesis text.
        Falls back to returning the entire synthesis summary as a single
        task if no ``TASK:`` lines are found.
        """
        synthesis_text = synthesis_result.summary or ""
        tasks: List[str] = []
        for line in synthesis_text.splitlines():
            stripped = line.strip()
            # Match lines like "1. TASK: ..." or "TASK: ..."
            if "TASK:" in stripped:
                # Extract everything after "TASK:"
                task_desc = stripped.split("TASK:", 1)[1].strip()
                if task_desc:
                    tasks.append(task_desc)

        if not tasks and synthesis_text.strip():
            # No structured tasks found — treat whole synthesis as one task
            tasks.append(synthesis_text.strip()[:500])

        return tasks

    def _collect_files_changed(self) -> List[str]:
        """Scan implementation results for file paths that were changed.

        Heuristic: look for lines containing common file-change markers
        in the implementation phase results.
        """
        files: List[str] = []
        for pr in self.phase_results:
            if pr.phase != CoordinatorPhase.IMPLEMENTATION:
                continue
            for task in pr.tasks:
                if not task.result:
                    continue
                for line in task.result.splitlines():
                    stripped = line.strip()
                    # Detect common patterns like "Modified: path/to/file.py"
                    for prefix in ("Modified:", "Created:", "Deleted:", "Changed:", "File:"):
                        if stripped.startswith(prefix):
                            path = stripped.split(prefix, 1)[1].strip()
                            if path and path not in files:
                                files.append(path)
        return files

    def _build_final_summary(self, objective: str, all_success: bool) -> str:
        """Build a human-readable summary of the full coordination run."""
        status = "SUCCESS" if all_success else "COMPLETED WITH ERRORS"
        parts = [f"## Coordination {status}", f"Objective: {objective}", ""]

        for pr in self.phase_results:
            phase_status = "passed" if pr.success else "had failures"
            parts.append(
                f"- **{pr.phase.value.title()}**: {phase_status} "
                f"({len(pr.tasks)} tasks, {pr.duration_ms:.0f}ms)"
            )

        return "\n".join(parts)
