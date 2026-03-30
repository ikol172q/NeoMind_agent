"""Comprehensive integration tests for NeoMind SkillForge.

Tests cover:
- Database initialization and schema
- Skill creation (forge_skill and convenience methods)
- Skill matching and retrieval
- Usage recording and automatic promotion/deprecation
- Skill lifecycle (DRAFT → TESTED → ACTIVE → PROMOTED)
- Statistics and reporting
- Recipe compression
- General bank promotion (SkillRL dual bank)
"""

import json
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sqlite3

from agent.evolution.skill_forge import SkillForge


class TestSkillForgeInitialization(unittest.TestCase):
    """Test database initialization and schema creation."""

    def setUp(self):
        """Create a temporary directory for each test."""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        # Patch the global SKILLS_DIR to use temp directory
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()

    def tearDown(self):
        """Clean up temporary directory."""
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_db_creation(self):
        """Verify that DB file is created on initialization."""
        self.assertFalse(self.db_path.exists())
        forge = SkillForge(db_path=self.db_path)
        self.assertTrue(self.db_path.exists())

    def test_tables_exist(self):
        """Verify that required tables are created."""
        forge = SkillForge(db_path=self.db_path)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check skills table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skills'")
        self.assertIsNotNone(cursor.fetchone())

        # Check skill_usage table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='skill_usage'")
        self.assertIsNotNone(cursor.fetchone())

        conn.close()

    def test_schema_columns(self):
        """Verify that skills table has all required columns."""
        forge = SkillForge(db_path=self.db_path)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(skills)")
        columns = {row[1] for row in cursor.fetchall()}

        required_columns = {
            'id', 'name', 'mode', 'status', 'trust_tier', 'trigger_type',
            'trigger_value', 'recipe_type', 'recipe', 'recipe_compressed',
            'description', 'source', 'success_count', 'failure_count',
            'total_uses', 'avg_latency_ms', 'created_at', 'updated_at',
            'promoted_at', 'bank_type'
        }
        self.assertTrue(required_columns.issubset(columns))

        conn.close()

    def test_indices_created(self):
        """Verify that indices are created for query optimization."""
        forge = SkillForge(db_path=self.db_path)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {row[0] for row in cursor.fetchall()}

        expected_indices = {
            'idx_skills_mode', 'idx_skills_status', 'idx_skills_trigger'
        }
        self.assertTrue(expected_indices.issubset(indices))

        conn.close()


class TestSkillForgeCreation(unittest.TestCase):
    """Test skill creation methods."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_forge_skill_basic(self):
        """Test basic skill creation."""
        skill_id = self.forge.forge_skill(
            name="test_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test", "example"]},
            recipe_type="code_snippet",
            recipe="print('hello')",
            description="A test skill",
            source="test"
        )

        self.assertIsNotNone(skill_id)
        self.assertIsInstance(skill_id, int)
        self.assertGreater(skill_id, 0)

    def test_forge_skill_draft_status(self):
        """Verify that newly forged skills have DRAFT status."""
        skill_id = self.forge.forge_skill(
            name="draft_skill",
            mode="coding",
            trigger_type="error_pattern",
            trigger_value={"error_pattern": "TypeError"},
            recipe_type="code_snippet",
            recipe="x = str(y)",
            description="Fix for TypeError",
            source="test"
        )

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "DRAFT")

    def test_forge_skill_in_db(self):
        """Verify that forged skill is stored in database."""
        skill_id = self.forge.forge_skill(
            name="persist_test",
            mode="fin",
            trigger_type="task_type",
            trigger_value={"task_type": "portfolio_analysis"},
            recipe_type="procedure",
            recipe=json.dumps(["step1", "step2"]),
            description="Portfolio analysis procedure",
            source="test"
        )

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT name, mode, recipe_type FROM skills WHERE id = ?",
            (skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "persist_test")
        self.assertEqual(row[1], "fin")
        self.assertEqual(row[2], "procedure")

    def test_forge_skill_duplicate(self):
        """Verify that duplicate skill names in same mode return existing ID."""
        skill_id_1 = self.forge.forge_skill(
            name="unique_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["unique"]},
            recipe_type="code_snippet",
            recipe="code1",
        )

        skill_id_2 = self.forge.forge_skill(
            name="unique_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["different"]},
            recipe_type="code_snippet",
            recipe="code2",
        )

        self.assertEqual(skill_id_1, skill_id_2)

    def test_forge_from_error_fix(self):
        """Test convenience method for error-based skills."""
        skill_id = self.forge.forge_from_error_fix(
            mode="coding",
            error_type="ImportError",
            error_pattern="No module named 'xyz'",
            fix_code="import sys; sys.path.append('/path')",
            description="Fix import errors"
        )

        self.assertIsNotNone(skill_id)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT name, trigger_type, source FROM skills WHERE id = ?",
            (skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], "fix_ImportError")
        self.assertEqual(row[1], "error_pattern")
        self.assertEqual(row[2], "error_learning")

    def test_forge_from_procedure(self):
        """Test convenience method for procedure-based skills."""
        steps = ["Open data file", "Parse CSV", "Validate schema", "Store results"]

        skill_id = self.forge.forge_from_procedure(
            mode="fin",
            task_type="data_import",
            steps=steps,
            name="import_procedure",
            description="Standard data import procedure"
        )

        self.assertIsNotNone(skill_id)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT recipe, trigger_type FROM skills WHERE id = ?",
            (skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        stored_steps = json.loads(row[0])
        self.assertEqual(stored_steps, steps)
        self.assertEqual(row[1], "task_type")


class TestSkillMatching(unittest.TestCase):
    """Test skill search and matching."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)
        self._create_test_skills()

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def _create_test_skills(self):
        """Create test skills for matching tests."""
        # Keyword-based skill
        self.forge.forge_skill(
            name="keyword_skill_1",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["error", "database"]},
            recipe_type="code_snippet",
            recipe="code1"
        )

        # Error pattern skill
        self.forge.forge_skill(
            name="error_skill_1",
            mode="chat",
            trigger_type="error_pattern",
            trigger_value={"error_pattern": "database is locked"},
            recipe_type="code_snippet",
            recipe="code2"
        )

        # Task type skill
        self.forge.forge_skill(
            name="task_skill_1",
            mode="coding",
            trigger_type="task_type",
            trigger_value={"task_type": "debugging"},
            recipe_type="code_snippet",
            recipe="code3"
        )

    def test_find_matching_skills_by_keyword(self):
        """Test finding skills by keyword match."""
        # First, promote skills so they appear in results
        self._promote_all_skills()

        context = {
            "user_query": "How do I handle database errors?",
            "error_msg": "error in database",
            "task_type": "debugging"
        }

        matches = self.forge.find_matching_skills("chat", context)

        # Should find keyword_skill_1
        self.assertGreater(len(matches), 0)
        skill_names = [m["name"] for m in matches]
        self.assertIn("keyword_skill_1", skill_names)

    def test_find_matching_skills_by_error_pattern(self):
        """Test finding skills by error pattern match."""
        self._promote_all_skills()

        context = {
            "error_msg": "database is locked",
            "task_type": "debugging"
        }

        matches = self.forge.find_matching_skills("chat", context)

        # Should find error_skill_1
        self.assertGreater(len(matches), 0)
        skill_names = [m["name"] for m in matches]
        self.assertIn("error_skill_1", skill_names)

    def test_find_matching_skills_by_task_type(self):
        """Test finding skills by task type match."""
        self._promote_all_skills()

        context = {
            "task_type": "debugging"
        }

        matches = self.forge.find_matching_skills("coding", context)

        # Should find task_skill_1
        self.assertGreater(len(matches), 0)
        skill_names = [m["name"] for m in matches]
        self.assertIn("task_skill_1", skill_names)

    def test_find_matching_skills_respects_mode(self):
        """Test that find_matching_skills respects mode filtering."""
        self._promote_all_skills()

        context = {"task_type": "debugging"}

        # Search in 'chat' mode
        matches_chat = self.forge.find_matching_skills("chat", context)
        skill_names_chat = [m["name"] for m in matches_chat]

        # task_skill_1 is coding mode only, should not appear
        self.assertNotIn("task_skill_1", skill_names_chat)

    def test_find_matching_skills_includes_all_mode(self):
        """Test that 'all' mode skills are included in any search."""
        # Create an 'all' mode skill
        self.forge.forge_skill(
            name="all_mode_skill",
            mode="all",
            trigger_type="keyword",
            trigger_value={"keywords": ["universal"]},
            recipe_type="code_snippet",
            recipe="code4"
        )
        self._promote_all_skills()

        context = {"user_query": "This is universal"}

        matches = self.forge.find_matching_skills("chat", context)
        skill_names = [m["name"] for m in matches]

        self.assertIn("all_mode_skill", skill_names)

    def test_find_matching_skills_sorts_by_success_rate(self):
        """Test that results are sorted by match score and success rate."""
        self._promote_all_skills()

        # Record different success rates for the skills
        # Get skill IDs
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT id, name FROM skills ORDER BY name")
        skill_ids = {row[1]: row[0] for row in cursor.fetchall()}
        conn.close()

        # Record successes for skill_1
        for _ in range(3):
            self.forge.record_usage(skill_ids["keyword_skill_1"], success=True, latency_ms=100)

        # Record mixed results for skill_2
        for _ in range(2):
            self.forge.record_usage(skill_ids["error_skill_1"], success=True, latency_ms=100)
        for _ in range(1):
            self.forge.record_usage(skill_ids["error_skill_1"], success=False, latency_ms=100)

        context = {
            "user_query": "error database",
            "error_msg": "error in database"
        }

        matches = self.forge.find_matching_skills("chat", context)

        # Both should match, but skill_1 should rank higher due to higher success rate
        if len(matches) >= 2:
            self.assertGreaterEqual(
                matches[0]["_success_rate"],
                matches[1]["_success_rate"]
            )

    def _promote_all_skills(self):
        """Helper to promote all skills to TESTED status."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT id FROM skills")
        skill_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        for skill_id in skill_ids:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "UPDATE skills SET status = 'TESTED' WHERE id = ?",
                (skill_id,)
            )
            conn.commit()
            conn.close()


class TestUsageRecording(unittest.TestCase):
    """Test skill usage recording and evaluation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

        # Create a test skill
        self.skill_id = self.forge.forge_skill(
            name="test_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_record_success(self):
        """Test recording a successful usage."""
        self.forge.record_usage(self.skill_id, success=True, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT success_count, failure_count, total_uses FROM skills WHERE id = ?",
            (self.skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], 1)  # success_count
        self.assertEqual(row[1], 0)  # failure_count
        self.assertEqual(row[2], 1)  # total_uses

    def test_record_failure(self):
        """Test recording a failed usage."""
        self.forge.record_usage(self.skill_id, success=False, latency_ms=50)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT success_count, failure_count, total_uses FROM skills WHERE id = ?",
            (self.skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], 0)  # success_count
        self.assertEqual(row[1], 1)  # failure_count
        self.assertEqual(row[2], 1)  # total_uses

    def test_record_multiple_usages(self):
        """Test recording multiple mixed usages."""
        for _ in range(3):
            self.forge.record_usage(self.skill_id, success=True, latency_ms=100)
        for _ in range(2):
            self.forge.record_usage(self.skill_id, success=False, latency_ms=150)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT success_count, failure_count, total_uses FROM skills WHERE id = ?",
            (self.skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], 3)  # success_count
        self.assertEqual(row[1], 2)  # failure_count
        self.assertEqual(row[2], 5)  # total_uses

    def test_record_usage_with_context(self):
        """Test recording usage with contextual information."""
        context = {"task_type": "debugging", "user_id": "user123"}
        self.forge.record_usage(
            self.skill_id, success=True, latency_ms=120, context=context
        )

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT context FROM skill_usage WHERE skill_id = ?",
            (self.skill_id,)
        )
        stored_context = json.loads(cursor.fetchone()[0])
        conn.close()

        self.assertEqual(stored_context, context)


class TestSkillLifecycle(unittest.TestCase):
    """Test skill lifecycle: DRAFT → TESTED → ACTIVE → PROMOTED."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

        self.skill_id = self.forge.forge_skill(
            name="lifecycle_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_initial_status_draft(self):
        """Test that newly forged skills start in DRAFT status."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "DRAFT")

    def test_promotion_to_tested(self):
        """Test promotion from DRAFT to TESTED on first success."""
        self.forge.record_usage(self.skill_id, success=True, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "TESTED")

    def test_promotion_to_active(self):
        """Test promotion from TESTED to ACTIVE on second success."""
        # First success
        self.forge.record_usage(self.skill_id, success=True, latency_ms=100)

        # Second success
        self.forge.record_usage(self.skill_id, success=True, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "ACTIVE")

    def test_promotion_to_promoted(self):
        """Test promotion from ACTIVE to PROMOTED (3+ uses, 70%+ success rate)."""
        # Record 3 successful uses
        for _ in range(3):
            self.forge.record_usage(self.skill_id, success=True, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "PROMOTED")

    def test_promotion_with_mixed_results(self):
        """Test promotion to PROMOTED with 70% success rate (3 success, 1 failure)."""
        # 3 successes + 1 failure = 75% success rate
        for _ in range(3):
            self.forge.record_usage(self.skill_id, success=True, latency_ms=100)
        self.forge.record_usage(self.skill_id, success=False, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        # Should still be PROMOTED with 75% > 70% threshold
        self.assertEqual(status, "PROMOTED")

    def test_no_promotion_below_threshold(self):
        """Test that skills don't promote below 70% success rate."""
        # 2 successes + 2 failures = 50% success rate
        for _ in range(2):
            self.forge.record_usage(self.skill_id, success=True, latency_ms=100)
        for _ in range(2):
            self.forge.record_usage(self.skill_id, success=False, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        # Should stay at ACTIVE (2 successes = ACTIVE) but not PROMOTED
        self.assertNotEqual(status, "PROMOTED")


class TestAutoDeprecation(unittest.TestCase):
    """Test automatic skill deprecation on poor performance."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

        self.skill_id = self.forge.forge_skill(
            name="deprecation_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_deprecation_on_five_failures(self):
        """Test that skills are deprecated after 5+ uses with <30% success rate."""
        # Record 5 failures (0% success rate)
        for _ in range(5):
            self.forge.record_usage(self.skill_id, success=False, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "DEPRECATED")

    def test_deprecation_with_low_success_rate(self):
        """Test deprecation with 5 uses and 20% success rate."""
        # 1 success + 4 failures = 20% success rate
        self.forge.record_usage(self.skill_id, success=True, latency_ms=100)
        for _ in range(4):
            self.forge.record_usage(self.skill_id, success=False, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(status, "DEPRECATED")

    def test_no_deprecation_at_boundary(self):
        """Test that skills with exactly 30% success rate are not deprecated."""
        # 2 success + 4 failures is not exactly 30%, let's use 3 success + 7 failures = 30%
        for _ in range(3):
            self.forge.record_usage(self.skill_id, success=True, latency_ms=100)
        for _ in range(7):
            self.forge.record_usage(self.skill_id, success=False, latency_ms=100)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT status FROM skills WHERE id = ?", (self.skill_id,))
        status = cursor.fetchone()[0]
        conn.close()

        # 30% exactly should not trigger deprecation (< 0.3 threshold)
        self.assertNotEqual(status, "DEPRECATED")


class TestSkillStatistics(unittest.TestCase):
    """Test statistics and reporting."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)
        self._create_test_skills()

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def _create_test_skills(self):
        """Create multiple test skills with different statuses."""
        # Draft skill
        self.forge.forge_skill(
            name="draft_skill", mode="chat", trigger_type="keyword",
            trigger_value={"keywords": ["draft"]}, recipe_type="code_snippet",
            recipe="code"
        )

        # Active skill (2 successes)
        active_id = self.forge.forge_skill(
            name="active_skill", mode="chat", trigger_type="keyword",
            trigger_value={"keywords": ["active"]}, recipe_type="code_snippet",
            recipe="code"
        )
        for _ in range(2):
            self.forge.record_usage(active_id, success=True, latency_ms=100)

        # Promoted skill (3 successes)
        promoted_id = self.forge.forge_skill(
            name="promoted_skill", mode="coding", trigger_type="keyword",
            trigger_value={"keywords": ["promoted"]}, recipe_type="code_snippet",
            recipe="code"
        )
        for _ in range(3):
            self.forge.record_usage(promoted_id, success=True, latency_ms=100)

    def test_get_stats_total_count(self):
        """Test that total skill count is correct."""
        stats = self.forge.get_stats()

        self.assertEqual(stats["total"], 3)

    def test_get_stats_by_status(self):
        """Test that skills are counted by status."""
        stats = self.forge.get_stats()

        self.assertIn("by_status", stats)
        self.assertEqual(stats["by_status"].get("DRAFT"), 1)
        self.assertEqual(stats["by_status"].get("ACTIVE"), 1)
        self.assertEqual(stats["by_status"].get("PROMOTED"), 1)

    def test_get_stats_by_mode(self):
        """Test that skills are counted by mode."""
        stats = self.forge.get_stats()

        self.assertIn("by_mode", stats)
        self.assertEqual(stats["by_mode"].get("chat"), 2)
        self.assertEqual(stats["by_mode"].get("coding"), 1)

    def test_get_stats_top_skills(self):
        """Test that top promoted skills are listed."""
        stats = self.forge.get_stats()

        self.assertIn("top_skills", stats)
        # Should only have promoted skills in top_skills
        self.assertEqual(len(stats["top_skills"]), 1)
        self.assertEqual(stats["top_skills"][0]["name"], "promoted_skill")

    def test_get_stats_empty_db(self):
        """Test statistics on empty database."""
        empty_forge = SkillForge(db_path=Path(self.test_dir) / "empty.db")
        stats = empty_forge.get_stats()

        self.assertEqual(stats["total"], 0)


class TestRecipeCompression(unittest.TestCase):
    """Test recipe compression for token efficiency."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_compress_code_snippet(self):
        """Test compression of code snippet recipes."""
        verbose_recipe = '''
def fix_error(x):
    """This is a docstring that should be removed"""
    # This is a comment that should be removed
    y = str(x)
    # More comments
    return y
        '''

        skill_id = self.forge.forge_skill(
            name="compress_test",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe=verbose_recipe,
            source="test"
        )

        compressed = self.forge.compress_recipe(skill_id)

        self.assertIsNotNone(compressed)
        self.assertLess(len(compressed), len(verbose_recipe))
        # Should contain function definition and return
        self.assertIn("def fix_error", compressed)
        self.assertIn("return", compressed)

    def test_compress_procedure(self):
        """Test compression of procedure recipes."""
        procedure = """
1. Open the file
   This is extra explanation
2. Parse the content
   More details here
3. Validate the data
   Additional notes
        """

        skill_id = self.forge.forge_skill(
            name="proc_compress",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="procedure",
            recipe=procedure,
            source="test"
        )

        compressed = self.forge.compress_recipe(skill_id)

        self.assertIsNotNone(compressed)
        self.assertIn("1.", compressed)
        self.assertIn("2.", compressed)
        self.assertIn("3.", compressed)

    def test_compress_stores_in_db(self):
        """Test that compressed recipe is stored in database."""
        skill_id = self.forge.forge_skill(
            name="store_compress",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="def test():\n    # comment\n    return True",
            source="test"
        )

        self.forge.compress_recipe(skill_id)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT recipe_compressed FROM skills WHERE id = ?",
            (skill_id,)
        )
        compressed = cursor.fetchone()[0]
        conn.close()

        self.assertIsNotNone(compressed)
        self.assertGreater(len(compressed), 0)


class TestPromoteToGeneral(unittest.TestCase):
    """Test SkillRL dual bank promotion (task-specific to general)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_promote_to_general_requires_promoted_status(self):
        """Test that only PROMOTED skills can be promoted to general."""
        skill_id = self.forge.forge_skill(
            name="test_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

        result = self.forge.promote_to_general(skill_id)

        # Should fail because skill is DRAFT, not PROMOTED
        self.assertFalse(result)

    def test_promote_to_general_requires_context_diversity(self):
        """Test that promotion to general requires 2+ different contexts."""
        skill_id = self.forge.forge_skill(
            name="diverse_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

        # Promote to PROMOTED status with all same context
        for _ in range(3):
            self.forge.record_usage(
                skill_id, success=True, latency_ms=100,
                context={"task_type": "debug"}
            )

        # One more use with same context only
        self.forge.record_usage(
            skill_id, success=True, latency_ms=100,
            context={"task_type": "debug"}
        )

        result = self.forge.promote_to_general(skill_id)

        # Should fail due to insufficient context diversity (only "debug" task_type)
        self.assertFalse(result)

    def test_promote_to_general_succeeds(self):
        """Test successful promotion to general bank with diverse contexts."""
        skill_id = self.forge.forge_skill(
            name="general_ready_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

        # Promote to PROMOTED status
        for _ in range(3):
            self.forge.record_usage(skill_id, success=True, latency_ms=100)

        # Use with 2+ different contexts
        self.forge.record_usage(
            skill_id, success=True, latency_ms=100,
            context={"task_type": "debug"}
        )
        self.forge.record_usage(
            skill_id, success=True, latency_ms=100,
            context={"task_type": "refactor"}
        )

        result = self.forge.promote_to_general(skill_id)

        self.assertTrue(result)

    def test_promote_to_general_updates_mode(self):
        """Test that promoted skills are changed to 'all' mode."""
        skill_id = self.forge.forge_skill(
            name="mode_test_skill",
            mode="chat",
            trigger_type="keyword",
            trigger_value={"keywords": ["test"]},
            recipe_type="code_snippet",
            recipe="code",
            source="test"
        )

        # Promote and record diverse contexts
        for _ in range(3):
            self.forge.record_usage(skill_id, success=True, latency_ms=100)
        self.forge.record_usage(
            skill_id, success=True, latency_ms=100,
            context={"task_type": "debug"}
        )
        self.forge.record_usage(
            skill_id, success=True, latency_ms=100,
            context={"task_type": "refactor"}
        )

        self.forge.promote_to_general(skill_id)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT mode, bank_type FROM skills WHERE id = ?", (skill_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], "all")
        self.assertEqual(row[1], "general")


class TestIntegrationWithAgenticLoop(unittest.TestCase):
    """Test integration scenarios with AgenticLoop."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = Path(self.test_dir) / "test_skills.db"
        self.skills_dir = Path(self.test_dir) / "skills"
        self.skills_dir_patcher = patch('agent.evolution.skill_forge.SKILLS_DIR', self.skills_dir)
        self.skills_dir_patcher.start()
        self.forge = SkillForge(db_path=self.db_path)

    def tearDown(self):
        self.skills_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    @patch('agent.evolution.skill_forge.logger')
    def test_find_matching_skills_on_iteration_0(self, mock_logger):
        """Test that find_matching_skills is called with appropriate context."""
        # Create and promote some skills
        for i in range(3):
            skill_id = self.forge.forge_skill(
                name=f"skill_{i}",
                mode="chat",
                trigger_type="keyword",
                trigger_value={"keywords": [f"keyword_{i}"]},
                recipe_type="code_snippet",
                recipe="code",
                source="test"
            )
            # Promote to ACTIVE
            self.forge.record_usage(skill_id, success=True, latency_ms=100)
            self.forge.record_usage(skill_id, success=True, latency_ms=100)

        # Simulate AgenticLoop calling find_matching_skills on iteration 0
        context = {
            "user_query": "How do I use keyword_0?",
            "error_msg": "",
            "task_type": "general"
        }

        matches = self.forge.find_matching_skills("chat", context)

        # Should find skill_0
        self.assertGreater(len(matches), 0)
        self.assertTrue(any(m["name"] == "skill_0" for m in matches))

    def test_integration_forge_search_use_cycle(self):
        """Test complete cycle: forge skill → search for it → record usage."""
        # Forge a skill
        skill_id = self.forge.forge_skill(
            name="integration_skill",
            mode="coding",
            trigger_type="error_pattern",
            trigger_value={"error_pattern": "IndexError"},
            recipe_type="code_snippet",
            recipe="x = [1, 2, 3]; y = x[0]",
            description="Safe list access",
            source="test"
        )

        # Promote to TESTED
        self.forge.record_usage(skill_id, success=True, latency_ms=100)

        # Search for it
        context = {"error_msg": "IndexError: list index out of range"}
        matches = self.forge.find_matching_skills("coding", context)

        self.assertGreater(len(matches), 0)

        # Use it
        matched_skill = matches[0]
        self.forge.record_usage(matched_skill["id"], success=True, latency_ms=95)

        # Verify it was recorded
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT total_uses, success_count FROM skills WHERE id = ?",
            (skill_id,)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[1], 2)  # 2 successful uses


if __name__ == "__main__":
    unittest.main()
