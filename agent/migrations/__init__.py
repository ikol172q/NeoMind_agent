"""
NeoMind Configuration Migration System.

Runs versioned, idempotent migrations on startup to evolve config
across NeoMind versions. Each migration checks preconditions, applies
changes, and records completion.

Migrations are numbered and run in order. Applied migrations are
tracked in ~/.neomind/migration_state.json.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Callable

logger = logging.getLogger(__name__)

MIGRATION_STATE_PATH = Path(os.path.expanduser('~/.neomind/migration_state.json'))


class MigrationRunner:
    """Run pending config migrations on startup."""

    def __init__(self):
        self._applied: List[str] = []
        self._load_state()

    def _load_state(self):
        try:
            if MIGRATION_STATE_PATH.exists():
                with open(MIGRATION_STATE_PATH) as f:
                    data = json.load(f)
                self._applied = data.get('applied', [])
        except Exception:
            self._applied = []

    def _save_state(self):
        try:
            MIGRATION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(MIGRATION_STATE_PATH, 'w') as f:
                json.dump({'applied': self._applied}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save migration state: {e}")

    def run_pending(self):
        """Run all pending migrations in order."""
        for name, fn in MIGRATIONS:
            if name not in self._applied:
                try:
                    logger.info(f"Running migration: {name}")
                    fn()
                    self._applied.append(name)
                    self._save_state()
                    logger.info(f"Migration completed: {name}")
                except Exception as e:
                    logger.error(f"Migration failed: {name}: {e}")
                    # Don't block startup on migration failure


# ── Migration definitions ───────────────────────────────────────

def _migrate_001_ensure_neomind_dirs():
    """Ensure ~/.neomind directory structure exists."""
    dirs = [
        '~/.neomind',
        '~/.neomind/sessions',
        '~/.neomind/checkpoints',
        '~/.neomind/session_notes',
    ]
    for d in dirs:
        os.makedirs(os.path.expanduser(d), exist_ok=True)


def _migrate_002_default_feature_flags():
    """Create default feature flags config if missing."""
    flags_path = Path(os.path.expanduser('~/.neomind/feature_flags.json'))
    if not flags_path.exists():
        try:
            from agent.services.feature_flags import DEFAULT_FLAGS
            defaults = {k: v['default'] for k, v in DEFAULT_FLAGS.items()}
            flags_path.parent.mkdir(parents=True, exist_ok=True)
            with open(flags_path, 'w') as f:
                json.dump(defaults, f, indent=2)
        except Exception:
            pass


def _migrate_003_update_version_marker():
    """Update the version marker for NeoMind 0.3.0."""
    marker_path = Path(os.path.expanduser('~/.neomind/version'))
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text('0.3.0')
    except Exception:
        pass


def _migrate_004_ensure_memory_dirs():
    """Create memory directories for private/project scope."""
    dirs = [
        '~/.neomind/memory',
        '~/.neomind/evolution',
    ]
    for d in dirs:
        os.makedirs(os.path.expanduser(d), exist_ok=True)


def _migrate_005_permission_rules_file():
    """Create permission rules JSON if missing."""
    rules_path = Path(os.path.expanduser('~/.neomind/permission_rules.json'))
    if not rules_path.exists():
        try:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text('[]')
        except Exception:
            pass


def _migrate_006_output_styles_dir():
    """Create output styles directory."""
    styles_dir = Path(os.path.expanduser('~/.neomind/output-styles'))
    styles_dir.mkdir(parents=True, exist_ok=True)


def _migrate_007_deprecated_model_aliases():
    """Map any deprecated model names to current aliases in config."""
    import yaml
    config_paths = [
        os.path.expanduser('~/.neomind/config.json'),
    ]
    # Auto-migrate any persisted reference to a deprecated DeepSeek name
    # to deepseek-v4-flash (matches DeepSeek's own legacy alias mapping —
    # deepseek-chat / deepseek-reasoner now both point at v4-flash). This
    # protects users restoring an old config DB from getting silently
    # routed to a 404'ing model name.
    deprecated_models = {
        'deepseek-chat': 'deepseek-v4-flash',
        'deepseek-chat-v2': 'deepseek-v4-flash',
        'deepseek-reasoner': 'deepseek-v4-flash',
        'deepseek-coder': 'deepseek-v4-flash',
        'glm-4': 'glm-4.5',
        'glm-4-flash': 'glm-4.5-flash',
    }
    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    config = json.load(f)
                model = config.get('model', '')
                if model in deprecated_models:
                    config['model'] = deprecated_models[model]
                    with open(config_path, 'w') as f:
                        json.dump(config, f, indent=2)
                    logger.info(f"Migrated model: {model} → {config['model']}")
            except Exception:
                pass


# Registry of all migrations (name, function) — ORDER MATTERS
MIGRATIONS: List[tuple] = [
    ('001_ensure_neomind_dirs', _migrate_001_ensure_neomind_dirs),
    ('002_default_feature_flags', _migrate_002_default_feature_flags),
    ('003_update_version_marker', _migrate_003_update_version_marker),
    ('004_ensure_memory_dirs', _migrate_004_ensure_memory_dirs),
    ('005_permission_rules_file', _migrate_005_permission_rules_file),
    ('006_output_styles_dir', _migrate_006_output_styles_dir),
    ('007_deprecated_model_aliases', _migrate_007_deprecated_model_aliases),
]


def run_startup_migrations():
    """Convenience function called from main.py or core.py."""
    runner = MigrationRunner()
    runner.run_pending()
