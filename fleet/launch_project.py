"""
Multi-instance fleet launcher for NeoMind.

Reads a ProjectConfig and spawns N agent instances as asyncio tasks
in one process, each bound to its assigned persona.

Contract: contracts/persona_fleet/05_fleet_launcher.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Dict, Any

from agent_config import AgentConfigManager, set_current_config
from fleet.project_config import (
    create_project,
    add_project_member,
    get_project,
    delete_project,
)
from fleet.project_schema import ProjectConfig, MemberConfig
from fleet.worker_turn import execute_task as _execute_task
from agent.agentic.swarm import (
    Mailbox,
    SharedTaskQueue,
    TeamManager,
    format_task_notification,
)
from agent.modes.chat_supervisor import ChatSupervisor

logger = logging.getLogger(__name__)


class FleetLauncher:
    """Launch and manage a fleet of agent instances for a project."""

    def __init__(
        self,
        config: ProjectConfig,
        base_dir: Optional[str] = None,
        shared_memory: Optional[Any] = None,
    ):
        """
        Args:
            config: Validated project configuration.
            base_dir: Optional base dir for team storage.
            shared_memory: Optional SharedMemory instance used by
                workers' fail_fast entry check (Phase 3 integration).
                When None, the fail_fast gate is skipped. Passing an
                instance enables the KPI-driven fleet downgrade.
        """
        self.config = config
        self._base_dir = base_dir
        self._shared_memory = shared_memory
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._supervisor: Optional[ChatSupervisor] = None
        self._mailboxes: Dict[str, Mailbox] = {}
        self._task_queue: Optional[SharedTaskQueue] = None
        self._leader_name: Optional[str] = None

    async def start(self) -> None:
        """Start all agent instances as asyncio tasks.

        1. Creates the team via project_config (with personas).
        2. Sets up Mailbox for each member.
        3. Sets up SharedTaskQueue for the team.
        4. Spawns each member as an asyncio task.
        5. The leader's task includes ChatSupervisor.
        """
        if self._running:
            logger.warning("Fleet already running")
            return

        # Create the project (team) with leader
        leader_cfg = None
        for m in self.config.members:
            if m.role == "leader":
                leader_cfg = m
                break

        if not leader_cfg:
            raise ValueError("No leader found in project config")

        self._leader_name = leader_cfg.name

        try:
            create_project(
                self.config.project_id,
                leader_cfg.name,
                leader_cfg.persona,
                base_dir=self._base_dir,
            )
        except ValueError:
            # Team may already exist from a previous run
            pass

        # Add non-leader members
        for m in self.config.members:
            if m.role != "leader":
                try:
                    add_project_member(
                        self.config.project_id,
                        m.name,
                        m.persona,
                        role=m.role,
                        base_dir=self._base_dir,
                    )
                except ValueError:
                    pass  # Member may already exist

        # Set up infrastructure
        self._task_queue = SharedTaskQueue(
            self.config.project_id, base_dir=self._base_dir
        )
        for m in self.config.members:
            self._mailboxes[m.name] = Mailbox(
                self.config.project_id, m.name, base_dir=self._base_dir
            )

        # Set up supervisor for leader
        self._supervisor = ChatSupervisor(
            team_name=self.config.project_id,
            leader_name=leader_cfg.name,
            base_dir=self._base_dir,
        )

        # Spawn asyncio tasks for each member
        for m in self.config.members:
            task = asyncio.create_task(
                self._run_member(m),
                name=f"fleet-{m.name}",
            )
            self._tasks[m.name] = task

        self._running = True
        logger.info(
            f"Fleet '{self.config.project_id}' started with "
            f"{len(self._tasks)} members"
        )

    async def _run_member(self, member: MemberConfig) -> None:
        """Run a single member's event loop.

        Each member watches its mailbox for incoming messages, claims
        tasks when available, and invokes the persona-specific worker
        handler via ``fleet.worker_turn.execute_task``. Leaders also
        run the supervisor check loop.

        **Option E contextvar isolation (Phase 4.A):** the first thing
        this coroutine does is bind a fresh ``AgentConfigManager(mode=
        member.persona)`` as the current config for THIS asyncio task.
        Because ``asyncio.create_task`` captured an independent context
        snapshot when the launcher spawned this coroutine, that set()
        only affects the current worker's view — sibling members
        running concurrently each see their own per-persona config,
        with zero cross-contamination and zero serialization. Proven
        by ``tests/test_agent_config_contextvar.py::
        test_sibling_tasks_isolated_across_asyncio_gather``.
        """
        # Per-task persona binding — Phase 4.A Option E
        member_cfg = AgentConfigManager(mode=member.persona)
        set_current_config(member_cfg)

        mailbox = self._mailboxes[member.name]

        try:
            while self._running:
                # Check for messages
                messages = mailbox.read_unread()
                for msg in messages:
                    if msg.msg_type == "shutdown":
                        logger.info(f"Member '{member.name}' received shutdown")
                        return
                    # Process task assignments, etc.
                    logger.debug(
                        f"Member '{member.name}' received {msg.msg_type} "
                        f"from {msg.sender}"
                    )

                # Leaders also check the supervisor
                if member.role == "leader" and self._supervisor:
                    self._supervisor.check_mailbox()

                # Workers check for available tasks
                if member.role == "worker" and self._task_queue:
                    task = self._task_queue.try_claim_next(member.name)
                    if task:
                        await self._run_worker_turn(member, task)

                await asyncio.sleep(0.5)  # Poll interval

        except asyncio.CancelledError:
            logger.info(f"Member '{member.name}' cancelled")
        except Exception as e:
            logger.error(f"Member '{member.name}' error: {e}")

    async def _run_worker_turn(
        self, member: MemberConfig, task: Dict[str, Any]
    ) -> None:
        """Execute one claimed task and report the result to the leader.

        Delegates to ``fleet.worker_turn.execute_task`` for the actual
        persona dispatch — this method stays persona-agnostic on
        purpose (grep audit gates on zero persona string literals in
        launch_project.py).

        On completion:
          1. Mark the task as complete in the shared queue.
          2. Write a ``format_task_notification`` XML message into the
             leader's mailbox so the ``ChatSupervisor`` aggregation
             path picks it up on the next polling tick.

        Exceptions from ``execute_task`` should be impossible (that
        function catches everything internally and returns
        ``status=failed``), but we still wrap this call defensively so
        a bug here cannot take down the whole member coroutine.
        """
        logger.info(
            f"Worker '{member.name}' claimed task "
            f"{task.get('id', '?')}: {task.get('description', '')[:80]}"
        )
        try:
            result = await _execute_task(
                member,
                task,
                shared_memory=self._shared_memory,
                project_id=self.config.project_id,
            )
        except Exception as exc:
            logger.exception(
                "Worker '%s' crashed during execute_task", member.name
            )
            result = {
                "status": "failed",
                "result": f"launcher-caught exception: {type(exc).__name__}: {exc}",
                "layer_used": None,
                "artifacts": [],
            }

        # Mark task in queue (best-effort — result string truncated to
        # keep the shared JSON file from ballooning)
        try:
            if self._task_queue is not None:
                self._task_queue.complete_task(
                    task["id"], result=str(result.get("result", ""))[:1000],
                )
        except Exception as exc:
            logger.warning(
                "Worker '%s' failed to mark task %s complete: %s",
                member.name, task.get("id"), exc,
            )

        # Report back to leader via XML notification in the leader's mailbox
        if self._leader_name and self._leader_name != member.name:
            leader_mailbox = self._mailboxes.get(self._leader_name)
            if leader_mailbox is not None:
                try:
                    notification = format_task_notification(
                        task_id=str(task.get("id", "")),
                        status=result.get("status", "completed"),
                        summary=str(task.get("description", ""))[:200],
                        result=str(result.get("result", "")),
                    )
                    leader_mailbox.write_message(
                        sender=member.name,
                        content=notification,
                        msg_type="task_notification",
                    )
                except Exception as exc:
                    logger.warning(
                        "Worker '%s' failed to notify leader: %s",
                        member.name, exc,
                    )

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop all instances.

        1. Sends shutdown message to all member mailboxes.
        2. Waits for tasks to complete (up to timeout).
        3. Cancels remaining tasks.
        4. Cleans up team resources.
        """
        self._running = False

        # Send shutdown messages
        for name, mailbox in self._mailboxes.items():
            mailbox.write_message(
                sender="fleet-launcher",
                content="shutdown",
                msg_type="shutdown",
            )

        # Wait for graceful shutdown
        if self._tasks:
            done, pending = await asyncio.wait(
                self._tasks.values(),
                timeout=timeout,
            )

            # Cancel any remaining
            for task in pending:
                task.cancel()

            # Wait for cancellation to complete
            if pending:
                await asyncio.wait(pending, timeout=5.0)

        self._tasks.clear()
        self._mailboxes.clear()
        self._supervisor = None
        self._task_queue = None

        logger.info(f"Fleet '{self.config.project_id}' stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get current fleet status."""
        members = {}
        for m in self.config.members:
            task = self._tasks.get(m.name)
            status = "stopped"
            if task and not task.done():
                status = "running"
            elif task and task.done():
                status = "finished"

            members[m.name] = {
                "persona": m.persona,
                "role": m.role,
                "status": status,
            }

        task_info = {"available": 0, "claimed": 0, "completed": 0}
        if self._task_queue:
            for t in self._task_queue.list_tasks():
                s = t.get("status", "available")
                if s in task_info:
                    task_info[s] += 1

        return {
            "project_id": self.config.project_id,
            "running": self._running,
            "members": members,
            "tasks": task_info,
        }

    async def submit_task(self, description: str,
                          target_persona: Optional[str] = None) -> str:
        """Submit a task to the fleet (delegates to leader's ChatSupervisor).

        Returns task_id.
        """
        if not self._supervisor:
            raise RuntimeError("Fleet not started — no supervisor available")
        return self._supervisor.dispatch_task(
            description, target_persona=target_persona
        )
