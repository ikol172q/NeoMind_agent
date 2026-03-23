"""NeoMind Vault — Markdown-based long-term memory.

Reads and writes to ~/neomind-vault (or /data/vault in Docker).
Obsidian on the host can browse this folder as a vault.
NeoMind does not depend on Obsidian — it reads/writes plain .md files.

Architecture doc: plans/2026-03-22_obsidian-vault-integration.md
Troubleshooting: plans/OBSIDIAN_TROUBLESHOOTING.md
"""

try:
    from agent.vault.reader import VaultReader
    from agent.vault.writer import VaultWriter
    from agent.vault.promoter import promote_patterns, PROMOTION_THRESHOLD
    HAS_VAULT = True
except ImportError:
    HAS_VAULT = False
    VaultReader = None
    VaultWriter = None

__all__ = ["VaultReader", "VaultWriter", "promote_patterns", "HAS_VAULT"]
