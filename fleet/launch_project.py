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

from fleet.project_config import (
    create_project,
    add_project_member,
    get_project,
    delete_project,
)
from fleet.project_schema import ProjectConfig, MemberConfig
from agent.agentic.swarm import Mailbox, SharedTaskQueue, TeamManager
from agent.modes.chat_supervisor import ChatSupervisor

logger = logging.getLogger(__name__)


class FleetLauncher:
    """Launch and manage a fleet of agent instances for a project."""

    def __init__(self, config: ProjectConfig, base_dir: Optional[str] = None):
        """
        Args:
            config: Validated project configuration.
            base_dir: Optional base dir for team storage.
        """
        self.config = config
        self._base_dir = base_dir
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._supervisor: Optional[ChatSupervisor] = None
        self._mailboxes: Dict[str, Mailbox] = {}
        self._task_queue: Optional[SharedTaskQueue] = None

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

        Each member watches its mailbox for incoming messages and tasks.
        Leaders also run the supervisor check loop.
        """
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
                        logger.info(
                            f"Worker '{member.name}' claimed task "
                            f"{task['id']}: {task['description']}"
                        )

                await asyncio.sleep(0.5)  # Poll interval

        except asyncio.CancelledError:
            logger.info(f"Member '{member.name}' cancelled")
        except Exception as e:
            logger.error(f"Member '{member.name}' error: {e}")

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
