"""
Tests for Phase 3 — Chat-as-Manager Delegation.

Contract: contracts/persona_fleet/03_chat_supervisor.md
"""

import os
import shutil
import tempfile
import time
import pytest

from agent.agentic.swarm import (
    TeamManager,
    Mailbox,
    SharedTaskQueue,
    format_task_notification,
)
from agent.modes.chat_supervisor import ChatSupervisor


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="neomind_test_supervisor_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def team_setup(tmp_dir):
    """Set up a team with 1 leader + 3 workers."""
    mgr = TeamManager(base_dir=tmp_dir)
    mgr.create_team("proj-1", "manager-1", leader_persona="chat")
    mgr.add_member("proj-1", "coder-1", persona="coding")
    mgr.add_member("proj-1", "coder-2", persona="coding")
    mgr.add_member("proj-1", "quant-1", persona="fin")
    return tmp_dir


@pytest.fixture
def supervisor(team_setup):
    return ChatSupervisor("proj-1", "manager-1", base_dir=team_setup)


class TestSupervisorInit:

    def test_init_valid_team(self, supervisor):
        """Contract test 1: supervisor initializes with valid team."""
        assert supervisor.team_name == "proj-1"
        assert supervisor.leader_name == "manager-1"

    def test_worker_status_initialized(self, supervisor):
        """Workers are tracked after init."""
        status = supervisor.get_team_status()
        assert len(status["members"]) == 3  # 3 workers (leader excluded)
        names = {m["name"] for m in status["members"]}
        assert names == {"coder-1", "coder-2", "quant-1"}


class TestTeamStatus:

    def test_get_team_status(self, supervisor):
        """Contract test 2: get_team_status returns correct shape."""
        status = supervisor.get_team_status()
        assert status["team_name"] == "proj-1"
        assert "members" in status
        assert "tasks" in status
        assert all(m["status"] == "idle" for m in status["members"])

    def test_task_counts(self, supervisor):
        """Task counts reflect queue state."""
        supervisor.dispatch_task("task 1")
        supervisor.dispatch_task("task 2")
        status = supervisor.get_team_status()
        assert status["tasks"]["available"] == 2


class TestDispatch:

    def test_dispatch_to_queue(self, supervisor):
        """Contract test 3: dispatch without target adds to shared queue."""
        task_id = supervisor.dispatch_task("build API")
        assert task_id.startswith("task_")
        # Task should be in queue
        tasks = supervisor._task_queue.list_tasks()
        assert any(t["id"] == task_id for t in tasks)

    def test_dispatch_to_persona(self, supervisor):
        """Contract test 4: dispatch to persona targets idle member."""
        task_id = supervisor.dispatch_task("analyze stock", target_persona="fin")
        # quant-1 should be busy
        status = supervisor.get_team_status()
        quant = [m for m in status["members"] if m["name"] == "quant-1"][0]
        assert quant["status"] == "busy"
        assert quant["current_task"] == task_id

    def test_dispatch_to_member(self, supervisor, team_setup):
        """Contract test 5: dispatch to specific member sends to their mailbox."""
        task_id = supervisor.dispatch_task("fix bug", target_member="coder-1")
        # Check coder-1's mailbox
        coder_mailbox = Mailbox("proj-1", "coder-1", base_dir=team_setup)
        messages = coder_mailbox.read_unread()
        assert len(messages) == 1
        assert "fix bug" in messages[0].content

    def test_dispatch_to_persona_no_idle(self, supervisor):
        """Dispatch to persona when all busy → task stays in queue."""
        supervisor.dispatch_task("task 1", target_persona="fin")  # quant-1 busy
        task_id = supervisor.dispatch_task("task 2", target_persona="fin")
        # quant-1 already busy, so task stays as available
        status = supervisor.get_team_status()
        quant = [m for m in status["members"] if m["name"] == "quant-1"][0]
        assert quant["status"] == "busy"  # still busy from task 1


class TestCheckMailbox:

    def test_parse_task_notification(self, supervisor, team_setup):
        """Contract test 6: check_mailbox parses XML task notifications."""
        # Simulate a worker sending completion notification to leader
        leader_mailbox = Mailbox("proj-1", "manager-1", base_dir=team_setup)
        notification = format_task_notification(
            task_id="task_123",
            status="completed",
            summary="Built the API",
            result="API endpoint at /v1/stock",
        )
        leader_mailbox.write_message(
            sender="coder-1",
            content=notification,
            msg_type="task_notification",
        )

        parsed = supervisor.check_mailbox()
        assert len(parsed) == 1
        assert parsed[0]["sender"] == "coder-1"
        assert "parsed" in parsed[0]
        assert parsed[0]["parsed"]["task_id"] == "task_123"
        assert parsed[0]["parsed"]["status"] == "completed"
        assert parsed[0]["parsed"]["summary"] == "Built the API"


class TestStuckWorker:

    def test_detect_stuck_worker(self, supervisor):
        """Contract test 7: detect workers busy longer than timeout."""
        supervisor.dispatch_task("long task", target_member="coder-1")
        # Manually set busy_since to the past
        supervisor._worker_status["coder-1"]["busy_since"] = time.time() - 700
        stuck = supervisor.get_stuck_workers(timeout_minutes=10.0)
        assert "coder-1" in stuck

    def test_no_stuck_when_recent(self, supervisor):
        """No stuck workers when all recently dispatched."""
        supervisor.dispatch_task("task", target_member="coder-1")
        stuck = supervisor.get_stuck_workers(timeout_minutes=10.0)
        assert len(stuck) == 0

    def test_redispatch_stuck(self, supervisor):
        """Contract test 8: redispatch stuck worker's task to idle worker."""
        supervisor.dispatch_task("important task", target_member="coder-1")
        supervisor._worker_status["coder-1"]["busy_since"] = time.time() - 700

        new_task_id = supervisor.redispatch_stuck("coder-1")
        assert new_task_id is not None
        # coder-1 should be idle now
        assert supervisor._worker_status["coder-1"]["status"] == "idle"


class TestAggregateResults:

    def test_aggregate_completed_tasks(self, supervisor):
        """Contract test 9: aggregate results from completed tasks."""
        tid1 = supervisor.dispatch_task("task A")
        tid2 = supervisor.dispatch_task("task B")
        tid3 = supervisor.dispatch_task("task C")

        # Complete tasks in the queue
        supervisor._task_queue.complete_task(tid1, result="Result A done")
        supervisor._task_queue.complete_task(tid2, result="Result B done")
        supervisor._task_queue.complete_task(tid3, result="Result C done")

        summary = supervisor.aggregate_results([tid1, tid2, tid3])
        assert "Result A done" in summary
        assert "Result B done" in summary
        assert "Result C done" in summary
        assert "3 tasks" in summary


class TestFullDelegationCycle:

    def test_full_cycle(self, supervisor, team_setup):
        """Contract test 10: full dispatch → complete → check → aggregate cycle."""
        # Leader dispatches 3 tasks
        t1 = supervisor.dispatch_task("build login", target_member="coder-1")
        t2 = supervisor.dispatch_task("build dashboard", target_member="coder-2")
        t3 = supervisor.dispatch_task("analyze market", target_persona="fin")

        # All 3 workers should be busy
        status = supervisor.get_team_status()
        busy = [m for m in status["members"] if m["status"] == "busy"]
        assert len(busy) == 3

        # Workers complete and send notifications
        for worker, tid, result in [
            ("coder-1", t1, "login page done"),
            ("coder-2", t2, "dashboard built"),
            ("quant-1", t3, "market analysis complete"),
        ]:
            leader_mailbox = Mailbox("proj-1", "manager-1", base_dir=team_setup)
            leader_mailbox.write_message(
                sender=worker,
                content=format_task_notification(
                    task_id=tid, status="completed",
                    summary=f"completed by {worker}", result=result,
                ),
                msg_type="task_notification",
            )

        # Leader checks mailbox
        parsed = supervisor.check_mailbox()
        assert len(parsed) == 3

        # All workers should be idle again
        status = supervisor.get_team_status()
        idle = [m for m in status["members"] if m["status"] == "idle"]
        assert len(idle) == 3

        # Leader aggregates
        summary = supervisor.aggregate_results([t1, t2, t3])
        assert "login page done" in summary
        assert "dashboard built" in summary
        assert "market analysis complete" in summary
