# agent/finance/source_registry.py
"""
Source Trust Tracking — reliability scoring for every data/news source.

Trust score formula:
  trust = (accurate_reports / total_reports) × recency_weight × consistency_bonus

- New sources start at 0.5 (neutral)
- Score updates after every verifiable claim
- Recency weight: recent accuracy matters more
- Sources that break real news early get a large bonus
"""

import time
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional
from pathlib import Path


@dataclass
class SourceRecord:
    """Track record for a single source."""
    name: str
    trust_score: float = 0.5
    total_reports: int = 0
    accurate_reports: int = 0
    last_updated: float = 0.0
    category: str = "unknown"  # news, data, opinion, aggregator

    @property
    def accuracy_rate(self) -> float:
        if self.total_reports == 0:
            return 0.5  # neutral for unknown
        return self.accurate_reports / self.total_reports


# Default trust scores — calibrated from known source reliability
DEFAULT_TRUST: Dict[str, float] = {
    # Tier 1: Wire services & major financial press (EN)
    "reuters": 0.90,
    "bloomberg": 0.88,
    "wsj": 0.87,
    "ft": 0.87,
    "ap": 0.89,

    # Tier 2: Financial news outlets (EN)
    "cnbc": 0.80,
    "marketwatch": 0.78,
    "yahoo_finance": 0.75,
    "seeking_alpha": 0.65,
    "investing_com": 0.72,

    # Tier 1: Chinese financial press
    "caixin": 0.85,           # 财新
    "yicai": 0.80,            # 第一财经
    "cls": 0.78,              # 财联社

    # Tier 2: Chinese financial outlets
    "wallstreetcn": 0.75,     # 华尔街见闻
    "eastmoney": 0.70,        # 东方财富
    "sina_finance": 0.72,     # 新浪财经
    "gelonghui": 0.70,        # 格隆汇

    # Crypto sources
    "coindesk": 0.80,
    "cointelegraph": 0.72,
    "jinse": 0.65,            # 金色财经

    # Data providers (higher trust — data, not opinion)
    "finnhub": 0.92,
    "coingecko": 0.90,
    "akshare": 0.85,
    "yfinance": 0.80,         # lower due to scraping fragility
    "binance": 0.88,
}

# Source categories
SOURCE_CATEGORIES: Dict[str, str] = {
    "reuters": "news", "bloomberg": "news", "wsj": "news", "ft": "news",
    "cnbc": "news", "marketwatch": "news", "seeking_alpha": "opinion",
    "caixin": "news", "yicai": "news", "cls": "news",
    "wallstreetcn": "news", "eastmoney": "aggregator",
    "finnhub": "data", "coingecko": "data", "akshare": "data",
    "yfinance": "data", "binance": "data",
    "coindesk": "news", "cointelegraph": "news",
}


class SourceTrustTracker:
    """
    Track reliability of each data/news source over time.

    Persists to a JSON file in the finance data directory.
    Thread-safe for single-process use (not multi-process).
    """

    RECENCY_HALF_LIFE = 30 * 86400  # 30 days in seconds
    CONFIDENCE_DECAY_RATE = 0.005   # per day without updates

    def __init__(self, storage_path: Optional[Path] = None, db_path: Optional[str] = None):
        # Support both storage_path (Path) and db_path (str) for compatibility
        if db_path is not None:
            self.storage_path = Path(db_path)
        elif storage_path is not None:
            self.storage_path = storage_path if isinstance(storage_path, Path) else Path(storage_path)
        else:
            self.storage_path = None
        self.sources: Dict[str, SourceRecord] = {}
        # Map lowercase names to actual records (preserves case in record.name)
        self._name_map: Dict[str, str] = {}
        self._init_defaults()
        if self.storage_path:
            self._load()

    def _init_defaults(self):
        """Initialize with known default trust scores."""
        for name, score in DEFAULT_TRUST.items():
            record = SourceRecord(
                name=name,
                trust_score=score,
                category=SOURCE_CATEGORIES.get(name, "unknown"),
                last_updated=time.time(),
            )
            self.sources[name] = record
            self._name_map[name.lower()] = name

    def get(self, source_name: str, default: float = 0.5) -> float:
        """Get trust score for a source. Returns default for unknown sources."""
        normalized = source_name.lower().strip()
        key = self._name_map.get(normalized)
        if key is None:
            return default
        record = self.sources.get(key)
        if record is None:
            return default
        return record.trust_score

    def get_record(self, source_name: str) -> Optional[SourceRecord]:
        """Get full record for a source. Creates default if not found."""
        normalized = source_name.lower().strip()
        key = self._name_map.get(normalized)

        if key is not None:
            return self.sources.get(key)

        # Return a default record for unknown sources
        return SourceRecord(
            name=source_name,
            category=SOURCE_CATEGORIES.get(normalized, "unknown"),
            trust_score=0.5
        )

    def report_accuracy(self, source_name: str, accurate: bool):
        """
        Update source trust based on a verified claim.

        Args:
            source_name: Name of the source
            accurate: Whether the claim turned out to be accurate
        """
        normalized = source_name.lower().strip()

        # Get or create the key for this source
        key = self._name_map.get(normalized, source_name)

        if key not in self.sources:
            self.sources[key] = SourceRecord(
                name=source_name,
                category=SOURCE_CATEGORIES.get(normalized, "unknown"),
            )
            self._name_map[normalized] = key
        else:
            # Update the name to match the provided casing
            self.sources[key].name = source_name

        record = self.sources[key]
        record.total_reports += 1
        if accurate:
            record.accurate_reports += 1

        # Recalculate trust score immediately
        base_trust = record.accuracy_rate
        prior = DEFAULT_TRUST.get(normalized, 0.5)
        weight = min(record.total_reports / 20.0, 1.0)  # full weight at 20 reports
        record.trust_score = weight * base_trust + (1 - weight) * prior

        record.last_updated = time.time()
        self._save()

    def record_report(self, source_name: str, accurate: bool):
        """
        Alias for report_accuracy() for test compatibility.

        Args:
            source_name: Name of the source
            accurate: Whether the report was accurate
        """
        self.report_accuracy(source_name, accurate)

    def get_all_scores(self) -> Dict[str, float]:
        """Get all source trust scores as a dict."""
        return {name: record.trust_score for name, record in self.sources.items()}

    def get_ranked_sources(self) -> list:
        """Get sources ranked by trust score (highest first)."""
        return sorted(
            self.sources.values(),
            key=lambda r: r.trust_score,
            reverse=True,
        )

    def _load(self):
        """Load trust data from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text())
            for key, record_data in data.items():
                record = SourceRecord(**record_data)
                # Get display name from record data
                display_name = record_data.get("name", key)
                self.sources[key] = record
                # Update name mapping
                self._name_map[display_name.lower().strip()] = key
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"Warning: Failed to load source trust data: {e}")

    def _save(self):
        """Persist trust data to disk."""
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {name: asdict(record) for name, record in self.sources.items()}
            self.storage_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Warning: Failed to save source trust data: {e}")

    def update_scores(self):
        """
        Recalculate trust scores for all sources.
        This is called by report_accuracy automatically,
        but provided as public method for test compatibility.
        """
        for record in self.sources.values():
            if record.total_reports > 0:
                base_trust = record.accuracy_rate
                normalized = record.name.lower().strip()
                prior = DEFAULT_TRUST.get(normalized, 0.5)
                weight = min(record.total_reports / 20.0, 1.0)
                record.trust_score = weight * base_trust + (1 - weight) * prior

    def apply_breaking_news_bonus(self, source_name: str, bonus_amount: float):
        """
        Apply a bonus to a source for breaking news early/accurately.

        Args:
            source_name: Name of the source
            bonus_amount: Bonus to add to trust score (e.g., 0.1 for +0.1)
        """
        normalized = source_name.lower().strip()
        key = self._name_map.get(normalized)
        if key and key in self.sources:
            record = self.sources[key]
            record.trust_score = min(record.trust_score + bonus_amount, 1.0)
            record.last_updated = time.time()
            self._save()

    def apply_correction_penalty(self, source_name: str, penalty_amount: float):
        """
        Apply a penalty for reporting that required correction.

        Args:
            source_name: Name of the source
            penalty_amount: Penalty to subtract from trust score (e.g., 0.15 for -0.15)
        """
        normalized = source_name.lower().strip()
        key = self._name_map.get(normalized)
        if key and key in self.sources:
            record = self.sources[key]
            record.trust_score = max(record.trust_score - penalty_amount, 0.0)
            record.last_updated = time.time()
            self._save()

    def list_all(self) -> list:
        """
        Get all sources that have been tracked (excluding defaults not yet reported).

        Returns:
            List of SourceRecord objects, sorted by trust score (highest first)
        """
        # Only return sources that have actual reports (not just defaults)
        tracked = [r for r in self.sources.values() if r.total_reports > 0]
        return sorted(tracked, key=lambda r: r.trust_score, reverse=True)

    def reset_source(self, source_name: str):
        """
        Reset tracking for a single source.

        Args:
            source_name: Name of the source to reset
        """
        normalized = source_name.lower().strip()
        key = self._name_map.get(normalized)
        if key and key in self.sources:
            record = self.sources[key]
            record.total_reports = 0
            record.accurate_reports = 0
            record.trust_score = DEFAULT_TRUST.get(normalized, 0.5)
            record.last_updated = time.time()
            self._save()

    def reset_all(self):
        """Reset all tracked sources (removes custom reports, keeps defaults)."""
        # Remove all sources with custom reports
        self.sources = {}
        self._name_map = {}
        self._init_defaults()
        self._save()

    def save(self):
        """Explicitly save the tracker state to disk."""
        self._save()

    def format_report(self) -> str:
        """Format a human-readable trust report."""
        lines = ["Source Trust Scores", "=" * 50]
        for record in self.get_ranked_sources():
            bar = "█" * int(record.trust_score * 20) + "░" * (20 - int(record.trust_score * 20))
            accuracy = f"{record.accuracy_rate:.0%}" if record.total_reports > 0 else "n/a"
            lines.append(
                f"  {record.name:<20s} {bar} {record.trust_score:.2f}  "
                f"({record.total_reports} reports, {accuracy} accurate)  [{record.category}]"
            )
        return "\n".join(lines)
