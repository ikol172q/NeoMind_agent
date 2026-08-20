"""The runtime may not know a frontend exists.

`code_commands.stream_response()` printed straight to stdout, so headless had
to redirect stdout to suppress it. That is the shape of the problem this
boundary prevents: once a runtime renders, every other surface has to work
around the rendering instead of consuming events.

AST-based rather than import-based, so a violation is caught in source even if
the offending line never executes.
"""

import ast
import pathlib

import pytest

RUNTIME_DIR = pathlib.Path(__file__).resolve().parents[2] / "agent" / "runtime"

# Frontends and renderers. A runtime module importing any of these has, by
# definition, picked a surface.
FORBIDDEN_ROOTS = {
    "cli",
    "prompt_toolkit",
    "rich",
    "telegram",
    "textual",
    "tkinter",
    "curses",
}

FORBIDDEN_CALLS = {"print", "input"}


def _runtime_modules():
    return sorted(RUNTIME_DIR.glob("*.py"))


def test_runtime_package_exists():
    assert _runtime_modules(), "agent/runtime contains no modules"


@pytest.mark.parametrize("path", _runtime_modules(), ids=lambda p: p.name)
def test_no_frontend_imports(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_ROOTS:
                    offenders.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_ROOTS:
                    offenders.append((node.lineno, node.module))

    assert not offenders, (
        f"{path.name} imports a frontend: {offenders}. "
        "The runtime must emit events; surfaces render them."
    )


@pytest.mark.parametrize("path", _runtime_modules(), ids=lambda p: p.name)
def test_no_print_or_input(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders = [
        (node.lineno, node.func.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in FORBIDDEN_CALLS
    ]

    assert not offenders, (
        f"{path.name} calls {offenders}. Runtime output is an event; runtime "
        "input is resolve_permission(). A print() here forces every non-terminal "
        "surface to redirect stdout, which is exactly what headless had to do."
    )


def test_runtime_modules_add_no_frontend_import():
    """Belt and braces: measure what the runtime *itself* pulls in.

    Catches an indirect pull-in the per-file AST scan cannot see — a runtime
    module importing a helper that imports rich.

    Measured as a delta against `import agent`, deliberately. The parent
    package already drags in the whole of rich (confirmed on py3.14), which is
    real debt but predates this boundary and is not something Phase 1 can fix
    without touching every consumer of `agent/__init__`. Charging it to the
    runtime would make this test permanently red and therefore ignored. The
    delta is the part the runtime controls, and it must stay zero.
    """
    import subprocess
    import sys

    probe = (
        "import sys;"
        "import agent;"                      # baseline: the parent package's cost
        "before=set(sys.modules);"
        "import agent.runtime.tool_executor, agent.runtime.events,"
        " agent.runtime.permissions, agent.runtime.ports;"
        "added=set(sys.modules)-before;"
        "bad=[m for m in added if m.split('.')[0] in "
        f"{sorted(FORBIDDEN_ROOTS)!r}];"
        "print(','.join(sorted(bad)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    pulled = [m for m in result.stdout.strip().split(",") if m]
    assert not pulled, (
        f"the runtime modules pulled in frontend modules: {pulled}. "
        "Runtime code must not reach a renderer, even transitively."
    )


def test_runtime_produces_no_stdout_on_import_or_denial(capsys):
    """A denied call must be silent — the caller decides what the user sees."""
    import asyncio

    from agent.runtime.permissions import PermissionPolicy
    from agent.runtime.tool_executor import ToolExecutor

    class Registry:
        def get_tool(self, name):
            return None

        def get_all_tools(self):
            return []

    ex = ToolExecutor(Registry(), PermissionPolicy())
    outcome = asyncio.run(ex.execute("Whatever", {}))

    captured = capsys.readouterr()
    assert outcome.denied
    assert captured.out == "", f"runtime wrote to stdout: {captured.out!r}"
    assert captured.err == "", f"runtime wrote to stderr: {captured.err!r}"
