"""NeoMind State Checkpoint — Restart Recovery

Saves agent state atomically so restarts can resume where they left off.
Uses atomic file replacement (write to .tmp, then rename) to prevent
corruption from crashes mid-write.

No external dependencies — stdlib only.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = Path("/data/neomind/state_checkpoint.json")
CHECKPOINT_HISTORY = Path("/data/neomind/checkpoint_history.jsonl")
MAX_HISTORY = 100  # Keep last 100 checkpoint entries


class Checkpoint:
    """Atomic state checkpoint for restart recovery.

    Usage:
        # Save after each interaction
        cp = Checkpoint()
        cp.save({
            "mode": "fin",
            "last_conversation_id": "abc-123",
            "turn_count": 42,
            "active_tasks": [...],
            "evolution_state": {...},
            "safe_mode": False,
        })

        # Restore after restart
        state = cp.load()
        if state:
            resume_from(state)
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or CHECKPOINT_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, state: Dict[str, Any]) -> bool:
        """Atomically save checkpoint state.

        Writes to .tmp file first, then renames — prevents corruption
        if process is killed mid-write.

        Args:
            state: Dictionary of state to persist

        Returns:
            True if saved successfully
        """
        try:
            # Add metadata
            enriched = {
                **state,
                "_checkpoint_ts": datetime.now(timezone.utc).isoformat(),
                "_checkpoint_version": 1,
            }

            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
            tmp.replace(self.path)  # atomic on POSIX

            # Append to history (for debugging)
            self._append_history(enriched)

            return True
        except Exception as e:
            logger.error(f"Checkpoint save failed: {e}")
            return False

    def load(self) -> Optional[Dict[str, Any]]:
        """Load most recent checkpoint.

        Returns:
            State dictionary, or None if no checkpoint exists
        """
        if not self.path.exists():
            return None

        try:
            data = json.loads(self.path.read_text())
            logger.info(
                f"Checkpoint loaded from {data.get('_checkpoint_ts', 'unknown')}"
            )
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Checkpoint corrupted: {e}")
            # Try to recover from history
            return self._recover_from_history()
        except Exception as e:
            logger.error(f"Checkpoint load failed: {e}")
            return None

    def exists(self) -> bool:
        """Check if a checkpoint exists."""
        return self.path.exists()

    def clear(self):
        """Remove checkpoint (e.g., after clean shutdown)."""
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass

    def get_age_seconds(self) -> Optional[float]:
        """How old is the current checkpoint?"""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            ts = data.get("_checkpoint_ts")
            if ts:
                saved = datetime.fromisoformat(ts)
                return (datetime.now(timezone.utc) - saved).total_seconds()
        except Exception:
            pass
        return None

    def _append_history(self, state: Dict[str, Any]):
        """Append to checkpoint history for debugging."""
        try:
            history_path = CHECKPOINT_HISTORY
            summary = {
                "ts": state.get("_checkpoint_ts"),
                "mode": state.get("mode"),
                "turn_count": state.get("turn_count"),
                "safe_mode": state.get("safe_mode"),
            }
            with open(history_path, "a") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")

            # Trim history if too long
            if history_path.stat().st_size > 100_000:  # ~100KB
                lines = history_path.read_text().splitlines()
                history_path.write_text(
                    "\n".join(lines[-MAX_HISTORY:]) + "\n"
                )
        except Exception:
            pass  # History is best-effort

    def _recover_from_history(self) -> Optional[Dict[str, Any]]:
        """Try to recover state from history if main checkpoint is corrupted."""
        try:
            if not CHECKPOINT_HISTORY.exists():
                return None
            lines = CHECKPOINT_HISTORY.read_text().splitlines()
            if lines:
                last = json.loads(lines[-1])
                logger.info(f"Recovered partial state from history: {last}")
                return last
        except Exception:
            pass
        return None


class DecisionCheckpoint:
    """Checkpoint at decision boundaries for precise crash recovery.

    Research: Round 5 — regular checkpoints only save periodic state.
    Decision checkpoints save state right before critical operations
    (self-edit, model routing, goal decisions) so crash recovery
    returns to the exact decision point.

    Usage:
        dcp = DecisionCheckpoint()

        # Before critical operation
        with dcp.at_decision("self_edit", {"file": "learnings.py", "change": "..."}):
            perform_self_edit()
        # Checkpoint is auto-cleared on success, preserved on crash
    """

    DECISIONS_DIR = Path("/data/neomind/decision_checkpoints")
    MAX_DECISION_CHECKPOINTS = 50

    def __init__(self):
        self.DECISIONS_DIR.mkdir(parents=True, exist_ok=True)

    def save_decision(self, decision_type: str,
                      context: Dict[str, Any],
                      state: Optional[Dict[str, Any]] = None) -> str:
        """Save state at a decision boundary.

        Args:
            decision_type: Type of decision (self_edit, model_routing, goal_update, etc.)
            context: Decision context (what's being decided)
            state: Full agent state to preserve (optional)

        Returns:
            Decision checkpoint ID
        """
        decision_id = f"{decision_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"

        checkpoint_data = {
            "id": decision_id,
            "type": decision_type,
            "context": context,
            "state": state or {},
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": "pending",  # pending → completed | rolled_back
        }

        filepath = self.DECISIONS_DIR / f"{decision_id}.json"
        try:
            tmp = filepath.with_suffix(".tmp")
            tmp.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2))
            tmp.replace(filepath)

            self._cleanup_old()
            logger.debug(f"Decision checkpoint saved: {decision_id}")
            return decision_id
        except Exception as e:
            logger.error(f"Failed to save decision checkpoint: {e}")
            return ""

    def complete_decision(self, decision_id: str,
                          outcome: str = "completed",
                          result: Optional[Dict] = None) -> bool:
        """Mark a decision as completed (success or failure).

        Args:
            decision_id: The checkpoint ID
            outcome: Result (completed, rolled_back, failed)
            result: Optional result data

        Returns:
            True if updated
        """
        filepath = self.DECISIONS_DIR / f"{decision_id}.json"
        if not filepath.exists():
            return False

        try:
            data = json.loads(filepath.read_text())
            data["status"] = outcome
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            if result:
                data["result"] = result

            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return True
        except Exception as e:
            logger.error(f"Failed to complete decision checkpoint: {e}")
            return False

    def get_pending_decisions(self) -> List[Dict[str, Any]]:
        """Get all pending (incomplete) decision checkpoints.

        After a crash, these represent decisions that were interrupted.
        """
        pending = []
        try:
            for f in sorted(self.DECISIONS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    if data.get("status") == "pending":
                        pending.append(data)
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            pass
        return pending

    def recover_latest(self, decision_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Recover the most recent pending decision checkpoint.

        Args:
            decision_type: Optional filter by decision type

        Returns:
            Decision checkpoint data, or None
        """
        pending = self.get_pending_decisions()
        if decision_type:
            pending = [p for p in pending if p.get("type") == decision_type]

        if pending:
            latest = max(pending, key=lambda x: x.get("ts", ""))
            logger.info(f"Recovered decision checkpoint: {latest.get('id')}")
            return latest
        return None

    def at_decision(self, decision_type: str, context: Dict[str, Any]):
        """Context manager for decision boundary checkpointing.

        Usage:
            with dcp.at_decision("self_edit", {"file": "x.py"}):
                do_edit()
        """
        return _DecisionContext(self, decision_type, context)

    def get_history(self, limit: int = 20) -> List[Dict]:
        """Get recent decision checkpoint history."""
        history = []
        try:
            files = sorted(self.DECISIONS_DIR.glob("*.json"), reverse=True)
            for f in files[:limit]:
                try:
                    data = json.loads(f.read_text())
                    history.append({
                        "id": data.get("id"),
                        "type": data.get("type"),
                        "status": data.get("status"),
                        "ts": data.get("ts"),
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return history

    def _cleanup_old(self):
        """Remove old completed checkpoints, keep last MAX_DECISION_CHECKPOINTS."""
        try:
            files = sorted(self.DECISIONS_DIR.glob("*.json"))
            if len(files) > self.MAX_DECISION_CHECKPOINTS:
                for f in files[:-self.MAX_DECISION_CHECKPOINTS]:
                    try:
                        data = json.loads(f.read_text())
                        if data.get("status") != "pending":
                            f.unlink()
                    except Exception:
                        pass
        except Exception:
            pass


class _DecisionContext:
    """Context manager for decision checkpointing."""

    def __init__(self, dcp: DecisionCheckpoint, decision_type: str, context: Dict):
        self.dcp = dcp
        self.decision_type = decision_type
        self.context = context
        self.decision_id = ""

    def __enter__(self):
        self.decision_id = self.dcp.save_decision(self.decision_type, self.context)
        return self.decision_id

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.dcp.complete_decision(self.decision_id, "completed")
        else:
            self.dcp.complete_decision(self.decision_id, "failed",
                                       {"error": str(exc_val)})
        return False  # Don't suppress exceptions


# ── Convenience functions ──────────────────────────────────


_default_checkpoint = None


def get_checkpoint() -> Checkpoint:
    """Get the singleton Checkpoint instance."""
    global _default_checkpoint
    if _default_checkpoint is None:
        _default_checkpoint = Checkpoint()
    return _default_checkpoint


def save_checkpoint(state: Dict[str, Any]) -> bool:
    """Convenience: save checkpoint state."""
    return get_checkpoint().save(state)


def load_checkpoint() -> Optional[Dict[str, Any]]:
    """Convenience: load checkpoint state."""
    return get_checkpoint().load()


_default_decision_checkpoint = None


def get_decision_checkpoint() -> DecisionCheckpoint:
    """Get the singleton DecisionCheckpoint instance."""
    global _default_decision_checkpoint
    if _default_decision_checkpoint is None:
        _default_decision_checkpoint = DecisionCheckpoint()
    return _default_decision_checkpoint
