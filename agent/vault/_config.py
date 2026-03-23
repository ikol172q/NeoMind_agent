"""Vault configuration — shared between reader and writer."""

import os
from pathlib import Path


def get_vault_dir() -> str:
    """Return the vault directory path.

    Priority:
    1. NEOMIND_VAULT_DIR env var
    2. /data/vault (Docker)
    3. ~/neomind-vault (local Mac)
    """
    env_dir = os.environ.get("NEOMIND_VAULT_DIR")
    if env_dir:
        return env_dir
    if os.path.isdir("/data"):
        return "/data/vault"
    return str(Path.home() / "neomind-vault")
