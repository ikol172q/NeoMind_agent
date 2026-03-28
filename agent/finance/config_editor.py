"""ConfigEditor — lets NeoMind edit its own prompts and config at runtime.

Architecture:
    Default config:  /app/agent/config/{mode}.yaml     (baked in image, read-only)
    User overrides:  /data/neomind/config_overrides.yaml (persistent volume, writable)

The override file is a flat YAML dict keyed by mode, e.g.:

    fin:
      extra_system_prompt: |
        额外的 prompt 指令...
      search_triggers:
        - 半导体
        - AI芯片
    chat:
      extra_system_prompt: |
        ...

At runtime, the bot merges overrides on top of defaults. The /tune command
lets the user modify overrides via natural language, and NeoMind generates
the appropriate YAML edits.
"""

import os
import yaml
import copy
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Persistent directory inside the Docker volume
_DATA_DIR = Path(os.environ.get("NEOMIND_DATA_DIR", "/data/neomind"))
_OVERRIDES_FILE = _DATA_DIR / "config_overrides.yaml"
_HISTORY_DIR = _DATA_DIR / "config_history"


class ConfigEditor:
    """Read/write NeoMind's runtime config overrides.

    Overrides are stored in a single YAML file on a persistent Docker volume,
    so they survive container restarts and image rebuilds.
    """

    def __init__(self, overrides_path: Optional[Path] = None):
        self.path = overrides_path or _OVERRIDES_FILE
        self.history_dir = _HISTORY_DIR
        self._cache: Optional[Dict] = None

    # ── Read ────────────────────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        """Load overrides from disk. Returns empty dict if file doesn't exist."""
        if self._cache is not None:
            return self._cache
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._cache = data
                return data
        except Exception as e:
            logger.warning(f"Failed to load config overrides: {e}")
        self._cache = {}
        return {}

    def get_mode_overrides(self, mode: str) -> Dict[str, Any]:
        """Get overrides for a specific mode (fin/chat/coding)."""
        return self.load().get(mode, {})

    def get_extra_prompt(self, mode: str) -> str:
        """Get extra system prompt text for a mode. Empty string if none."""
        return self.get_mode_overrides(mode).get("extra_system_prompt", "")

    def get_extra_search_triggers(self, mode: str = "") -> List[str]:
        """Get extra search trigger keywords. Merges all modes if mode is empty."""
        overrides = self.load()
        triggers = []
        modes = [mode] if mode else list(overrides.keys())
        for m in modes:
            mode_data = overrides.get(m, {})
            triggers.extend(mode_data.get("search_triggers", []))
        return triggers

    def get_setting(self, mode: str, key: str, default=None):
        """Get any override setting by key."""
        return self.get_mode_overrides(mode).get(key, default)

    # ── Write ───────────────────────────────────────────────────────

    def save(self, data: Dict[str, Any]):
        """Save overrides to disk, creating parent dirs if needed."""
        # Save backup first
        self._save_history()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False, width=120)
        self._cache = data
        logger.info(f"Config overrides saved to {self.path}")

    def update_mode(self, mode: str, updates: Dict[str, Any]):
        """Merge updates into a mode's overrides."""
        data = self.load()
        if mode not in data:
            data[mode] = {}
        data[mode].update(updates)
        self.save(data)

    def set_extra_prompt(self, mode: str, prompt_text: str):
        """Set or replace the extra system prompt for a mode."""
        self.update_mode(mode, {"extra_system_prompt": prompt_text})

    def append_to_prompt(self, mode: str, text: str):
        """Append text to existing extra prompt (doesn't replace)."""
        existing = self.get_extra_prompt(mode)
        new_prompt = (existing + "\n" + text).strip() if existing else text
        self.set_extra_prompt(mode, new_prompt)

    def add_search_triggers(self, triggers: List[str], mode: str = "fin"):
        """Add new search trigger keywords (deduplicates)."""
        data = self.load()
        if mode not in data:
            data[mode] = {}
        existing = set(data[mode].get("search_triggers", []))
        existing.update(triggers)
        data[mode]["search_triggers"] = sorted(existing)
        self.save(data)

    def remove_search_triggers(self, triggers: List[str], mode: str = "fin"):
        """Remove search trigger keywords."""
        data = self.load()
        if mode not in data:
            return
        existing = data[mode].get("search_triggers", [])
        data[mode]["search_triggers"] = [t for t in existing if t not in triggers]
        self.save(data)

    def set_setting(self, mode: str, key: str, value):
        """Set any arbitrary setting."""
        self.update_mode(mode, {key: value})

    def reset_mode(self, mode: str):
        """Reset all overrides for a mode back to defaults."""
        data = self.load()
        if mode in data:
            del data[mode]
            self.save(data)

    def reset_all(self):
        """Reset ALL overrides (back to pure defaults)."""
        self.save({})

    # ── History / Undo ──────────────────────────────────────────────

    def _save_history(self):
        """Save a timestamped backup before any write."""
        if not self.path.exists():
            return
        try:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = self.history_dir / f"overrides_{ts}.yaml"
            import shutil
            shutil.copy2(self.path, backup)
            # Keep only last 20 backups
            backups = sorted(self.history_dir.glob("overrides_*.yaml"))
            for old in backups[:-20]:
                old.unlink()
        except Exception as e:
            logger.debug(f"Config history save failed: {e}")

    # ── Display ─────────────────────────────────────────────────────

    def format_status(self) -> str:
        """Format current overrides as a readable status string."""
        data = self.load()
        if not data:
            return "📋 No custom overrides — using all defaults."

        lines = ["📋 <b>NeoMind Config Overrides</b>", ""]
        for mode, overrides in data.items():
            lines.append(f"<b>[{mode}]</b>")
            prompt = overrides.get("extra_system_prompt", "")
            if prompt:
                # Show first 200 chars
                preview = prompt[:200].replace("\n", " ")
                if len(prompt) > 200:
                    preview += "..."
                lines.append(f"  Prompt: {preview}")
            triggers = overrides.get("search_triggers", [])
            if triggers:
                lines.append(f"  Search triggers: {', '.join(triggers[:20])}")
                if len(triggers) > 20:
                    lines.append(f"    ... +{len(triggers)-20} more")
            # Other settings
            for k, v in overrides.items():
                if k not in ("extra_system_prompt", "search_triggers"):
                    lines.append(f"  {k}: {v}")
            lines.append("")

        return "\n".join(lines)
