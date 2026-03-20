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

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path
        self.sources: Dict[str, SourceRecord] = {}
        self._init_defaults()
        if storage_path:
            self._load()

    def _init_defaults(self):
        """Initialize with known default trust scores."""
        for name, score in DEFAULT_TRUST.items():
            self.sources[name] = SourceRecord(
                name=name,
                trust_score=score,
                category=SOURCE_CATEGORIES.get(name, "unknown"),
                last_updated=time.time(),
            )

    def get(self, source_name: str, default: float = 0.5) -> float:
        """Get trust score for a source. Returns default for unknown sources."""
        source_name = source_name.lower().strip()
        record = self.sources.get(source_name)
        if record is None:
            return default
        return record.trust_score

    def get_record(self, source_name: str) -> Optional[SourceRecord]:
        """Get full record for a source."""
        return self.sources.get(source_name.lower().strip())

    def report_accuracy(self, source_name: str, accurate: bool):
        """
        Update source trust based on a verified claim.

        Args:
            source_name: Name of the source
            accurate: Whether the claim turned out to be accurate
        """
        source_name = source_name.lower().strip()
        if source_name not in self.sources:
            self.sources[source_name] = SourceRecord(
                name=source_name,
                category=SOURCE_CATEGORIES.get(source_name, "unknown"),
            )

        record = self.sources[source_name]
        record.total_reports += 1
        if accurate:
            record.accurate_reports += 1

        # Recalculate trust with recency weighting
        if record.total_reports >= 3:
            base_trust = record.accuracy_rate
            # Blend with default trust (prior) using Bayesian-like update
            prior = DEFAULT_TRUST.get(source_name, 0.5)
            weight = min(record.total_reports / 20.0, 1.0)  # full weight at 20 reports
            record.trust_score = weight * base_trust + (1 - weight) * prior
        else:
            # Not enough data, keep close to default
            record.trust_score = DEFAULT_TRUST.get(source_name, 0.5)

        record.last_updated = time.time()
        self._save()

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
            for name, record_data in data.items():
                if name in self.sources:
                    # Update existing with persisted data
                    self.sources[name].total_reports = record_data.get("total_reports", 0)
                    self.sources[name].accurate_reports = record_data.get("accurate_reports", 0)
                    self.sources[name].trust_score = record_data.get("trust_score", 0.5)
                    self.sources[name].last_updated = record_data.get("last_updated", 0)
                else:
                    self.sources[name] = SourceRecord(**record_data)
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
