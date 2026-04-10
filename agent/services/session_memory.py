"""
Session Memory Service for NeoMind Agent.

Provides session persistence across restarts — saves and restores
conversation state, tool history, and session metadata.

Created: 2026-04-02
"""

from __future__ import annotations
import json, os, time, hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime

__all__ = ["SessionState", "SessionMemory"]


@dataclass
class SessionState:
    session_id: str
    created_at: str
    updated_at: str
    mode: str  # chat, coding, finance
    messages: List[Dict[str, str]]
    tool_history: List[Dict[str, Any]]
    files_read: List[str]
    working_dir: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionMemory:
    """Persist and restore sessions across restarts."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or os.path.expanduser("~/.neomind/sessions"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current: Optional[SessionState] = None

    def create_session(self, mode: str = "chat", working_dir: str = "") -> SessionState:
        """Generate a new session from timestamp + hash and return it."""
        now = datetime.utcnow()
        ts = now.isoformat(timespec="seconds") + "Z"
        raw = f"{ts}-{os.getpid()}-{time.monotonic_ns()}"
        session_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        state = SessionState(
            session_id=session_id,
            created_at=ts,
            updated_at=ts,
            mode=mode,
            messages=[],
            tool_history=[],
            files_read=[],
            working_dir=working_dir or os.getcwd(),
            metadata={},
        )
        self._current = state
        self.save(state)
        return state

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _session_path(self, session_id: str) -> Path:
        return self.storage_dir / f"session_{session_id}.json"

    def save(self, state: Optional[SessionState] = None) -> bool:
        """Save session state to ``storage_dir/session_{id}.json``.

        Updates the ``updated_at`` timestamp before writing.
        Returns *True* on success, *False* on failure.
        """
        state = state or self._current
        if state is None:
            return False

        state.updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        path = self._session_path(state.session_id)
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(state), indent=2, default=str), encoding="utf-8")
            tmp.replace(path)  # atomic on POSIX
            return True
        except OSError:
            return False

    def restore(self, session_id: Optional[str] = None) -> Optional[SessionState]:
        """Restore a session.

        If *session_id* is given, load that specific session.  Otherwise
        load the most-recently-updated session in the storage directory.
        """
        if session_id is not None:
            path = self._session_path(session_id)
            if not path.exists():
                return None
            return self._load_state(path)

        # Find the most recent session file
        candidates = sorted(
            self.storage_dir.glob("session_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        return self._load_state(candidates[0])

    def _load_state(self, path: Path) -> Optional[SessionState]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = SessionState(**data)
            self._current = state
            return state
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Listing / deletion
    # ------------------------------------------------------------------

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent sessions (id, mode, created_at, message_count).

        Sorted by ``updated_at`` descending.
        """
        results: List[Dict[str, Any]] = []
        for path in self.storage_dir.glob("session_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "session_id": data.get("session_id", ""),
                    "mode": data.get("mode", ""),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", [])),
                })
            except (OSError, json.JSONDecodeError):
                continue

        results.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return results[:limit]

    def delete_session(self, session_id: str) -> bool:
        """Delete the session file for *session_id*. Returns success."""
        path = self._session_path(session_id)
        try:
            path.unlink()
            if self._current and self._current.session_id == session_id:
                self._current = None
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Auto-save helper
    # ------------------------------------------------------------------

    def auto_save(
        self,
        messages: List[Dict],
        tool_history: List[Dict],
        files_read: set,
        mode: str,
        working_dir: str,
    ) -> None:
        """Update the current session and save.

        If no current session exists one is created automatically.
        """
        if self._current is None:
            self.create_session(mode=mode, working_dir=working_dir)

        assert self._current is not None  # guaranteed by create_session
        self._current.messages = list(messages)
        self._current.tool_history = list(tool_history)
        self._current.files_read = sorted(files_read)
        self._current.mode = mode
        self._current.working_dir = working_dir
        self.save()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_old(self, max_sessions: int = 50, max_age_days: int = 30) -> int:
        """Delete sessions exceeding *max_sessions* or *max_age_days*.

        Returns the number of sessions deleted.
        """
        now = time.time()
        max_age_secs = max_age_days * 86400
        deleted = 0

        # Gather (path, mtime) pairs
        entries: List[tuple[Path, float]] = []
        for path in self.storage_dir.glob("session_*.json"):
            try:
                entries.append((path, path.stat().st_mtime))
            except OSError:
                continue

        # Sort newest-first
        entries.sort(key=lambda e: e[1], reverse=True)

        for idx, (path, mtime) in enumerate(entries):
            should_delete = (idx >= max_sessions) or (now - mtime > max_age_secs)
            if should_delete:
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    pass

        return deleted

    @property
    def current(self) -> Optional[SessionState]:
        return self._current
