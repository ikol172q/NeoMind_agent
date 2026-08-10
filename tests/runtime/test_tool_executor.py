"""Security contract for ToolExecutor.

Each test here corresponds to a way the pre-runtime code could be talked into
executing something nobody authorized. They are written so they fail against
the old behaviour, not merely pass against the new.
"""

import asyncio

import pytest

from agent.runtime.permissions import (
    Approval,
    CapabilitySnapshot,
    Decision,
    PermissionPolicy,
    Scope,
    SessionRule,
    fingerprint,
    redact_params,
)
from agent.runtime.tool_executor import ExecutionOutcome, ToolExecutor


# ── doubles that mimic the real ToolDefinition/ToolRegistry surface ───────


class FakeResult:
    def __init__(self, success=True, output="", error="", metadata=None):
        self.success = success
        self.output = output
        self.error = error
        self.metadata = metadata or {}


class FakeTool:
    def __init__(self, name, level="read_only", fn=None, valid=True):
        self.name = name
        self.permission_level = level
        self._fn = fn or (lambda **kw: FakeResult(output=f"ran {name} {sorted(kw.items())}"))
        self._valid = valid
        self.calls = []

    def validate_params(self, params):
        return (True, "") if self._valid else (False, "bad params")

    def apply_defaults(self, params):
        return dict(params)

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self._fn(**kwargs)


class FakeRegistry:
    def __init__(self, *tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools.get(name)

    def get_all_tools(self):
        return list(self._tools.values())


def interactive_policy(**kw):
    kw.setdefault("interactive", True)
    return PermissionPolicy(**kw)


def approve(tool, params, working_dir="", request_id="req", scope=Scope.ONCE, rule=None):
    return Approval(
        request_id=request_id,
        fingerprint=fingerprint(tool, params, working_dir),
        scope=scope,
        rule=rule,
    )


class RecordingAudit:
    def __init__(self):
        self.entries = []

    def record(self, entry):
        self.entries.append(dict(entry))


# ── the silence-is-denial invariant ──────────────────────────────────────


def test_write_denied_when_no_broker_exists():
    """A surface that cannot ask must not execute.

    The old loop's `approved: bool = True` meant a frontend that never answered
    got the tool run for it. Telegram set nothing, so it ran everything.
    """
    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy(interactive=False))

    out = asyncio.run(ex.execute("Write", {"path": "/tmp/x"}))

    assert out.denied
    assert tool.calls == []
    assert "no interactive broker" in out.denied_reason


def test_broker_that_never_answers_denies_and_does_not_execute():
    class SilentBroker:
        async def request(self, **kw):
            await asyncio.sleep(3600)

    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(
        FakeRegistry(tool), interactive_policy(), broker=SilentBroker(),
        permission_timeout=0.05,
    )

    out = asyncio.run(ex.execute("Write", {"path": "/tmp/x"}))
    assert out.denied and tool.calls == []


def test_broker_that_raises_denies():
    class BrokenBroker:
        async def request(self, **kw):
            raise RuntimeError("frontend disconnected")

    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), interactive_policy(), broker=BrokenBroker())

    out = asyncio.run(ex.execute("Write", {"path": "/tmp/x"}))
    assert out.denied and tool.calls == []


def test_bare_true_is_not_an_approval():
    """`return True` names no call, so it cannot authorize one."""

    class SloppyBroker:
        async def request(self, **kw):
            return True

    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), interactive_policy(), broker=SloppyBroker())

    out = asyncio.run(ex.execute("Write", {"path": "/tmp/x"}))
    assert out.denied and tool.calls == []


# ── approval is bound to the exact call ──────────────────────────────────


def test_approval_for_different_params_does_not_authorize():
    """Approving `Read a.txt` must not run `Read /etc/shadow`."""

    class MaliciousBroker:
        async def request(self, **kw):
            return approve("Read", {"path": "a.txt"})

    tool = FakeTool("Read", level="write")  # forced through the ASK path
    ex = ToolExecutor(FakeRegistry(tool), interactive_policy(), broker=MaliciousBroker())

    out = asyncio.run(ex.execute("Read", {"path": "/etc/shadow"}))

    assert out.denied
    assert tool.calls == []
    assert "fingerprint" in out.denied_reason


def test_matching_approval_executes_exactly_once():
    params = {"path": "a.txt"}

    class Broker:
        async def request(self, **kw):
            return approve("Write", params)

    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), interactive_policy(), broker=Broker())

    out = asyncio.run(ex.execute("Write", dict(params)))

    assert out.executed and out.success
    assert tool.calls == [params]


# ── policy decisions ─────────────────────────────────────────────────────


def test_read_only_auto_approves_without_a_broker():
    tool = FakeTool("Read", level="read_only")
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy(interactive=False))

    out = asyncio.run(ex.execute("Read", {"path": "a.txt"}))
    assert out.executed and out.success


def test_unclassified_permission_level_denies():
    """Missing or non-enum levels are dangerous, not harmless.

    Headless previously executed anything it could look up, including tools
    whose level was absent or a plain string.
    """
    tool = FakeTool("Weird", level=None)
    ex = ToolExecutor(FakeRegistry(tool), interactive_policy())

    out = asyncio.run(ex.execute("Weird", {}))
    assert out.denied and "unclassified" in out.denied_reason


def test_critical_risk_stays_interactive_under_auto_accept():
    """auto-accept is not a bypass for destructive actions."""
    tool = FakeTool("Bash", level="execute")
    ex = ToolExecutor(
        FakeRegistry(tool),
        PermissionPolicy(interactive=False, auto_accept=True),
        risk_classifier=lambda *_: "CRITICAL",
    )

    out = asyncio.run(ex.execute("Bash", {"command": "rm -rf /"}))
    assert out.denied and tool.calls == []


def test_auto_accept_allows_ordinary_write():
    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy(auto_accept=True))

    out = asyncio.run(ex.execute("Write", {"path": "a.txt"}))
    assert out.executed and out.success


def test_capability_snapshot_denies_tool_outside_it():
    """Prompt visibility and execution authority come from one snapshot."""
    tool = FakeTool("Bash", level="execute")
    ex = ToolExecutor(
        FakeRegistry(tool),
        PermissionPolicy(capabilities=CapabilitySnapshot.only("Read"), auto_accept=True),
    )

    out = asyncio.run(ex.execute("Bash", {"command": "ls"}))
    assert out.denied and "capability" in out.denied_reason


def test_risk_classifier_failure_is_treated_as_critical():
    def boom(*_):
        raise ValueError("classifier broken")

    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(
        FakeRegistry(tool),
        PermissionPolicy(interactive=False, auto_accept=True),
        risk_classifier=boom,
    )

    out = asyncio.run(ex.execute("Write", {"path": "a.txt"}))
    assert out.denied


# ── session rules are scoped, never global ───────────────────────────────


def test_session_rule_applies_only_to_its_pattern():
    policy = PermissionPolicy(
        interactive=False,
        session_rules=[SessionRule("Write", "docs/*.md")],
    )
    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), policy)

    allowed = asyncio.run(ex.execute("Write", {"path": "docs/a.md"}))
    refused = asyncio.run(ex.execute("Write", {"path": "/etc/passwd"}))

    assert allowed.executed
    assert refused.denied


def test_session_rule_does_not_cover_critical_actions():
    policy = PermissionPolicy(interactive=False, session_rules=[SessionRule("Bash", "*")])
    tool = FakeTool("Bash", level="execute")
    ex = ToolExecutor(FakeRegistry(tool), policy, risk_classifier=lambda *_: "CRITICAL")

    out = asyncio.run(ex.execute("Bash", {"command": "rm -rf /"}))
    assert out.denied


# ── execution mechanics ──────────────────────────────────────────────────


def test_async_tool_is_awaited():
    async def async_fn(**kw):
        await asyncio.sleep(0)
        return FakeResult(output="async ok")

    tool = FakeTool("Async", level="read_only", fn=async_fn)
    tool.execute = async_fn  # the registry hands back a coroutine function
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy())

    out = asyncio.run(ex.execute("Async", {}))
    assert out.executed and out.output == "async ok"


def test_tool_exception_is_reported_not_raised():
    def explode(**kw):
        raise RuntimeError("disk on fire")

    tool = FakeTool("Boom", level="read_only", fn=explode)
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy())

    out = asyncio.run(ex.execute("Boom", {}))
    assert out.executed and not out.success
    assert "disk on fire" in out.error


def test_invalid_params_deny_before_execution():
    tool = FakeTool("Read", level="read_only", valid=False)
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy())

    out = asyncio.run(ex.execute("Read", {}))
    assert out.denied and tool.calls == []


def test_unknown_tool_denies():
    ex = ToolExecutor(FakeRegistry(), PermissionPolicy())
    out = asyncio.run(ex.execute("Nope", {}))
    assert out.denied and "unknown tool" in out.denied_reason


def test_denied_is_distinguishable_from_failed():
    """The model must be able to tell 'blocked' from 'errored'."""
    denied = ExecutionOutcome(executed=False, denied_reason="nope")
    failed = ExecutionOutcome(executed=True, success=False, error="boom")

    assert denied.denied and not failed.denied


# ── audit ────────────────────────────────────────────────────────────────


def test_audit_records_decision_without_raw_secrets():
    audit = RecordingAudit()
    tool = FakeTool("Write", level="write")
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy(interactive=False), audit=audit)

    secret = "123456789" + ":" + "AAH" + "x" * 32
    asyncio.run(ex.execute("Write", {"token": secret}))

    assert audit.entries, "a denial must still be audited"
    blob = repr(audit.entries)
    assert secret not in blob
    assert audit.entries[0]["outcome"] == "denied"


def test_redact_params_masks_credentials():
    secret = "sk-" + "a" * 32
    assert secret not in redact_params({"key": secret})


def test_audit_failure_does_not_change_the_decision():
    class BrokenAudit:
        def record(self, entry):
            raise IOError("audit disk full")

    tool = FakeTool("Read", level="read_only")
    ex = ToolExecutor(FakeRegistry(tool), PermissionPolicy(), audit=BrokenAudit())

    out = asyncio.run(ex.execute("Read", {"path": "a.txt"}))
    assert out.executed


# ── policy unit checks ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "level,interactive,expected",
    [
        ("read_only", False, Decision.ALLOW),
        ("write", False, Decision.DENY),
        ("write", True, Decision.ASK),
        ("execute", True, Decision.ASK),
        ("destructive", True, Decision.ASK),
        ("destructive", False, Decision.DENY),
    ],
)
def test_policy_matrix(level, interactive, expected):
    policy = PermissionPolicy(interactive=interactive)
    decision, _ = policy.evaluate("T", level, {})
    assert decision is expected


def test_fingerprint_is_order_independent():
    a = fingerprint("Write", {"path": "x", "content": "y"})
    b = fingerprint("Write", {"content": "y", "path": "x"})
    assert a == b


def test_fingerprint_includes_working_dir():
    assert fingerprint("Read", {"path": "a"}, "/one") != fingerprint("Read", {"path": "a"}, "/two")
