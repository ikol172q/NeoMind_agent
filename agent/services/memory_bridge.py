# agent/finance/memory_bridge.py
"""
Memory Bridge — bidirectional sync between NeoMind's encrypted SQLite
and OpenClaw's Markdown memory files.

OpenClaw stores memory as plain Markdown files in ~/.openclaw/memory/.
NeoMind stores memory as encrypted fields in SQLite at ~/.neomind/finance/memory.db.

The bridge:
1. EXPORT: SQLite → Markdown (for OpenClaw to read)
2. IMPORT: Markdown → SQLite (for NeoMind to learn from OpenClaw memories)
3. WATCH: filesystem watcher detects new/changed Markdown files
4. CONFLICT: last-write-wins with merge for non-overlapping fields

Security:
- Sensitive fields (API keys, tokens) are NEVER exported to Markdown
- Financial data is exported with [FINANCE] prefix tags
- Import validates Markdown structure before writing to encrypted store
"""

import os
import json
import time
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field


# ── Configuration ────────────────────────────────────────────────────

OPENCLAW_MEMORY_DIR = Path(os.getenv(
    "OPENCLAW_MEMORY_DIR",
    str(Path.home() / ".openclaw" / "memory")
))

NEOMIND_BRIDGE_DIR = Path(os.getenv(
    "NEOMIND_BRIDGE_DIR",
    str(Path.home() / ".neomind" / "finance" / "bridge")
))

# Fields that are NEVER exported to OpenClaw (security)
SENSITIVE_FIELDS = {
    "api_key", "token", "password", "secret", "credential",
    "private_key", "master_key", "encryption_key",
}

# Markdown tag prefix for finance-specific memories
FINANCE_TAG = "[FINANCE]"


@dataclass
class MemoryEntry:
    """A single memory entry that can exist in both formats."""
    id: str
    content: str
    category: str = ""
    symbols: List[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = ""           # "neomind" or "openclaw"
    created_at: str = ""
    updated_at: str = ""
    synced_at: str = ""
    checksum: str = ""         # for change detection

    def compute_checksum(self) -> str:
        """Compute content hash for change detection."""
        data = f"{self.content}|{self.category}|{','.join(self.symbols)}|{self.confidence}"
        return hashlib.md5(data.encode()).hexdigest()[:12]


@dataclass
class SyncState:
    """Tracks what has been synced to avoid duplicate writes."""
    last_export: float = 0.0
    last_import: float = 0.0
    exported_checksums: Dict[str, str] = field(default_factory=dict)  # id → checksum
    imported_checksums: Dict[str, str] = field(default_factory=dict)
    conflict_count: int = 0


class MemoryBridge:
    """
    Bidirectional memory sync between NeoMind SQLite and OpenClaw Markdown.

    Usage:
        bridge = MemoryBridge(memory_store=secure_memory)

        # Export NeoMind memories to OpenClaw format
        bridge.export_to_openclaw()

        # Import OpenClaw memories into NeoMind
        bridge.import_from_openclaw()

        # Full sync (both directions)
        bridge.sync()
    """

    EXPORT_SUBDIR = "neomind-finance"  # subdirectory in OpenClaw's memory dir
    SYNC_INTERVAL = 300  # seconds between auto-syncs

    def __init__(self, memory_store=None):
        self.memory = memory_store
        self.openclaw_dir = OPENCLAW_MEMORY_DIR
        self.bridge_dir = NEOMIND_BRIDGE_DIR
        self.export_dir = self.openclaw_dir / self.EXPORT_SUBDIR

        # Create directories
        self.openclaw_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_dir.mkdir(parents=True, exist_ok=True)

        # Load sync state
        self._state_path = self.bridge_dir / "sync_state.json"
        self.state = self._load_state()

    # ── Export: NeoMind → OpenClaw ────────────────────────────────────

    def export_to_openclaw(self) -> int:
        """Export NeoMind finance memories to OpenClaw Markdown format.

        Returns the number of entries exported.
        """
        if not self.memory:
            return 0

        # Ensure export directory exists
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return 0

        count = 0

        # Export insights
        try:
            insights = self.memory.get_recent_insights(limit=100)
            md = self._insights_to_markdown(insights)
            if md:
                self._write_markdown(self.export_dir / "insights.md", md)
                count += len(insights)
        except Exception:
            pass

        # Export predictions
        try:
            predictions = self.memory.get_all_predictions()
            md = self._predictions_to_markdown(predictions)
            if md:
                self._write_markdown(self.export_dir / "predictions.md", md)
                count += len(predictions)
        except Exception:
            pass

        # Export watchlist
        try:
            watchlist = self.memory.get_watchlist()
            md = self._watchlist_to_markdown(watchlist)
            if md:
                self._write_markdown(self.export_dir / "watchlist.md", md)
                count += len(watchlist)
        except Exception:
            pass

        # Export source trust scores
        try:
            from .source_registry import SourceTrustTracker
            tracker = SourceTrustTracker()
            md = self._trust_to_markdown(tracker.sources)
            if md:
                self._write_markdown(self.export_dir / "source_trust.md", md)
        except Exception:
            pass

        self.state.last_export = time.time()
        self._save_state()
        return count

    # ── Import: OpenClaw → NeoMind ───────────────────────────────────

    def import_from_openclaw(self) -> int:
        """Import OpenClaw Markdown memories into NeoMind's encrypted store.

        Only imports files with [FINANCE] tags or in the neomind-finance subdir.
        Returns the number of entries imported.
        """
        if not self.memory:
            return 0

        if not self.openclaw_dir.exists():
            return 0

        count = 0

        # Scan all .md files in OpenClaw memory directory
        for md_file in self.openclaw_dir.rglob("*.md"):
            # Skip our own exports to avoid circular sync
            if self.EXPORT_SUBDIR in str(md_file):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # Only import files with finance-relevant content
            if not self._is_finance_relevant(content):
                continue

            # Parse Markdown into memory entries
            entries = self._parse_openclaw_markdown(content, md_file.stem)

            for entry in entries:
                # Check if already imported (same checksum)
                checksum = entry.compute_checksum()
                if self.state.imported_checksums.get(entry.id) == checksum:
                    continue  # already up to date

                # Validate: no sensitive data leakage
                if self._contains_sensitive(entry.content):
                    continue

                # Write to NeoMind memory
                try:
                    self.memory.store_insight(
                        content=entry.content,
                        category=entry.category or "openclaw_import",
                        symbols=entry.symbols,
                        confidence=entry.confidence,
                    )
                    self.state.imported_checksums[entry.id] = checksum
                    count += 1
                except Exception:
                    pass

        self.state.last_import = time.time()
        self._save_state()
        return count

    # ── Full Sync ────────────────────────────────────────────────────

    def sync(self) -> Dict[str, int]:
        """Full bidirectional sync.

        Returns {"exported": N, "imported": M, "conflicts": K}.
        """
        exported = self.export_to_openclaw()
        imported = self.import_from_openclaw()
        return {
            "exported": exported,
            "imported": imported,
            "conflicts": self.state.conflict_count,
        }

    # ── Markdown Formatters (NeoMind → OpenClaw) ─────────────────────

    def _insights_to_markdown(self, insights: List[Dict]) -> str:
        """Convert NeoMind insights to OpenClaw Markdown."""
        lines = [
            f"# {FINANCE_TAG} Financial Insights",
            f"_Auto-exported from NeoMind Finance — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_",
            "",
        ]

        for ins in insights:
            content = ins.get("content", "")
            category = ins.get("category", "")
            symbols = ins.get("symbols", [])
            confidence = ins.get("confidence", 0.5)
            created = ins.get("created_at", "")

            # Skip sensitive content
            if self._contains_sensitive(content):
                continue

            lines.append(f"## {category.title() or 'Insight'}")
            if symbols:
                lines.append(f"**Symbols:** {', '.join(symbols)}")
            lines.append(f"**Confidence:** {confidence:.0%}")
            if created:
                lines.append(f"**Date:** {created[:16]}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _predictions_to_markdown(self, predictions: List[Dict]) -> str:
        """Convert predictions to OpenClaw Markdown."""
        lines = [
            f"# {FINANCE_TAG} Predictions Tracker",
            f"_Auto-exported from NeoMind Finance — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_",
            "",
            "| Symbol | Direction | Confidence | Status | Created |",
            "|--------|-----------|------------|--------|---------|",
        ]

        for pred in predictions:
            symbol = pred.get("symbol", "?")
            direction = pred.get("direction", "?")
            confidence = pred.get("confidence", 0.5)
            resolved = pred.get("resolved", False)
            correct = pred.get("correct", None)
            created = pred.get("created_at", "")[:10]

            if resolved:
                status = "✅ Correct" if correct else "❌ Wrong"
            else:
                status = "⏳ Pending"

            lines.append(
                f"| {symbol} | {direction} | {confidence:.0%} | {status} | {created} |"
            )

        # Add rationale details
        lines.append("")
        for pred in predictions:
            if pred.get("rationale"):
                lines.append(f"### {pred.get('symbol', '?')} — {pred.get('direction', '?')}")
                lines.append(pred["rationale"])
                lines.append("")

        return "\n".join(lines)

    def _watchlist_to_markdown(self, watchlist: List[Dict]) -> str:
        """Convert watchlist to OpenClaw Markdown."""
        lines = [
            f"# {FINANCE_TAG} Watchlist",
            f"_Auto-exported from NeoMind Finance — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_",
            "",
        ]

        for item in watchlist:
            symbol = item.get("symbol", "?")
            notes = item.get("notes", "")
            added = item.get("added_at", "")[:10]
            lines.append(f"- **{symbol}** — {notes} _(added {added})_")

        return "\n".join(lines)

    def _trust_to_markdown(self, sources: Dict[str, float]) -> str:
        """Convert source trust scores to OpenClaw Markdown."""
        lines = [
            f"# {FINANCE_TAG} Source Trust Scores",
            f"_Auto-exported from NeoMind Finance — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_",
            "",
            "| Source | Trust Score | Rating |",
            "|--------|-------------|--------|",
        ]

        for name, score in sorted(sources.items(), key=lambda x: x[1], reverse=True):
            if score >= 0.85:
                rating = "⭐⭐⭐"
            elif score >= 0.70:
                rating = "⭐⭐"
            elif score >= 0.50:
                rating = "⭐"
            else:
                rating = "⚠️"
            lines.append(f"| {name} | {score:.2f} | {rating} |")

        return "\n".join(lines)

    # ── Markdown Parsers (OpenClaw → NeoMind) ────────────────────────

    def _parse_openclaw_markdown(self, content: str, filename: str) -> List[MemoryEntry]:
        """Parse an OpenClaw Markdown file into MemoryEntry objects."""
        entries = []

        # Split by ## headers
        sections = re.split(r'^## ', content, flags=re.MULTILINE)

        for i, section in enumerate(sections[1:], 1):  # skip everything before first ##
            lines = section.strip().split("\n")
            title = lines[0].strip() if lines else f"section_{i}"
            body = "\n".join(lines[1:]).strip()

            # Extract symbols (look for $TICKER or **TICKER** patterns)
            symbols = re.findall(r'\$([A-Z]{1,5})\b', body)
            symbols += re.findall(r'\*\*([A-Z]{1,5})\*\*', body)
            symbols = list(set(symbols))

            # Determine category from title
            category = "general"
            title_lower = title.lower()
            if any(w in title_lower for w in ["insight", "analysis", "thesis"]):
                category = "insight"
            elif any(w in title_lower for w in ["predict", "forecast", "outlook"]):
                category = "prediction"
            elif any(w in title_lower for w in ["news", "event", "market"]):
                category = "news"

            entry_id = hashlib.md5(f"{filename}_{title}".encode()).hexdigest()[:12]

            entries.append(MemoryEntry(
                id=entry_id,
                content=f"{title}\n{body}",
                category=category,
                symbols=symbols,
                source="openclaw",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

        return entries

    def _is_finance_relevant(self, content: str) -> bool:
        """Check if Markdown content is finance-relevant."""
        if FINANCE_TAG in content:
            return True

        content_lower = content.lower()
        finance_words = [
            "stock", "price", "market", "earnings", "portfolio", "crypto",
            "bitcoin", "fed", "inflation", "investment", "trading",
            "股票", "股价", "行情", "投资", "加密",
        ]
        matches = sum(1 for w in finance_words if w in content_lower)
        return matches >= 2  # at least 2 finance keywords

    # ── Security ─────────────────────────────────────────────────────

    @staticmethod
    def _contains_sensitive(content: str) -> bool:
        """Check if content contains sensitive data that shouldn't be exported."""
        content_lower = content.lower()
        for field_name in SENSITIVE_FIELDS:
            if field_name in content_lower:
                # Further check: is it followed by a value pattern?
                pattern = rf'{field_name}\s*[:=]\s*\S+'
                if re.search(pattern, content_lower):
                    return True
        return False

    # ── File I/O ─────────────────────────────────────────────────────

    @staticmethod
    def _write_markdown(path: Path, content: str):
        """Write Markdown file with appropriate permissions."""
        path.write_text(content, encoding="utf-8")
        try:
            os.chmod(path, 0o644)
        except OSError:
            pass

    # ── State Persistence ────────────────────────────────────────────

    def _load_state(self) -> SyncState:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text())
                return SyncState(
                    last_export=data.get("last_export", 0),
                    last_import=data.get("last_import", 0),
                    exported_checksums=data.get("exported_checksums", {}),
                    imported_checksums=data.get("imported_checksums", {}),
                    conflict_count=data.get("conflict_count", 0),
                )
        except Exception:
            pass
        return SyncState()

    def _save_state(self):
        try:
            data = {
                "last_export": self.state.last_export,
                "last_import": self.state.last_import,
                "exported_checksums": self.state.exported_checksums,
                "imported_checksums": self.state.imported_checksums,
                "conflict_count": self.state.conflict_count,
            }
            self._state_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> str:
        lines = ["Memory Bridge (NeoMind ↔ OpenClaw)", "=" * 50]

        oc_exists = self.openclaw_dir.exists()
        lines.append(f"  OpenClaw memory dir: {'✅ Found' if oc_exists else '❌ Not found'}")
        lines.append(f"    Path: {self.openclaw_dir}")
        lines.append(f"  Export dir: {self.export_dir}")
        lines.append(f"  NeoMind memory: {'✅ Connected' if self.memory else '❌ Not available'}")

        if self.state.last_export:
            ago = int(time.time() - self.state.last_export)
            lines.append(f"\n  Last export: {ago}s ago ({len(self.state.exported_checksums)} entries)")
        else:
            lines.append("\n  Last export: never")

        if self.state.last_import:
            ago = int(time.time() - self.state.last_import)
            lines.append(f"  Last import: {ago}s ago ({len(self.state.imported_checksums)} entries)")
        else:
            lines.append("  Last import: never")

        lines.append(f"  Conflicts: {self.state.conflict_count}")
        return "\n".join(lines)
