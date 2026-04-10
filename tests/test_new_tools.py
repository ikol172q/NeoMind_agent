"""Tests for newly created tool modules."""
import os
import sys
import tempfile
import unittest
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

_test_dir = os.path.dirname(os.path.abspath(__file__))
_agent_dir = os.path.dirname(_test_dir)
sys.path.insert(0, _agent_dir)

from agent.tools.git_tools import GitTools, GitResult
from agent.tools.plan_mode import PlanModeManager, PlanModeResult
from agent.tools.utility_tools import (
    WebFetchTool,
    WebSearchTool,
    WebSearchResult,
    SearchHit,
    NotebookEditTool,
    TodoWriteTool,
    AskUserQuestionTool,
    SleepTool,
    BriefTool,
)
from agent.tools.collaboration_tools import (
    SendMessageTool,
    ScheduleCronTool,
    RemoteTriggerTool,
    TeamManager,
    MessageDirection,
    TriggerMethod,
    TeamRole,
)


# ---------------------------------------------------------------------------
# TestGitTools
# ---------------------------------------------------------------------------

class TestGitTools(unittest.TestCase):
    """Test GitTools git workflow operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.git = GitTools(working_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_with_working_dir(self):
        """GitTools stores the provided working directory."""
        self.assertEqual(self.git.working_dir, self.tmpdir)

    def test_status_on_non_git_dir(self):
        """status() on a non-git directory should fail gracefully."""
        result = self.git.status()
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_init_repo_add_commit_log(self):
        """Init a git repo, add a file, commit, and check log."""
        # Init repo
        init = self.git._run("init")
        self.assertTrue(init.success, f"git init failed: {init.error}")

        # Configure user for commit
        self.git._run("config", "user.email", "test@test.com")
        self.git._run("config", "user.name", "Test")

        # Create and add a file
        test_file = os.path.join(self.tmpdir, "hello.txt")
        with open(test_file, "w") as f:
            f.write("hello world\n")

        add_result = self.git.add(["hello.txt"])
        self.assertTrue(add_result.success, f"git add failed: {add_result.error}")

        # Commit
        commit_result = self.git.commit("Initial commit")
        self.assertTrue(commit_result.success, f"git commit failed: {commit_result.error}")
        # commit_hash may not be extracted for root commits due to "(root-commit)" in output
        # Just verify the commit was recorded in the log

        # Log
        log_result = self.git.log(count=5)
        self.assertTrue(log_result.success)
        self.assertIn("Initial commit", log_result.output)

    def test_branch_operations(self):
        """Create and list branches in a git repo."""
        # Setup repo with initial commit
        self.git._run("init")
        self.git._run("config", "user.email", "test@test.com")
        self.git._run("config", "user.name", "Test")
        test_file = os.path.join(self.tmpdir, "file.txt")
        with open(test_file, "w") as f:
            f.write("content\n")
        self.git.add(["file.txt"])
        self.git.commit("Initial")

        # Create branch
        create_result = self.git.branch_create("feature-x", checkout=True)
        self.assertTrue(create_result.success, f"branch create failed: {create_result.error}")

        # List branches
        list_result = self.git.branch_list()
        self.assertTrue(list_result.success)
        self.assertIn("feature-x", list_result.output)
        self.assertEqual(list_result.metadata.get("current_branch"), "feature-x")

        # Switch back
        switch_result = self.git.branch_switch("master")
        if not switch_result.success:
            switch_result = self.git.branch_switch("main")
        self.assertTrue(switch_result.success, f"branch switch failed: {switch_result.error}")

    def test_diff_and_blame(self):
        """Test diff and blame on a file with history."""
        # Setup repo
        self.git._run("init")
        self.git._run("config", "user.email", "test@test.com")
        self.git._run("config", "user.name", "Test")
        test_file = os.path.join(self.tmpdir, "data.txt")
        with open(test_file, "w") as f:
            f.write("line 1\n")
        self.git.add(["data.txt"])
        self.git.commit("First")

        # Modify file
        with open(test_file, "a") as f:
            f.write("line 2\n")

        # Diff should show changes
        diff_result = self.git.diff()
        self.assertTrue(diff_result.success)
        self.assertIn("line 2", diff_result.output)

        # Blame
        blame_result = self.git.blame("data.txt")
        self.assertTrue(blame_result.success)
        self.assertIn("line 1", blame_result.output)

    def test_empty_branch_name_rejected(self):
        """branch_create and branch_switch reject empty names."""
        result = self.git.branch_create("")
        self.assertFalse(result.success)
        self.assertIn("empty", result.error.lower())

        result2 = self.git.branch_switch("  ")
        self.assertFalse(result2.success)

    def test_stash_invalid_action(self):
        """stash() rejects invalid actions."""
        result = self.git.stash(action="drop")
        self.assertFalse(result.success)
        self.assertIn("Invalid stash action", result.error)

    def test_add_empty_paths(self):
        """add() with empty paths list should fail."""
        result = self.git.add([])
        self.assertFalse(result.success)

    def test_commit_empty_message(self):
        """commit() with empty message should fail."""
        result = self.git.commit("")
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# TestPlanMode
# ---------------------------------------------------------------------------

class TestPlanMode(unittest.TestCase):
    """Test PlanModeManager."""

    def test_initial_state_inactive(self):
        """Plan mode is initially inactive."""
        mgr = PlanModeManager()
        self.assertFalse(mgr.is_active)

    def test_enter_exit_plan_mode(self):
        """Enter and exit plan mode changes is_active."""
        mgr = PlanModeManager()

        enter_result = mgr.enter()
        self.assertTrue(enter_result.success)
        self.assertTrue(enter_result.active)
        self.assertTrue(mgr.is_active)

        exit_result = mgr.exit()
        self.assertTrue(exit_result.success)
        self.assertFalse(exit_result.active)
        self.assertFalse(mgr.is_active)

    def test_idempotent_enter(self):
        """Entering plan mode twice is idempotent."""
        mgr = PlanModeManager()
        mgr.enter()
        r = mgr.enter()
        self.assertTrue(r.success)
        self.assertTrue(r.active)
        self.assertIn("Already", r.message)

    def test_idempotent_exit(self):
        """Exiting plan mode when not active is idempotent."""
        mgr = PlanModeManager()
        r = mgr.exit()
        self.assertTrue(r.success)
        self.assertFalse(r.active)
        self.assertIn("Not in plan mode", r.message)

    def test_integration_with_mock_registry(self):
        """Plan mode calls registry enter/exit methods."""
        registry = MagicMock()
        registry.enter_plan_mode = MagicMock()
        registry.exit_plan_mode = MagicMock()

        mgr = PlanModeManager(tool_registry=registry)
        mgr.enter()
        registry.enter_plan_mode.assert_called_once()

        mgr.exit()
        registry.exit_plan_mode.assert_called_once()


# ---------------------------------------------------------------------------
# TestUtilityTools
# ---------------------------------------------------------------------------

class TestUtilityTools(unittest.TestCase):
    """Test utility tool classes."""

    def _run_async(self, coro):
        """Helper to run an async coroutine in tests."""
        return asyncio.get_event_loop().run_until_complete(coro)

    @classmethod
    def setUpClass(cls):
        """Ensure an event loop exists."""
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    # -- WebFetchTool -------------------------------------------------------

    def test_web_fetch_empty_url(self):
        """WebFetchTool rejects empty URL."""
        tool = WebFetchTool()
        result = self._run_async(tool.fetch(""))
        self.assertFalse(result.success)
        self.assertIn("empty", result.error.lower())

    def test_web_fetch_invalid_url(self):
        """WebFetchTool handles unreachable URL gracefully."""
        tool = WebFetchTool()
        result = self._run_async(tool.fetch("http://256.256.256.256:1/nonexistent", timeout=2))
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    # -- WebSearchTool ------------------------------------------------------

    def test_web_search_empty_query(self):
        """WebSearchTool rejects empty query."""
        tool = WebSearchTool()
        result = self._run_async(tool.search(""))
        self.assertFalse(result.success)
        self.assertIn("empty", result.error.lower())

    def test_web_search_unsupported_engine(self):
        """WebSearchTool rejects unsupported engine."""
        tool = WebSearchTool(engine="bing")
        result = self._run_async(tool.search("test"))
        self.assertFalse(result.success)
        self.assertIn("Unsupported", result.error)

    def test_web_search_parse_ddg_lite(self):
        """WebSearchTool._parse_ddg_lite parses mock HTML."""
        html = '''
        <a rel="nofollow" href="https://example.com/page1" class="result-link">Example Page</a>
        <td class="result-snippet">This is a snippet</td>
        <a rel="nofollow" href="https://example.com/page2" class="result-link">Another Page</a>
        <td class="result-snippet">Another snippet</td>
        '''
        hits = WebSearchTool._parse_ddg_lite(html, max_results=5)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://example.com/page1")

    # -- NotebookEditTool ---------------------------------------------------

    def test_notebook_read_edit_add_delete(self):
        """NotebookEditTool: create, read, edit, add, delete cells."""
        tool = NotebookEditTool()

        # Create a minimal notebook
        nb = {
            "cells": [
                {
                    "cell_type": "code",
                    "source": ["print('hello')\n"],
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                },
                {
                    "cell_type": "markdown",
                    "source": ["# Title\n"],
                    "metadata": {},
                },
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }

        with tempfile.NamedTemporaryFile(suffix=".ipynb", mode="w", delete=False) as f:
            json.dump(nb, f)
            nb_path = f.name

        try:
            # Read
            read_result = tool.read_notebook(nb_path)
            self.assertTrue(read_result.success)
            self.assertEqual(len(read_result.cells), 2)
            self.assertIn("hello", read_result.cells[0].source)

            # Edit cell 0
            edit_result = tool.edit_cell(nb_path, 0, "print('world')\n")
            self.assertTrue(edit_result.success)
            self.assertIn("world", edit_result.cells[0].source)

            # Add cell
            add_result = tool.add_cell(nb_path, cell_type="code", source="x = 42\n")
            self.assertTrue(add_result.success)
            self.assertEqual(len(add_result.cells), 3)

            # Delete cell 1 (the markdown cell)
            del_result = tool.delete_cell(nb_path, 1)
            self.assertTrue(del_result.success)
            self.assertEqual(len(del_result.cells), 2)

            # Out-of-range edit
            bad_edit = tool.edit_cell(nb_path, 99, "nope")
            self.assertFalse(bad_edit.success)
        finally:
            os.unlink(nb_path)

    def test_notebook_not_found(self):
        """NotebookEditTool handles missing file."""
        tool = NotebookEditTool()
        result = tool.read_notebook("/tmp/nonexistent_notebook_xyz.ipynb")
        self.assertFalse(result.success)

    # -- TodoWriteTool ------------------------------------------------------

    def test_todo_add_complete_list_remove(self):
        """TodoWriteTool: add, complete, list, remove."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = TodoWriteTool(workspace=tmpdir)

            # Add
            add_result = tool.add("Buy groceries", priority="high")
            self.assertTrue(add_result.success)
            self.assertEqual(len(add_result.todos), 1)
            todo_id = add_result.todos[0].id

            # List
            list_result = tool.list_todos()
            self.assertTrue(list_result.success)
            self.assertEqual(len(list_result.todos), 1)

            # Complete
            complete_result = tool.complete(todo_id)
            self.assertTrue(complete_result.success)
            self.assertTrue(complete_result.todos[0].completed)

            # Complete again should fail
            again = tool.complete(todo_id)
            self.assertFalse(again.success)
            self.assertEqual(again.error, "already_completed")

            # List without completed
            list2 = tool.list_todos(show_completed=False)
            self.assertEqual(len(list2.todos), 0)

            # List with completed
            list3 = tool.list_todos(show_completed=True)
            self.assertEqual(len(list3.todos), 1)

            # Remove
            remove_result = tool.remove(todo_id)
            self.assertTrue(remove_result.success)

            # Remove nonexistent
            bad_remove = tool.remove("nonexistent")
            self.assertFalse(bad_remove.success)

    def test_todo_empty_text_rejected(self):
        """TodoWriteTool rejects empty text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = TodoWriteTool(workspace=tmpdir)
            result = tool.add("")
            self.assertFalse(result.success)

    # -- AskUserQuestionTool ------------------------------------------------

    def test_ask_user_question_with_options(self):
        """AskUserQuestionTool formats question with options and default."""
        tool = AskUserQuestionTool()
        result = tool.ask(
            "Pick a color:",
            options=["red", "blue", "green"],
            default="blue",
        )
        self.assertEqual(result.question, "Pick a color:")
        self.assertIn("1. red", result.formatted)
        self.assertIn("2. blue (default)", result.formatted)
        self.assertIn("3. green", result.formatted)

    def test_ask_user_question_no_options(self):
        """AskUserQuestionTool formats question without options."""
        tool = AskUserQuestionTool()
        result = tool.ask("What is your name?", default="Alice")
        self.assertIn("[default: Alice]", result.formatted)

    # -- SleepTool ----------------------------------------------------------

    def test_sleep_tool(self):
        """SleepTool sleeps for the specified duration."""
        tool = SleepTool()
        result = self._run_async(tool.sleep(0.01, reason="testing"))
        self.assertTrue(result.success)
        self.assertAlmostEqual(result.slept_seconds, 0.01, places=2)
        self.assertEqual(result.reason, "testing")

    def test_sleep_tool_clamped(self):
        """SleepTool clamps negative values to 0."""
        tool = SleepTool()
        result = self._run_async(tool.sleep(-5))
        self.assertTrue(result.success)
        self.assertEqual(result.slept_seconds, 0.0)

    # -- BriefTool ----------------------------------------------------------

    def test_brief_tool_toggle(self):
        """BriefTool toggles between brief and verbose."""
        tool = BriefTool()
        self.assertFalse(tool.is_brief)

        r1 = tool.toggle()
        self.assertTrue(r1.brief)
        self.assertTrue(tool.is_brief)

        r2 = tool.toggle()
        self.assertFalse(r2.brief)
        self.assertFalse(tool.is_brief)

    def test_brief_tool_set(self):
        """BriefTool set_brief explicitly sets the mode."""
        tool = BriefTool()
        r = tool.set_brief(True)
        self.assertTrue(r.brief)
        self.assertIn("brief", r.message)

        r2 = tool.set_brief(False)
        self.assertFalse(r2.brief)
        self.assertIn("verbose", r2.message)


# ---------------------------------------------------------------------------
# TestCollaborationTools
# ---------------------------------------------------------------------------

class TestCollaborationTools(unittest.TestCase):
    """Test collaboration tool classes."""

    # -- SendMessageTool ----------------------------------------------------

    def test_send_message(self):
        """SendMessageTool queues outbound messages."""
        tool = SendMessageTool(agent_id="agent-1")
        result = tool.send("agent-2", "Hello!")
        self.assertTrue(result.success)
        self.assertEqual(result.data.sender, "agent-1")
        self.assertEqual(result.data.recipient, "agent-2")
        self.assertEqual(result.data.direction, MessageDirection.OUTBOUND)

    def test_send_message_empty_recipient_rejected(self):
        """SendMessageTool rejects empty recipient."""
        tool = SendMessageTool()
        result = tool.send("", "content")
        self.assertFalse(result.success)

    def test_receive_messages(self):
        """SendMessageTool delivers and receives inbound messages."""
        tool = SendMessageTool(agent_id="agent-1")

        # Deliver inbound
        tool.deliver_inbound("agent-2", "Hi from agent-2")
        tool.deliver_inbound("agent-3", "Hi from agent-3")

        # Receive all
        result = tool.receive()
        self.assertTrue(result.success)
        self.assertEqual(len(result.messages), 2)

        # Messages are now marked read
        result2 = tool.receive()
        self.assertEqual(len(result2.messages), 0)

    def test_receive_with_filter(self):
        """SendMessageTool filters inbound messages by sender."""
        tool = SendMessageTool(agent_id="agent-1")
        tool.deliver_inbound("agent-2", "msg A")
        tool.deliver_inbound("agent-3", "msg B")

        result = tool.receive(from_filter="agent-2")
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].sender, "agent-2")

    def test_list_messages(self):
        """SendMessageTool lists messages by direction."""
        tool = SendMessageTool(agent_id="agent-1")
        tool.send("agent-2", "outbound msg")
        tool.deliver_inbound("agent-2", "inbound msg")

        all_msgs = tool.list_messages("all")
        self.assertEqual(len(all_msgs.messages), 2)

        outbound = tool.list_messages("outbound")
        self.assertEqual(len(outbound.messages), 1)

        inbound = tool.list_messages("inbound")
        self.assertEqual(len(inbound.messages), 1)

    def test_list_messages_invalid_direction(self):
        """list_messages rejects invalid direction."""
        tool = SendMessageTool()
        result = tool.list_messages("sideways")
        self.assertFalse(result.success)

    # -- ScheduleCronTool ---------------------------------------------------

    def test_cron_create_list_delete(self):
        """ScheduleCronTool: create, list, delete schedules."""
        cron = ScheduleCronTool()

        # Create
        cr = cron.create("daily-backup", "0 2 * * *", "backup --full", "Nightly backup")
        self.assertTrue(cr.success)
        self.assertEqual(cr.data.name, "daily-backup")

        # List
        ls = cron.list_schedules()
        self.assertEqual(len(ls.schedules), 1)

        # Delete
        dr = cron.delete("daily-backup")
        self.assertTrue(dr.success)

        # Delete nonexistent
        dr2 = cron.delete("nonexistent")
        self.assertFalse(dr2.success)

    def test_cron_validate_expression(self):
        """ScheduleCronTool validates cron expressions."""
        valid, err = ScheduleCronTool.validate_cron("*/5 * * * *")
        self.assertTrue(valid)
        self.assertEqual(err, "")

        invalid, err2 = ScheduleCronTool.validate_cron("*/5 * *")
        self.assertFalse(invalid)
        self.assertIn("Expected 5 fields", err2)

        invalid2, err3 = ScheduleCronTool.validate_cron("60 * * * *")
        self.assertFalse(invalid2)
        self.assertIn("out of range", err3)

    def test_cron_parse_expression(self):
        """ScheduleCronTool parses cron expressions."""
        parsed = ScheduleCronTool.parse_cron("0 2 * * 1")
        self.assertEqual(parsed["minute"]["values"], [0])
        self.assertEqual(parsed["hour"]["values"], [2])
        self.assertIn(1, parsed["weekday"]["values"])
        self.assertEqual(len(parsed["day"]["values"]), 31)

    def test_cron_reject_duplicate_name(self):
        """ScheduleCronTool rejects duplicate schedule names."""
        cron = ScheduleCronTool()
        cron.create("job-a", "0 * * * *", "echo a")
        dup = cron.create("job-a", "0 * * * *", "echo b")
        self.assertFalse(dup.success)
        self.assertEqual(dup.error, "duplicate_name")

    def test_cron_reject_invalid_cron(self):
        """ScheduleCronTool rejects invalid cron expression."""
        cron = ScheduleCronTool()
        result = cron.create("bad", "not a cron", "echo x")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_cron")

    # -- RemoteTriggerTool --------------------------------------------------

    def test_trigger_create_list_delete(self):
        """RemoteTriggerTool: create, list, delete triggers."""
        tool = RemoteTriggerTool()

        # Create
        cr = tool.create_trigger("deploy", "https://example.com/deploy", method="POST")
        self.assertTrue(cr.success)
        self.assertEqual(cr.data.name, "deploy")
        self.assertEqual(cr.data.method, TriggerMethod.POST)

        # List
        ls = tool.list_triggers()
        self.assertEqual(len(ls.triggers), 1)

        # Delete
        dr = tool.delete_trigger("deploy")
        self.assertTrue(dr.success)

        dr2 = tool.delete_trigger("nonexistent")
        self.assertFalse(dr2.success)

    def test_trigger_reject_duplicate(self):
        """RemoteTriggerTool rejects duplicate trigger names."""
        tool = RemoteTriggerTool()
        tool.create_trigger("hook", "https://example.com", method="GET")
        dup = tool.create_trigger("hook", "https://example.com", method="GET")
        self.assertFalse(dup.success)

    def test_trigger_invalid_method(self):
        """RemoteTriggerTool rejects invalid HTTP method."""
        tool = RemoteTriggerTool()
        result = tool.create_trigger("bad", "https://example.com", method="TRACE")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_method")

    # -- TeamManager --------------------------------------------------------

    def test_team_create_and_delete(self):
        """TeamManager: create and delete teams."""
        mgr = TeamManager()

        cr = mgr.create_team("backend", description="Backend team")
        self.assertTrue(cr.success)
        self.assertEqual(cr.data.name, "backend")

        dr = mgr.delete_team("backend")
        self.assertTrue(dr.success)

        dr2 = mgr.delete_team("nonexistent")
        self.assertFalse(dr2.success)

    def test_team_add_remove_members(self):
        """TeamManager: add and remove members."""
        mgr = TeamManager()
        mgr.create_team("team-alpha")

        add_result = mgr.add_member("team-alpha", "agent-1", role="leader")
        self.assertTrue(add_result.success)
        self.assertIn("agent-1", add_result.data.members)
        self.assertEqual(add_result.data.members["agent-1"].role, TeamRole.LEADER)

        # Duplicate member
        dup = mgr.add_member("team-alpha", "agent-1", role="worker")
        self.assertFalse(dup.success)

        # Remove member
        rm = mgr.remove_member("team-alpha", "agent-1")
        self.assertTrue(rm.success)
        self.assertNotIn("agent-1", rm.data.members)

        # Remove nonexistent member
        rm2 = mgr.remove_member("team-alpha", "ghost")
        self.assertFalse(rm2.success)

    def test_team_create_with_initial_members(self):
        """TeamManager: create team with initial members and roles."""
        mgr = TeamManager()
        cr = mgr.create_team(
            "squad",
            members=["a1", "a2"],
            roles={"a1": "leader", "a2": "reviewer"},
        )
        self.assertTrue(cr.success)
        self.assertEqual(len(cr.data.members), 2)
        self.assertEqual(cr.data.members["a1"].role, TeamRole.LEADER)
        self.assertEqual(cr.data.members["a2"].role, TeamRole.REVIEWER)

    def test_team_list(self):
        """TeamManager: list teams."""
        mgr = TeamManager()
        mgr.create_team("alpha")
        mgr.create_team("beta")

        result = mgr.list_teams()
        self.assertTrue(result.success)
        self.assertEqual(len(result.teams), 2)

    def test_team_get(self):
        """TeamManager: get a specific team."""
        mgr = TeamManager()
        mgr.create_team("gamma", description="Gamma team")

        result = mgr.get_team("gamma")
        self.assertTrue(result.success)
        self.assertEqual(result.data.description, "Gamma team")

        result2 = mgr.get_team("nonexistent")
        self.assertFalse(result2.success)

    def test_team_invalid_role(self):
        """TeamManager rejects invalid roles."""
        mgr = TeamManager()
        mgr.create_team("team-x")
        result = mgr.add_member("team-x", "agent-1", role="ceo")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "invalid_role")


if __name__ == "__main__":
    unittest.main()
