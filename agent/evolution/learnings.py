"""NeoMind Learnings Engine — Extract, Store, and Recall Structured Knowledge

Unlike auto_evolve's pattern matching (regex on conversations), this module
extracts *actionable learnings* — things the agent discovered that change
how it should behave in the future.

Three types of learnings:
  1. INSIGHT  — "When user asks X, approach Y works better than Z"
  2. ERROR    — "Calling API with param X causes Y; use Z instead"
  3. PREFERENCE — "This user prefers short answers in Chinese for finance"

Memory model:
  - Ebbinghaus forgetting curve: learnings decay unless recalled
  - strength = importance * e^(-λ * days) * (1 + recall_count * 0.2)
  - High-strength learnings are injected into system prompts
  - Low-strength learnings are pruned after 30 days

Inspired by: OpenClaw LEARNINGS.md/ERRORS.md, ExpeL, Reflexion
Different from OpenClaw: SQLite-backed, per-personality, decay-based pruning

No external dependencies — stdlib only.
"""

import json
import math
import struct
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/learnings.db")
DECAY_LAMBDA_0 = 0.05     # Initial forgetting rate (FOREVER paper: λ₀)
FOREVER_BETA = 0.8        # Max decay relief (FOREVER: β)
FOREVER_GAMMA = 0.5       # Relief speed (FOREVER: γ)
PRUNE_THRESHOLD = 0.1     # Below this strength → eligible for pruning
PRUNE_AGE_DAYS = 30       # Only prune if also older than 30 days
MAX_PROMPT_LEARNINGS = 10  # Max learnings to inject into system prompt
MAX_PROMPT_TOKENS = 500    # Token budget for learnings in prompt
# Legacy constant for backward compatibility
DECAY_LAMBDA = DECAY_LAMBDA_0

# ── Vector Search Configuration ────────────────────────────────
VECTOR_DIMENSION = 256        # Compact embedding dimension
VECTOR_SIMILARITY_THRESHOLD = 0.75  # Cosine similarity threshold for "similar"
MAX_VECTOR_SEARCH_RESULTS = 20      # Max results from vector search


class LearningsEngine:
    """Structured learning extraction, storage, and recall.

    Lifecycle:
    1. After conversation: extract_learnings(conversation) → stores insights
    2. Before response: get_relevant(mode, context) → returns applicable learnings
    3. Daily: decay_and_prune() → forget unused learnings
    4. On recall: recall(learning_id) → strengthens the learning
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,          -- INSIGHT | ERROR | PREFERENCE
            mode TEXT NOT NULL,          -- chat | coding | fin | all
            category TEXT NOT NULL,      -- topic/area (e.g., "api_calls", "user_style")
            content TEXT NOT NULL,       -- the actual learning
            context TEXT,               -- when this applies (JSON)
            importance REAL DEFAULT 0.5, -- 0.0 to 1.0
            recall_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_recalled_at TEXT,
            source TEXT,                -- what triggered this learning
            related_ids TEXT            -- JSON array of related learning IDs
        );

        CREATE INDEX IF NOT EXISTS idx_learnings_mode ON learnings(mode);
        CREATE INDEX IF NOT EXISTS idx_learnings_type ON learnings(type);
        CREATE INDEX IF NOT EXISTS idx_learnings_category ON learnings(category);

        CREATE TABLE IF NOT EXISTS learning_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            learning_id INTEGER,
            event_type TEXT NOT NULL,   -- created | recalled | pruned | promoted | merged | consolidated
            ts TEXT NOT NULL,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS consolidated_learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER,        -- reference to original learning ID
            type TEXT NOT NULL,
            mode TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            context TEXT,
            importance REAL DEFAULT 0.5,
            recall_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            consolidated_at TEXT NOT NULL,
            related_ids TEXT            -- JSON array of merged learning IDs
        );

        CREATE INDEX IF NOT EXISTS idx_consolidated_mode ON consolidated_learnings(mode);
        CREATE INDEX IF NOT EXISTS idx_consolidated_category ON consolidated_learnings(category);

        CREATE TABLE IF NOT EXISTS learning_vectors (
            learning_id INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL,
            dimension INTEGER NOT NULL,
            model TEXT DEFAULT 'deepseek-chat',
            created_at TEXT NOT NULL,
            FOREIGN KEY (learning_id) REFERENCES learnings(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_learning_vectors_model ON learning_vectors(model);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init learnings DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── Store Learnings ────────────────────────────────────

    def add_learning(self, learning_type: str, mode: str, category: str,
                     content: str, importance: float = 0.5,
                     context: Optional[Dict] = None,
                     source: Optional[str] = None) -> Optional[int]:
        """Store a new learning.

        Args:
            learning_type: INSIGHT | ERROR | PREFERENCE
            mode: chat | coding | fin | all
            category: Topic area (e.g., "api_usage", "code_style", "user_preference")
            content: The actual learning (human-readable)
            importance: 0.0-1.0, higher = more important
            context: When this applies (JSON dict of conditions)
            source: What triggered this (e.g., "user_feedback", "error_analysis")

        Returns:
            Learning ID, or None on failure
        """
        # Dedup: check if very similar learning exists
        existing = self._find_similar(mode, category, content)
        if existing:
            # Strengthen existing instead of duplicating
            self._strengthen(existing["id"])
            logger.debug(f"Strengthened existing learning #{existing['id']}")
            return existing["id"]

        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            cursor = conn.execute(
                """INSERT INTO learnings
                   (type, mode, category, content, context, importance,
                    recall_count, created_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (learning_type, mode, category, content,
                 json.dumps(context or {}), min(1.0, max(0.0, importance)),
                 now, source)
            )
            learning_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO learning_events (learning_id, event_type, ts, detail) VALUES (?, 'created', ?, ?)",
                (learning_id, now, source)
            )
            conn.commit()
            conn.close()
            logger.info(f"New {learning_type} learning #{learning_id}: {content[:80]}")
            return learning_id
        except Exception as e:
            logger.error(f"Failed to add learning: {e}")
            return None

    def add_error_learning(self, mode: str, error_type: str,
                           error_msg: str, fix: str,
                           source: str = "auto") -> Optional[int]:
        """Shortcut: store an error + its fix as a learning."""
        content = f"Error: {error_type} — {error_msg[:150]}\nFix: {fix}"
        return self.add_learning(
            "ERROR", mode, f"error_{error_type}",
            content, importance=0.7,
            context={"error_type": error_type},
            source=source
        )

    def add_preference_learning(self, mode: str, key: str,
                                value: str, source: str = "user_feedback") -> Optional[int]:
        """Shortcut: store a user preference as a learning."""
        return self.add_learning(
            "PREFERENCE", mode, f"pref_{key}",
            f"User prefers: {key} = {value}",
            importance=0.8,
            context={"preference_key": key, "preference_value": value},
            source=source
        )

    # ── Recall Learnings ───────────────────────────────────

    def get_relevant(self, mode: str, context: Optional[Dict] = None,
                     limit: int = MAX_PROMPT_LEARNINGS,
                     query_embedding: Optional[List[float]] = None) -> List[Dict]:
        """Get learnings relevant to current context, ranked by strength.

        Returns learnings for both the specific mode and "all" mode,
        sorted by current strength (importance * decay * recall bonus).

        If query_embedding is provided and vectors are stored, uses vector search
        as a supplementary signal to boost semantically similar learnings.

        Args:
            mode: chat | coding | fin | all
            context: Optional context dict for filtering
            limit: Max learnings to return
            query_embedding: Optional embedding vector for semantic search
        """
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT * FROM learnings
                   WHERE mode IN (?, 'all')
                   ORDER BY importance DESC""",
                (mode,)
            ).fetchall()
            conn.close()

            # Calculate strength and sort
            scored = []
            now = datetime.now(timezone.utc)
            for row in rows:
                strength = self._calculate_strength(dict(row), now)
                if strength > PRUNE_THRESHOLD:
                    entry = dict(row)
                    entry["_strength"] = strength
                    scored.append(entry)

            # If query embedding provided, use vector search as supplementary signal
            if query_embedding is not None:
                vector_results = self.vector_search(
                    query_embedding,
                    mode=mode,
                    limit=limit * 2,
                    threshold=VECTOR_SIMILARITY_THRESHOLD
                )

                # Merge vector results with strength-based results
                # Boost vector-matched items by similarity * 0.3
                vector_ids = set()
                for vresult in vector_results:
                    vector_ids.add(vresult["id"])
                    # Find matching entry in scored and boost it
                    for entry in scored:
                        if entry["id"] == vresult["id"]:
                            boost = vresult.get("_similarity", 0) * 0.3
                            entry["_strength"] = min(1.0, entry["_strength"] + boost)
                            entry["_vector_similarity"] = vresult.get("_similarity", 0)
                            break

            scored.sort(key=lambda x: x["_strength"], reverse=True)
            return scored[:limit]
        except Exception as e:
            logger.error(f"Failed to get learnings: {e}")
            return []

    def get_prompt_injection(self, mode: str,
                             max_tokens: int = MAX_PROMPT_TOKENS) -> str:
        """Format top learnings for system prompt injection.

        Returns a concise block of text to append to the system prompt,
        containing the agent's most relevant learnings.
        """
        learnings = self.get_relevant(mode)
        if not learnings:
            return ""

        lines = ["[NeoMind Learnings — auto-extracted, strength-ranked]"]
        token_estimate = 10  # header

        for l in learnings:
            line = f"- [{l['type']}] {l['content']}"
            # Rough token estimate: ~4 chars per token
            tokens = len(line) // 4
            if token_estimate + tokens > max_tokens:
                break
            lines.append(line)
            token_estimate += tokens

            # Record recall
            self.recall(l["id"])

        return "\n".join(lines) if len(lines) > 1 else ""

    def recall(self, learning_id: int):
        """Mark a learning as recalled — strengthens it against decay."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn = self._conn()
            conn.execute(
                """UPDATE learnings
                   SET recall_count = recall_count + 1, last_recalled_at = ?
                   WHERE id = ?""",
                (now, learning_id)
            )
            conn.execute(
                "INSERT INTO learning_events (learning_id, event_type, ts) VALUES (?, 'recalled', ?)",
                (learning_id, now)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to record recall: {e}")

    # ── LLM-Assisted Extraction ────────────────────────────

    def extract_learnings_prompt(self, conversation_summary: str,
                                 mode: str) -> str:
        """Generate a prompt for LLM to extract learnings from a conversation.

        The caller should send this to the LLM and parse the JSON result,
        then call add_learning() for each extracted learning.

        Returns:
            Prompt string for LLM
        """
        return f"""Analyze this conversation and extract learnings for future improvement.

Conversation ({mode} mode):
{conversation_summary[:2000]}

Extract 0-3 learnings in this JSON format:
[
  {{
    "type": "INSIGHT" | "ERROR" | "PREFERENCE",
    "category": "short_topic_name",
    "content": "One sentence describing what was learned",
    "importance": 0.1-1.0
  }}
]

Rules:
- Only extract genuinely useful, actionable learnings
- Skip trivial or obvious observations
- INSIGHT = something that improves future responses
- ERROR = a mistake to avoid next time
- PREFERENCE = something about what the user wants
- Return empty array [] if nothing notable was learned

JSON output only, no explanation:"""

    def ingest_llm_learnings(self, llm_output: str, mode: str,
                              source: str = "conversation_extraction") -> int:
        """Parse LLM extraction output and store learnings.

        Returns: number of learnings stored
        """
        count = 0
        try:
            # Strip markdown fences if present
            text = llm_output.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("\n", 1)[0]

            items = json.loads(text)
            if not isinstance(items, list):
                return 0

            for item in items[:5]:  # Max 5 per extraction
                if all(k in item for k in ("type", "category", "content")):
                    self.add_learning(
                        learning_type=item["type"],
                        mode=mode,
                        category=item["category"],
                        content=item["content"],
                        importance=item.get("importance", 0.5),
                        source=source,
                    )
                    count += 1
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Failed to parse LLM learnings: {e}")
        return count

    # ── Decay & Maintenance ────────────────────────────────

    def decay_and_prune(self) -> Tuple[int, int]:
        """Run Ebbinghaus decay and prune weak old learnings.

        Should be called daily (by scheduler).

        Returns:
            (total_learnings, pruned_count)
        """
        try:
            conn = self._conn()
            rows = conn.execute("SELECT * FROM learnings").fetchall()
            now = datetime.now(timezone.utc)
            pruned = 0

            for row in rows:
                strength = self._calculate_strength(dict(row), now)
                age_days = (now - datetime.fromisoformat(row["created_at"])).days

                if strength < PRUNE_THRESHOLD and age_days > PRUNE_AGE_DAYS:
                    conn.execute("DELETE FROM learnings WHERE id = ?", (row["id"],))
                    conn.execute(
                        "INSERT INTO learning_events (learning_id, event_type, ts, detail) "
                        "VALUES (?, 'pruned', ?, ?)",
                        (row["id"], now.isoformat(), f"strength={strength:.3f}")
                    )
                    pruned += 1

            conn.commit()
            total = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
            conn.close()

            if pruned:
                logger.info(f"Learnings pruned: {pruned} (remaining: {total})")
            return total, pruned
        except Exception as e:
            logger.error(f"Decay/prune failed: {e}")
            return 0, 0

    # ── Sleep-Cycle Memory Consolidation ────────────────────

    def consolidate(self) -> Dict[str, int]:
        """Sleep-cycle memory consolidation — run during off-peak hours.

        Inspired by Claude's Auto Dream pattern:
        1. Merge redundant learnings within same category
        2. Promote frequently-recalled learnings
        3. Cross-link related learnings
        4. Archive old-but-strong learnings

        Returns: {"merged": N, "promoted": N, "archived": N, "cross_linked": N}
        """
        try:
            conn = self._conn()
            now = datetime.now(timezone.utc)

            merged = 0
            promoted = 0
            archived = 0
            cross_linked = 0

            # Step 1: Group learnings by mode and category, then merge
            for mode in ["chat", "coding", "fin", "all"]:
                categories = conn.execute(
                    "SELECT DISTINCT category FROM learnings WHERE mode = ?",
                    (mode,)
                ).fetchall()

                for cat_row in categories:
                    category = cat_row[0]
                    learnings = conn.execute(
                        "SELECT * FROM learnings WHERE mode = ? AND category = ?",
                        (mode, category)
                    ).fetchall()
                    merged += self._merge_similar_learnings(conn, mode, category, learnings)

            conn.commit()

            # Step 2: Promote frequently-recalled learnings
            promoted = self._promote_learnings(conn, now)

            # Step 3: Archive old-but-strong learnings
            archived = self._archive_old_strong(conn, now)

            # Step 4: Cross-link related learnings
            cross_linked = self._cross_link_learnings(conn, now)

            conn.commit()
            conn.close()

            logger.info(
                f"Consolidation complete: merged={merged}, promoted={promoted}, "
                f"archived={archived}, cross_linked={cross_linked}"
            )
            return {
                "merged": merged,
                "promoted": promoted,
                "archived": archived,
                "cross_linked": cross_linked,
            }
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return {"merged": 0, "promoted": 0, "archived": 0, "cross_linked": 0}

    def _merge_similar_learnings(self, conn: sqlite3.Connection, mode: str,
                                 category: str, learnings: List) -> int:
        """Merge learnings with overlapping content in same category."""
        merged = 0
        now = datetime.now(timezone.utc).isoformat()

        # Sort by strength (keep strongest, merge weaker)
        learning_dicts = [dict(row) for row in learnings]
        learning_dicts.sort(
            key=lambda x: self._calculate_strength(x, datetime.now(timezone.utc)),
            reverse=True
        )

        if len(learning_dicts) < 2:
            return 0

        # Keep the strongest, check others for similarity
        keeper = learning_dicts[0]
        keeper_id = keeper["id"]
        related = []

        for candidate in learning_dicts[1:]:
            # Simple similarity: check if content overlap > 50%
            keeper_content = keeper["content"].lower()[:100]
            cand_content = candidate["content"].lower()[:100]

            overlap = sum(1 for a, b in zip(keeper_content, cand_content) if a == b)
            similarity = overlap / max(len(keeper_content), len(cand_content))

            if similarity > 0.5:
                # Merge: strengthen keeper, delete candidate
                candidate_id = candidate["id"]
                conn.execute(
                    """UPDATE learnings
                       SET importance = MIN(1.0, importance + 0.15),
                           recall_count = recall_count + ?
                       WHERE id = ?""",
                    (candidate["recall_count"], keeper_id)
                )
                related.append(candidate_id)
                conn.execute("DELETE FROM learnings WHERE id = ?", (candidate_id,))
                conn.execute(
                    "INSERT INTO learning_events (learning_id, event_type, ts, detail) "
                    "VALUES (?, 'merged', ?, ?)",
                    (candidate_id, now, f"merged_into={keeper_id}")
                )
                merged += 1

        # Update keeper's related_ids if we merged anything
        if related:
            try:
                existing_related = json.loads(keeper.get("related_ids") or "[]")
                existing_related.extend(related)
                existing_related = list(set(existing_related))  # deduplicate
                conn.execute(
                    "UPDATE learnings SET related_ids = ? WHERE id = ?",
                    (json.dumps(existing_related), keeper_id)
                )
            except Exception:
                pass

        return merged

    def _promote_learnings(self, conn: sqlite3.Connection, now: datetime) -> int:
        """Promote frequently-recalled learnings to higher importance."""
        promoted = 0
        now_iso = now.isoformat()

        # Find learnings with high recall count relative to age
        rows = conn.execute("SELECT * FROM learnings").fetchall()

        for row in rows:
            row_dict = dict(row)
            recall_count = row_dict.get("recall_count", 0)
            created = datetime.fromisoformat(row_dict["created_at"])
            age_days = max(1, (now - created).days)

            # Recall rate: recalls per day
            recall_rate = recall_count / age_days

            # Promote if high recall rate (>1 per day) and not already at max importance
            if recall_rate > 1.0 and row_dict["importance"] < 0.95:
                new_importance = min(1.0, row_dict["importance"] + 0.2)
                conn.execute(
                    "UPDATE learnings SET importance = ? WHERE id = ?",
                    (new_importance, row_dict["id"])
                )
                conn.execute(
                    "INSERT INTO learning_events (learning_id, event_type, ts, detail) "
                    "VALUES (?, 'promoted', ?, ?)",
                    (row_dict["id"], now_iso, f"recall_rate={recall_rate:.2f}")
                )
                promoted += 1

        return promoted

    def _archive_old_strong(self, conn: sqlite3.Connection, now: datetime) -> int:
        """Archive old but strong learnings to consolidated table."""
        archived = 0
        now_iso = now.isoformat()
        cutoff_days = 90  # Archive learnings older than 90 days

        rows = conn.execute("SELECT * FROM learnings").fetchall()

        for row in rows:
            row_dict = dict(row)
            created = datetime.fromisoformat(row_dict["created_at"])
            age_days = (now - created).days
            strength = self._calculate_strength(row_dict, now)

            # Archive if old (90+ days) AND strong (>0.6 strength)
            if age_days >= cutoff_days and strength > 0.6:
                try:
                    conn.execute(
                        """INSERT INTO consolidated_learnings
                           (original_id, type, mode, category, content, context,
                            importance, recall_count, created_at, consolidated_at, related_ids)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (row_dict["id"], row_dict["type"], row_dict["mode"],
                         row_dict["category"], row_dict["content"], row_dict["context"],
                         row_dict["importance"], row_dict["recall_count"],
                         row_dict["created_at"], now_iso, row_dict.get("related_ids"))
                    )
                    conn.execute("DELETE FROM learnings WHERE id = ?", (row_dict["id"],))
                    conn.execute(
                        "INSERT INTO learning_events (learning_id, event_type, ts, detail) "
                        "VALUES (?, 'consolidated', ?, ?)",
                        (row_dict["id"], now_iso, f"strength={strength:.3f}")
                    )
                    archived += 1
                except Exception as e:
                    logger.debug(f"Failed to archive learning {row_dict['id']}: {e}")

        return archived

    def _cross_link_learnings(self, conn: sqlite3.Connection, now: datetime) -> int:
        """Cross-link related learnings based on content and category similarity."""
        cross_linked = 0
        now_iso = now.isoformat()

        rows = conn.execute("SELECT * FROM learnings").fetchall()
        learning_dicts = [dict(row) for row in rows]

        # Build graph of relationships
        for i, learning1 in enumerate(learning_dicts):
            related_ids = []

            # Find related learnings: same category or similar content
            for j, learning2 in enumerate(learning_dicts):
                if i >= j:
                    continue

                # Same category = related
                if learning1["category"] == learning2["category"]:
                    related_ids.append(learning2["id"])
                    continue

                # Similar content in same mode
                if learning1["mode"] == learning2["mode"]:
                    content1 = learning1["content"].lower()[:100]
                    content2 = learning2["content"].lower()[:100]
                    overlap = sum(1 for a, b in zip(content1, content2) if a == b)
                    similarity = overlap / max(len(content1), len(content2))

                    if similarity > 0.4:
                        related_ids.append(learning2["id"])

            # Update related_ids if we found any
            if related_ids:
                try:
                    existing = json.loads(learning1.get("related_ids") or "[]")
                    combined = list(set(existing + related_ids))
                    conn.execute(
                        "UPDATE learnings SET related_ids = ? WHERE id = ?",
                        (json.dumps(combined), learning1["id"])
                    )
                    if combined != existing:
                        cross_linked += 1
                except Exception:
                    pass

        return cross_linked

    # ── Vector Search ──────────────────────────────────────────

    def store_embedding(self, learning_id: int, embedding: List[float],
                        model: str = "deepseek-chat") -> bool:
        """Store an embedding vector for a learning.

        Args:
            learning_id: ID of the learning to embed
            embedding: Float list of embedding values
            model: Name of the model that generated the embedding

        Returns:
            True if successful, False otherwise
        """
        if not embedding or len(embedding) == 0:
            logger.warning(f"Empty embedding for learning {learning_id}")
            return False

        try:
            blob = self._pack_embedding(embedding)
            now = datetime.now(timezone.utc).isoformat()
            conn = self._conn()
            conn.execute(
                """INSERT OR REPLACE INTO learning_vectors
                   (learning_id, embedding, dimension, model, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (learning_id, blob, len(embedding), model, now)
            )
            conn.commit()
            conn.close()
            logger.debug(f"Stored embedding for learning {learning_id} (dim={len(embedding)})")
            return True
        except Exception as e:
            logger.error(f"Failed to store embedding for learning {learning_id}: {e}")
            return False

    def vector_search(self, query_embedding: List[float],
                      mode: Optional[str] = None,
                      limit: int = MAX_VECTOR_SEARCH_RESULTS,
                      threshold: float = VECTOR_SIMILARITY_THRESHOLD) -> List[Dict]:
        """Perform semantic vector search across stored embeddings.

        Uses brute-force cosine similarity search. Returns learnings sorted
        by semantic similarity to the query embedding.

        Args:
            query_embedding: Query embedding vector
            mode: Optional mode filter (chat, coding, fin, all)
            limit: Max results to return
            threshold: Min cosine similarity (0.0-1.0) to include result

        Returns:
            List of learning dicts with _similarity score, sorted descending
        """
        if not query_embedding or len(query_embedding) == 0:
            logger.warning("Empty query embedding for vector search")
            return []

        try:
            conn = self._conn()

            # Get all vectorized learnings
            if mode:
                rows = conn.execute(
                    """SELECT l.*, v.embedding, v.dimension
                       FROM learnings l
                       JOIN learning_vectors v ON l.id = v.learning_id
                       WHERE l.mode IN (?, 'all')""",
                    (mode,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT l.*, v.embedding, v.dimension
                       FROM learnings l
                       JOIN learning_vectors v ON l.id = v.learning_id"""
                ).fetchall()

            conn.close()

            # Score by cosine similarity
            scored = []
            for row in rows:
                row_dict = dict(row)
                try:
                    # Unpack the embedding blob
                    dimension = row_dict["dimension"]
                    embedding_blob = row_dict["embedding"]
                    stored_embedding = self._unpack_embedding(embedding_blob, dimension)

                    # Compute cosine similarity
                    similarity = self._cosine_similarity(query_embedding, stored_embedding)

                    if similarity >= threshold:
                        entry = {k: v for k, v in row_dict.items()
                                if k not in ("embedding", "dimension")}
                        entry["_similarity"] = similarity
                        scored.append(entry)
                except Exception as e:
                    logger.debug(f"Failed to score embedding for learning {row_dict.get('id')}: {e}")
                    continue

            # Sort by similarity descending
            scored.sort(key=lambda x: x["_similarity"], reverse=True)
            return scored[:limit]
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def get_embedding_stats(self) -> Dict[str, Any]:
        """Return statistics on vectorized learnings.

        Returns:
            Dict with vectorized_count, total_learnings, coverage_pct
        """
        try:
            conn = self._conn()
            vectorized = conn.execute(
                "SELECT COUNT(*) FROM learning_vectors"
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM learnings"
            ).fetchone()[0]
            conn.close()

            coverage = (vectorized / total * 100) if total > 0 else 0
            return {
                "vectorized_count": vectorized,
                "total_learnings": total,
                "coverage_pct": round(coverage, 1),
            }
        except Exception as e:
            logger.error(f"Failed to get embedding stats: {e}")
            return {"vectorized_count": 0, "total_learnings": 0, "coverage_pct": 0}

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec_a: Vector A
            vec_b: Vector B

        Returns:
            Cosine similarity score (-1.0 to 1.0, typically 0.0-1.0)
        """
        if len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    @staticmethod
    def _pack_embedding(embedding: List[float]) -> bytes:
        """Pack a float list into a binary blob.

        Args:
            embedding: List of floats

        Returns:
            Packed binary blob
        """
        try:
            return struct.pack(f'{len(embedding)}f', *embedding)
        except Exception as e:
            logger.error(f"Failed to pack embedding: {e}")
            return b""

    @staticmethod
    def _unpack_embedding(blob: bytes, dimension: int) -> List[float]:
        """Unpack a binary blob into a float list.

        Args:
            blob: Binary blob
            dimension: Expected number of dimensions

        Returns:
            List of floats
        """
        try:
            return list(struct.unpack(f'{dimension}f', blob))
        except Exception as e:
            logger.error(f"Failed to unpack embedding: {e}")
            return []

    # ── Statistics ─────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return learning statistics for dashboard."""
        try:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
            by_type = {}
            for row in conn.execute("SELECT type, COUNT(*) as c FROM learnings GROUP BY type"):
                by_type[row["type"]] = row["c"]
            by_mode = {}
            for row in conn.execute("SELECT mode, COUNT(*) as c FROM learnings GROUP BY mode"):
                by_mode[row["mode"]] = row["c"]

            avg_strength = 0
            rows = conn.execute("SELECT * FROM learnings").fetchall()
            now = datetime.now(timezone.utc)
            if rows:
                strengths = [self._calculate_strength(dict(r), now) for r in rows]
                avg_strength = sum(strengths) / len(strengths)

            conn.close()
            return {
                "total": total,
                "by_type": by_type,
                "by_mode": by_mode,
                "avg_strength": round(avg_strength, 3),
            }
        except Exception:
            return {"total": 0}

    # ── Internal ───────────────────────────────────────────

    def _calculate_strength(self, learning: Dict, now: datetime) -> float:
        """FOREVER-enhanced Ebbinghaus forgetting curve.

        Adaptive decay rate decreases with each recall (FOREVER paper):
            λ(n) = λ₀ × (1 − β × tanh(γ × n))

        Where n = recall_count. After 3 recalls, λ drops from 0.05 to ~0.012,
        making the learning nearly permanent.

        Full formula:
            strength = importance × e^(-λ(n) × days) × (1 + n × 0.2)
        """
        importance = learning.get("importance", 0.5)
        recall_count = learning.get("recall_count", 0)
        created = datetime.fromisoformat(learning["created_at"])
        days = max(0, (now - created).total_seconds() / 86400)

        # FOREVER adaptive decay: λ decreases with recalls
        lambda_n = DECAY_LAMBDA_0 * (1 - FOREVER_BETA * math.tanh(FOREVER_GAMMA * recall_count))

        decay = math.exp(-lambda_n * days)
        recall_bonus = 1 + recall_count * 0.2

        return importance * decay * recall_bonus

    def _find_similar(self, mode: str, category: str,
                      content: str) -> Optional[Dict]:
        """Find existing learning with same category and similar content."""
        try:
            conn = self._conn()
            # Exact category match + content prefix match (first 50 chars)
            rows = conn.execute(
                """SELECT * FROM learnings
                   WHERE mode = ? AND category = ?
                   ORDER BY created_at DESC LIMIT 10""",
                (mode, category)
            ).fetchall()
            conn.close()

            content_lower = content.lower()[:100]
            for row in rows:
                existing = row["content"].lower()[:100]
                # Simple similarity: shared prefix > 60%
                overlap = sum(1 for a, b in zip(content_lower, existing) if a == b)
                if overlap > len(content_lower) * 0.6:
                    return dict(row)
            return None
        except Exception:
            return None

    def _strengthen(self, learning_id: int):
        """Increase importance of an existing learning (on duplicate)."""
        try:
            conn = self._conn()
            conn.execute(
                """UPDATE learnings
                   SET importance = MIN(1.0, importance + 0.1),
                       recall_count = recall_count + 1,
                       last_recalled_at = ?
                   WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(), learning_id)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
