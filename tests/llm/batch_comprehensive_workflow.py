#!/usr/bin/env python3
"""
Comprehensive real-terminal workflow tests for NeoMind.
Batch 1-4: Developer workflows, complex multi-tool, UI stress, session management.

Runs against real `python3 main.py --mode coding` via pexpect.
Appends results to BUG_REPORTS.md.
"""

import os
import sys
import re
import time
import pexpect
import traceback

NEOMIND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_PATH = os.path.join(NEOMIND_DIR, 'tests', 'llm', 'BUG_REPORTS.md')

LLM_TIMEOUT = 120
CMD_TIMEOUT = 15
STARTUP_TIMEOUT = 30


def clean_ansi(text):
    """Remove ANSI escape codes, spinners, thinking animation."""
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\[\?[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'[\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f]', '', text)
    text = re.sub(r'\[K', '', text)
    text = re.sub(r'Thinking\u2026', '', text)
    text = re.sub(r'Thought for [\d.]+s [^\n]*\n?', '', text)
    text = re.sub(r'\r', '', text)
    return text.strip()


def check_thinking_leak(text):
    """Check if <think> tokens leaked into visible output."""
    leaks = []
    for pat in [r'<think>', r'</think>', r'<\|thinking\|>', r'<\|/thinking\|>']:
        if re.search(pat, text):
            leaks.append(pat)
    return leaks


def check_spinner_garbage(text):
    """Check for leftover spinner/progress artifacts."""
    garbage = []
    # spinner chars that shouldn't appear in final text
    if re.search(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]{3,}', text):
        garbage.append('spinner_chars')
    if re.search(r'\x1b\[', text):
        garbage.append('raw_ansi')
    return garbage


class WorkflowTester:
    def __init__(self, mode='coding'):
        self.child = None
        self.results = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.mode = mode

    def start(self):
        env = os.environ.copy()
        env['NEOMIND_DISABLE_VAULT'] = '1'
        env['NEOMIND_AUTO_ACCEPT'] = '1'
        env['PYTHONPATH'] = NEOMIND_DIR
        env['TERM'] = 'dumb'

        print(f"Starting NeoMind in {self.mode} mode...")
        self.child = pexpect.spawn(
            'python3', ['main.py', '--mode', self.mode],
            cwd=NEOMIND_DIR, env=env, encoding='utf-8',
            timeout=STARTUP_TIMEOUT, maxread=65536,
            dimensions=(50, 200),
        )

        self.child.setecho(False)
        try:
            self.child.expect(r'> $', timeout=STARTUP_TIMEOUT)
            print(f"  NeoMind started OK (mode={self.mode})")
            return True
        except (pexpect.TIMEOUT, pexpect.EOF):
            out = self.child.before[:500] if self.child.before else 'none'
            print(f"  Startup FAILED. Output: {out}")
            return False

    def _drain(self):
        for _ in range(5):
            try:
                self.child.read_nonblocking(size=65536, timeout=1.0)
            except (pexpect.TIMEOUT, pexpect.EOF):
                break
            time.sleep(0.3)

    def send_command(self, command):
        """Send a slash command (instant, no LLM)."""
        self._drain()
        time.sleep(1)
        self.child.sendline(command)
        try:
            self.child.expect(r'> $', timeout=CMD_TIMEOUT)
            raw = self.child.before or ""
            r = clean_ansi(raw)
            if command in r:
                r = r.split(command, 1)[-1].strip()
            return r
        except pexpect.TIMEOUT:
            return clean_ansi(self.child.before or "")
        except pexpect.EOF:
            return "[EOF]"

    def send_chat(self, message):
        """Send a chat message (waits for LLM response)."""
        self._drain()
        time.sleep(3)
        self.child.sendline(message)
        try:
            self.child.expect(r'> $', timeout=LLM_TIMEOUT)
            raw = self.child.before or ""
            r = clean_ansi(raw)
            if message in r:
                r = r.split(message, 1)[-1].strip()
            return r
        except pexpect.TIMEOUT:
            return clean_ansi(self.child.before or "")
        except pexpect.EOF:
            return "[EOF]"

    def check(self, scenario_id, scenario_name, response, conditions, is_chat=True):
        """
        conditions: list of (description, bool_result)
        Also auto-checks: not empty, no thinking leak, no spinner garbage, no duplication.
        """
        issues = []
        passed = True

        # Auto-check 1: Response arrived
        if not response or len(response) < 5:
            issues.append(f"EMPTY or too short response (len={len(response) if response else 0})")
            passed = False

        # Auto-check 2: No thinking token leak
        leaks = check_thinking_leak(response)
        if leaks:
            issues.append(f"THINKING TOKEN LEAK: {leaks}")
            passed = False

        # Auto-check 3: No spinner garbage
        garbage = check_spinner_garbage(response)
        if garbage:
            issues.append(f"SPINNER GARBAGE: {garbage}")
            # warning, not failure
            self.warnings += 1

        # Auto-check 4: Content checks
        for desc, result in conditions:
            if not result:
                issues.append(f"FAILED: {desc}")
                passed = False

        detail = "; ".join(issues) if issues else "OK"
        snippet = response[:150].replace('\n', ' ') if response else "(empty)"

        self.results.append({
            'id': scenario_id,
            'name': scenario_name,
            'passed': passed,
            'detail': detail,
            'snippet': snippet,
        })

        if passed:
            self.passed += 1
            print(f"  PASS {scenario_id}: {scenario_name}")
        else:
            self.failed += 1
            print(f"  FAIL {scenario_id}: {scenario_name}")
            print(f"       {detail}")
            print(f"       snippet: {snippet[:120]}")

        return passed

    def stop(self):
        if self.child and self.child.isalive():
            try:
                self.child.sendline('/exit')
                time.sleep(1)
            except:
                pass
            try:
                if self.child.isalive():
                    self.child.terminate(force=True)
            except:
                pass


def run_batch1(t):
    """Batch 1: Developer daily workflow."""
    print("\n" + "=" * 60)
    print("BATCH 1: Developer Daily Workflow")
    print("=" * 60)

    # S1001: Morning startup — git changes
    r = t.send_chat("Show me the current git status")
    t.check("S1001", "Git status query", r, [
        ("mentions git or status or branch or file",
         any(w in r.lower() for w in ['git', 'status', 'branch', 'commit', 'file', 'track', 'untrack', 'modif', 'clean'])),
    ])

    # S1002: What branch
    r = t.send_chat("What git branch am I on?")
    t.check("S1002", "Git branch query", r, [
        ("mentions a branch name or git info",
         any(w in r.lower() for w in ['branch', 'main', 'master', 'git', 'head', 'current'])),
    ])

    # S1003: Code review request
    r = t.send_chat("Review agent/agentic/agentic_loop.py briefly — any obvious bugs or improvements?")
    t.check("S1003", "Code review request", r, [
        ("provides code analysis or review",
         len(r) > 50 and any(w in r.lower() for w in ['code', 'function', 'loop', 'error', 'improv', 'bug', 'suggest', 'review', 'file', 'read', 'agent'])),
    ])

    # S1004: Chinese language code question
    r = t.send_chat("main.py的核心功能是什么？用中文简短回答")
    t.check("S1004", "Chinese language query about main.py", r, [
        ("response is non-trivial",
         len(r) > 30),
        ("mentions main or entry or function or NeoMind concepts",
         any(w in r.lower() for w in ['main', 'entry', 'mode', 'neomind', 'agent', 'cli', 'chat', 'coding', 'fin',
                                       '入口', '模式', '主', '功能', '命令'])),
    ])

    # S1005: Write a function
    r = t.send_chat("Write a Python function that validates email addresses using regex. Include type hints and docstring. Just the code, no explanation.")
    t.check("S1005", "Code generation: email validator", r, [
        ("contains def keyword", 'def ' in r),
        ("contains re or regex usage", 're.' in r or 'regex' in r.lower() or 'import re' in r),
        ("contains type hints", '->' in r or ': str' in r or ': bool' in r),
    ])

    # S1006: Write tests for it
    r = t.send_chat("Now write pytest unit tests for that email validation function. Just the code.")
    t.check("S1006", "Code generation: pytest tests", r, [
        ("contains test function", 'def test_' in r or 'def test' in r),
        ("mentions pytest or assert", 'assert' in r or 'pytest' in r),
    ])


def run_batch2(t):
    """Batch 2: Complex multi-tool tasks."""
    print("\n" + "=" * 60)
    print("BATCH 2: Complex Multi-Tool Tasks")
    print("=" * 60)

    # S2001: Count Python files + find largest
    r = t.send_chat("Count all Python files in the project. Just tell me the total count.")
    t.check("S2001", "Count Python files in project", r, [
        ("contains a number", bool(re.search(r'\d+', r))),
        ("mentions python or .py or files", any(w in r.lower() for w in ['python', '.py', 'file'])),
    ])

    # S2002: TODO search
    r = t.send_chat("Search for TODO comments in the agent/ directory. Summarize what you find briefly.")
    t.check("S2002", "Search TODO comments", r, [
        ("response is substantive", len(r) > 30),
        ("mentions TODO or tasks or findings",
         any(w in r.lower() for w in ['todo', 'task', 'found', 'comment', 'none', 'no ', 'fix', 'implement'])),
    ])

    # S2003: Import dependency analysis
    r = t.send_chat("What are the import dependencies of main.py? List them briefly.")
    t.check("S2003", "Import dependency analysis", r, [
        ("mentions imports or modules",
         any(w in r.lower() for w in ['import', 'module', 'depend', 'os', 'sys', 'agent'])),
    ])

    # S2004: Multi-file comparison
    r = t.send_chat("Briefly compare agent_config.py and main.py — what does each one do?")
    t.check("S2004", "Multi-file comparison", r, [
        ("mentions both files or their purposes", len(r) > 50),
        ("discusses functionality",
         any(w in r.lower() for w in ['config', 'main', 'entry', 'setting', 'function', 'class', 'purpose'])),
    ])


def run_batch3(t):
    """Batch 3: Terminal UI stress test."""
    print("\n" + "=" * 60)
    print("BATCH 3: Terminal UI Stress Test")
    print("=" * 60)

    # S3001: Long output — list files
    r = t.send_chat("List all files in the agent/ directory recursively. Just filenames.")
    t.check("S3001", "Long output: recursive file listing", r, [
        ("contains file names with .py extension", '.py' in r),
        ("response length is reasonable for a directory listing", len(r) > 50),
    ])

    # S3002: Think mode on
    r = t.send_command('/think')
    t.check("S3002", "/think toggle ON", r, [
        ("acknowledges think mode", any(w in r.lower() for w in ['think', 'enabled', 'extended', 'on', 'toggle'])),
    ])

    # S3003: Chat with think mode on
    r = t.send_chat("Explain recursion in 2 sentences.")
    leaks = check_thinking_leak(r)
    t.check("S3003", "Chat with think mode ON", r, [
        ("provides explanation", len(r) > 20),
        ("no thinking tokens leaked", len(leaks) == 0),
        ("mentions recursion concept", any(w in r.lower() for w in ['recursion', 'recursive', 'call', 'itself', 'base'])),
    ])

    # S3004: Think mode off
    r = t.send_command('/think')
    t.check("S3004", "/think toggle OFF", r, [
        ("acknowledges think mode change", any(w in r.lower() for w in ['think', 'disabled', 'off', 'toggle', 'standard'])),
    ])

    # S3005: Chat after think off
    r = t.send_chat("Explain recursion again in 1 sentence.")
    t.check("S3005", "Chat with think mode OFF", r, [
        ("provides explanation", len(r) > 10),
        ("no thinking tokens leaked", len(check_thinking_leak(r)) == 0),
    ])

    # S3006: Error handling — nonexistent file
    r = t.send_chat("Read the file /nonexistent/path/bogus.txt")
    t.check("S3006", "Error handling: nonexistent file read", r, [
        ("handles error gracefully — no crash",
         len(r) > 5 and '[EOF]' not in r),
        ("mentions error or not found or doesn't exist",
         any(w in r.lower() for w in ['error', 'not found', 'not exist', "doesn't exist", 'no such', 'cannot', "can't", 'unable'])),
    ])

    # S3007: Chinese + tool use
    r = t.send_chat("用中文简单告诉我pyproject.toml里项目的名称和版本号")
    t.check("S3007", "Chinese + tool use: pyproject.toml analysis", r, [
        ("response is non-trivial", len(r) > 15),
        ("mentions neomind or version",
         any(w in r.lower() for w in ['neomind', '0.2', 'version', '版本', '名称', '项目'])),
    ])


def run_batch4(t):
    """Batch 4: Session and state management."""
    print("\n" + "=" * 60)
    print("BATCH 4: Session & State Management")
    print("=" * 60)

    # S4001: Memory test — set a fact
    r = t.send_chat("Remember this: my project deadline is next Friday. Acknowledge.")
    t.check("S4001", "Set memory: deadline fact", r, [
        ("acknowledges the information", len(r) > 5),
        ("mentions deadline or friday or remember",
         any(w in r.lower() for w in ['deadline', 'friday', 'remember', 'noted', 'acknowledged', 'got it', 'will remember'])),
    ])

    # S4002: Recall the fact
    r = t.send_chat("What is my project deadline?")
    t.check("S4002", "Recall memory: deadline", r, [
        ("recalls friday or deadline info",
         any(w in r.lower() for w in ['friday', 'deadline', 'next week'])),
    ])

    # S4003: /save session
    save_path = '/tmp/neomind_test_session.md'
    r = t.send_command(f'/save {save_path}')
    t.check("S4003", "/save session to file", r, [
        ("command executed without crash", '[EOF]' not in r),
    ])

    # S4004: /config check
    r = t.send_command('/config')
    t.check("S4004", "/config shows settings", r, [
        ("shows configuration info",
         any(w in r.lower() for w in ['mode', 'model', 'config', 'temperature', 'setting', 'coding'])),
    ])

    # S4005: /context check
    r = t.send_command('/context')
    t.check("S4005", "/context shows token info", r, [
        ("shows context info",
         any(w in r.lower() for w in ['context', 'token', 'message', 'conversation'])),
    ])

    # S4006: /help
    r = t.send_command('/help')
    t.check("S4006", "/help shows available commands", r, [
        ("lists commands", len(r) > 30),
        ("mentions some commands",
         any(w in r.lower() for w in ['help', 'think', 'exit', 'mode', 'save', 'command'])),
    ])

    # S4007: What tools does NeoMind have
    r = t.send_chat("What tools or capabilities do you have? List them briefly.")
    t.check("S4007", "Tools/capabilities self-report", r, [
        ("lists tools or capabilities", len(r) > 30),
        ("mentions specific tools",
         any(w in r.lower() for w in ['read', 'write', 'search', 'file', 'tool', 'execute', 'bash', 'code'])),
    ])


def write_report(results, passed, failed, warnings):
    """Append results to BUG_REPORTS.md."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "",
        "---",
        "",
        f"## {ts} — Comprehensive Workflow Tests (Batches 1-4)",
        "",
        f"**Environment:** `TERM=dumb`, `NEOMIND_AUTO_ACCEPT=1`, `NEOMIND_DISABLE_VAULT=1`",
        f"**Mode:** coding",
        f"**LLM Timeout:** {LLM_TIMEOUT}s",
        "",
        f"### Summary",
        f"- **Passed:** {passed}",
        f"- **Failed:** {failed}",
        f"- **Warnings:** {warnings}",
        f"- **Total:** {passed + failed}",
        "",
    ]

    # Failures section
    failures = [r for r in results if not r['passed']]
    if failures:
        lines.append("### FAILURES:")
        lines.append("")
        for r in failures:
            lines.append(f"- **{r['id']} ({r['name']}):** {r['detail']}")
            lines.append(f"  - Snippet: `{r['snippet'][:120]}`")
        lines.append("")

    # All results
    lines.append("### All Results:")
    lines.append("")

    current_batch = ""
    for r in results:
        batch = r['id'][0:2]  # S1, S2, S3, S4
        batch_num = r['id'][1]
        batch_label = {
            '1': 'Batch 1: Developer Daily Workflow',
            '2': 'Batch 2: Complex Multi-Tool Tasks',
            '3': 'Batch 3: Terminal UI Stress Test',
            '4': 'Batch 4: Session & State Management',
        }.get(batch_num, f'Batch {batch_num}')

        if batch_num != current_batch:
            current_batch = batch_num
            lines.append(f"**{batch_label}:**")

        mark = "PASS" if r['passed'] else "FAIL"
        lines.append(f"- {r['id']}: {r['name']} -- {mark}")

    lines.append("")

    # Bug analysis
    if failures:
        lines.append("### Bug Analysis:")
        lines.append("")
        for r in failures:
            lines.append(f"#### {r['id']}: {r['name']}")
            lines.append(f"- **Issue:** {r['detail']}")
            lines.append(f"- **Output snippet:** `{r['snippet'][:200]}`")
            lines.append(f"- **Severity:** {'HIGH' if 'LEAK' in r['detail'] or 'EOF' in r['detail'] or 'EMPTY' in r['detail'] else 'MEDIUM'}")
            lines.append("")

    # Append to file
    with open(REPORT_PATH, 'a') as f:
        f.write('\n'.join(lines))
    print(f"\nReport appended to {REPORT_PATH}")


def main():
    t = WorkflowTester(mode='coding')
    if not t.start():
        print("FATAL: Could not start NeoMind. Aborting.")
        sys.exit(1)

    try:
        run_batch1(t)
        run_batch2(t)
        run_batch3(t)
        run_batch4(t)
    except Exception as e:
        print(f"\nEXCEPTION during test: {e}")
        traceback.print_exc()
        t.results.append({
            'id': 'SXXXX',
            'name': f'EXCEPTION: {e}',
            'passed': False,
            'detail': traceback.format_exc()[:300],
            'snippet': str(e)[:150],
        })
        t.failed += 1
    finally:
        t.stop()

    write_report(t.results, t.passed, t.failed, t.warnings)

    print(f"\n{'=' * 60}")
    print(f"FINAL: {t.passed} passed, {t.failed} failed, {t.warnings} warnings")
    print(f"{'=' * 60}")

    return t.failed == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
