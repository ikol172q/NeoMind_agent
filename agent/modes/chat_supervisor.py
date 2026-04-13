"""
Chat-as-Manager Delegation Policy.

When the chat persona operates as team leader, this module adds supervisor
behavior: watch the mailbox, dispatch tasks, detect stuck workers, aggregate
results.

Contract: contracts/persona_fleet/03_chat_supervisor.md
"""

from __future__ import annotations

import re
import time
import logging
from typing import Optional, Dict, List, Any

from agent.agentic.swarm import (
    Mailbox,
    SharedTaskQueue,
    TeamManager,
    format_task_notification,
)

logger = logging.getLogger(__name__)


class ChatSupervisor:
    """Delegation policy for chat-as-leader in a team project."""

    def __init__(self, team_name: str, leader_name: str,
                 base_dir: Optional[str] = None):
        """
        Args:
            team_name: The team/project this supervisor manages.
            leader_name: This leader's agent name.
            base_dir: Optional base dir for team storage.
        """
        self.team_name = team_name
        self.leader_name = leader_name
        self._base_dir = base_dir

        self._mailbox = Mailbox(team_name, leader_name, base_dir=base_dir)
        self._task_queue = SharedTaskQueue(team_name, base_dir=base_dir)
        self._team_mgr = TeamManager(base_dir=base_dir)

        # Track worker status: {name: {"status": "idle"|"busy", "task_id": str|None, "busy_since": float|None}}
        self._worker_status: Dict[str, Dict[str, Any]] = {}
        self._init_worker_status()

    def _init_worker_status(self):
        """Initialize worker status from team data."""
        team = self._team_mgr.get_team(self.team_name)
        if not team:
            return
        for member in team.get("members", []):
            name = member["name"]
            if name != self.leader_name:
                self._worker_status[name] = {
                    "status": "idle",
                    "persona": member.get("persona"),
                    "task_id": None,
                    "busy_since": None,
                }

    def get_team_status(self) -> Dict[str, Any]:
        """Get current status of all team members.

        Returns:
            {
                "team_name": "proj-1",
                "members": [...],
                "tasks": {"available": N, "claimed": N, "completed": N, "failed": N}
            }
        """
        members = []
        for name, info in self._worker_status.items():
            members.append({
                "name": name,
                "persona": info.get("persona"),
                "status": info["status"],
                "current_task": info.get("task_id"),
            })

        # Count tasks by status
        all_tasks = self._task_queue.list_tasks()
        task_counts = {"available": 0, "claimed": 0, "completed": 0, "failed": 0}
        for t in all_tasks:
            status = t.get("status", "available")
            if status in task_counts:
                task_counts[status] += 1

        return {
            "team_name": self.team_name,
            "members": members,
            "tasks": task_counts,
        }

    def dispatch_task(self, description: str,
                      target_persona: Optional[str] = None,
                      target_member: Optional[str] = None) -> str:
        """Create and dispatch a task.

        If target_member is specified, sends directly to that member's mailbox.
        If target_persona is specified, sends to the first idle member with
        that persona.
        If neither, adds to the shared queue for any idle worker to claim.

        Args:
            description: Task description.
            target_persona: Optional persona filter.
            target_member: Optional specific member.

        Returns:
            task_id
        """
        task_id = self._task_queue.add_task(description, self.leader_name)

        if target_member:
            # Send directly to that member
            member_mailbox = Mailbox(
                self.team_name, target_member, base_dir=self._base_dir
            )
            member_mailbox.write_message(
                sender=self.leader_name,
                content=format_task_notification(
                    task_id=task_id,
                    status="assigned",
                    summary=description,
                ),
                msg_type="task_assignment",
            )
            if target_member in self._worker_status:
                self._worker_status[target_member]["status"] = "busy"
                self._worker_status[target_member]["task_id"] = task_id
                self._worker_status[target_member]["busy_since"] = time.time()

        elif target_persona:
            # Find first idle member with that persona
            for name, info in self._worker_status.items():
                if info.get("persona") == target_persona and info["status"] == "idle":
                    member_mailbox = Mailbox(
                        self.team_name, name, base_dir=self._base_dir
                    )
                    member_mailbox.write_message(
                        sender=self.leader_name,
                        content=format_task_notification(
                            task_id=task_id,
                            status="assigned",
                            summary=description,
                        ),
                        msg_type="task_assignment",
                    )
                    self._worker_status[name]["status"] = "busy"
                    self._worker_status[name]["task_id"] = task_id
                    self._worker_status[name]["busy_since"] = time.time()
                    break
            # If no idle worker found, task stays in queue as "available"

        # If neither target specified, task stays in queue for self-service claiming.

        return task_id

    def check_mailbox(self) -> List[Dict[str, Any]]:
        """Read unread messages from the leader's mailbox.

        Parses task-notifications (XML format), updates internal worker
        status tracking.

        Returns:
            List of parsed messages with type annotations.
        """
        unread = self._mailbox.read_unread()
        parsed = []

        for msg in unread:
            entry: Dict[str, Any] = {
                "sender": msg.sender,
                "type": msg.msg_type,
                "raw_content": msg.content,
                "timestamp": msg.timestamp,
            }

            # Try to parse task-notification XML
            task_id_match = re.search(
                r"<task-id>(.*?)</task-id>", msg.content, re.DOTALL
            )
            status_match = re.search(
                r"<status>(.*?)</status>", msg.content, re.DOTALL
            )
            summary_match = re.search(
                r"<summary>(.*?)</summary>", msg.content, re.DOTALL
            )
            result_match = re.search(
                r"<result>(.*?)</result>", msg.content, re.DOTALL
            )

            if task_id_match and status_match:
                entry["parsed"] = {
                    "task_id": task_id_match.group(1).strip(),
                    "status": status_match.group(1).strip(),
                    "summary": summary_match.group(1).strip() if summary_match else "",
                    "result": result_match.group(1).strip() if result_match else "",
                }

                # Update worker status if task completed
                task_status = entry["parsed"]["status"]
                if task_status in ("completed", "failed"):
                    if msg.sender in self._worker_status:
                        self._worker_status[msg.sender]["status"] = "idle"
                        self._worker_status[msg.sender]["task_id"] = None
                        self._worker_status[msg.sender]["busy_since"] = None

                    # Mark task in queue
                    if task_status == "completed":
                        self._task_queue.complete_task(
                            entry["parsed"]["task_id"],
                            result=entry["parsed"]["result"],
                        )

            parsed.append(entry)

        return parsed

    def get_stuck_workers(self, timeout_minutes: float = 10.0) -> List[str]:
        """Detect workers that have been busy for too long.

        Args:
            timeout_minutes: Threshold for considering a worker stuck.

        Returns:
            List of worker names that are stuck.
        """
        stuck = []
        now = time.time()
        timeout_sec = timeout_minutes * 60

        for name, info in self._worker_status.items():
            if info["status"] == "busy" and info.get("busy_since"):
                if now - info["busy_since"] > timeout_sec:
                    stuck.append(name)

        return stuck

    def redispatch_stuck(self, worker_name: str) -> Optional[str]:
        """Re-dispatch a stuck worker's task to another idle worker.

        Returns the new task_id if re-dispatched, None if no idle workers.
        """
        info = self._worker_status.get(worker_name)
        if not info or info["status"] != "busy":
            return None

        old_task_id = info.get("task_id")
        if not old_task_id:
            return None

        # Find the task description from the queue
        tasks = self._task_queue.list_tasks()
        description = None
        for t in tasks:
            if t["id"] == old_task_id:
                description = t.get("description", "redispatched task")
                break

        if description is None:
            description = "redispatched task"

        # Mark original worker as idle
        self._worker_status[worker_name]["status"] = "idle"
        self._worker_status[worker_name]["task_id"] = None
        self._worker_status[worker_name]["busy_since"] = None

        # Find another idle worker
        for name, w_info in self._worker_status.items():
            if name != worker_name and w_info["status"] == "idle":
                return self.dispatch_task(
                    description, target_member=name
                )

        return None

    def aggregate_results(self, task_ids: List[str]) -> str:
        """Aggregate completed task results into a summary.

        Args:
            task_ids: Task IDs to aggregate.

        Returns:
            Formatted summary of all completed tasks.
        """
        all_tasks = self._task_queue.list_tasks()
        task_map = {t["id"]: t for t in all_tasks}

        lines = [f"## Task Summary ({len(task_ids)} tasks)\n"]

        for tid in task_ids:
            task = task_map.get(tid)
            if not task:
                lines.append(f"- **{tid}**: not found")
                continue

            status = task.get("status", "unknown")
            desc = task.get("description", "(no description)")
            result = task.get("result", "")

            lines.append(f"### {tid} [{status}]")
            lines.append(f"**Task:** {desc}")
            if result:
                lines.append(f"**Result:** {result}")
            lines.append("")

        return "\n".join(lines)
