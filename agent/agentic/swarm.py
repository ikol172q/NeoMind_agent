"""
Swarm System — Multi-agent team orchestration for NeoMind.

Provides team-based agent collaboration with:
- Named teammates with persistent identity
- File-based mailbox for inter-agent communication
- Permission delegation (workers ask leader for approval)
- Shared task queue with atomic claiming
- XML task notifications for structured reporting

This is distinct from Coordinator mode (which is phase-based orchestration).
Swarm mode creates persistent teams that collaborate via mailboxes.
"""

import os
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


VALID_PERSONAS = frozenset({"chat", "coding", "fin"})


@dataclass
class TeammateIdentity:
    """Identity of a team member."""
    agent_id: str
    agent_name: str
    team_name: str
    color: str = "default"
    is_leader: bool = False
    persona: Optional[str] = None  # "chat" | "coding" | "fin" | None (legacy)


@dataclass
class MailboxMessage:
    """A message in an agent's mailbox."""
    sender: str
    content: str
    msg_type: str = "text"  # text, permission_request, permission_response, shutdown, plan_approval
    timestamp: float = 0.0
    read: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


TEAM_COLORS = ["blue", "green", "yellow", "magenta", "cyan", "red", "white"]


class Mailbox:
    """File-based mailbox for inter-agent communication.

    Each agent has an inbox at:
      .neomind/teams/{team_name}/inboxes/{agent_name}.json

    Lock-file protected against concurrent writes.
    """

    def __init__(self, team_name: str, agent_name: str,
                 base_dir: str = None):
        self._base = Path(base_dir or os.path.expanduser('~/.neomind'))
        self._inbox_dir = self._base / 'teams' / team_name / 'inboxes'
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._inbox_file = self._inbox_dir / f"{agent_name}.json"
        self._lock_file = self._inbox_dir / f"{agent_name}.lock"

    def write_message(self, sender: str, content: str,
                      msg_type: str = "text", metadata: Dict = None):
        """Write a message to this inbox."""
        self._acquire_lock()
        try:
            messages = self._load_messages()
            messages.append({
                'sender': sender,
                'content': content,
                'type': msg_type,
                'timestamp': time.time(),
                'read': False,
                'metadata': metadata or {},
            })
            self._save_messages(messages)
        finally:
            self._release_lock()

    def read_unread(self) -> List[MailboxMessage]:
        """Read all unread messages and mark them as read."""
        self._acquire_lock()
        try:
            messages = self._load_messages()
            unread = []
            for msg in messages:
                if not msg.get('read', False):
                    msg['read'] = True
                    unread.append(MailboxMessage(
                        sender=msg['sender'],
                        content=msg['content'],
                        msg_type=msg.get('type', 'text'),
                        timestamp=msg.get('timestamp', 0),
                        read=True,
                        metadata=msg.get('metadata', {}),
                    ))
            if unread:
                self._save_messages(messages)
            return unread
        finally:
            self._release_lock()

    def _load_messages(self) -> List[Dict]:
        if self._inbox_file.exists():
            try:
                return json.loads(self._inbox_file.read_text())
            except json.JSONDecodeError:
                return []
        return []

    def _save_messages(self, messages: List[Dict]):
        self._inbox_file.write_text(json.dumps(messages, indent=2))

    def _acquire_lock(self, timeout: float = 5.0):
        start = time.time()
        while time.time() - start < timeout:
            try:
                fd = os.open(str(self._lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return
            except FileExistsError:
                # Check if lock is stale (>60s old)
                try:
                    if time.time() - self._lock_file.stat().st_mtime > 60:
                        self._lock_file.unlink()
                        continue
                except Exception:
                    pass
                time.sleep(0.05)
        raise TimeoutError(f"Failed to acquire mailbox lock: {self._lock_file}")

    def _release_lock(self):
        try:
            self._lock_file.unlink()
        except Exception:
            pass


class SharedTaskQueue:
    """Shared task queue for team collaboration.

    Tasks can be claimed atomically by team members.
    """

    def __init__(self, team_name: str, base_dir: str = None):
        self._base = Path(base_dir or os.path.expanduser('~/.neomind'))
        self._tasks_file = self._base / 'teams' / team_name / 'tasks.json'
        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)

    def add_task(self, description: str, created_by: str) -> str:
        """Add a task to the shared queue. Returns task_id."""
        tasks = self._load()
        task_id = f"task_{int(time.time())}_{len(tasks)}"
        tasks.append({
            'id': task_id,
            'description': description,
            'status': 'available',  # available, claimed, completed, failed
            'created_by': created_by,
            'claimed_by': None,
            'created_at': time.time(),
            'claimed_at': None,
            'completed_at': None,
        })
        self._save(tasks)
        return task_id

    def try_claim_next(self, agent_name: str) -> Optional[Dict]:
        """Atomically claim the next available task.

        Returns the claimed task or None if no tasks available.
        """
        tasks = self._load()
        for task in tasks:
            if task['status'] == 'available':
                task['status'] = 'claimed'
                task['claimed_by'] = agent_name
                task['claimed_at'] = time.time()
                self._save(tasks)
                return task
        return None

    def complete_task(self, task_id: str, result: str = ""):
        """Mark a task as completed."""
        tasks = self._load()
        for task in tasks:
            if task['id'] == task_id:
                task['status'] = 'completed'
                task['completed_at'] = time.time()
                task['result'] = result
                break
        self._save(tasks)

    def list_tasks(self, status: str = None) -> List[Dict]:
        """List tasks, optionally filtered by status."""
        tasks = self._load()
        if status:
            return [t for t in tasks if t['status'] == status]
        return tasks

    def _load(self) -> List[Dict]:
        if self._tasks_file.exists():
            try:
                return json.loads(self._tasks_file.read_text())
            except json.JSONDecodeError:
                return []
        return []

    def _save(self, tasks: List[Dict]):
        self._tasks_file.write_text(json.dumps(tasks, indent=2))


def format_task_notification(task_id: str, status: str, summary: str,
                              result: str = "", tokens_used: int = 0) -> str:
    """Format a task completion as XML notification.

    Claude Code uses XML task-notifications for structured reporting
    from workers to coordinator.
    """
    return (
        f"<task-notification>\n"
        f"  <task-id>{task_id}</task-id>\n"
        f"  <status>{status}</status>\n"
        f"  <summary>{summary}</summary>\n"
        f"  <result>{result[:2000]}</result>\n"
        f"  <tokens-used>{tokens_used}</tokens-used>\n"
        f"</task-notification>"
    )


class TeamManager:
    """Manages team lifecycle and member registration."""

    def __init__(self, base_dir: str = None):
        self._base = Path(base_dir or os.path.expanduser('~/.neomind'))

    def create_team(self, team_name: str, leader_name: str,
                    leader_persona: Optional[str] = None) -> Dict[str, Any]:
        """Create a new team with a leader.

        Args:
            team_name: Unique team name.
            leader_name: Name of the team leader.
            leader_persona: Optional persona for the leader ("chat", "coding", "fin").

        Raises:
            ValueError: If the team already exists or persona is invalid.
        """
        if leader_persona is not None and leader_persona not in VALID_PERSONAS:
            raise ValueError(
                f"Invalid persona '{leader_persona}'. "
                f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}"
            )

        team_dir = self._base / 'teams' / team_name
        team_file = team_dir / 'team.json'

        if team_file.exists():
            raise ValueError(f"Team '{team_name}' already exists")

        team_dir.mkdir(parents=True, exist_ok=True)
        (team_dir / 'inboxes').mkdir(exist_ok=True)

        team_data = {
            'name': team_name,
            'leader': leader_name,
            'members': [
                {
                    'name': leader_name,
                    'color': TEAM_COLORS[0],
                    'is_leader': True,
                    'persona': leader_persona,
                }
            ],
            'created_at': time.time(),
        }
        team_file.write_text(json.dumps(team_data, indent=2))
        return team_data

    def add_member(self, team_name: str, member_name: str,
                   persona: Optional[str] = None) -> TeammateIdentity:
        """Add a member to a team.

        Args:
            team_name: Name of the team.
            member_name: Name of the new member.
            persona: Optional persona ("chat", "coding", "fin").

        Raises:
            ValueError: If the team doesn't exist or persona is invalid.
        """
        if persona is not None and persona not in VALID_PERSONAS:
            raise ValueError(
                f"Invalid persona '{persona}'. "
                f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}"
            )

        team_file = self._base / 'teams' / team_name / 'team.json'
        if not team_file.exists():
            raise ValueError(f"Team '{team_name}' does not exist")

        team_data = json.loads(team_file.read_text())
        color_idx = len(team_data['members']) % len(TEAM_COLORS)

        member = {
            'name': member_name,
            'color': TEAM_COLORS[color_idx],
            'is_leader': False,
            'persona': persona,
        }
        team_data['members'].append(member)
        team_file.write_text(json.dumps(team_data, indent=2))

        return TeammateIdentity(
            agent_id=f"{member_name}@{team_name}",
            agent_name=member_name,
            team_name=team_name,
            color=TEAM_COLORS[color_idx],
            persona=persona,
        )

    def remove_member(self, team_name: str, member_name: str):
        """Remove a member from a team."""
        team_file = self._base / 'teams' / team_name / 'team.json'
        if team_file.exists():
            team_data = json.loads(team_file.read_text())
            team_data['members'] = [
                m for m in team_data['members'] if m['name'] != member_name
            ]
            team_file.write_text(json.dumps(team_data, indent=2))

    def get_team(self, team_name: str) -> Optional[Dict]:
        """Get team data."""
        team_file = self._base / 'teams' / team_name / 'team.json'
        if team_file.exists():
            return json.loads(team_file.read_text())
        return None

    def delete_team(self, team_name: str):
        """Delete a team and all its data."""
        import shutil
        team_dir = self._base / 'teams' / team_name
        if team_dir.exists():
            shutil.rmtree(str(team_dir))
