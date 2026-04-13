"""
Persistent per-agent conversation log for the fleet multi-agent view.

Each sub-agent in a running fleet gets its own ``AgentTranscript`` ——
an append-only list of ``AgentTurn`` rows backed by a JSONL file on
disk. When the user focuses on that agent in the multi-agent terminal
view, the UI renders this transcript directly as the message pane
contents. Switching focus away leaves the transcript intact; switching
back re-renders from the same in-memory list with no redraw loss.

Design principles (all independent of any specific prior art):

  1. **Each agent's transcript is its own file.** Multiple fleet
     workers writing to separate files avoids cross-agent lock
     contention and makes manual inspection / grep trivial.

  2. **JSONL is the on-disk format.** One turn per line, UTF-8, no
     atomic rewrites needed — appends are naturally atomic on POSIX
     for small payloads (< PIPE_BUF ≈ 4 KB per write). A turn larger
     than that would be rare and the append still lands as a full
     line because we write once with ``\\n`` terminator.

  3. **Lazy disk load.** An AgentTranscript starts empty in memory.
     The first call to ``ensure_loaded()`` (typically when the user
     first focuses on that agent) reads the file into the in-memory
     turns list. Subsequent appends hit memory AND file in lockstep
     so reloading from disk after an in-memory accumulation still
     produces the correct sequence.

  4. **In-memory stays warm once loaded.** Unlike a ring buffer,
     memory is not capped — the whole conversation stays in-memory
     as long as the FleetSession is alive. This is what makes "switch
     back to agent X and see exactly the same conversation as before"
     work. For very long-running fleets this could grow, so we expose
     ``mark_accessed()`` + ``is_stale()`` so the FleetSession can
     optionally trim agents that haven't been viewed for a while.

  5. **Persona-agnostic.** Zero persona string literals. The only
     thing an AgentTranscript knows about an agent is its name.

Contract: plans/2026-04-12_phase4_fleet_llm_loop.md §11 (Phase 5
scope expansion per 2026-04-12 user directives).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "AgentTurn",
    "AgentTranscript",
    "TranscriptError",
    "transcript_path_for",
]


# Allowed role values in AgentTurn. Using Literal here would be
# prettier but we want to accept free-form roles from future code
# without schema churn, so validate as a set instead.
_ALLOWED_ROLES = frozenset({
    "user",       # a user-visible instruction that was sent to this agent
    "assistant",  # the agent's LLM reply (may be partial for streaming)
    "system",     # lifecycle notes (spawned, shut down, fail-fast gate hit)
    "tool",       # a tool call result (used when agentic loop lands)
    "meta",       # internal metadata (parse_layer info, cost, timing)
})

# Agent name validation — matches the MemberConfig naming rule, so a
# transcript file can never collide with something like "../foo" from
# a malformed config.
_AGENT_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


class TranscriptError(ValueError):
    """Raised on invalid inputs (bad agent name, bad role, IO failure)."""


def _now_iso() -> str:
    """UTC ISO8601 with microsecond precision — stable sort key."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def transcript_path_for(
    project_id: str, agent_name: str, base_dir: Optional[str] = None,
) -> Path:
    """Resolve the JSONL path for a given project+agent.

    Lives under ``<base_dir or ~/.neomind>/teams/<project_id>/
    transcripts/<agent_name>.jsonl``. The parent dirs are NOT created
    here — AgentTranscript.persist_append does that on first write so
    we don't touch disk in the constructor.
    """
    if not _AGENT_NAME_RE.match(agent_name):
        raise TranscriptError(
            f"invalid agent name {agent_name!r} "
            f"(must match ^[a-zA-Z][a-zA-Z0-9_-]*$)"
        )
    import os
    root = Path(base_dir).expanduser() if base_dir else Path.home() / ".neomind"
    return root / "teams" / project_id / "transcripts" / f"{agent_name}.jsonl"


@dataclass
class AgentTurn:
    """One row in an agent's conversation log.

    Fields:
      ts       — UTC ISO8601 timestamp, set at construction
      role     — one of _ALLOWED_ROLES
      content  — the human-readable text (prompt / response / note)
      metadata — optional free-form dict (model name, duration_s,
                 task_id, token counts, etc.)

    ``to_json`` / ``from_json`` handle the JSONL serialization round-
    trip. Equality compares all fields so repeated loads produce the
    same objects (matters for test reproducibility).
    """

    role: str
    content: str
    ts: str = field(default_factory=_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.role not in _ALLOWED_ROLES:
            raise TranscriptError(
                f"invalid role {self.role!r}; must be one of "
                f"{sorted(_ALLOWED_ROLES)}"
            )
        if not isinstance(self.content, str):
            raise TranscriptError(
                f"content must be a string, got {type(self.content).__name__}"
            )
        if not isinstance(self.metadata, dict):
            raise TranscriptError(
                f"metadata must be a dict, got {type(self.metadata).__name__}"
            )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "AgentTurn":
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptError(f"corrupt JSONL line: {exc}") from exc
        if not isinstance(data, dict):
            raise TranscriptError(f"JSONL line must decode to object, got {type(data)}")
        return cls(
            role=data.get("role", "system"),
            content=data.get("content", ""),
            ts=data.get("ts", _now_iso()),
            metadata=data.get("metadata") or {},
        )


class AgentTranscript:
    """Append-only conversation log for one sub-agent in a fleet.

    Thread-safety: an internal ``threading.Lock`` guards the in-memory
    turns list and disk appends. Multiple fleet workers writing to
    different agents' transcripts don't contend (each has its own
    instance). A single agent receiving concurrent writes from
    (a) the CLI dispatch thread adding a user turn and (b) the
    background worker thread appending llm_call_end events DOES
    contend, and the lock serializes them cleanly.

    Usage:
        t = AgentTranscript("fin-core", "fin-rt")
        t.ensure_loaded()  # lazy disk read; no-op if already loaded
        t.append_turn(AgentTurn(role="user", content="analyze AAPL"))
        t.append_turn(AgentTurn(role="assistant", content="hold/7"))
        for turn in t.turns:
            print(turn.content)
    """

    def __init__(
        self,
        project_id: str,
        agent_name: str,
        base_dir: Optional[str] = None,
        evict_after_seconds: float = 900.0,  # 15 minutes
    ):
        self.project_id = project_id
        self.agent_name = agent_name
        self._path = transcript_path_for(project_id, agent_name, base_dir=base_dir)
        self._turns: List[AgentTurn] = []
        self._loaded_from_disk = False
        self._lock = threading.Lock()
        self._last_accessed = time.monotonic()
        self._evict_after_seconds = evict_after_seconds

    # ── Path / state inspection ────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def loaded(self) -> bool:
        return self._loaded_from_disk

    @property
    def turns(self) -> List[AgentTurn]:
        """Read-only view of the in-memory turns list.

        This deliberately returns the internal list, not a copy, so
        the renderer doesn't have to deep-copy on every frame. Do
        not mutate it from outside the class.
        """
        return self._turns

    def turn_count(self) -> int:
        with self._lock:
            return len(self._turns)

    def mark_accessed(self) -> None:
        """Refresh the last-accessed timestamp.

        Called by the UI every time this transcript is rendered or
        appended to. Used by ``is_stale`` for optional eviction.
        """
        self._last_accessed = time.monotonic()

    def is_stale(self) -> bool:
        """True when nothing has touched the transcript recently.

        The FleetSession may drop stale transcripts' in-memory turns
        to bound memory for very long-running fleets. Reloading is
        cheap because the disk copy is complete.
        """
        return (
            time.monotonic() - self._last_accessed > self._evict_after_seconds
        )

    # ── Disk I/O ──────────────────────────────────────────────────

    def ensure_loaded(self) -> None:
        """Load all existing turns from disk into memory once.

        Subsequent calls are no-ops. Safe to call from any thread.
        If the file doesn't exist yet, the transcript is considered
        loaded (empty). Corrupt lines are skipped with a warning —
        better to show a partial transcript than crash the UI.
        """
        with self._lock:
            if self._loaded_from_disk:
                return
            if not self._path.exists():
                self._loaded_from_disk = True
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        try:
                            self._turns.append(AgentTurn.from_json(line))
                        except TranscriptError as exc:
                            logger.warning(
                                "transcript %s: skipping corrupt line %d: %s",
                                self._path, i + 1, exc,
                            )
            except OSError as exc:
                logger.warning("transcript %s: read failed: %s", self._path, exc)
            self._loaded_from_disk = True

    def append_turn(self, turn: AgentTurn) -> None:
        """Append a turn to memory AND disk atomically w.r.t other
        appends on the same transcript.

        Writes the JSONL line in one open/write call with ``\\n``
        terminator so it lands as a complete line even under concurrent
        writers (POSIX guarantees this for writes smaller than
        PIPE_BUF ≈ 4 KB).
        """
        if not isinstance(turn, AgentTurn):
            raise TranscriptError(
                f"append_turn expects AgentTurn, got {type(turn).__name__}"
            )
        with self._lock:
            # Make sure in-memory reflects disk first; otherwise a
            # race between load and append could drop earlier turns.
            if not self._loaded_from_disk:
                self._load_from_disk_locked()
            self._turns.append(turn)
            self._last_accessed = time.monotonic()
            self._append_line_to_disk_locked(turn.to_json())

    def append_turns(self, turns: List[AgentTurn]) -> None:
        """Append many turns in one lock acquisition."""
        if not turns:
            return
        with self._lock:
            if not self._loaded_from_disk:
                self._load_from_disk_locked()
            for t in turns:
                if not isinstance(t, AgentTurn):
                    raise TranscriptError(
                        f"append_turns expects AgentTurn, got {type(t).__name__}"
                    )
                self._turns.append(t)
                self._append_line_to_disk_locked(t.to_json())
            self._last_accessed = time.monotonic()

    def evict_memory(self) -> None:
        """Drop in-memory turns but keep the file on disk.

        Reloading is triggered lazily on the next ensure_loaded call.
        Used by FleetSession when many agents accumulate stale
        transcripts and we want to free memory without losing data.
        """
        with self._lock:
            self._turns = []
            self._loaded_from_disk = False

    # ── Internal helpers (must be called with self._lock held) ─────

    def _load_from_disk_locked(self) -> None:
        if self._loaded_from_disk:
            return
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        line = line.rstrip("\n")
                        if not line:
                            continue
                        try:
                            self._turns.append(AgentTurn.from_json(line))
                        except TranscriptError as exc:
                            logger.warning(
                                "transcript %s: skipping corrupt line %d: %s",
                                self._path, i + 1, exc,
                            )
            except OSError as exc:
                logger.warning("transcript %s: read failed: %s", self._path, exc)
        self._loaded_from_disk = True

    def _append_line_to_disk_locked(self, line: str) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            # Intentionally does not raise — a disk write failure
            # should NOT crash the fleet worker. Log it and move on.
            logger.error(
                "transcript %s: append failed (in-memory only): %s",
                self._path, exc,
            )
