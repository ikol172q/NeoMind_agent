"""NeoMind Skill Forge — Crystallize Successful Solutions into Reusable Skills

When NeoMind successfully solves a novel problem, the Skill Forge:
1. Detects the solution pattern (multi-step reasoning, code snippet, tool chain)
2. Abstracts it into a reusable "skill" with trigger conditions
3. Stores it with success metrics and usage count
4. Promotes high-performing skills into the agent's permanent toolkit

Skill lifecycle:
  DRAFT → TESTED → ACTIVE → PROMOTED (or DEPRECATED)

A skill needs 3+ successful uses and >70% success rate to be PROMOTED.
(Inspired by OpenClaw's Foundry 70% crystallization, but with NeoMind's
own multi-personality + Docker-native approach.)

Difference from OpenClaw:
- OpenClaw: JS-based skills in vector index, community marketplace
- NeoMind: Python snippets + YAML configs, per-personality, local-only,
  success-metric driven promotion

No external dependencies — stdlib only.
"""

import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/skills.db")
SKILLS_DIR = Path("/data/neomind/evolution/skills")

# Promotion thresholds
MIN_USES_FOR_PROMOTION = 3
MIN_SUCCESS_RATE = 0.70   # 70% success rate
MAX_ACTIVE_SKILLS = 50    # Per mode


class SkillForge:
    """Crystallize successful solutions into reusable skills.

    A "skill" is:
    - trigger: when to activate (keywords, error patterns, task types)
    - recipe: what to do (code snippet, tool chain, prompt template)
    - metrics: success rate, usage count, avg latency
    """

    # ── SkillRL Dual Skill Bank ─────────────────────────────
    # General SkillBank: cross-task patterns that generalize
    # Task-Specific SkillBank: context-bound techniques
    # Trust tiers for skill reliability scoring
    TRUST_TIERS = {
        "system": 1.0,     # NeoMind core skills
        "verified": 0.8,   # Multi-success verified
        "user": 0.6,       # User-provided
        "external": 0.3,   # External sources
    }

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mode TEXT NOT NULL,          -- chat | coding | fin | all
            bank_type TEXT DEFAULT 'task_specific',  -- general | task_specific (SkillRL dual bank)
            status TEXT DEFAULT 'DRAFT', -- DRAFT | TESTED | ACTIVE | PROMOTED | DEPRECATED
            trust_tier TEXT DEFAULT 'system',  -- system | verified | user | external
            trigger_type TEXT NOT NULL,  -- keyword | error_pattern | task_type | context
            trigger_value TEXT NOT NULL,  -- JSON: conditions for activation
            recipe_type TEXT NOT NULL,   -- code_snippet | tool_chain | prompt_template | procedure
            recipe TEXT NOT NULL,        -- the actual solution template
            recipe_compressed TEXT,      -- compressed version for token efficiency (SkillRL 10-20x)
            description TEXT,
            source TEXT,                 -- how this skill was discovered
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            total_uses INTEGER DEFAULT 0,
            avg_latency_ms REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            promoted_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_skills_mode ON skills(mode);
        CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);
        CREATE INDEX IF NOT EXISTS idx_skills_trigger ON skills(trigger_type);

        CREATE TABLE IF NOT EXISTS skill_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id INTEGER NOT NULL,
            success INTEGER NOT NULL,    -- 0 or 1
            latency_ms REAL,
            context TEXT,                -- JSON: what was the context
            ts TEXT NOT NULL
        );
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init skills DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── Create Skills ──────────────────────────────────────

    def forge_skill(self, name: str, mode: str,
                    trigger_type: str, trigger_value: Dict,
                    recipe_type: str, recipe: str,
                    description: str = "",
                    source: str = "auto_detected") -> Optional[int]:
        """Create a new skill from a successful solution.

        Args:
            name: Short skill name (e.g., "fix_sqlite_locked")
            mode: Which personality mode (chat/coding/fin/all)
            trigger_type: "keyword" | "error_pattern" | "task_type" | "context"
            trigger_value: Dict of trigger conditions
                e.g., {"keywords": ["sqlite", "locked"]}
                e.g., {"error_pattern": "database is locked"}
                e.g., {"task_type": "data_analysis"}
            recipe_type: "code_snippet" | "tool_chain" | "prompt_template" | "procedure"
            recipe: The actual solution (code, steps, template)
            description: Human-readable description
            source: How this skill was discovered

        Returns:
            Skill ID, or None on failure
        """
        # Check for duplicate
        existing = self._find_by_name(name, mode)
        if existing:
            logger.debug(f"Skill '{name}' already exists for {mode}")
            return existing["id"]

        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            cursor = conn.execute(
                """INSERT INTO skills
                   (name, mode, status, trigger_type, trigger_value,
                    recipe_type, recipe, description, source,
                    created_at, updated_at)
                   VALUES (?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, mode, trigger_type, json.dumps(trigger_value),
                 recipe_type, recipe, description, source, now, now)
            )
            skill_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # Also save as a file for easy browsing
            self._save_skill_file(skill_id, name, mode, recipe_type, recipe, description)

            logger.info(f"Forged new skill #{skill_id}: {name} ({mode})")
            return skill_id
        except Exception as e:
            logger.error(f"Failed to forge skill: {e}")
            return None

    def forge_from_error_fix(self, mode: str, error_type: str,
                              error_pattern: str, fix_code: str,
                              description: str = "") -> Optional[int]:
        """Convenience: create a skill from an error + its fix."""
        return self.forge_skill(
            name=f"fix_{error_type}",
            mode=mode,
            trigger_type="error_pattern",
            trigger_value={"error_pattern": error_pattern, "error_type": error_type},
            recipe_type="code_snippet",
            recipe=fix_code,
            description=description or f"Auto-fix for {error_type}",
            source="error_learning",
        )

    def forge_from_procedure(self, mode: str, task_type: str,
                              steps: List[str], name: str = "",
                              description: str = "") -> Optional[int]:
        """Convenience: create a skill from a multi-step procedure."""
        return self.forge_skill(
            name=name or f"procedure_{task_type}",
            mode=mode,
            trigger_type="task_type",
            trigger_value={"task_type": task_type},
            recipe_type="procedure",
            recipe=json.dumps(steps, ensure_ascii=False),
            description=description or f"Procedure for {task_type}",
            source="procedure_extraction",
        )

    # ── Match & Retrieve Skills ────────────────────────────

    def find_matching_skills(self, mode: str, context: Dict) -> List[Dict]:
        """Find skills that match the current context.

        Context can contain:
        - "error_msg": current error message
        - "task_type": type of task
        - "keywords": list of relevant keywords
        - "user_query": the user's question

        Returns skills sorted by success rate.
        """
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT * FROM skills
                   WHERE mode IN (?, 'all')
                   AND status IN ('ACTIVE', 'PROMOTED', 'TESTED')
                   ORDER BY success_count DESC""",
                (mode,)
            ).fetchall()
            conn.close()

            matches = []
            for row in rows:
                score = self._match_score(dict(row), context)
                if score > 0:
                    skill = dict(row)
                    skill["_match_score"] = score
                    skill["_success_rate"] = (
                        skill["success_count"] / max(1, skill["total_uses"])
                    )
                    matches.append(skill)

            matches.sort(key=lambda x: (x["_match_score"], x["_success_rate"]),
                         reverse=True)
            return matches[:5]
        except Exception as e:
            logger.error(f"Skill matching failed: {e}")
            return []

    def get_skill_recipe(self, skill_id: int) -> Optional[str]:
        """Get the recipe for a specific skill."""
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT recipe FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()
            conn.close()
            return row["recipe"] if row else None
        except Exception:
            return None

    # ── Record Usage & Evaluate ────────────────────────────

    def record_usage(self, skill_id: int, success: bool,
                     latency_ms: float = 0,
                     context: Optional[Dict] = None):
        """Record a skill usage outcome. Drives promotion/deprecation."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO skill_usage (skill_id, success, latency_ms, context, ts) VALUES (?, ?, ?, ?, ?)",
                (skill_id, int(success), latency_ms,
                 json.dumps(context or {}), now)
            )

            # Update skill stats
            if success:
                conn.execute(
                    """UPDATE skills SET
                       success_count = success_count + 1,
                       total_uses = total_uses + 1,
                       avg_latency_ms = (avg_latency_ms * total_uses + ?) / (total_uses + 1),
                       updated_at = ?
                       WHERE id = ?""",
                    (latency_ms, now, skill_id)
                )
            else:
                conn.execute(
                    """UPDATE skills SET
                       failure_count = failure_count + 1,
                       total_uses = total_uses + 1,
                       updated_at = ?
                       WHERE id = ?""",
                    (now, skill_id)
                )
            conn.commit()
            conn.close()

            # Check for promotion or deprecation
            self._evaluate_skill(skill_id)
        except Exception as e:
            logger.error(f"Failed to record skill usage: {e}")

    def _evaluate_skill(self, skill_id: int):
        """Check if a skill should be promoted or deprecated."""
        try:
            conn = self._conn()
            row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
            if not row:
                return
            skill = dict(row)
            conn.close()

            total = skill["total_uses"]
            success_rate = skill["success_count"] / max(1, total)

            # Promotion: enough uses + high success rate
            if (skill["status"] in ("DRAFT", "TESTED", "ACTIVE")
                    and total >= MIN_USES_FOR_PROMOTION
                    and success_rate >= MIN_SUCCESS_RATE):
                self._update_status(skill_id, "PROMOTED")
                logger.info(
                    f"Skill #{skill_id} '{skill['name']}' PROMOTED "
                    f"({total} uses, {success_rate:.0%} success)"
                )

            # Activation: first successful use
            elif skill["status"] == "DRAFT" and skill["success_count"] >= 1:
                self._update_status(skill_id, "TESTED")

            elif skill["status"] == "TESTED" and skill["success_count"] >= 2:
                self._update_status(skill_id, "ACTIVE")

            # Deprecation: too many failures
            elif total >= 5 and success_rate < 0.3:
                self._update_status(skill_id, "DEPRECATED")
                logger.info(
                    f"Skill #{skill_id} '{skill['name']}' DEPRECATED "
                    f"({success_rate:.0%} success rate)"
                )
        except Exception as e:
            logger.error(f"Skill evaluation failed: {e}")

    # ── LLM-Assisted Skill Extraction ──────────────────────

    def extract_skill_prompt(self, conversation_summary: str,
                              mode: str) -> str:
        """Generate a prompt for LLM to extract a skill from a conversation.

        Only call this when a conversation involved solving a non-trivial problem.
        """
        return f"""Analyze this conversation where a problem was successfully solved.
Extract a reusable "skill" — a recipe that can be applied to similar problems in the future.

Conversation ({mode} mode):
{conversation_summary[:2000]}

If a reusable skill can be extracted, output JSON:
{{
  "name": "short_snake_case_name",
  "trigger_type": "keyword" | "error_pattern" | "task_type",
  "trigger_value": {{"keywords": [...]}},
  "recipe_type": "code_snippet" | "procedure" | "prompt_template",
  "recipe": "the actual solution steps or code",
  "description": "one sentence description"
}}

If nothing reusable was learned, output: null

JSON only, no explanation:"""

    # ── Statistics ─────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return skill statistics for dashboard."""
        try:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            by_status = {}
            for row in conn.execute("SELECT status, COUNT(*) as c FROM skills GROUP BY status"):
                by_status[row["status"]] = row["c"]
            by_mode = {}
            for row in conn.execute("SELECT mode, COUNT(*) as c FROM skills GROUP BY mode"):
                by_mode[row["mode"]] = row["c"]

            top_skills = []
            for row in conn.execute(
                "SELECT name, mode, total_uses, success_count FROM skills "
                "WHERE status = 'PROMOTED' ORDER BY total_uses DESC LIMIT 5"
            ):
                top_skills.append(dict(row))

            conn.close()
            return {
                "total": total,
                "by_status": by_status,
                "by_mode": by_mode,
                "top_skills": top_skills,
            }
        except Exception:
            return {"total": 0}

    # ── Internal ───────────────────────────────────────────

    def _match_score(self, skill: Dict, context: Dict) -> float:
        """Score how well a skill matches the current context."""
        trigger = json.loads(skill.get("trigger_value", "{}"))
        score = 0.0

        # Keyword matching
        if skill["trigger_type"] == "keyword":
            keywords = trigger.get("keywords", [])
            query = (context.get("user_query", "") + " " +
                     context.get("error_msg", "")).lower()
            hits = sum(1 for kw in keywords if kw.lower() in query)
            if hits:
                score = hits / max(1, len(keywords))

        # Error pattern matching
        elif skill["trigger_type"] == "error_pattern":
            pattern = trigger.get("error_pattern", "").lower()
            error_msg = context.get("error_msg", "").lower()
            if pattern and pattern in error_msg:
                score = 1.0

        # Task type matching
        elif skill["trigger_type"] == "task_type":
            if trigger.get("task_type") == context.get("task_type"):
                score = 1.0

        return score

    def _find_by_name(self, name: str, mode: str) -> Optional[Dict]:
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT * FROM skills WHERE name = ? AND mode = ?",
                (name, mode)
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception:
            return None

    def _update_status(self, skill_id: int, status: str):
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn = self._conn()
            updates = {"updated_at": now}
            if status == "PROMOTED":
                conn.execute(
                    "UPDATE skills SET status = ?, updated_at = ?, promoted_at = ? WHERE id = ?",
                    (status, now, now, skill_id)
                )
            else:
                conn.execute(
                    "UPDATE skills SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, skill_id)
                )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _save_skill_file(self, skill_id: int, name: str, mode: str,
                          recipe_type: str, recipe: str, description: str):
        """Save skill as a file for easy browsing."""
        try:
            ext = ".py" if recipe_type == "code_snippet" else ".md"
            path = SKILLS_DIR / f"{mode}_{name}{ext}"
            header = f"# Skill: {name}\n# Mode: {mode}\n# {description}\n\n"
            path.write_text(header + recipe)
        except Exception:
            pass

    # ── SkillRL Dual Bank Methods ─────────────────────────

    def promote_to_general(self, skill_id: int) -> bool:
        """Promote a task-specific skill to the general bank.

        A skill is eligible when:
        - Status is PROMOTED
        - Used successfully in 2+ different contexts
        - bank_type is still 'task_specific'

        SkillRL insight: general skills are mode-agnostic and more reusable.
        """
        try:
            conn = self._conn()
            skill = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (skill_id,)
            ).fetchone()

            if not skill:
                conn.close()
                return False

            if skill["status"] != "PROMOTED" or skill["bank_type"] == "general":
                conn.close()
                return False

            # Check context diversity (2+ unique task_types in usage)
            usages = conn.execute(
                "SELECT DISTINCT context FROM skill_usage WHERE skill_id = ? AND success = 1",
                (skill_id,),
            ).fetchall()

            contexts = set()
            for u in usages:
                try:
                    ctx = json.loads(u["context"] or "{}")
                    contexts.add(ctx.get("task_type", "unknown"))
                except (json.JSONDecodeError, TypeError):
                    pass

            if len(contexts) < 2:
                conn.close()
                return False

            # Promote to general bank
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE skills SET bank_type='general', mode='all', updated_at=? WHERE id=?",
                (now, skill_id),
            )
            conn.commit()
            conn.close()

            logger.info(
                f"Skill #{skill_id} '{skill['name']}' promoted to general bank "
                f"(contexts: {contexts})"
            )
            return True

        except Exception as e:
            logger.error(f"General bank promotion failed: {e}")
            return False

    def compress_recipe(self, skill_id: int) -> Optional[str]:
        """Compress a skill's recipe for token-efficient injection.

        SkillRL approach: 10-20x token compression by extracting
        only the essential pattern from verbose recipes.

        Returns compressed recipe text, or None on failure.
        """
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT recipe, recipe_type, name FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()

            if not row:
                conn.close()
                return None

            recipe = row["recipe"]
            recipe_type = row["recipe_type"]

            # Simple compression: extract key lines
            if recipe_type == "code_snippet":
                # Keep function signatures + key logic, strip comments/docstrings
                lines = recipe.split("\n")
                compressed_lines = []
                for line in lines:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or stripped.startswith('"""'):
                        continue
                    if stripped.startswith("def ") or stripped.startswith("class "):
                        compressed_lines.append(line)
                    elif "return " in stripped or "raise " in stripped:
                        compressed_lines.append(line)
                    elif "=" in stripped and "import" not in stripped:
                        compressed_lines.append(line)
                compressed = "\n".join(compressed_lines)

            elif recipe_type == "procedure":
                # Keep numbered steps only
                lines = recipe.split("\n")
                compressed_lines = [
                    line for line in lines
                    if line.strip() and (
                        line.strip()[0].isdigit() or
                        line.strip().startswith("- ") or
                        line.strip().startswith("→")
                    )
                ]
                compressed = "\n".join(compressed_lines)

            else:
                # For other types, truncate to first 200 chars
                compressed = recipe[:200]

            # Store compressed version
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE skills SET recipe_compressed=?, updated_at=? WHERE id=?",
                (compressed, now, skill_id),
            )
            conn.commit()
            conn.close()

            ratio = len(recipe) / max(1, len(compressed))
            logger.info(
                f"Skill #{skill_id} '{row['name']}' compressed: "
                f"{len(recipe)} → {len(compressed)} chars ({ratio:.1f}x)"
            )
            return compressed

        except Exception as e:
            logger.error(f"Recipe compression failed: {e}")
            return None

    def auto_promote_to_general(self) -> list[int]:
        """Scan all PROMOTED task-specific skills and promote eligible ones."""
        promoted = []
        try:
            conn = self._conn()
            candidates = conn.execute(
                "SELECT id FROM skills WHERE status='PROMOTED' AND bank_type='task_specific'"
            ).fetchall()
            conn.close()

            for row in candidates:
                if self.promote_to_general(row["id"]):
                    promoted.append(row["id"])
                    # Also compress the newly promoted skill
                    self.compress_recipe(row["id"])

        except Exception as e:
            logger.error(f"Auto-promote scan failed: {e}")

        return promoted
