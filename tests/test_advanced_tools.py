"""Tests for advanced tool modules."""
import os
import sys
import tempfile
import unittest
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)

from agent.tools.task_tools import TaskManager, TaskStatus
from agent.services.config_editor import ConfigEditor
from agent.services.mcp_client.client import MCPClient, MCPTool, MCPResult
from agent.skills.loader import SkillLoader, Skill
from agent.tools.collaboration_tools import ScheduleCronTool


# ---------------------------------------------------------------------------
# TestWorktreeTool — git worktree operations
# ---------------------------------------------------------------------------

class TestWorktreeTool(unittest.TestCase):
    """Test git worktree-like operations using GitTools as a proxy."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_worktree_on_non_git_dir(self):
        """Worktree list on non-git dir should fail."""
        from agent.tools.git_tools import GitTools
        git = GitTools(working_dir=self.tmpdir)
        result = git._run("worktree", "list")
        self.assertFalse(result.success)

    def test_worktree_list_on_git_repo(self):
        """Worktree list on a valid git repo should succeed."""
        from agent.tools.git_tools import GitTools
        git = GitTools(working_dir=self.tmpdir)
        git._run("init")
        result = git._run("worktree", "list")
        self.assertTrue(result.success)
        self.assertIn(self.tmpdir, result.output)

    def test_worktree_add_and_remove(self):
        """Add and remove a git worktree."""
        from agent.tools.git_tools import GitTools
        git = GitTools(working_dir=self.tmpdir)
        git._run("init")
        git._run("config", "user.email", "test@test.com")
        git._run("config", "user.name", "Test")

        # Need at least one commit
        f = os.path.join(self.tmpdir, "init.txt")
        with open(f, "w") as fh:
            fh.write("init\n")
        git._run("add", "init.txt")
        git._run("commit", "-m", "init")

        wt_path = os.path.join(self.tmpdir, "worktree-branch")
        result = git._run("worktree", "add", wt_path, "-b", "wt-branch")
        self.assertTrue(result.success, f"worktree add failed: {result.error}")

        # Remove
        remove = git._run("worktree", "remove", wt_path)
        self.assertTrue(remove.success, f"worktree remove failed: {remove.error}")


# ---------------------------------------------------------------------------
# TestREPLTool — Python code execution
# ---------------------------------------------------------------------------

class TestREPLTool(unittest.TestCase):
    """Test REPL-like Python code execution."""

    def test_execute_python_code(self):
        """Execute simple Python code and capture output."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", "print(2+2)"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "4")

    def test_execute_bad_code(self):
        """Bad Python code returns non-zero exit code."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", "raise ValueError('boom')"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ValueError", result.stderr)

    def test_session_independence(self):
        """Separate REPL invocations are independent."""
        import subprocess
        # Set variable in one session
        r1 = subprocess.run(
            [sys.executable, "-c", "x = 42; print(x)"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r1.stdout.strip(), "42")

        # Variable should not exist in another session
        r2 = subprocess.run(
            [sys.executable, "-c", "print(x)"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(r2.returncode, 0)


# ---------------------------------------------------------------------------
# TestMCPTool
# ---------------------------------------------------------------------------

class TestMCPTool(unittest.TestCase):
    """Test MCPClient initialization and introspection."""

    def test_init_empty(self):
        """MCPClient starts with no servers or tools."""
        client = MCPClient()
        self.assertEqual(len(client.list_tools()), 0)
        self.assertEqual(len(client.list_servers()), 0)

    def test_list_servers_when_empty(self):
        """list_servers returns empty dict when no servers connected."""
        client = MCPClient()
        servers = client.list_servers()
        self.assertIsInstance(servers, dict)
        self.assertEqual(len(servers), 0)

    def test_call_unknown_tool(self):
        """Calling an unknown tool returns an error result."""

        async def _test():
            client = MCPClient()
            result = await client.call_tool("nonexistent_tool")
            self.assertFalse(result.success)
            self.assertIn("Unknown tool", result.error)

        asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# TestSkillTool
# ---------------------------------------------------------------------------

class TestSkillTool(unittest.TestCase):
    """Test SkillLoader."""

    def test_list_skills_empty_dir(self):
        """SkillLoader with empty dir returns no skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = SkillLoader(skills_dir=tmpdir)
            count = loader.load_all()
            self.assertEqual(count, 0)
            self.assertEqual(loader.list_skills(), [])

    def test_load_skill_from_file(self):
        """SkillLoader parses a SKILL.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create shared/my-skill/SKILL.md
            skill_dir = Path(tmpdir) / "shared" / "my-skill"
            skill_dir.mkdir(parents=True)
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text(
                "---\n"
                "name: my-skill\n"
                "description: A test skill\n"
                "modes: [chat, coding]\n"
                "version: 1.0.0\n"
                "---\n\n"
                "# My Skill\n\n"
                "This is the skill prompt body.\n"
            )

            loader = SkillLoader(skills_dir=tmpdir)
            count = loader.load_all()
            self.assertEqual(count, 1)

            skill = loader.get("my-skill")
            self.assertIsNotNone(skill)
            self.assertEqual(skill.name, "my-skill")
            self.assertEqual(skill.description, "A test skill")
            self.assertIn("chat", skill.modes)
            self.assertIn("coding", skill.modes)
            self.assertIn("My Skill", skill.body)

    def test_get_skills_for_mode(self):
        """SkillLoader filters skills by mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for cat, name, modes in [
                ("shared", "global-skill", "[chat, coding, fin]"),
                ("coding", "code-only", "[coding]"),
            ]:
                d = Path(tmpdir) / cat / name
                d.mkdir(parents=True)
                (d / "SKILL.md").write_text(
                    f"---\nname: {name}\nmodes: {modes}\n---\nBody\n"
                )

            loader = SkillLoader(skills_dir=tmpdir)
            loader.load_all()

            coding_skills = loader.get_skills_for_mode("coding")
            self.assertEqual(len(coding_skills), 2)

            fin_skills = loader.get_skills_for_mode("fin")
            self.assertEqual(len(fin_skills), 1)
            self.assertEqual(fin_skills[0].name, "global-skill")


# ---------------------------------------------------------------------------
# TestConfigTool
# ---------------------------------------------------------------------------

class TestConfigTool(unittest.TestCase):
    """Test ConfigEditor get/set/reset."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "overrides.yaml"
        self.editor = ConfigEditor(overrides_path=self.config_path)
        # Override history dir to temp
        self.editor.history_dir = Path(self.tmpdir) / "history"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_empty(self):
        """Loading when no file exists returns empty dict."""
        data = self.editor.load()
        self.assertEqual(data, {})

    def test_set_and_get_setting(self):
        """Set a setting and retrieve it."""
        self.editor.set_setting("chat", "temperature", 0.7)
        val = self.editor.get_setting("chat", "temperature")
        self.assertEqual(val, 0.7)

    def test_set_extra_prompt(self):
        """Set and get extra system prompt for a mode."""
        self.editor.set_extra_prompt("coding", "Always use type hints.")
        prompt = self.editor.get_extra_prompt("coding")
        self.assertEqual(prompt, "Always use type hints.")

    def test_reset_mode(self):
        """Reset a mode's overrides."""
        self.editor.set_setting("fin", "key", "value")
        self.editor.reset_mode("fin")
        data = self.editor.get_mode_overrides("fin")
        self.assertEqual(data, {})

    def test_reset_all(self):
        """Reset all overrides."""
        self.editor.set_setting("chat", "a", 1)
        self.editor.set_setting("fin", "b", 2)
        self.editor.reset_all()
        data = self.editor.load()
        self.assertEqual(data, {})

    def test_search_triggers(self):
        """Add and remove search triggers."""
        self.editor.add_search_triggers(["AI", "GPU"], mode="fin")
        triggers = self.editor.get_extra_search_triggers("fin")
        self.assertIn("AI", triggers)
        self.assertIn("GPU", triggers)

        self.editor.remove_search_triggers(["GPU"], mode="fin")
        triggers2 = self.editor.get_extra_search_triggers("fin")
        self.assertIn("AI", triggers2)
        self.assertNotIn("GPU", triggers2)


# ---------------------------------------------------------------------------
# TestToolSearchTool — search tool registry
# ---------------------------------------------------------------------------

class TestToolSearchTool(unittest.TestCase):
    """Test tool search against a mock registry."""

    def test_search_by_name(self):
        """Search a mock tool registry by name."""
        tools = {
            "Bash": {"description": "Execute shell commands"},
            "Read": {"description": "Read file contents"},
            "Edit": {"description": "Edit file contents"},
            "WebSearch": {"description": "Search the web"},
        }

        def search_tools(query):
            query_lower = query.lower()
            return [
                {"name": name, **info}
                for name, info in tools.items()
                if query_lower in name.lower() or query_lower in info["description"].lower()
            ]

        results = search_tools("edit")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Edit")

    def test_search_by_description(self):
        """Search returns matches by description content."""
        tools = {
            "Bash": {"description": "Execute shell commands"},
            "Read": {"description": "Read file contents"},
        }

        def search_tools(query):
            query_lower = query.lower()
            return [
                {"name": name, **info}
                for name, info in tools.items()
                if query_lower in name.lower() or query_lower in info["description"].lower()
            ]

        results = search_tools("shell")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Bash")


# ---------------------------------------------------------------------------
# TestTaskOutputTool — reading task output
# ---------------------------------------------------------------------------

class TestTaskOutputTool(unittest.TestCase):
    """Test reading output from the task manager."""

    def test_read_task_output(self):
        """Read the result of a completed task."""
        mgr = TaskManager()
        cr = mgr.create("Test task", "Run some tests")
        task_id = cr.task.id

        mgr.update(task_id, status=TaskStatus.IN_PROGRESS)
        mgr.update(task_id, status=TaskStatus.COMPLETED, metadata={"output": "All tests passed"})

        result = mgr.get(task_id)
        self.assertTrue(result.success)
        self.assertEqual(result.task.status, TaskStatus.COMPLETED)
        self.assertEqual(result.task.metadata["output"], "All tests passed")

    def test_read_nonexistent_task(self):
        """Reading a nonexistent task returns an error."""
        mgr = TaskManager()
        result = mgr.get("nonexistent-id")
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# TestPowerShellTool
# ---------------------------------------------------------------------------

class TestPowerShellTool(unittest.TestCase):
    """Test PowerShell availability check."""

    def test_check_pwsh_availability(self):
        """Check if pwsh is available on the system."""
        import subprocess
        try:
            result = subprocess.run(
                ["pwsh", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            # If we get here, pwsh is installed
            self.assertEqual(result.returncode, 0)
            self.assertIn("PowerShell", result.stdout)
        except FileNotFoundError:
            # pwsh not installed -- that's fine, just verify we handled it
            self.skipTest("pwsh not installed on this system")


# ---------------------------------------------------------------------------
# TestCronManager
# ---------------------------------------------------------------------------

class TestCronManager(unittest.TestCase):
    """Test ScheduleCronTool persistence and lifecycle."""

    def test_create_and_list_schedules(self):
        """Create schedules and list them."""
        cron = ScheduleCronTool()
        cron.create("job-1", "0 * * * *", "echo 1")
        cron.create("job-2", "30 2 * * *", "echo 2")

        ls = cron.list_schedules()
        self.assertEqual(len(ls.schedules), 2)

    def test_delete_schedule(self):
        """Delete a schedule and verify it's gone."""
        cron = ScheduleCronTool()
        cron.create("temp-job", "0 0 * * *", "cleanup")
        result = cron.delete("temp-job")
        self.assertTrue(result.success)

        ls = cron.list_schedules()
        self.assertEqual(len(ls.schedules), 0)

    def test_persistence_to_file(self):
        """Schedules persist to a file and reload."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            storage_path = f.name

        try:
            # Create and save
            cron1 = ScheduleCronTool(storage_path=storage_path)
            cron1.create("persist-job", "*/10 * * * *", "do_something")

            # Load in a new instance
            cron2 = ScheduleCronTool(storage_path=storage_path)
            ls = cron2.list_schedules()
            self.assertEqual(len(ls.schedules), 1)
            self.assertEqual(ls.schedules[0].name, "persist-job")
        finally:
            os.unlink(storage_path)

    def test_cron_step_zero_rejected(self):
        """Cron expression with step 0 is rejected."""
        valid, err = ScheduleCronTool.validate_cron("*/0 * * * *")
        self.assertFalse(valid)
        self.assertIn("cannot be 0", err)


if __name__ == "__main__":
    unittest.main()
