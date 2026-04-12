"""
Session Storage — Append-only JSONL event log for session persistence.

Replaces simple JSON snapshot with JSONL (JSON Lines) append-only format:
- Each message is one JSON line (append-only, never rewritten)
- Metadata entries (title, mode, tag) re-appended to tail for fast listing
- Lite reader reads only head/tail for session lists (65KB window)
- Subagent sidechains stored in separate files
- Interrupt detection on resume (incomplete turn gets continuation prompt)

Format: One JSON object per line, each with:
  {type, role?, content?, metadata?, timestamp, uuid}
"""

import os
import json
import time
import uuid
import hashlib
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

LITE_WINDOW = 65 * 1024  # 65KB for head/tail reading
METADATA_REAPPEND_INTERVAL = 50  # Re-append metadata every N entries


class SessionWriter:
    """Append-only JSONL session writer.

    Usage:
        writer = SessionWriter(session_id="abc123")
        writer.append_message("user", "Hello")
        writer.append_message("assistant", "Hi there")
        writer.append_metadata("title", "Bug fix session")
        writer.flush()
    """

    def __init__(self, session_id: str = None,
                 sessions_dir: str = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self._dir = Path(sessions_dir or os.path.expanduser('~/.neomind/transcripts'))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._filepath = self._dir / f"{self.session_id}.jsonl"
        self._buffer: List[str] = []
        self._entry_count = 0
        self._metadata: Dict[str, Any] = {}
        self._uuid_set: set = set()  # Deduplication

    def append_message(self, role: str, content: Any, msg_uuid: str = None):
        """Append a message entry."""
        msg_uuid = msg_uuid or str(uuid.uuid4())

        # Deduplication
        if msg_uuid in self._uuid_set:
            return
        self._uuid_set.add(msg_uuid)

        entry = {
            'type': 'message',
            'role': role,
            'content': content,
            'timestamp': time.time(),
            'uuid': msg_uuid,
        }
        self._buffer.append(json.dumps(entry, ensure_ascii=False))
        self._entry_count += 1

        # Periodic metadata re-append
        if self._entry_count % METADATA_REAPPEND_INTERVAL == 0:
            self._reappend_metadata()

    def append_metadata(self, key: str, value: Any):
        """Append a metadata entry (title, mode, tag, etc.)."""
        self._metadata[key] = value
        entry = {
            'type': 'metadata',
            'key': key,
            'value': value,
            'timestamp': time.time(),
        }
        self._buffer.append(json.dumps(entry, ensure_ascii=False))

    def append_tool_use(self, tool_name: str, tool_input: Dict,
                        tool_result: Any, success: bool):
        """Append a tool use/result pair."""
        entry = {
            'type': 'tool',
            'tool_name': tool_name,
            'input': tool_input,
            'result': str(tool_result)[:5000],
            'success': success,
            'timestamp': time.time(),
            'uuid': str(uuid.uuid4()),
        }
        self._buffer.append(json.dumps(entry, ensure_ascii=False))

    def _reappend_metadata(self):
        """Re-append all metadata to the tail of the file.

        This ensures session lists can read metadata from the tail window
        without parsing the entire file.
        """
        for key, value in self._metadata.items():
            entry = {
                'type': 'metadata',
                'key': key,
                'value': value,
                'timestamp': time.time(),
                '_reappended': True,
            }
            self._buffer.append(json.dumps(entry, ensure_ascii=False))

    def flush(self):
        """Write buffered entries to disk."""
        if not self._buffer:
            return
        try:
            with open(self._filepath, 'a', encoding='utf-8') as f:
                for line in self._buffer:
                    f.write(line + '\n')
            # Set owner-only permissions
            os.chmod(self._filepath, 0o600)
            self._buffer.clear()
        except Exception as e:
            logger.error(f"Session flush failed: {e}")

    def close(self):
        """Flush and finalize the session."""
        self._reappend_metadata()
        self.flush()

    @property
    def filepath(self) -> str:
        return str(self._filepath)


class SessionReader:
    """Read session transcripts with optimized loading.

    Supports:
    - Lite reading (head/tail only, 65KB window)
    - Full loading with message reconstruction
    - Interrupt detection
    """

    def __init__(self, sessions_dir: str = None):
        self._dir = Path(sessions_dir or os.path.expanduser('~/.neomind/transcripts'))

    def list_sessions_lite(self, max_count: int = 20) -> List[Dict[str, Any]]:
        """List sessions using lite reader (reads only head/tail).

        Returns minimal metadata without loading full transcripts.
        """
        if not self._dir.exists():
            return []

        sessions = []
        files = sorted(self._dir.glob('*.jsonl'), key=lambda f: f.stat().st_mtime, reverse=True)

        for f in files[:max_count]:
            try:
                meta = self._read_lite(f)
                if meta:
                    sessions.append(meta)
            except Exception:
                pass

        return sessions

    def _read_lite(self, filepath: Path) -> Optional[Dict[str, Any]]:
        """Read only head and tail of a JSONL file for quick metadata."""
        size = filepath.stat().st_size
        session_id = filepath.stem

        result = {
            'session_id': session_id,
            'file': str(filepath),
            'size': size,
            'mtime': filepath.stat().st_mtime,
        }

        with open(filepath, 'r', encoding='utf-8') as f:
            # Read first line (usually first user message)
            first_line = f.readline().strip()
            if first_line:
                try:
                    first = json.loads(first_line)
                    if first.get('type') == 'message' and first.get('role') == 'user':
                        content = str(first.get('content', ''))[:100]
                        result['first_message'] = content
                except json.JSONDecodeError:
                    pass

            # Read tail (last LITE_WINDOW bytes) for metadata
            if size > LITE_WINDOW:
                f.seek(size - LITE_WINDOW)
                f.readline()  # Skip partial line
            else:
                f.seek(0)

            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get('type') == 'metadata':
                        result[entry['key']] = entry['value']
                except json.JSONDecodeError:
                    pass

        return result

    def load_full(self, session_id: str) -> Tuple[List[Dict], Dict[str, Any]]:
        """Load a full session transcript.

        Returns (messages, metadata).
        """
        filepath = self._dir / f"{session_id}.jsonl"
        if not filepath.exists():
            return [], {}

        messages = []
        metadata = {}
        seen_uuids = set()

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_type = entry.get('type')

                    if entry_type == 'message':
                        uid = entry.get('uuid')
                        if uid and uid in seen_uuids:
                            continue  # Dedup
                        if uid:
                            seen_uuids.add(uid)
                        messages.append({
                            'role': entry.get('role', 'user'),
                            'content': entry.get('content', ''),
                        })
                    elif entry_type == 'metadata':
                        metadata[entry['key']] = entry['value']
                    elif entry_type == 'tool':
                        pass  # Tool entries are for audit, not conversation
                except json.JSONDecodeError:
                    pass

        return messages, metadata

    def detect_interrupt(self, messages: List[Dict]) -> bool:
        """Detect if the last turn was interrupted (incomplete).

        An incomplete turn is one where the last message is from the user
        (assistant never responded) or a tool_use without a tool_result.
        """
        if not messages:
            return False
        last = messages[-1]
        # If last message is from user → assistant never responded
        if last.get('role') == 'user':
            return True
        # If last message is assistant with tool_use but no following tool_result
        if last.get('role') == 'assistant':
            content = last.get('content', '')
            if isinstance(content, list):
                has_tool_use = any(
                    isinstance(b, dict) and b.get('type') == 'tool_use'
                    for b in content
                )
                if has_tool_use:
                    return True  # Tool was called but never completed
        return False

    def get_continuation_prompt(self) -> str:
        """Generate a continuation prompt for an interrupted session."""
        return (
            "The previous session was interrupted. Please review the context "
            "above and continue where you left off. If you were in the middle "
            "of executing tools, summarize what was done and what remains."
        )


class SubagentSidechain:
    """Separate JSONL file for subagent transcripts.

    Stored under {session_id}/subagents/{agent_id}.jsonl.
    Allows duplicate UUIDs (preserves fork inheritance context).
    """

    def __init__(self, session_id: str, agent_id: str,
                 sessions_dir: str = None):
        base = Path(sessions_dir or os.path.expanduser('~/.neomind/transcripts'))
        self._dir = base / session_id / 'subagents'
        self._dir.mkdir(parents=True, exist_ok=True)
        self._filepath = self._dir / f"{agent_id}.jsonl"
        self._buffer: List[str] = []

    def append(self, role: str, content: Any):
        """Append a message to the sidechain (no dedup)."""
        entry = {
            'type': 'message',
            'role': role,
            'content': content,
            'timestamp': time.time(),
        }
        self._buffer.append(json.dumps(entry, ensure_ascii=False))

    def flush(self):
        """Write buffer to disk."""
        if self._buffer:
            with open(self._filepath, 'a', encoding='utf-8') as f:
                for line in self._buffer:
                    f.write(line + '\n')
            self._buffer.clear()

    def load(self) -> List[Dict]:
        """Load all messages from sidechain."""
        messages = []
        if self._filepath.exists():
            with open(self._filepath) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') == 'message':
                            messages.append({
                                'role': entry.get('role'),
                                'content': entry.get('content'),
                            })
                    except json.JSONDecodeError:
                        pass
        return messages
