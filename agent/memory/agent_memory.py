"""
Agent Memory — Per-agent persistent knowledge with three scopes.

Distinct from SharedMemory (cross-personality) and AutoDream (consolidation).
Agent Memory binds knowledge to specific agent definitions.

Three scopes:
  - user: Cross-project reusable agent knowledge (~/.neomind/agent-memory/)
  - project: Shared within current project (.neomind/agent-memory/)
  - local: Machine/workspace-specific (.neomind/agent-memory-local/)

Snapshot system allows distributing agent memory as a portable asset.
"""

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AgentMemory:
    """Per-agent persistent memory with scoped storage.

    Usage:
        mem = AgentMemory(agent_type="researcher")
        mem.write("findings.md", "# Key Findings\n...")
        content = mem.read("findings.md")
        all_files = mem.list_files()
    """

    def __init__(self, agent_type: str, project_dir: str = None):
        self.agent_type = agent_type
        self._project_dir = project_dir or os.getcwd()

        # Three scope directories
        self._user_dir = Path(os.path.expanduser(f'~/.neomind/agent-memory/{agent_type}'))
        self._project_dir_path = Path(self._project_dir) / '.neomind' / 'agent-memory' / agent_type
        self._local_dir = Path(self._project_dir) / '.neomind' / 'agent-memory-local' / agent_type

    def _ensure_dir(self, scope: str) -> Path:
        """Get directory for scope, creating if needed."""
        dirs = {
            'user': self._user_dir,
            'project': self._project_dir_path,
            'local': self._local_dir,
        }
        d = dirs.get(scope, self._user_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, filename: str, content: str, scope: str = 'project'):
        """Write a memory file to the specified scope."""
        d = self._ensure_dir(scope)
        filepath = d / filename
        filepath.write_text(content, encoding='utf-8')
        logger.debug(f"Agent memory written: {filepath}")

    def read(self, filename: str, scope: str = None) -> Optional[str]:
        """Read a memory file. If scope is None, searches all scopes."""
        if scope:
            filepath = self._ensure_dir(scope) / filename
            if filepath.exists():
                return filepath.read_text(encoding='utf-8')
            return None

        # Search all scopes: local → project → user
        for s in ('local', 'project', 'user'):
            d = self._ensure_dir(s)
            filepath = d / filename
            if filepath.exists():
                return filepath.read_text(encoding='utf-8')
        return None

    def list_files(self, scope: str = None) -> List[Dict[str, Any]]:
        """List memory files. If scope is None, list all scopes."""
        files = []
        scopes = [scope] if scope else ['user', 'project', 'local']
        for s in scopes:
            d = self._ensure_dir(s)
            for f in d.iterdir():
                if f.is_file() and f.suffix == '.md':
                    files.append({
                        'name': f.name,
                        'scope': s,
                        'path': str(f),
                        'size': f.stat().st_size,
                        'mtime': f.stat().st_mtime,
                    })
        return sorted(files, key=lambda x: x['mtime'], reverse=True)

    def delete(self, filename: str, scope: str = 'project'):
        """Delete a memory file."""
        d = self._ensure_dir(scope)
        filepath = d / filename
        if filepath.exists():
            filepath.unlink()

    def get_context_injection(self) -> str:
        """Get all agent memory content for system prompt injection."""
        files = self.list_files()
        if not files:
            return ""
        parts = [f"\n## Agent Memory ({self.agent_type})\n"]
        for f in files[:10]:  # Max 10 files
            content = self.read(f['name'], f['scope'])
            if content:
                parts.append(f"### {f['name']} ({f['scope']})")
                parts.append(content[:2000])
                parts.append("")
        return "\n".join(parts)

    # ── Snapshot System ────────────────────────────────────────

    def create_snapshot(self, snapshot_dir: str = None) -> str:
        """Create a distributable snapshot of agent memory.

        Copies all memory files to a snapshot directory.
        Returns the snapshot path.
        """
        snap_dir = Path(snapshot_dir or os.path.join(
            self._project_dir, '.neomind', 'agent-memory-snapshots', self.agent_type
        ))
        snap_dir.mkdir(parents=True, exist_ok=True)

        # Copy all files from all scopes
        for f in self.list_files():
            src = Path(f['path'])
            dst = snap_dir / f"{f['scope']}_{f['name']}"
            shutil.copy2(str(src), str(dst))

        # Write sync metadata
        meta = {
            'agent_type': self.agent_type,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'file_count': len(self.list_files()),
        }
        (snap_dir / '.snapshot-synced.json').write_text(json.dumps(meta, indent=2))

        logger.info(f"Agent memory snapshot created: {snap_dir}")
        return str(snap_dir)

    def restore_snapshot(self, snapshot_dir: str):
        """Restore agent memory from a snapshot.

        Only initializes if the local directory is empty (won't overwrite).
        """
        snap_dir = Path(snapshot_dir)
        if not snap_dir.exists():
            logger.warning(f"Snapshot directory not found: {snapshot_dir}")
            return

        # Only restore if local is empty
        local_files = self.list_files(scope='project')
        if local_files:
            logger.info("Agent memory not empty — skipping snapshot restore")
            return

        # Restore files
        for f in snap_dir.iterdir():
            if f.is_file() and f.suffix == '.md':
                name = f.name
                # Strip scope prefix if present
                for prefix in ('user_', 'project_', 'local_'):
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                        break
                dst = self._ensure_dir('project') / name
                shutil.copy2(str(f), str(dst))

        logger.info(f"Agent memory restored from snapshot: {snapshot_dir}")
