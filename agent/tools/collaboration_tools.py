"""
Collaboration and Scheduling Tools for NeoMind Agent.

- SendMessageTool: Send messages between agents/sessions
- ScheduleCronTool: Schedule recurring tasks
- RemoteTriggerTool: Trigger remote agent execution
- TeamCreateTool: Create agent teams
- TeamDeleteTool: Delete agent teams

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from string import Template


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageDirection(Enum):
    """Direction of a message."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class TriggerMethod(Enum):
    """HTTP method for remote triggers."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class TeamRole(Enum):
    """Roles within an agent team."""
    LEADER = "leader"
    WORKER = "worker"
    REVIEWER = "reviewer"
    OBSERVER = "observer"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A message exchanged between agents or services."""
    id: str
    sender: str
    recipient: str
    content: str
    direction: MessageDirection
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    read: bool = False


@dataclass
class MessageResult:
    """Result from a messaging operation."""
    success: bool
    message: str
    data: Optional[Message] = None
    messages: Optional[List[Message]] = None
    error: Optional[str] = None


@dataclass
class Schedule:
    """A scheduled recurring task."""
    name: str
    cron_expr: str
    command: str
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    enabled: bool = True
    last_run: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleResult:
    """Result from a scheduling operation."""
    success: bool
    message: str
    data: Optional[Schedule] = None
    schedules: Optional[List[Schedule]] = None
    error: Optional[str] = None


@dataclass
class Trigger:
    """A remote trigger definition."""
    name: str
    url: str
    method: TriggerMethod
    headers: Dict[str, str] = field(default_factory=dict)
    payload_template: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_fired: Optional[datetime] = None
    fire_count: int = 0


@dataclass
class TriggerResult:
    """Result from a trigger operation."""
    success: bool
    message: str
    data: Optional[Trigger] = None
    triggers: Optional[List[Trigger]] = None
    response_body: Optional[str] = None
    status_code: Optional[int] = None
    error: Optional[str] = None


VALID_PERSONAS = frozenset({"chat", "coding", "fin"})


@dataclass
class TeamMember:
    """A member of an agent team."""
    member_id: str
    role: TeamRole
    persona: Optional[str] = None  # "chat" | "coding" | "fin" | None (legacy)
    joined_at: datetime = field(default_factory=datetime.now)


@dataclass
class Team:
    """An agent team for collaborative work."""
    name: str
    description: str = ""
    members: Dict[str, TeamMember] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamResult:
    """Result from a team management operation."""
    success: bool
    message: str
    data: Optional[Team] = None
    teams: Optional[List[Team]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Cron parsing helpers
# ---------------------------------------------------------------------------

# Allowed ranges for each cron field: (min, max)
_CRON_FIELD_RANGES: List[Tuple[str, int, int]] = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 6),
]


def _validate_cron(expr: str) -> Tuple[bool, str]:
    """
    Validate a cron expression in the standard 5-field format.

    Format: ``minute hour day month weekday``

    Supports: ``*``, ``*/N``, ``N``, ``N-M``, ``N,M,...``

    Returns:
        Tuple of (is_valid, error_message).  error_message is empty on
        success.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        return False, f"Expected 5 fields, got {len(parts)}"

    token_re = re.compile(
        r"^(?:\*(?:/\d+)?|\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)$"
    )

    for i, part in enumerate(parts):
        field_name, lo, hi = _CRON_FIELD_RANGES[i]

        if not token_re.match(part):
            return False, f"Invalid syntax in {field_name} field: '{part}'"

        # Extract all literal numbers and validate range
        numbers = [int(n) for n in re.findall(r"\d+", part)]
        for n in numbers:
            # For step values like */N, the N is a divisor, not a value
            if part.startswith("*/"):
                if n == 0:
                    return False, f"Step value in {field_name} cannot be 0"
                continue
            if n < lo or n > hi:
                return (
                    False,
                    f"Value {n} out of range for {field_name} "
                    f"(allowed {lo}-{hi})",
                )

    return True, ""


def _parse_cron(expr: str) -> Dict[str, Any]:
    """
    Parse a validated 5-field cron expression into a dict of field
    descriptors.

    Each field value is stored as-is (string) together with its expanded
    set of matching integers when practical.

    Returns:
        Dict with keys ``minute``, ``hour``, ``day``, ``month``,
        ``weekday``, each mapping to ``{"raw": str, "values": List[int]}``.
    """
    parts = expr.strip().split()
    result: Dict[str, Any] = {}

    for i, part in enumerate(parts):
        field_name, lo, hi = _CRON_FIELD_RANGES[i]
        values: List[int] = []

        if part == "*":
            values = list(range(lo, hi + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            values = list(range(lo, hi + 1, step))
        else:
            for segment in part.split(","):
                if "-" in segment:
                    a, b = segment.split("-", 1)
                    values.extend(range(int(a), int(b) + 1))
                else:
                    values.append(int(segment))

        result[field_name] = {"raw": part, "values": sorted(set(values))}

    return result


# ---------------------------------------------------------------------------
# SendMessageTool
# ---------------------------------------------------------------------------

class SendMessageTool:
    """Send messages between agents or to external services."""

    def __init__(self, agent_id: str = "local"):
        """
        Initialize the messaging tool.

        Args:
            agent_id: Identifier for this agent (used as default sender).
        """
        self._agent_id = agent_id
        self._inbox: List[Message] = []
        self._outbox: List[Message] = []
        self._next_id: int = 1

    def _generate_id(self) -> str:
        msg_id = f"msg-{self._next_id}"
        self._next_id += 1
        return msg_id

    def send(
        self,
        to: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageResult:
        """
        Queue a message for delivery.

        Args:
            to: Recipient identifier -- an agent ID, ``"user"``, or a
                channel name.
            content: Message body.
            metadata: Optional extra data to attach.

        Returns:
            MessageResult with the queued Message.
        """
        if not to or not to.strip():
            return MessageResult(
                success=False,
                message="Recipient cannot be empty",
                error="invalid_recipient",
            )
        if not content or not content.strip():
            return MessageResult(
                success=False,
                message="Message content cannot be empty",
                error="invalid_content",
            )

        msg = Message(
            id=self._generate_id(),
            sender=self._agent_id,
            recipient=to.strip(),
            content=content.strip(),
            direction=MessageDirection.OUTBOUND,
            metadata=metadata or {},
        )
        self._outbox.append(msg)

        return MessageResult(
            success=True,
            message=f"Message {msg.id} queued for delivery to '{to}'",
            data=msg,
        )

    def receive(
        self,
        from_filter: Optional[str] = None,
    ) -> MessageResult:
        """
        Retrieve pending inbound messages.

        Args:
            from_filter: If provided, only return messages from this sender.

        Returns:
            MessageResult with matching unread messages.
        """
        pending = [m for m in self._inbox if not m.read]
        if from_filter:
            pending = [m for m in pending if m.sender == from_filter]

        # Mark as read
        for m in pending:
            m.read = True

        return MessageResult(
            success=True,
            message=f"Retrieved {len(pending)} message(s)",
            messages=pending,
        )

    def deliver_inbound(
        self,
        sender: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageResult:
        """
        Deliver an inbound message into this agent's inbox.

        Typically called by the message transport layer, not by user code.

        Args:
            sender: Sender identifier.
            content: Message body.
            metadata: Optional extra data.

        Returns:
            MessageResult with the delivered Message.
        """
        msg = Message(
            id=self._generate_id(),
            sender=sender,
            recipient=self._agent_id,
            content=content.strip(),
            direction=MessageDirection.INBOUND,
            metadata=metadata or {},
        )
        self._inbox.append(msg)

        return MessageResult(
            success=True,
            message=f"Message {msg.id} delivered from '{sender}'",
            data=msg,
        )

    def list_messages(
        self,
        direction: str = "all",
    ) -> MessageResult:
        """
        List sent, received, or all messages.

        Args:
            direction: One of ``"inbound"``, ``"outbound"``, or ``"all"``.

        Returns:
            MessageResult with the matching messages.
        """
        valid_directions = {"inbound", "outbound", "all"}
        if direction not in valid_directions:
            return MessageResult(
                success=False,
                message=f"Invalid direction '{direction}'. "
                        f"Must be one of: {', '.join(sorted(valid_directions))}",
                error="invalid_direction",
            )

        if direction == "inbound":
            msgs = list(self._inbox)
        elif direction == "outbound":
            msgs = list(self._outbox)
        else:
            msgs = list(self._inbox) + list(self._outbox)

        msgs.sort(key=lambda m: m.timestamp, reverse=True)

        return MessageResult(
            success=True,
            message=f"Found {len(msgs)} message(s)",
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# ScheduleCronTool
# ---------------------------------------------------------------------------

class ScheduleCronTool:
    """Schedule recurring tasks using cron-like expressions."""

    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize the scheduler.

        Args:
            storage_path: Optional file path for persisting schedules.
                If ``None``, schedules are kept in memory only.
        """
        self._schedules: Dict[str, Schedule] = {}
        self._storage_path = storage_path

        if storage_path:
            self._load()

    # -- persistence helpers ------------------------------------------------

    def _load(self) -> None:
        """Load schedules from *storage_path* if it exists."""
        if not self._storage_path:
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as fh:
                raw: List[Dict[str, Any]] = json.load(fh)
            for item in raw:
                sched = Schedule(
                    name=item["name"],
                    cron_expr=item["cron_expr"],
                    command=item["command"],
                    description=item.get("description", ""),
                    enabled=item.get("enabled", True),
                )
                self._schedules[sched.name] = sched
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        """Persist current schedules to *storage_path*."""
        if not self._storage_path:
            return
        data = [
            {
                "name": s.name,
                "cron_expr": s.cron_expr,
                "command": s.command,
                "description": s.description,
                "enabled": s.enabled,
            }
            for s in self._schedules.values()
        ]
        with open(self._storage_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    # -- public API ---------------------------------------------------------

    def create(
        self,
        name: str,
        cron_expr: str,
        command: str,
        description: str = "",
    ) -> ScheduleResult:
        """
        Create a new scheduled task.

        Args:
            name: Unique schedule name.
            cron_expr: Cron expression (``minute hour day month weekday``).
            command: Command or action to execute on each trigger.
            description: Human-readable description.

        Returns:
            ScheduleResult with the created Schedule.
        """
        if not name or not name.strip():
            return ScheduleResult(
                success=False,
                message="Schedule name cannot be empty",
                error="invalid_name",
            )

        name = name.strip()

        if name in self._schedules:
            return ScheduleResult(
                success=False,
                message=f"Schedule '{name}' already exists",
                error="duplicate_name",
            )

        if not command or not command.strip():
            return ScheduleResult(
                success=False,
                message="Command cannot be empty",
                error="invalid_command",
            )

        valid, err = _validate_cron(cron_expr)
        if not valid:
            return ScheduleResult(
                success=False,
                message=f"Invalid cron expression: {err}",
                error="invalid_cron",
            )

        sched = Schedule(
            name=name,
            cron_expr=cron_expr.strip(),
            command=command.strip(),
            description=description.strip(),
        )
        self._schedules[name] = sched
        self._save()

        return ScheduleResult(
            success=True,
            message=f"Schedule '{name}' created",
            data=sched,
        )

    def delete(self, name: str) -> ScheduleResult:
        """
        Delete a schedule by name.

        Args:
            name: Schedule name.

        Returns:
            ScheduleResult indicating success or failure.
        """
        if name not in self._schedules:
            return ScheduleResult(
                success=False,
                message=f"Schedule '{name}' not found",
                error="not_found",
            )

        removed = self._schedules.pop(name)
        self._save()

        return ScheduleResult(
            success=True,
            message=f"Schedule '{name}' deleted",
            data=removed,
        )

    def list_schedules(self) -> ScheduleResult:
        """
        List all registered schedules.

        Returns:
            ScheduleResult with list of schedules.
        """
        schedules = sorted(
            self._schedules.values(), key=lambda s: s.created_at
        )
        return ScheduleResult(
            success=True,
            message=f"Found {len(schedules)} schedule(s)",
            schedules=schedules,
        )

    def get_next_run(self, name: str) -> ScheduleResult:
        """
        Compute the next run time for a schedule.

        This performs a simple forward search from ``datetime.now()`` over
        the parsed cron fields (up to ~one year ahead).

        Args:
            name: Schedule name.

        Returns:
            ScheduleResult with ``data.metadata["next_run"]`` set to the
            computed :class:`datetime`, or an error if not found.
        """
        if name not in self._schedules:
            return ScheduleResult(
                success=False,
                message=f"Schedule '{name}' not found",
                error="not_found",
            )

        sched = self._schedules[name]
        parsed = _parse_cron(sched.cron_expr)

        now = datetime.now().replace(second=0, microsecond=0)
        # Brute-force minute-by-minute scan (max ~525600 iterations = 1 year)
        from datetime import timedelta

        candidate = now + timedelta(minutes=1)
        limit = now + timedelta(days=366)

        while candidate <= limit:
            if (
                candidate.minute in parsed["minute"]["values"]
                and candidate.hour in parsed["hour"]["values"]
                and candidate.day in parsed["day"]["values"]
                and candidate.month in parsed["month"]["values"]
                and candidate.weekday() in parsed["weekday"]["values"]
            ):
                sched.metadata["next_run"] = candidate.isoformat()
                return ScheduleResult(
                    success=True,
                    message=f"Next run for '{name}': {candidate.isoformat()}",
                    data=sched,
                )
            candidate += timedelta(minutes=1)

        return ScheduleResult(
            success=False,
            message=f"Could not determine next run for '{name}' within one year",
            error="no_next_run",
        )

    # -- static helpers (exposed for external callers) ----------------------

    @staticmethod
    def parse_cron(expr: str) -> Dict[str, Any]:
        """Public wrapper around :func:`_parse_cron`."""
        return _parse_cron(expr)

    @staticmethod
    def validate_cron(expr: str) -> Tuple[bool, str]:
        """Public wrapper around :func:`_validate_cron`."""
        return _validate_cron(expr)


# ---------------------------------------------------------------------------
# RemoteTriggerTool
# ---------------------------------------------------------------------------

class RemoteTriggerTool:
    """Trigger remote agent execution via webhooks or API."""

    def __init__(self):
        """Initialize with an empty trigger registry."""
        self._triggers: Dict[str, Trigger] = {}

    def create_trigger(
        self,
        name: str,
        url: str,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        payload_template: Optional[str] = None,
    ) -> TriggerResult:
        """
        Register a new remote trigger.

        Args:
            name: Unique trigger name.
            url: Target URL (webhook endpoint).
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            headers: Optional HTTP headers.
            payload_template: Optional :class:`string.Template`-style body.
                Use ``$key`` placeholders that will be substituted from the
                payload dict when the trigger is fired.

        Returns:
            TriggerResult with the created Trigger.
        """
        if not name or not name.strip():
            return TriggerResult(
                success=False,
                message="Trigger name cannot be empty",
                error="invalid_name",
            )

        name = name.strip()

        if name in self._triggers:
            return TriggerResult(
                success=False,
                message=f"Trigger '{name}' already exists",
                error="duplicate_name",
            )

        if not url or not url.strip():
            return TriggerResult(
                success=False,
                message="Trigger URL cannot be empty",
                error="invalid_url",
            )

        method_upper = method.upper()
        try:
            trigger_method = TriggerMethod(method_upper)
        except ValueError:
            valid = ", ".join(m.value for m in TriggerMethod)
            return TriggerResult(
                success=False,
                message=f"Invalid HTTP method '{method}'. Must be one of: {valid}",
                error="invalid_method",
            )

        trigger = Trigger(
            name=name,
            url=url.strip(),
            method=trigger_method,
            headers=headers or {},
            payload_template=payload_template,
        )
        self._triggers[name] = trigger

        return TriggerResult(
            success=True,
            message=f"Trigger '{name}' created",
            data=trigger,
        )

    async def fire(
        self,
        name: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> TriggerResult:
        """
        Fire a registered trigger by sending an HTTP request.

        If the trigger has a ``payload_template``, the *payload* dict values
        are substituted into the template using :class:`string.Template`.
        Otherwise the *payload* dict is serialised as JSON directly.

        Args:
            name: Trigger name.
            payload: Optional data to send.

        Returns:
            TriggerResult with response status and body.
        """
        if name not in self._triggers:
            return TriggerResult(
                success=False,
                message=f"Trigger '{name}' not found",
                error="not_found",
            )

        trigger = self._triggers[name]
        payload = payload or {}

        # Build request body
        body: Optional[bytes] = None
        if trigger.method != TriggerMethod.GET:
            if trigger.payload_template:
                rendered = Template(trigger.payload_template).safe_substitute(
                    payload
                )
                body = rendered.encode("utf-8")
            elif payload:
                body = json.dumps(payload).encode("utf-8")

        # Build headers
        req_headers: Dict[str, str] = dict(trigger.headers)
        if body and "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            trigger.url,
            data=body,
            headers=req_headers,
            method=trigger.method.value,
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status_code = resp.status
                response_body = resp.read().decode("utf-8", errors="replace")

            trigger.last_fired = datetime.now()
            trigger.fire_count += 1

            return TriggerResult(
                success=True,
                message=f"Trigger '{name}' fired successfully (HTTP {status_code})",
                data=trigger,
                response_body=response_body,
                status_code=status_code,
            )
        except urllib.error.HTTPError as exc:
            trigger.last_fired = datetime.now()
            trigger.fire_count += 1
            resp_body = exc.read().decode("utf-8", errors="replace")
            return TriggerResult(
                success=False,
                message=f"Trigger '{name}' returned HTTP {exc.code}",
                data=trigger,
                response_body=resp_body,
                status_code=exc.code,
                error=f"HTTP {exc.code}: {exc.reason}",
            )
        except urllib.error.URLError as exc:
            return TriggerResult(
                success=False,
                message=f"Trigger '{name}' failed: {exc.reason}",
                data=trigger,
                error=str(exc.reason),
            )
        except Exception as exc:
            return TriggerResult(
                success=False,
                message=f"Trigger '{name}' failed unexpectedly",
                data=trigger,
                error=str(exc),
            )

    def list_triggers(self) -> TriggerResult:
        """
        List all registered triggers.

        Returns:
            TriggerResult with list of triggers.
        """
        triggers = sorted(
            self._triggers.values(), key=lambda t: t.created_at
        )
        return TriggerResult(
            success=True,
            message=f"Found {len(triggers)} trigger(s)",
            triggers=triggers,
        )

    def delete_trigger(self, name: str) -> TriggerResult:
        """
        Delete a trigger by name.

        Args:
            name: Trigger name.

        Returns:
            TriggerResult indicating success or failure.
        """
        if name not in self._triggers:
            return TriggerResult(
                success=False,
                message=f"Trigger '{name}' not found",
                error="not_found",
            )

        removed = self._triggers.pop(name)
        return TriggerResult(
            success=True,
            message=f"Trigger '{name}' deleted",
            data=removed,
        )


# ---------------------------------------------------------------------------
# TeamManager (covers TeamCreateTool / TeamDeleteTool)
# ---------------------------------------------------------------------------

class TeamManager:
    """Manage agent teams for collaborative work."""

    def __init__(self):
        """Initialize with an empty team registry."""
        self._teams: Dict[str, Team] = {}

    def create_team(
        self,
        name: str,
        description: str = "",
        members: Optional[List[str]] = None,
        roles: Optional[Dict[str, str]] = None,
        personas: Optional[Dict[str, str]] = None,
    ) -> TeamResult:
        """
        Create a new agent team.

        Args:
            name: Unique team name.
            description: Human-readable description.
            members: Optional list of member IDs to add initially.
            roles: Optional mapping of ``member_id -> role_name`` for
                initial members.  Members not present in *roles* default
                to ``"worker"``.
            personas: Optional mapping of ``member_id -> persona_name``
                for initial members (``"chat"``, ``"coding"``, ``"fin"``).

        Returns:
            TeamResult with the created Team.
        """
        if not name or not name.strip():
            return TeamResult(
                success=False,
                message="Team name cannot be empty",
                error="invalid_name",
            )

        name = name.strip()

        if name in self._teams:
            return TeamResult(
                success=False,
                message=f"Team '{name}' already exists",
                error="duplicate_name",
            )

        roles = roles or {}
        personas = personas or {}
        team_members: Dict[str, TeamMember] = {}

        for mid in (members or []):
            role_str = roles.get(mid, "worker")
            try:
                role = TeamRole(role_str)
            except ValueError:
                valid = ", ".join(r.value for r in TeamRole)
                return TeamResult(
                    success=False,
                    message=f"Invalid role '{role_str}' for member '{mid}'. "
                            f"Must be one of: {valid}",
                    error="invalid_role",
                )
            persona = personas.get(mid)
            if persona is not None and persona not in VALID_PERSONAS:
                return TeamResult(
                    success=False,
                    message=f"Invalid persona '{persona}' for member '{mid}'. "
                            f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}",
                    error="invalid_persona",
                )
            team_members[mid] = TeamMember(
                member_id=mid, role=role, persona=persona,
            )

        team = Team(
            name=name,
            description=description.strip(),
            members=team_members,
        )
        self._teams[name] = team

        return TeamResult(
            success=True,
            message=f"Team '{name}' created with {len(team_members)} member(s)",
            data=team,
        )

    def delete_team(self, name: str) -> TeamResult:
        """
        Delete a team by name.

        Args:
            name: Team name.

        Returns:
            TeamResult indicating success or failure.
        """
        if name not in self._teams:
            return TeamResult(
                success=False,
                message=f"Team '{name}' not found",
                error="not_found",
            )

        removed = self._teams.pop(name)
        return TeamResult(
            success=True,
            message=f"Team '{name}' deleted",
            data=removed,
        )

    def add_member(
        self,
        team_name: str,
        member_id: str,
        role: str = "worker",
        persona: Optional[str] = None,
    ) -> TeamResult:
        """
        Add a member to an existing team.

        Args:
            team_name: Team name.
            member_id: Agent/member identifier to add.
            role: Role string (``leader``, ``worker``, ``reviewer``,
                ``observer``).
            persona: Optional persona (``"chat"``, ``"coding"``, ``"fin"``).

        Returns:
            TeamResult with the updated Team.
        """
        if team_name not in self._teams:
            return TeamResult(
                success=False,
                message=f"Team '{team_name}' not found",
                error="not_found",
            )

        team = self._teams[team_name]

        if member_id in team.members:
            return TeamResult(
                success=False,
                message=f"Member '{member_id}' is already in team '{team_name}'",
                error="duplicate_member",
            )

        try:
            member_role = TeamRole(role)
        except ValueError:
            valid = ", ".join(r.value for r in TeamRole)
            return TeamResult(
                success=False,
                message=f"Invalid role '{role}'. Must be one of: {valid}",
                error="invalid_role",
            )

        if persona is not None and persona not in VALID_PERSONAS:
            return TeamResult(
                success=False,
                message=f"Invalid persona '{persona}'. "
                        f"Must be one of: {', '.join(sorted(VALID_PERSONAS))}",
                error="invalid_persona",
            )

        team.members[member_id] = TeamMember(
            member_id=member_id, role=member_role, persona=persona,
        )

        return TeamResult(
            success=True,
            message=f"Member '{member_id}' added to team '{team_name}' as {role}",
            data=team,
        )

    def remove_member(
        self,
        team_name: str,
        member_id: str,
    ) -> TeamResult:
        """
        Remove a member from a team.

        Args:
            team_name: Team name.
            member_id: Agent/member identifier to remove.

        Returns:
            TeamResult with the updated Team.
        """
        if team_name not in self._teams:
            return TeamResult(
                success=False,
                message=f"Team '{team_name}' not found",
                error="not_found",
            )

        team = self._teams[team_name]

        if member_id not in team.members:
            return TeamResult(
                success=False,
                message=f"Member '{member_id}' is not in team '{team_name}'",
                error="member_not_found",
            )

        del team.members[member_id]

        return TeamResult(
            success=True,
            message=f"Member '{member_id}' removed from team '{team_name}'",
            data=team,
        )

    def list_teams(self) -> TeamResult:
        """
        List all teams.

        Returns:
            TeamResult with list of teams.
        """
        teams = sorted(self._teams.values(), key=lambda t: t.created_at)
        return TeamResult(
            success=True,
            message=f"Found {len(teams)} team(s)",
            teams=teams,
        )

    def get_team(self, name: str) -> TeamResult:
        """
        Get a team by name.

        Args:
            name: Team name.

        Returns:
            TeamResult with the team if found.
        """
        if name not in self._teams:
            return TeamResult(
                success=False,
                message=f"Team '{name}' not found",
                error="not_found",
            )

        return TeamResult(
            success=True,
            message=f"Team '{name}' retrieved",
            data=self._teams[name],
        )


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "MessageDirection",
    "TriggerMethod",
    "TeamRole",
    # Dataclasses
    "Message",
    "MessageResult",
    "Schedule",
    "ScheduleResult",
    "Trigger",
    "TriggerResult",
    "TeamMember",
    "Team",
    "TeamResult",
    # Tools
    "SendMessageTool",
    "ScheduleCronTool",
    "RemoteTriggerTool",
    "TeamManager",
]


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    print("=== Collaboration Tools Test ===\n")

    # -- SendMessageTool --
    msg_tool = SendMessageTool(agent_id="agent-1")
    r = msg_tool.send("agent-2", "Hello from agent-1!")
    print(f"Send: {r.message}")

    msg_tool.deliver_inbound("agent-2", "Reply from agent-2")
    inbox = msg_tool.receive()
    print(f"Receive: {inbox.message} - {[m.content for m in (inbox.messages or [])]}")

    all_msgs = msg_tool.list_messages("all")
    print(f"All messages: {all_msgs.message}")

    # -- ScheduleCronTool --
    cron = ScheduleCronTool()
    cr = cron.create("daily-backup", "0 2 * * *", "backup --full", "Nightly backup")
    print(f"\nSchedule create: {cr.message}")

    valid, err = ScheduleCronTool.validate_cron("*/5 * * * *")
    print(f"Validate '*/5 * * * *': valid={valid}")

    ls = cron.list_schedules()
    print(f"Schedules: {ls.message}")

    dr = cron.delete("daily-backup")
    print(f"Delete: {dr.message}")

    # -- RemoteTriggerTool --
    trigger_tool = RemoteTriggerTool()
    tr = trigger_tool.create_trigger(
        "deploy-hook",
        "https://example.com/deploy",
        method="POST",
        headers={"Authorization": "Bearer token123"},
        payload_template='{"branch": "$branch", "env": "$env"}',
    )
    print(f"\nTrigger create: {tr.message}")

    tl = trigger_tool.list_triggers()
    print(f"Triggers: {tl.message}")

    td = trigger_tool.delete_trigger("deploy-hook")
    print(f"Trigger delete: {td.message}")

    # -- TeamManager --
    teams = TeamManager()
    tc = teams.create_team(
        "backend-squad",
        description="Backend engineering team",
        members=["agent-1", "agent-2"],
        roles={"agent-1": "leader", "agent-2": "worker"},
    )
    print(f"\nTeam create: {tc.message}")

    ta = teams.add_member("backend-squad", "agent-3", role="reviewer")
    print(f"Add member: {ta.message}")

    tg = teams.get_team("backend-squad")
    members = list((tg.data or Team(name="")).members.keys())
    print(f"Team members: {members}")

    tr2 = teams.remove_member("backend-squad", "agent-3")
    print(f"Remove member: {tr2.message}")

    tl2 = teams.list_teams()
    print(f"Teams: {tl2.message}")

    tdel = teams.delete_team("backend-squad")
    print(f"Team delete: {tdel.message}")

    print("\nCollaboration tools test passed!")
