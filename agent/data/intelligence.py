"""
Cross-Mode Intelligence Pipeline
数据驱动的个人能力延伸系统 — 跨人格智能共享

Bridges data-collector → fin → chat:
- data-collector writes to market_data.db, news_data.db
- intelligence reads these + generates briefings.db entries
- fin reads briefings for deep analysis → writes to decisions.db
- chat reads decisions for proactive reminders to user
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = Path("/data/neomind/db")


def _connect_readonly(db_path: Path) -> Optional[sqlite3.Connection]:
    """Open a read-only connection to a SQLite WAL database."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.warning(f"Cannot connect to {db_path}: {e}")
        return None


def _connect_readwrite(db_path: Path) -> Optional[sqlite3.Connection]:
    """Open a read-write connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.warning(f"Cannot connect to {db_path}: {e}")
        return None


class CrossModeIntelligence:
    """
    Reads collected data and provides intelligence to each personality mode.

    Usage by scheduler:
        intel = CrossModeIntelligence()
        prompt_addition = intel.get_prompt_addition(mode="chat")
    """

    def get_latest_briefing(self, briefing_type: str = "daily",
                             max_age_hours: int = 24) -> Optional[dict]:
        """Get the most recent briefing."""
        conn = _connect_readonly(DB_DIR / "briefings.db")
        if not conn:
            return None

        try:
            cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
            row = conn.execute(
                """SELECT * FROM briefings
                WHERE type=? AND generated_at > ?
                ORDER BY generated_at DESC LIMIT 1""",
                (briefing_type, cutoff),
            ).fetchone()

            if row:
                return {
                    "id": row["id"],
                    "type": row["type"],
                    "date": row["date"],
                    "content": row["content"],
                    "key_events": json.loads(row["key_events"] or "[]"),
                    "market_mood": row["market_mood"],
                    "action_items": json.loads(row["action_items"] or "[]"),
                }
            return None
        finally:
            conn.close()

    def get_pending_decisions(self, mode: str = "fin",
                               limit: int = 5) -> list[dict]:
        """Get pending decisions from fin mode for chat to present."""
        conn = _connect_readonly(DB_DIR / "briefings.db")
        if not conn:
            return []

        try:
            rows = conn.execute(
                """SELECT * FROM decisions
                WHERE outcome='pending'
                ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "type": row["decision_type"],
                    "symbol": row["symbol"],
                    "reasoning": row["reasoning"],
                    "confidence": row["confidence"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def record_decision(self, mode: str, decision_type: str,
                         symbol: str = "", reasoning: str = "",
                         confidence: float = 0.5,
                         data_sources: list[str] = None) -> Optional[int]:
        """Record a new decision (typically from fin mode)."""
        conn = _connect_readwrite(DB_DIR / "briefings.db")
        if not conn:
            return None

        try:
            cursor = conn.execute(
                """INSERT INTO decisions
                (mode, decision_type, symbol, reasoning, confidence, data_sources)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (mode, decision_type, symbol, reasoning, confidence,
                 json.dumps(data_sources or [])),
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Failed to record decision: {e}")
            return None
        finally:
            conn.close()

    def update_decision_outcome(self, decision_id: int, outcome: str,
                                 detail: str = "") -> bool:
        """Update a decision's outcome (for tracking accuracy)."""
        conn = _connect_readwrite(DB_DIR / "briefings.db")
        if not conn:
            return False

        try:
            conn.execute(
                """UPDATE decisions SET outcome=?, outcome_detail=?,
                outcome_recorded_at=datetime('now')
                WHERE id=?""",
                (outcome, detail, decision_id),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to update decision: {e}")
            return False
        finally:
            conn.close()

    def get_market_snapshot(self, symbols: list[str] = None) -> dict:
        """Get latest market data snapshot for specified symbols."""
        conn = _connect_readonly(DB_DIR / "market_data.db")
        if not conn:
            return {"prices": [], "macro": []}

        try:
            result = {"prices": [], "macro": []}

            # Prices
            if symbols:
                placeholders = ",".join("?" * len(symbols))
                rows = conn.execute(
                    f"""SELECT symbol, market, close, ts FROM price_ohlcv
                    WHERE symbol IN ({placeholders})
                    ORDER BY ts DESC""",
                    symbols,
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT DISTINCT symbol, market, close, ts FROM price_ohlcv
                    WHERE ts > datetime('now', '-24 hours')
                    ORDER BY ts DESC LIMIT 20""",
                ).fetchall()

            seen = set()
            for row in rows:
                sym = row["symbol"]
                if sym not in seen:
                    seen.add(sym)
                    result["prices"].append({
                        "symbol": sym,
                        "market": row["market"],
                        "price": row["close"],
                        "as_of": row["ts"],
                    })

            # Macro
            macro_rows = conn.execute(
                """SELECT indicator, value, period FROM macro_indicators
                ORDER BY collected_at DESC LIMIT 10""",
            ).fetchall()

            seen_macro = set()
            for row in macro_rows:
                ind = row["indicator"]
                if ind not in seen_macro:
                    seen_macro.add(ind)
                    result["macro"].append({
                        "indicator": ind,
                        "value": row["value"],
                        "period": row["period"],
                    })

            return result
        finally:
            conn.close()

    def get_recent_news(self, limit: int = 10,
                         symbols: list[str] = None) -> list[dict]:
        """Get recent news articles."""
        conn = _connect_readonly(DB_DIR / "news_data.db")
        if not conn:
            return []

        try:
            if symbols:
                # Filter by symbols (JSON contains check)
                rows = conn.execute(
                    """SELECT headline, summary, source, published_at, symbols
                    FROM news WHERE published_at > datetime('now', '-48 hours')
                    ORDER BY published_at DESC LIMIT ?""",
                    (limit * 3,),  # Over-fetch then filter
                ).fetchall()

                result = []
                for row in rows:
                    news_symbols = json.loads(row["symbols"] or "[]")
                    if any(s in news_symbols for s in symbols):
                        result.append({
                            "headline": row["headline"],
                            "summary": row["summary"],
                            "source": row["source"],
                            "published_at": row["published_at"],
                        })
                        if len(result) >= limit:
                            break
                return result
            else:
                rows = conn.execute(
                    """SELECT headline, summary, source, published_at
                    FROM news WHERE published_at > datetime('now', '-48 hours')
                    ORDER BY published_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()

                return [
                    {
                        "headline": row["headline"],
                        "summary": row["summary"],
                        "source": row["source"],
                        "published_at": row["published_at"],
                    }
                    for row in rows
                ]
        finally:
            conn.close()

    def get_prompt_addition(self, mode: str) -> str:
        """
        Generate context injection for a personality's system prompt.
        Called by EvolutionScheduler.get_prompt_additions().
        """
        parts = []

        if mode in ("chat", "fin"):
            # Inject latest briefing summary
            briefing = self.get_latest_briefing()
            if briefing:
                # Truncate for token budget
                content = briefing["content"]
                if len(content) > 800:
                    content = content[:800] + "\n...(truncated)"
                parts.append(f"\n[Today's Market Overview]\n{content}")

        if mode == "chat":
            # Chat gets pending decisions from fin
            decisions = self.get_pending_decisions(limit=3)
            if decisions:
                decision_lines = []
                for d in decisions:
                    confidence_pct = f"{d['confidence']*100:.0f}%"
                    decision_lines.append(
                        f"- [{d['type'].upper()}] {d['symbol']} "
                        f"(confidence: {confidence_pct}) — {d['reasoning'][:100]}"
                    )
                parts.append(
                    "\n[Pending Investment Decisions]\n"
                    + "\n".join(decision_lines)
                    + "\n(Remind user proactively about these)"
                )

        if mode == "fin":
            # Fin gets raw market snapshot for analysis
            snapshot = self.get_market_snapshot()
            if snapshot["prices"]:
                price_lines = [
                    f"- {p['symbol']}: ${p['price']:.2f}"
                    for p in snapshot["prices"][:8]
                ]
                parts.append(
                    "\n[Live Data from Collector]\n"
                    + "\n".join(price_lines)
                )

        return "\n".join(parts) if parts else ""

    def get_decision_accuracy(self, days: int = 30) -> dict:
        """Calculate decision accuracy for self-evolution tracking."""
        conn = _connect_readonly(DB_DIR / "briefings.db")
        if not conn:
            return {"total": 0, "correct": 0, "accuracy": 0.0}

        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            rows = conn.execute(
                """SELECT outcome, COUNT(*) as cnt FROM decisions
                WHERE outcome != 'pending' AND created_at > ?
                GROUP BY outcome""",
                (cutoff,),
            ).fetchall()

            total = sum(row["cnt"] for row in rows)
            correct = sum(row["cnt"] for row in rows if row["outcome"] == "correct")

            return {
                "total": total,
                "correct": correct,
                "accuracy": correct / total if total > 0 else 0.0,
                "period_days": days,
            }
        finally:
            conn.close()

    # ── DK-CoT Domain Knowledge Chain-of-Thought (6.5) ────────
    # Research: Round 5 — DK-CoT improves financial sentiment analysis
    # accuracy by injecting domain-specific reasoning chains.

    # Financial domain knowledge templates
    DOMAIN_KNOWLEDGE = {
        "sentiment_analysis": {
            "prompt_prefix": (
                "You are analyzing financial news sentiment. Apply these domain rules:\n"
                "1. Fed rate decisions: hawkish=negative for growth stocks, dovish=positive\n"
                "2. Earnings beats: positive, but 'in-line' can be negative if expectations were high\n"
                "3. Layoff announcements: often positive for stock (cost cutting), negative for sector\n"
                "4. M&A rumors: positive for target, neutral-to-negative for acquirer\n"
                "5. Regulatory actions: generally negative, severity depends on fine amount vs revenue\n"
                "6. Supply chain disruptions: negative for affected, positive for alternatives\n"
                "7. Insider buying: strong positive signal; insider selling: weak negative signal\n"
            ),
            "reasoning_chain": [
                "Step 1: Identify the event type (earnings, macro, regulatory, M&A, etc.)",
                "Step 2: Determine affected entities (company, sector, market)",
                "Step 3: Apply domain rule for this event type",
                "Step 4: Consider second-order effects (sector rotation, supply chain)",
                "Step 5: Calibrate confidence based on source reliability and information completeness",
            ],
        },
        "risk_assessment": {
            "prompt_prefix": (
                "You are assessing investment risk. Apply these domain rules:\n"
                "1. Concentration risk: >10% in single position is high risk\n"
                "2. Correlation risk: assets moving together reduce diversification benefit\n"
                "3. Liquidity risk: small caps and crypto have higher liquidity risk\n"
                "4. Macro risk: rising rates → growth stocks underperform, value outperforms\n"
                "5. Event risk: earnings dates, FOMC meetings, options expiry are risk events\n"
                "6. Volatility regime: VIX>25 = elevated, VIX>35 = crisis\n"
            ),
            "reasoning_chain": [
                "Step 1: Identify asset class and market conditions",
                "Step 2: Assess systematic vs idiosyncratic risk factors",
                "Step 3: Check for upcoming risk events in calendar",
                "Step 4: Evaluate portfolio-level risk metrics",
                "Step 5: Recommend risk-appropriate position sizing",
            ],
        },
        "market_regime": {
            "prompt_prefix": (
                "You are identifying the current market regime. Consider:\n"
                "1. Bull/Bear: 20% from recent high/low defines regime change\n"
                "2. Volatility regime: Low(<15 VIX), Normal(15-25), High(25-35), Crisis(>35)\n"
                "3. Correlation regime: Rising correlations = risk-off, declining = stock-picking\n"
                "4. Monetary regime: Tightening (rate hikes, QT) vs Easing (cuts, QE)\n"
                "5. Sector rotation: Early cycle(industrials), Mid(tech), Late(energy,materials), Recession(utilities,healthcare)\n"
            ),
            "reasoning_chain": [
                "Step 1: Classify current regime on each dimension",
                "Step 2: Identify regime transition signals",
                "Step 3: Map regime to historical analogues",
                "Step 4: Derive regime-appropriate investment stance",
            ],
        },
    }

    def get_dkcot_prompt(self, task_type: str,
                          context: Optional[dict] = None) -> str:
        """Generate a DK-CoT enriched prompt for financial analysis.

        Injects domain knowledge and reasoning chain structure
        to improve financial analysis accuracy.

        Args:
            task_type: Type of analysis (sentiment_analysis, risk_assessment, market_regime)
            context: Optional additional context (market data, news, etc.)

        Returns:
            Domain-knowledge enriched prompt string
        """
        knowledge = self.DOMAIN_KNOWLEDGE.get(task_type)
        if not knowledge:
            logger.debug(f"No domain knowledge for task type: {task_type}")
            return ""

        parts = [knowledge["prompt_prefix"]]

        # Add reasoning chain
        parts.append("\nReasoning approach:")
        for step in knowledge["reasoning_chain"]:
            parts.append(f"  {step}")

        # Add contextual data if available
        if context:
            parts.append("\nCurrent context:")
            if "market_data" in context:
                parts.append(f"  Market data: {json.dumps(context['market_data'])[:500]}")
            if "recent_news" in context:
                parts.append(f"  Recent news: {context['recent_news'][:500]}")
            if "macro_indicators" in context:
                parts.append(f"  Macro indicators: {json.dumps(context['macro_indicators'])[:300]}")

        parts.append("\nNow analyze the following with this domain expertise:\n")
        return "\n".join(parts)

    def get_prompt_addition(self, mode: str,
                             context: Optional[dict] = None) -> str:
        """Get intelligence-based prompt additions for a mode.

        For fin mode, includes DK-CoT domain knowledge.
        For chat mode, includes relevant briefing highlights.
        """
        parts = []

        # Add briefing data
        briefing = self.get_latest_briefing()
        if briefing:
            parts.append(f"[Latest briefing ({briefing.get('type', 'daily')}): "
                        f"{briefing.get('content', '')[:200]}]")

        # For fin mode: inject DK-CoT
        if mode == "fin":
            # Default to sentiment analysis DK-CoT
            dkcot = self.get_dkcot_prompt("sentiment_analysis", context)
            if dkcot:
                parts.append(dkcot)

        return "\n\n".join(parts) if parts else ""
