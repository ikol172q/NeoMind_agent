# Contract 03 — Chat-as-Manager Delegation

**Phase:** 3
**Status:** SPEC — not implemented
**Scope:** New file `agent/modes/chat_supervisor.py`

---

## Summary

When the chat persona is the team leader, it needs supervisor behavior: watch the mailbox for incoming task-notifications from workers, dispatch new tasks to idle workers, and detect stuck workers. This module adds that delegation policy.

---

## Architecture

```
ChatPersonality (existing)
  └── ChatSupervisor (new, loaded when is_leader=True)
        ├── watches leader's Mailbox via read_unread()
        ├── dispatches tasks via SharedTaskQueue.add_task() + SendMessageTool
        ├── tracks worker status (idle/busy/stuck)
        └── aggregates completed task results
```

The supervisor is NOT a separate agent — it's a module that the chat personality loads when operating as team leader. It adds supervisor-specific methods to the chat session.

---

## Interface

### `ChatSupervisor` class

```python
class ChatSupervisor:
    """Delegation policy for chat-as-leader in a team project."""

    def __init__(self, team_name: str, leader_name: str,
                 base_dir: Optional[str] = None):
        """
        Args:
            team_name: The team/project this supervisor manages
            leader_name: This leader's agent name
            base_dir: Optional base dir for team storage
        """

    def get_team_status(self) -> Dict[str, Any]:
        """Get current status of all team members.
        
        Returns:
            {
                "team_name": "proj-1",
                "members": [
                    {"name": "coder-1", "persona": "coding", "status": "idle", "current_task": None},
                    {"name": "coder-2", "persona": "coding", "status": "busy", "current_task": "task_123"},
                    ...
                ],
                "tasks": {
                    "available": 2,
                    "claimed": 1,
                    "completed": 5,
                    "failed": 0
                }
            }
        """

    def dispatch_task(self, description: str,
                      target_persona: Optional[str] = None,
                      target_member: Optional[str] = None) -> str:
        """Create and dispatch a task.
        
        If target_member is specified, sends directly to that member.
        If target_persona is specified, sends to the first idle member
        with that persona.
        If neither, adds to the shared queue for any idle worker to claim.
        
        Args:
            description: Task description
            target_persona: Optional persona filter
            target_member: Optional specific member
        
        Returns:
            task_id
        """

    def check_mailbox(self) -> List[Dict[str, Any]]:
        """Read unread messages from the leader's mailbox.
        
        Parses task-notifications (XML format from format_task_notification),
        updates internal worker status tracking.
        
        Returns:
            List of parsed messages with type annotations
        """

    def get_stuck_workers(self, timeout_minutes: float = 10.0) -> List[str]:
        """Detect workers that have been busy for too long.
        
        Args:
            timeout_minutes: Threshold for considering a worker stuck
        
        Returns:
            List of worker names that are stuck
        """

    def redispatch_stuck(self, worker_name: str) -> Optional[str]:
        """Re-dispatch a stuck worker's task to another idle worker.
        
        Returns the new task_id if re-dispatched, None if no idle workers.
        """

    def aggregate_results(self, task_ids: List[str]) -> str:
        """Aggregate completed task results into a summary.
        
        Args:
            task_ids: Task IDs to aggregate
        
        Returns:
            Formatted summary of all completed tasks
        """
```

### Integration with `ChatPersonality`

In `agent/modes/chat.py`, when the chat personality detects it's operating as a team leader (via `TeammateIdentity.is_leader == True`), it:
1. Instantiates `ChatSupervisor(team_name, leader_name)`
2. Adds supervisor commands to its command handlers:
   - `/team status` → `supervisor.get_team_status()`
   - `/team dispatch <task>` → `supervisor.dispatch_task()`
   - `/team check` → `supervisor.check_mailbox()`
   - `/team stuck` → `supervisor.get_stuck_workers()`
3. Periodically calls `check_mailbox()` between user interactions

---

## Dependencies

- `agent/agentic/swarm.py`: `Mailbox`, `SharedTaskQueue`, `TeamManager`, `format_task_notification`, `TeammateIdentity`
- `agent/tools/collaboration_tools.py`: `SendMessageTool` (for dispatching to specific members)

---

## Test Contract (Pair A implements these)

### Unit Tests

1. **`test_supervisor_init`**: Create supervisor with valid team → no error.

2. **`test_get_team_status`**: Set up team with 3 members → `get_team_status()` returns correct member count and task counts.

3. **`test_dispatch_task_to_queue`**: `dispatch_task("build API")` → task appears in `SharedTaskQueue` with status "available".

4. **`test_dispatch_task_to_persona`**: `dispatch_task("analyze stock", target_persona="fin")` → task sent to a fin worker.

5. **`test_dispatch_task_to_member`**: `dispatch_task("fix bug", target_member="coder-1")` → message appears in coder-1's mailbox.

6. **`test_check_mailbox_parses_notifications`**: Write a `format_task_notification()` XML to leader's mailbox → `check_mailbox()` parses it into structured data.

7. **`test_stuck_worker_detection`**: Mark a worker as busy, advance time > timeout → `get_stuck_workers()` returns that worker.

8. **`test_redispatch_stuck`**: Worker stuck + another idle → `redispatch_stuck()` creates new task, returns task_id.

9. **`test_aggregate_results`**: Complete 3 tasks with results → `aggregate_results()` returns formatted summary containing all 3.

### Integration Test

10. **`test_full_delegation_cycle`**: Leader dispatches 3 tasks → workers claim → workers complete with results → leader checks mailbox → leader aggregates → final summary contains all results.
