"""Coding CLI Comprehensive Scenario Library — 2026-04-11

Developer-workflow scenarios for NeoMind CLI coding mode, exercised via
a real iTerm2 window running `main.py interactive --mode coding`.

**No fluff**: every scenario mirrors something a real programmer does in
a terminal while working on code. No finance queries, no chat smalltalk,
no "what is PE ratio" — pure coding workflow.

Scope:
- READ-ONLY operations run against the real NeoMind repo
- WRITE operations run against `/tmp/neomind_coding_sandbox/` (never the real repo)
- Long-turn scenarios are multi-step sequences sharing conversation context

Scenario tuple format:
    Scenario(
        sid,            # unique ID
        category,       # category letter + number
        send,           # the literal user message the tester types
        reply_timeout,  # seconds to wait for reply
        data_markers,   # strict: one of these MUST appear in the reply region
        tools_expected, # (optional) set of tool names at least one of which MUST fire
        long_turn,      # (optional) list of follow-up (send, markers, tools) tuples
    )

Categories:
    N  — Navigation / project exploration
    R  — Reading files
    G  — Grep / text search
    B  — Bash basics
    V  — Git / version control
    T  — Testing workflows
    E  — Editing (single-line + multi-line)
    F  — Refactoring
    D  — Debugging
    X  — Error recovery (intentional bad commands)
    L  — Long-turn workflows (50+ turn features and bug hunts)

Strict matching rule: a scenario PASSes iff
    (data_markers match in reply region) AND
    (tools_expected subset satisfied, if specified)
This avoids the status-bar keyword-collision false-PASS issue that
plagued the Phase C 5-scenario runner.

This file is DATA. Tester agents import it, do not modify.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


@dataclass
class Scenario:
    sid: str
    category: str
    send: str
    reply_timeout: float
    data_markers: List[str]
    tools_expected: Optional[Set[str]] = None
    long_turn: Optional[List[Tuple[str, List[str], Optional[Set[str]]]]] = None


SANDBOX = "/tmp/neomind_coding_sandbox"


# ── N — Navigation / Project Exploration (20) ────────────────────────

N_SCENARIOS: List[Scenario] = [
    Scenario("N01", "N", "what files are in the current directory", 45,
             ["agent", "tests", "main.py", "README", "docs"],
             {"Bash", "Glob", "LS"}),
    Scenario("N02", "N", "show me the top-level structure of this project, 1 level deep", 60,
             ["agent", "tests", "docs", "plans"],
             {"Bash", "Glob"}),
    Scenario("N03", "N", "what's the main entry point of this project", 45,
             ["main.py", "__main__", "if __name__"],
             {"Read", "Grep", "Bash"}),
    Scenario("N04", "N", "find all Python files in the agent/evolution/ directory", 45,
             ["transaction.py", "canary_deploy.py", "self_edit.py"],
             {"Glob", "Bash"}),
    Scenario("N05", "N", "which folder has the most Python files", 60,
             [".py", "agent"],
             {"Bash", "Glob"}),
    Scenario("N06", "N", "list all markdown files in docs/", 30,
             [".md"],
             {"Glob", "Bash"}),
    Scenario("N07", "N", "count the total number of Python files in this project", 45,
             [".py"],
             {"Bash"}),
    Scenario("N08", "N", "what does the docs/ directory contain", 45,
             [".md", "docs"],
             {"Bash", "LS", "Glob"}),
    Scenario("N09", "N", "show me the agent/ subdirectories", 30,
             ["evolution", "integration", "services", "tools"],
             {"Bash", "LS"}),
    Scenario("N10", "N", "how many tests are in tests/integration/", 30,
             ["tests/integration"],
             {"Bash", "Glob"}),
    Scenario("N11", "N", "find all files modified in the last hour", 30,
             [".py", ".md"],
             {"Bash"}),
    Scenario("N12", "N", "what's the biggest Python file in agent/integration/", 45,
             ["telegram_bot.py"],
             {"Bash"}),
    Scenario("N13", "N", "list all config yaml files", 30,
             [".yaml", "config"],
             {"Glob", "Bash"}),
    Scenario("N14", "N", "where is the CanaryDeployer class defined", 45,
             ["canary_deploy.py", "agent/evolution"],
             {"Grep", "Bash"}),
    Scenario("N15", "N", "what's in plans/ directory", 30,
             ["plans", ".md"],
             {"Bash", "LS"}),
    Scenario("N16", "N", "find all TODO comments in the agent/ folder", 45,
             ["TODO", "agent"],
             {"Grep", "Bash"}),
    Scenario("N17", "N", "show me the directory tree for tests/qa_archive/", 45,
             ["plans", "results"],
             {"Bash"}),
    Scenario("N18", "N", "how many lines of Python are in agent/integration/telegram_bot.py", 30,
             ["telegram_bot"],
             {"Bash", "Read"}),
    Scenario("N19", "N", "list every Python file that imports asyncio", 60,
             ["asyncio"],
             {"Grep", "Bash"}),
    Scenario("N20", "N", "find the Dockerfile", 30,
             ["Dockerfile"],
             {"Bash", "Glob"}),
]


# ── R — Reading files (15) ───────────────────────────────────────────

R_SCENARIOS: List[Scenario] = [
    Scenario("R01", "R", "read the first 20 lines of main.py", 30,
             ["#!/usr/bin/env python", "import", "load_dotenv"],
             {"Read", "Bash"}),
    Scenario("R02", "R", "show me the .env.example file", 45,
             ["DEEPSEEK_API_KEY", "LLM_ROUTER", "NEOMIND_"],
             {"Read", "Bash"}),
    Scenario("R03", "R", "read docs/CANARY_BOT_SETUP.md", 45,
             ["Canary", "BotFather", "TELEGRAM_TEST_BOT_TOKEN"],
             {"Read", "Bash"}),
    Scenario("R04", "R", "show me the last 30 lines of agent/coding/persistent_bash.py", 30,
             ["ToolResult", "bash", "Exit code"],
             {"Read", "Bash"}),
    Scenario("R05", "R", "read the __init__.py of agent/evolution/", 30,
             ["evolution"],
             {"Read", "Bash"}),
    Scenario("R06", "R", "show me docker-compose.yml", 45,
             ["services", "neomind-telegram", "neomind-canary"],
             {"Read", "Bash"}),
    Scenario("R07", "R", "read the Dockerfile", 45,
             ["FROM", "WORKDIR", "ENTRYPOINT"],
             {"Read", "Bash"}),
    Scenario("R08", "R", "what's in requirements.txt (or pyproject.toml)", 30,
             ["telethon", "python-telegram-bot", "dependencies"],
             {"Read", "Bash"}),
    Scenario("R09", "R", "show me agent/evolution/canary_deploy.py lines 100-130", 30,
             ["CanaryDeployer", "canary"],
             {"Read", "Bash"}),
    Scenario("R10", "R", "read plans/TODO_zero_downtime_self_evolution.md", 60,
             ["canary", "iTerm2", "evolution"],
             {"Read", "Bash"}),
    Scenario("R11", "R", "read the tail of .gitignore", 30,
             [".env", "pycache"],
             {"Read", "Bash"}),
    Scenario("R12", "R", "show me tests/integration/telegram_tester.py header", 30,
             ["Telethon", "tester"],
             {"Read", "Bash"}),
    Scenario("R13", "R", "read the first 50 lines of agent/integration/telegram_bot.py", 30,
             ["TelegramConfig", "import"],
             {"Read", "Bash"}),
    Scenario("R14", "R", "what's in the tests/qa_archive/README.md", 45,
             ["qa_archive", "plans", "results"],
             {"Read", "Bash"}),
    Scenario("R15", "R", "read docs/CLI_SELF_TEST_ITERM2.md", 60,
             ["iTerm2", "Python API", "1912"],
             {"Read", "Bash"}),
]


# ── G — Grep / text search (15) ──────────────────────────────────────

G_SCENARIOS: List[Scenario] = [
    Scenario("G01", "G", "grep for 'class CanaryDeployer' across the whole codebase", 45,
             ["canary_deploy.py"],
             {"Grep", "Bash"}),
    Scenario("G02", "G", "find every function named 'async_create' in agent/", 45,
             ["async_create", "def "],
             {"Grep", "Bash"}),
    Scenario("G03", "G", "how many times is 'finance_get_stock' referenced", 45,
             ["finance_get_stock"],
             {"Grep", "Bash"}),
    Scenario("G04", "G", "grep for the string 'TELEGRAM_BOT_TOKEN' in the repo", 45,
             ["TELEGRAM_BOT_TOKEN"],
             {"Grep", "Bash"}),
    Scenario("G05", "G", "find all places where 'raise NotImplementedError' appears", 45,
             ["NotImplementedError"],
             {"Grep", "Bash"}),
    Scenario("G06", "G", "look for 'def __init__' in agent/evolution/", 45,
             ["def __init__", "evolution"],
             {"Grep", "Bash"}),
    Scenario("G07", "G", "search for all 'FIXME' comments", 45,
             ["FIXME"],
             {"Grep", "Bash"}),
    Scenario("G08", "G", "find every import of 'asyncio' in tests/", 45,
             ["asyncio", "import"],
             {"Grep", "Bash"}),
    Scenario("G09", "G", "grep -r 'LLM_ROUTER_API_KEY' under agent/", 45,
             ["LLM_ROUTER_API_KEY"],
             {"Grep", "Bash"}),
    Scenario("G10", "G", "find '@your_neomind_bot' across the repo", 45,
             ["your_neomind_bot"],
             {"Grep", "Bash"}),
    Scenario("G11", "G", "search for '_ask_llm_streaming' definition", 45,
             ["_ask_llm_streaming", "def"],
             {"Grep", "Bash"}),
    Scenario("G12", "G", "find every file containing 'finance_compute'", 45,
             ["finance_compute"],
             {"Grep", "Bash"}),
    Scenario("G13", "G", "grep for 'class Scenario' in tests/", 45,
             ["class Scenario"],
             {"Grep", "Bash"}),
    Scenario("G14", "G", "how many times does 'agentic_loop' appear in agent/", 45,
             ["agentic_loop"],
             {"Grep", "Bash"}),
    Scenario("G15", "G", "find '.venv/bin/python' string occurrences in docs/", 45,
             [".venv/bin/python"],
             {"Grep", "Bash"}),
]


# ── B — Bash basics (20) ─────────────────────────────────────────────

B_SCENARIOS: List[Scenario] = [
    Scenario("B01", "B", "what's the current working directory", 15,
             ["/"],
             {"Bash"}),
    Scenario("B02", "B", "run `python3 --version` and tell me the output", 20,
             ["Python 3"],
             {"Bash"}),
    Scenario("B03", "B", "show me the PATH environment variable", 15,
             ["PATH", "/bin"],
             {"Bash"}),
    Scenario("B04", "B", "what's today's date", 15,
             ["20", "2026"],
             {"Bash"}),
    Scenario("B05", "B", "count lines in agent/integration/telegram_bot.py", 30,
             ["telegram_bot"],
             {"Bash"}),
    Scenario("B06", "B", "how many *.py files are there in the whole project", 45,
             [".py"],
             {"Bash", "Glob"}),
    Scenario("B07", "B", "show me the first 5 lines of main.py using head", 20,
             ["#!/usr/bin"],
             {"Bash", "Read"}),
    Scenario("B08", "B", "what shell am I using (echo $SHELL)", 15,
             ["/bash", "/zsh", "/sh"],
             {"Bash"}),
    Scenario("B09", "B", "run `uname -a` and give me the output", 15,
             ["Darwin", "arm64"],
             {"Bash"}),
    Scenario("B10", "B", "list python processes running right now with ps", 20,
             ["PID", "python"],
             {"Bash"}),
    Scenario("B11", "B", "how much disk space is free in /tmp", 20,
             ["Avail", "/tmp"],
             {"Bash"}),
    Scenario("B12", "B", "echo $HOME", 15,
             ["/Users", "/home"],
             {"Bash"}),
    Scenario("B13", "B", "print python3 -c 'import sys; print(sys.version_info)'", 30,
             ["major", "minor"],
             {"Bash"}),
    Scenario("B14", "B", "show me the file size of agent/integration/telegram_bot.py in bytes", 20,
             ["telegram_bot"],
             {"Bash"}),
    Scenario("B15", "B", "count lines in every .md file in docs/", 30,
             [".md", "docs"],
             {"Bash"}),
    Scenario("B16", "B", "find the 5 largest Python files in this repo", 45,
             [".py"],
             {"Bash"}),
    Scenario("B17", "B", "what's the MD5 checksum of main.py", 20,
             ["main.py"],
             {"Bash"}),
    Scenario("B18", "B", "count unique file extensions in the repo", 45,
             [".py"],
             {"Bash"}),
    Scenario("B19", "B", "show me the last modification date of agent/core.py", 20,
             ["core.py", "Apr", "Mar"],
             {"Bash"}),
    Scenario("B20", "B", "print the current timestamp in ISO 8601", 15,
             ["T", "20", "2026"],
             {"Bash"}),
]


# ── V — Git / version control (20) ───────────────────────────────────

V_SCENARIOS: List[Scenario] = [
    Scenario("V01", "V", "what's the current git branch", 20,
             ["feat", "main", "branch"],
             {"Bash"}),
    Scenario("V02", "V", "show me git status", 30,
             ["branch", "nothing to commit", "clean", "modified"],
             {"Bash"}),
    Scenario("V03", "V", "show the last 10 git commits, oneline", 30,
             ["fix", "feat", "test", "Merge"],
             {"Bash"}),
    Scenario("V04", "V", "what's the HEAD commit sha", 20,
             ["HEAD"],
             {"Bash"}),
    Scenario("V05", "V", "show the diff of the most recent commit", 60,
             ["diff", "+++", "---"],
             {"Bash"}),
    Scenario("V06", "V", "how many commits has main branch had in total", 30,
             ["commits", "main"],
             {"Bash"}),
    Scenario("V07", "V", "list all local git branches", 20,
             ["main", "feat"],
             {"Bash"}),
    Scenario("V08", "V", "who wrote the most recent commit on agent/core.py", 45,
             ["core.py"],
             {"Bash"}),
    Scenario("V09", "V", "show the commit message of HEAD", 20,
             ["commit"],
             {"Bash"}),
    Scenario("V10", "V", "what files changed in the last commit", 45,
             [".py", ".md"],
             {"Bash"}),
    Scenario("V11", "V", "git log showing only commits touching agent/evolution/", 45,
             ["evolution"],
             {"Bash"}),
    Scenario("V12", "V", "git blame the first 20 lines of main.py", 45,
             ["main.py"],
             {"Bash"}),
    Scenario("V13", "V", "show me git tags", 20,
             ["tag"],
             {"Bash"}),
    Scenario("V14", "V", "what's the remote url for origin", 20,
             ["github.com", "origin"],
             {"Bash"}),
    Scenario("V15", "V", "how many commits are there on feat/major-tool-system-update branch", 30,
             ["major-tool", "commits"],
             {"Bash"}),
    Scenario("V16", "V", "count commits made today", 30,
             ["commit"],
             {"Bash"}),
    Scenario("V17", "V", "show git log --oneline for the last 5 commits touching persistent_bash.py", 45,
             ["persistent_bash", "fix", "feat"],
             {"Bash"}),
    Scenario("V18", "V", "show the merge commit on main", 30,
             ["Merge", "main"],
             {"Bash"}),
    Scenario("V19", "V", "list the top 5 most-modified files in the last 20 commits", 60,
             [".py"],
             {"Bash"}),
    Scenario("V20", "V", "show me git log with author dates for the last 3 commits", 30,
             ["Date", "Author"],
             {"Bash"}),
]


# ── T — Testing workflows (15) ───────────────────────────────────────

T_SCENARIOS: List[Scenario] = [
    Scenario("T01", "T", "how many test files are there under tests/", 30,
             ["test_"],
             {"Bash", "Glob"}),
    Scenario("T02", "T", "find every pytest fixture in tests/", 45,
             ["@pytest.fixture"],
             {"Grep", "Bash"}),
    Scenario("T03", "T", "run pytest tests/test_mode_gating.py -q and tell me the result", 120,
             ["passed", "failed", "5 passed", "test"],
             {"Bash"}),
    Scenario("T04", "T", "list every test function whose name starts with test_tune", 45,
             ["test_tune"],
             {"Grep", "Bash"}),
    Scenario("T05", "T", "which tests import TelegramBotTester", 45,
             ["TelegramBotTester"],
             {"Grep", "Bash"}),
    Scenario("T06", "T", "count test classes (class Test...) in tests/", 45,
             ["class Test"],
             {"Grep", "Bash"}),
    Scenario("T07", "T", "find a pytest.mark.asyncio decorator usage", 45,
             ["@pytest.mark.asyncio"],
             {"Grep", "Bash"}),
    Scenario("T08", "T", "show me the test for finance_compute", 45,
             ["finance_compute"],
             {"Grep", "Read", "Bash"}),
    Scenario("T09", "T", "what's the biggest test file by line count", 45,
             ["test_"],
             {"Bash"}),
    Scenario("T10", "T", "list all conftest.py files", 30,
             ["conftest"],
             {"Glob", "Bash"}),
    Scenario("T11", "T", "find assert statements in tests/test_tool_parser.py", 45,
             ["assert"],
             {"Grep", "Read", "Bash"}),
    Scenario("T12", "T", "run pytest --collect-only on tests/test_mode_gating.py", 60,
             ["collected", "test_"],
             {"Bash"}),
    Scenario("T13", "T", "show me the docstring of tests/integration/telegram_tester.py", 30,
             ["tester", "Telethon"],
             {"Read", "Bash"}),
    Scenario("T14", "T", "find all files with 'def test_' under tests/", 45,
             ["def test_"],
             {"Grep", "Bash"}),
    Scenario("T15", "T", "what python version is the project using (check .python-version or pyproject.toml)", 30,
             ["python", "3.", "version"],
             {"Bash", "Read"}),
]


# ── E — Edit operations (15) — all against /tmp sandbox ──────────────

E_SCENARIOS: List[Scenario] = [
    Scenario("E01", "E", f"create a file at {SANDBOX}/hello.py with a simple print('hello') function", 45,
             ["hello.py", "print", "hello"],
             {"Write", "Bash"}),
    Scenario("E02", "E", f"read back {SANDBOX}/hello.py and show me its content", 30,
             ["hello", "print"],
             {"Read", "Bash"}),
    Scenario("E03", "E", f"add a docstring to {SANDBOX}/hello.py saying 'Sandbox file for testing'", 45,
             ["Sandbox", "testing"],
             {"Edit", "Write", "Read", "Bash"}),
    Scenario("E04", "E", f"create {SANDBOX}/math_utils.py with add(a,b) and sub(a,b) functions", 60,
             ["def add", "def sub"],
             {"Write", "Bash"}),
    Scenario("E05", "E", f"add a multiply(a,b) function to {SANDBOX}/math_utils.py", 60,
             ["def multiply", "def mul"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("E06", "E", f"rename the add function in {SANDBOX}/math_utils.py to plus", 60,
             ["def plus"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("E07", "E", f"create {SANDBOX}/config.json with a simple JSON object containing name and version", 45,
             ["name", "version", "{"],
             {"Write", "Bash"}),
    Scenario("E08", "E", f"update the version field in {SANDBOX}/config.json to 2.0.0", 45,
             ["2.0.0"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("E09", "E", f"create {SANDBOX}/script.sh that prints 'test' and make it executable", 60,
             ["script.sh", "test", "chmod"],
             {"Write", "Bash"}),
    Scenario("E10", "E", f"run {SANDBOX}/script.sh and show me its output", 30,
             ["test"],
             {"Bash"}),
    Scenario("E11", "E", f"create {SANDBOX}/todo.txt with 3 bullet items", 45,
             ["todo", "-", "*"],
             {"Write", "Bash"}),
    Scenario("E12", "E", f"append a 4th bullet to {SANDBOX}/todo.txt", 45,
             ["4", "todo"],
             {"Edit", "Write", "Read", "Bash"}),
    Scenario("E13", "E", f"delete the 2nd line from {SANDBOX}/todo.txt", 45,
             ["todo"],
             {"Edit", "Write", "Read", "Bash"}),
    Scenario("E14", "E", f"create a Python class Counter in {SANDBOX}/counter.py with increment/decrement/get methods", 90,
             ["class Counter", "def increment", "def decrement"],
             {"Write", "Bash"}),
    Scenario("E15", "E", f"add type hints to the Counter class in {SANDBOX}/counter.py", 90,
             ["int", "-> ", ": "],
             {"Edit", "Read", "Write", "Bash"}),
]


# ── F — Refactoring (15) — against /tmp sandbox ──────────────────────

F_SCENARIOS: List[Scenario] = [
    Scenario("F01", "F", f"create {SANDBOX}/calc.py with one function that takes a and b and returns a+b+a*b", 60,
             ["def ", "a+b", "a * b"],
             {"Write", "Bash"}),
    Scenario("F02", "F", f"refactor {SANDBOX}/calc.py to split the expression into two helper functions", 90,
             ["def ", "return"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F03", "F", f"in {SANDBOX}/calc.py rename variable a to x and b to y throughout", 60,
             ["x", "y"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F04", "F", f"create {SANDBOX}/old_module.py with 3 functions then move them to {SANDBOX}/new_module.py", 120,
             ["new_module", "def "],
             {"Write", "Read", "Edit", "Bash"}),
    Scenario("F05", "F", f"create {SANDBOX}/data.py with a list of dicts then refactor to use dataclasses", 120,
             ["dataclass", "@dataclass"],
             {"Write", "Read", "Edit", "Bash"}),
    Scenario("F06", "F", f"extract the body of a loop in {SANDBOX}/hello.py into a helper function", 90,
             ["def "],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F07", "F", f"create a Python file at {SANDBOX}/loops.py with 3 for-loops doing similar things, then DRY it", 120,
             ["for ", "def "],
             {"Write", "Edit", "Read", "Bash"}),
    Scenario("F08", "F", f"add logging to every function in {SANDBOX}/math_utils.py", 90,
             ["logging", "import", "logger"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F09", "F", f"convert all print() calls in {SANDBOX}/hello.py to logger.info() calls", 60,
             ["logger.info"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F10", "F", f"in {SANDBOX}/config.json add a new top-level 'features' field with 2 bool flags", 60,
             ["features", "true", "false"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F11", "F", f"create {SANDBOX}/greeter.py with a greet() function then extract a NameFormatter class", 120,
             ["class NameFormatter", "def greet"],
             {"Write", "Edit", "Read", "Bash"}),
    Scenario("F12", "F", f"convert {SANDBOX}/counter.py's Counter class into a @dataclass", 90,
             ["@dataclass"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F13", "F", f"extract the magic number 3.14 in {SANDBOX}/calc.py (if absent, add one) into a PI constant", 90,
             ["PI", "3.14"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("F14", "F", f"rename the file {SANDBOX}/old_module.py to {SANDBOX}/legacy.py", 45,
             ["legacy"],
             {"Bash"}),
    Scenario("F15", "F", f"show me all Python files in {SANDBOX} ordered by size", 30,
             [".py"],
             {"Bash"}),
]


# ── D — Debugging workflows (15) ─────────────────────────────────────

D_SCENARIOS: List[Scenario] = [
    Scenario("D01", "D", f"create {SANDBOX}/bug.py with a ZeroDivisionError bug", 60,
             ["ZeroDivision", "def "],
             {"Write", "Bash"}),
    Scenario("D02", "D", f"run {SANDBOX}/bug.py and catch the traceback", 45,
             ["Traceback", "ZeroDivisionError", "Error"],
             {"Bash"}),
    Scenario("D03", "D", f"fix the ZeroDivisionError in {SANDBOX}/bug.py with a guard clause", 90,
             ["if ", "return"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("D04", "D", f"re-run {SANDBOX}/bug.py and confirm it runs clean", 45,
             ["error", "0", "run"],
             {"Bash"}),
    Scenario("D05", "D", f"create {SANDBOX}/wrong_type.py that has a TypeError and reproduce the error", 90,
             ["TypeError", "def "],
             {"Write", "Bash"}),
    Scenario("D06", "D", f"add a print statement in {SANDBOX}/bug.py to show the input value", 60,
             ["print"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("D07", "D", f"use python -c to check if {SANDBOX}/math_utils.py's plus function works", 30,
             ["plus", "+"],
             {"Bash"}),
    Scenario("D08", "D", f"show me the output of running the existing {SANDBOX}/hello.py", 30,
             ["hello"],
             {"Bash"}),
    Scenario("D09", "D", f"write a one-line python command to import {SANDBOX}/math_utils.py and call plus(3,4)", 45,
             ["7"],
             {"Bash"}),
    Scenario("D10", "D", f"create {SANDBOX}/infinite_loop.py with a for-loop counting 0..9, then run it and verify it terminates", 60,
             ["9", "0", "for"],
             {"Write", "Bash"}),
    Scenario("D11", "D", f"add assert statements to {SANDBOX}/math_utils.py to verify plus(2,3)==5", 60,
             ["assert"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("D12", "D", f"execute {SANDBOX}/math_utils.py as a module from bash", 45,
             ["math_utils"],
             {"Bash"}),
    Scenario("D13", "D", f"in {SANDBOX}/bug.py, add a try/except to catch any unexpected exception", 60,
             ["try:", "except"],
             {"Edit", "Read", "Write", "Bash"}),
    Scenario("D14", "D", f"check if {SANDBOX}/counter.py is valid python (python -m py_compile)", 30,
             ["counter"],
             {"Bash"}),
    Scenario("D15", "D", f"list every .py file under {SANDBOX} with syntax errors (if any)", 45,
             [".py"],
             {"Bash"}),
]


# ── X — Error recovery (15) — intentional bad commands ───────────────
# These verify the agentic loop's error-feedback loop is working:
# the agent should either (a) self-correct on attempt 2 or (b) forced
# stop after 2 consecutive identical failures (per commit eb50655 fix).

X_SCENARIOS: List[Scenario] = [
    # Classic find typo — the one that sparked this whole session
    Scenario("X01", "X", f"run: find {SANDBOX} -maxdepth2 -name '*.py'", 60,
             ["hello.py", "counter.py", "math_utils", "Forced stop", "maxdepth 2"],
             {"Bash"}),
    Scenario("X02", "X", "show me the output of `ls --nonexistent-flag`", 60,
             ["ls", "Forced stop", "option"],
             {"Bash"}),
    Scenario("X03", "X", f"run: cat {SANDBOX}/this-file-does-not-exist.txt", 45,
             ["No such file", "directory", "Forced stop"],
             {"Bash"}),
    Scenario("X04", "X", f"grep for a pattern using `grep -z--invalid` in {SANDBOX}", 60,
             ["grep", "Forced stop", "option"],
             {"Bash"}),
    Scenario("X05", "X", "run: python3 -c 'print(undefined_variable)'", 45,
             ["NameError", "undefined_variable", "Forced stop"],
             {"Bash"}),
    Scenario("X06", "X", "execute `git lg -oneline` (that's a typo, lg should be log)", 60,
             ["git", "not a git command", "Forced stop"],
             {"Bash"}),
    Scenario("X07", "X", f"run python3 {SANDBOX}/does_not_exist.py", 45,
             ["No such file", "Forced stop"],
             {"Bash"}),
    Scenario("X08", "X", "execute: sed -e 'this is not valid sed' main.py", 45,
             ["sed", "Forced stop"],
             {"Bash"}),
    Scenario("X09", "X", "run `python3 -c 'import json; json.loads(\"{invalid}\")'`", 45,
             ["JSONDecodeError", "json", "Forced stop"],
             {"Bash"}),
    Scenario("X10", "X", f"run `cd {SANDBOX}/nonexistent && ls`", 45,
             ["No such file", "cd", "Forced stop"],
             {"Bash"}),
    Scenario("X11", "X", "run `chmod +x main.py.nonexistent`", 45,
             ["chmod", "No such", "Forced stop"],
             {"Bash"}),
    Scenario("X12", "X", f"run `mv {SANDBOX}/does_not_exist {SANDBOX}/anywhere`", 45,
             ["mv", "No such", "Forced stop"],
             {"Bash"}),
    Scenario("X13", "X", "try this broken command: `echo 'hi > file.txt` (unclosed quote)", 45,
             ["quote", "hi", "Forced stop"],
             {"Bash"}),
    Scenario("X14", "X", "run `python3 -m pytest /tmp/nonexistent_dir`", 60,
             ["pytest", "No", "Forced stop"],
             {"Bash"}),
    Scenario("X15", "X", "execute `tar -xfz` (missing archive name)", 45,
             ["tar", "Forced stop"],
             {"Bash"}),
]


# ── L — Long-turn workflows (10) ─────────────────────────────────────
# Each L scenario has a seed message + 5-20 follow-up turns that build
# a real developer task. The tester runs the seed then walks through
# the follow-ups sequentially without clearing context. Each step's
# data_markers must match OR the long-turn scenario fails at that step.

L_SCENARIOS: List[Scenario] = [
    # L01: implement a simple CLI tool end-to-end (15 turns)
    Scenario(
        "L01", "L",
        f"I want to implement a simple file line counter tool at {SANDBOX}/linecount.py. "
        f"Start by creating the file with a main() that takes a filename argument from sys.argv.",
        90, ["linecount.py", "sys.argv", "main"],
        {"Write", "Bash"},
        long_turn=[
            (f"now add file-not-found error handling", ["FileNotFoundError", "try"], {"Edit", "Read", "Write"}),
            (f"add line counting using open() and len()", ["len", "readlines", "splitlines"], {"Edit", "Read", "Write"}),
            (f"add word counting too", ["split", "words"], {"Edit", "Read", "Write"}),
            (f"add character counting", ["len", "char"], {"Edit", "Read", "Write"}),
            (f"run it against {SANDBOX}/hello.py and show the output", ["hello.py"], {"Bash"}),
            (f"add a --verbose flag that prints each line's number too", ["verbose", "argparse"], {"Edit", "Read", "Write"}),
            (f"refactor to use argparse instead of sys.argv", ["argparse", "ArgumentParser"], {"Edit", "Read", "Write"}),
            (f"add a docstring", ["\"\"\"", "linecount"], {"Edit", "Read", "Write"}),
            (f"run python3 -m py_compile on the file to check for syntax errors", ["py_compile", "linecount"], {"Bash"}),
            (f"add a __name__ == '__main__' guard", ["__main__"], {"Edit", "Read", "Write"}),
            (f"run it with --verbose on {SANDBOX}/hello.py", ["hello"], {"Bash"}),
            (f"show me the final file", ["linecount", "def main"], {"Read", "Bash"}),
            (f"count lines in this file itself", ["linecount.py"], {"Bash"}),
            (f"what's the line count of main.py in the project root", ["main.py"], {"Bash"}),
        ],
    ),

    # L02: debug a failing test and fix it (12 turns)
    Scenario(
        "L02", "L",
        f"Create {SANDBOX}/buggy_math.py with an add(a,b) function that returns a-b (buggy) and a test "
        f"{SANDBOX}/test_buggy_math.py asserting add(2,3)==5.",
        90, ["def add", "def test", "assert"],
        {"Write", "Bash"},
        long_turn=[
            (f"run the test with python3 and show the failure", ["AssertionError", "error", "failed"], {"Bash"}),
            (f"read buggy_math.py and tell me what's wrong", ["a-b", "minus", "a - b", "subtract"], {"Read", "Bash"}),
            (f"fix the bug so add returns a+b", ["a+b", "a + b"], {"Edit", "Read", "Write"}),
            (f"re-run the test and confirm it passes", ["pass", "ok", "success"], {"Bash"}),
            (f"add a second test asserting add(-1,1)==0", ["-1", "0"], {"Edit", "Read", "Write"}),
            (f"run both tests", ["pass", "ok", "2"], {"Bash"}),
            (f"add a test for add('a','b')=='ab' (string concatenation)", ["ab", "string"], {"Edit", "Read", "Write"}),
            (f"run the tests and see what happens", ["ab", "pass"], {"Bash"}),
            (f"add type hints to the add function", ["int", "->"], {"Edit", "Read", "Write"}),
            (f"verify python3 -m py_compile still passes", ["buggy_math"], {"Bash"}),
            (f"show me the final buggy_math.py", ["a + b"], {"Read", "Bash"}),
        ],
    ),

    # L03: explore an unknown codebase (10 turns — uses REAL repo)
    Scenario(
        "L03", "L",
        "I'm new to this codebase. What's the main entry point of the CLI?",
        60, ["main.py", "interactive", "argparse"],
        {"Read", "Grep", "Bash"},
        long_turn=[
            ("What modes does the CLI support?", ["chat", "coding", "fin"], {"Read", "Grep", "Bash"}),
            ("Which file implements coding mode?", ["coding", "agent"], {"Grep", "Bash"}),
            ("Where are the tool definitions registered?", ["tools.py", "tool_definitions", "ToolRegistry"], {"Grep", "Read", "Bash"}),
            ("How many tools are registered?", ["tool"], {"Grep", "Read", "Bash"}),
            ("What does the Bash tool do?", ["bash", "execute", "subprocess"], {"Read", "Grep", "Bash"}),
            ("Where is the agentic loop?", ["agentic_loop", "agent/agentic"], {"Grep", "Bash"}),
            ("What provider chains does the LLM use?", ["provider", "router", "kimi", "deepseek"], {"Grep", "Read", "Bash"}),
            ("Where are the tests for the agentic loop?", ["test_agentic_loop"], {"Glob", "Bash"}),
            ("What's the recent commit history of the agentic loop file?", ["agentic_loop", "fix"], {"Bash"}),
        ],
    ),

    # L04: refactor a file step by step (10 turns)
    Scenario(
        "L04", "L",
        f"Create {SANDBOX}/messy.py with a 30-line function that does too many things: reads a file, "
        f"counts words, prints them, and writes a summary. All in one function.",
        120, ["messy.py", "def "],
        {"Write", "Bash"},
        long_turn=[
            (f"read messy.py and identify 3 distinct responsibilities", ["read", "count", "write"], {"Read", "Bash"}),
            (f"refactor: extract the file-reading logic into read_file()", ["def read_file"], {"Edit", "Read", "Write"}),
            (f"refactor: extract the word counting into count_words()", ["def count_words"], {"Edit", "Read", "Write"}),
            (f"refactor: extract the summary writing into write_summary()", ["def write_summary"], {"Edit", "Read", "Write"}),
            (f"verify messy.py still has a valid main function that calls the three helpers", ["def main", "read_file", "count_words", "write_summary"], {"Read", "Bash"}),
            (f"add type hints to all four functions", ["->", ":"], {"Edit", "Read", "Write"}),
            (f"add docstrings to all four functions", ["\"\"\""], {"Edit", "Read", "Write"}),
            (f"check the final file compiles (py_compile)", ["messy"], {"Bash"}),
            (f"show me the final messy.py", ["def main", "def read_file"], {"Read", "Bash"}),
        ],
    ),

    # L05: add a feature to an existing module (12 turns)
    Scenario(
        "L05", "L",
        f"Create {SANDBOX}/json_config.py with a ConfigManager class that has load_file(path) and get(key) methods.",
        90, ["class ConfigManager", "def load_file", "def get"],
        {"Write", "Bash"},
        long_turn=[
            (f"show me the current json_config.py", ["ConfigManager"], {"Read", "Bash"}),
            (f"create a test file {SANDBOX}/example.json with some keys", ["example.json", "{"], {"Write", "Bash"}),
            (f"add a set(key, value) method to ConfigManager", ["def set"], {"Edit", "Read", "Write"}),
            (f"add a save_file(path) method to persist changes", ["def save_file"], {"Edit", "Read", "Write"}),
            (f"add a delete(key) method", ["def delete"], {"Edit", "Read", "Write"}),
            (f"add an exists(key) method", ["def exists"], {"Edit", "Read", "Write"}),
            (f"make ConfigManager subscriptable — implement __getitem__", ["__getitem__"], {"Edit", "Read", "Write"}),
            (f"also implement __setitem__", ["__setitem__"], {"Edit", "Read", "Write"}),
            (f"add a __len__ method", ["__len__"], {"Edit", "Read", "Write"}),
            (f"write a quick test: create a ConfigManager, load example.json, set/get/delete a key", ["ConfigManager", "set", "get"], {"Write", "Bash"}),
            (f"run the test", ["pass", "ok", "test"], {"Bash"}),
        ],
    ),

    # L06: investigate a bug across multiple files (15 turns)
    Scenario(
        "L06", "L",
        f"Create a small broken project at {SANDBOX}/proj/ with main.py importing utils.py's format_output(), "
        f"and utils.py defining format_output but returning the WRONG type (string instead of dict). Create both files.",
        150, ["main.py", "utils.py", "format_output"],
        {"Write", "Bash"},
        long_turn=[
            (f"run python3 {SANDBOX}/proj/main.py", ["error", "TypeError", "main"], {"Bash"}),
            (f"read main.py to see what it expects", ["format_output", "dict"], {"Read", "Bash"}),
            (f"read utils.py to see what it returns", ["format_output", "return"], {"Read", "Bash"}),
            (f"identify the root cause in one sentence", ["dict", "string", "str", "type"], None),
            (f"fix utils.py to return a dict", ["return {"], {"Edit", "Read", "Write"}),
            (f"re-run python3 {SANDBOX}/proj/main.py", ["output"], {"Bash"}),
            (f"add a type hint -> dict to format_output", ["dict", "->"], {"Edit", "Read", "Write"}),
            (f"run main.py one more time to confirm", ["output"], {"Bash"}),
            (f"also add a test file {SANDBOX}/proj/test_utils.py asserting format_output returns a dict", ["isinstance", "dict"], {"Write", "Bash"}),
            (f"run the test", ["pass", "ok"], {"Bash"}),
            (f"show me the final utils.py", ["return {", "format_output"], {"Read", "Bash"}),
            (f"show me the final main.py", ["format_output"], {"Read", "Bash"}),
            (f"show me the test file", ["isinstance", "dict"], {"Read", "Bash"}),
            (f"count total lines across all 3 files", ["main.py", "utils.py", "test_utils.py"], {"Bash"}),
        ],
    ),
]


# ── Combined registry ────────────────────────────────────────────────

ALL_SCENARIOS: List[Scenario] = (
    N_SCENARIOS + R_SCENARIOS + G_SCENARIOS + B_SCENARIOS
    + V_SCENARIOS + T_SCENARIOS + E_SCENARIOS + F_SCENARIOS
    + D_SCENARIOS + X_SCENARIOS + L_SCENARIOS
)

# Non-long-turn subset for smoke runs
SHORT_SCENARIOS: List[Scenario] = [s for s in ALL_SCENARIOS if s.long_turn is None]

# Category thresholds (tolerances for known flakes):
#   pass_count >= threshold → category PASS
CATEGORY_THRESHOLDS = {
    "N": 18,  # out of 20
    "R": 14,  # out of 15
    "G": 14,  # out of 15
    "B": 18,  # out of 20
    "V": 18,  # out of 20
    "T": 13,  # out of 15
    "E": 13,  # out of 15
    "F": 13,  # out of 15
    "D": 13,  # out of 15
    "X": 13,  # out of 15 — error recovery
    "L": 5,   # out of 6 — long-turn, allow one flake
}


def scenario_count_summary():
    """Return a summary of scenario counts by category."""
    counts = {}
    for s in ALL_SCENARIOS:
        counts.setdefault(s.category, 0)
        counts[s.category] += 1
    total = sum(counts.values())
    # Long-turn scenarios are counted by seed (1) not by follow-up count
    long_turn_total_turns = sum(
        1 + len(s.long_turn or []) for s in L_SCENARIOS
    )
    return {
        "by_category": counts,
        "total_seeds": total,
        "short_only": len(SHORT_SCENARIOS),
        "long_total_turns": long_turn_total_turns,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(scenario_count_summary(), indent=2))
