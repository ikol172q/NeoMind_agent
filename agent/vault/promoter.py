"""Promoter — Moves validated patterns from SharedMemory to vault MEMORY.md.

A pattern is "validated" when it has been observed 3+ times.
This prevents hallucinated or one-off observations from becoming
long-term memory.

Called by auto_evolve.run_weekly_retro() every Sunday.

Troubleshooting: plans/OBSIDIAN_TROUBLESHOOTING.md (OV-041, OV-042)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

PROMOTION_THRESHOLD = 3

# Maps SharedMemory pattern_type → MEMORY.md section heading
SECTION_MAP = {
    "frequent_stock": "Trading Patterns",
    "coding_language": "Coding Preferences",
    "tool": "Tool Preferences",
    "topic": "Conversation Topics",
    "language": "Language Preferences",
}


def promote_patterns(shared_memory, vault_writer=None) -> int:
    """Scan SharedMemory patterns table for entries with count >= threshold.

    Promotes them to the appropriate MEMORY.md section.

    Args:
        shared_memory: SharedMemory instance with get_all_patterns() method
        vault_writer: Optional VaultWriter instance (creates one if None)

    Returns:
        Number of patterns promoted.
    """
    if vault_writer is None:
        from agent.vault.writer import VaultWriter
        vault_writer = VaultWriter()

    try:
        patterns = shared_memory.get_all_patterns()
    except Exception as e:
        logger.warning(f"Failed to read patterns from SharedMemory: {e}")
        return 0

    promoted = 0
    for p in patterns:
        count = p.get("count", 0)
        if count < PROMOTION_THRESHOLD:
            continue

        pattern_type = p.get("pattern_type", "unknown")
        pattern_value = p.get("pattern_value", "")
        source_mode = p.get("source_mode", "unknown")

        if not pattern_value:
            continue

        section = SECTION_MAP.get(pattern_type, "Other Patterns")
        entry = f"{pattern_value} (observed {count}x, source: {source_mode})"

        vault_writer.append_to_memory(section, entry)
        promoted += 1

    if promoted:
        logger.info(f"Promoted {promoted} patterns to MEMORY.md")
    return promoted
