"""Freeze fleet worker turns as LLM-only until AgentSession owns execution."""

import ast
from pathlib import Path
from typing import List, Set


WORKER_TURN = Path(__file__).resolve().parents[2] / "fleet" / "worker_turn.py"
FORBIDDEN_IMPORTS = {"AgenticLoop", "ToolCallParser", "ToolRegistry"}
FORBIDDEN_MODULE_PREFIXES = {
    "agent.agentic",
    "agent.coding.tool_parser",
    "agent.coding.tools",
    "agent.tool_parser",
    "agent.tools",
}
REGISTRY_DISPATCH_METHODS = {
    "dispatch",
    "dispatch_tool",
    "execute",
    "execute_tool",
    "execute_tool_call",
}


def _attribute_name(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _semantic_string_constants(tree: ast.AST) -> List[str]:
    """Return runtime string literals, excluding module/function docstrings."""
    docstrings: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    docstrings.add(id(value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _is_forbidden_module(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in FORBIDDEN_MODULE_PREFIXES
    )


def _boundary_violations(source: str, filename: str = "<architecture-fixture>") -> List[str]:
    tree = ast.parse(source, filename=filename)
    violations = []
    imported_modules = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_name = ".".join(part for part in (node.module, alias.name) if part)
                imported_modules[alias.asname or alias.name] = imported_name
                if alias.name in FORBIDDEN_IMPORTS:
                    violations.append(f"line {node.lineno}: imports {alias.name}")
                if _is_forbidden_module(imported_name) or (
                    node.module and _is_forbidden_module(node.module)
                ):
                    violations.append(
                        f"line {node.lineno}: imports forbidden module {imported_name}"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                imported_modules[bound_name] = alias.name if alias.asname else bound_name
                if bound_name in FORBIDDEN_IMPORTS:
                    violations.append(f"line {node.lineno}: imports {alias.name}")
                if _is_forbidden_module(alias.name):
                    violations.append(
                        f"line {node.lineno}: imports forbidden module {alias.name}"
                    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        qualified_name = _attribute_name(node)
        root, separator, remainder = qualified_name.partition(".")
        if root in imported_modules:
            qualified_name = imported_modules[root] + (separator + remainder if separator else "")
        module_name, _, symbol = qualified_name.rpartition(".")
        if symbol in FORBIDDEN_IMPORTS and _is_forbidden_module(module_name):
            violations.append(
                f"line {node.lineno}: qualified use of {qualified_name}"
            )

    runtime_strings = _semantic_string_constants(tree)
    if any(
        "<tool_call" in value
        or "</tool_call" in value
        or "<|tool_call" in value
        for value in runtime_strings
    ):
        violations.append("contains runtime tool-call protocol tags")

    tool_definitions = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "get_tool"
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                tool_definitions.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = _attribute_name(node.func.value)
        if node.func.attr == "execute" and (
            receiver in tool_definitions
            or "tool_def" in receiver.lower()
            or (
                isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Attribute)
                and node.func.value.func.attr == "get_tool"
            )
        ):
            violations.append(f"line {node.lineno}: dispatches ToolDefinition.execute")
        if (
            node.func.attr in REGISTRY_DISPATCH_METHODS
            and "registry" in receiver.lower()
        ):
            violations.append(
                f"line {node.lineno}: generic tool-registry dispatch via {receiver}.{node.func.attr}"
            )

    return violations


def test_worker_turn_has_no_tool_execution_boundary():
    violations = _boundary_violations(
        WORKER_TURN.read_text(encoding="utf-8"), filename=str(WORKER_TURN)
    )
    assert not violations, "fleet/worker_turn.py crossed the AgentSession boundary:\n" + "\n".join(violations)


def test_detector_rejects_module_imports_with_qualified_dispatch():
    fixtures = {
        "registry": ("""
import agent.tools as tools
registry = tools.ToolRegistry()
registry.execute_tool_call(tool_call)
""", {"imports forbidden module", "qualified use", "generic tool-registry dispatch"}),
        "agentic_loop": ("""
import agent.agentic as agentic
loop = agentic.AgenticLoop(registry, config)
""", {"imports forbidden module", "qualified use"}),
        "tool_parser": ("""
import agent.tool_parser as parser
parser.ToolCallParser().parse(response)
""", {"imports forbidden module", "qualified use"}),
        "coding_tool_parser": ("""
import agent.coding.tool_parser as parser
parser.ToolCallParser().parse(response)
""", {"imports forbidden module", "qualified use"}),
    }

    for name, (source, expected_fragments) in fixtures.items():
        violations = _boundary_violations(source, filename=name)
        for fragment in expected_fragments:
            assert any(fragment in violation for violation in violations)


def test_detector_rejects_pipe_delimited_runtime_protocol_tag():
    violations = _boundary_violations(
        'response_marker = "<|tool_call|>"',
        filename="pipe-protocol",
    )
    assert "contains runtime tool-call protocol tags" in violations
