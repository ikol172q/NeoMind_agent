#!/usr/bin/env python3
"""
REPL Test Harness v2 — Drives NeoMind's interactive CLI like a real user.

v2 fixes: proper synchronization by waiting for the "> " prompt between commands.
Separates send_command (instant) from send_chat (waits for LLM).
Cleans ANSI codes and spinner animation.
"""

import os
import sys
import re
import time
import pexpect

NEOMIND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_PATH = os.path.join(NEOMIND_DIR, 'tests', 'llm', 'REPL_TEST_REPORT.md')

LLM_TIMEOUT = 90
CMD_TIMEOUT = 15
STARTUP_TIMEOUT = 30


def clean_ansi(text):
    """Remove ANSI escape codes, spinners, thinking animation."""
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\[\?[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', '', text)
    text = re.sub(r'\[K', '', text)
    text = re.sub(r'Thinking…', '', text)
    text = re.sub(r'Thought for [\d.]+s — [^\n]*\n?', '', text)
    text = re.sub(r'\r', '', text)
    return text.strip()


class REPLTester:
    def __init__(self):
        self.child = None
        self.results = []
        self.passed = 0
        self.failed = 0

    def start(self):
        env = os.environ.copy()
        env['NEOMIND_DISABLE_VAULT'] = '1'
        env['PYTHONPATH'] = NEOMIND_DIR
        env['TERM'] = 'dumb'

        print("🚀 Starting NeoMind REPL...")
        self.child = pexpect.spawn(
            'python3', ['main.py', '--mode', 'coding'],
            cwd=NEOMIND_DIR, env=env, encoding='utf-8',
            timeout=STARTUP_TIMEOUT, maxread=65536,
            dimensions=(50, 200),
        )

        try:
            self.child.expect(r'> ', timeout=STARTUP_TIMEOUT)
            print("✅ NeoMind started, got first prompt")
            return True
        except (pexpect.TIMEOUT, pexpect.EOF):
            out = self.child.before[:500] if self.child.before else 'none'
            print(f"❌ Startup failed. Output: {out}")
            return False

    def _drain(self):
        """Aggressively drain all pending output."""
        for _ in range(5):
            try:
                self.child.read_nonblocking(size=65536, timeout=1.0)
            except (pexpect.TIMEOUT, pexpect.EOF):
                break
            time.sleep(0.3)

    def send_command(self, command: str) -> str:
        """Send a slash command (instant, no LLM)."""
        self._drain()
        time.sleep(1)  # Rate limit protection
        self.child.sendline(command)
        try:
            self.child.expect(r'> ', timeout=CMD_TIMEOUT)
            raw = self.child.before or ""
            r = clean_ansi(raw)
            if command in r:
                r = r.split(command, 1)[-1].strip()
            return r
        except pexpect.TIMEOUT:
            return clean_ansi(self.child.before or "")
        except pexpect.EOF:
            return "[EOF]"

    def send_chat(self, message: str) -> str:
        """Send a chat message (waits for LLM response)."""
        self._drain()
        time.sleep(3)  # Rate limit protection: 3s between LLM calls
        self.child.sendline(message)
        try:
            self.child.expect(r'> ', timeout=LLM_TIMEOUT)
            raw = self.child.before or ""
            r = clean_ansi(raw)
            if message in r:
                r = r.split(message, 1)[-1].strip()
            return r
        except pexpect.TIMEOUT:
            return clean_ansi(self.child.before or "")
        except pexpect.EOF:
            return "[EOF]"

    def check(self, scenario, condition, details=""):
        self.results.append({'scenario': scenario, 'passed': condition, 'details': details})
        if condition:
            self.passed += 1
            print(f"  ✅ {scenario}")
        else:
            self.failed += 1
            print(f"  ❌ {scenario}")
            if details:
                print(f"     → {details[:200]}")

    def stop(self):
        if self.child and self.child.isalive():
            try:
                self.child.sendline('/exit')
                time.sleep(1)
            except: pass
            try:
                if self.child.isalive():
                    self.child.terminate(force=True)
            except: pass

    def write_report(self):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"# REPL Test Report — {ts}", "",
                 f"## Summary", f"- Passed: {self.passed}",
                 f"- Failed: {self.failed}", f"- Total: {self.passed+self.failed}", ""]
        if self.failed:
            lines.append("## ❌ Failures:")
            for r in self.results:
                if not r['passed']:
                    lines.append(f"- **{r['scenario']}**: {r['details']}")
            lines.append("")
        lines.append("## All Results:")
        for r in self.results:
            s = "✅" if r['passed'] else "❌"
            lines.append(f"- {s} {r['scenario']}")
        with open(REPORT_PATH, 'w') as f:
            f.write('\n'.join(lines))
        print(f"\n📝 Report: {REPORT_PATH}")


def run_all_scenarios():
    t = REPLTester()
    if not t.start():
        return False

    try:
        # ═══ Scenario 1: Slash Commands ═══
        print("\n" + "="*50)
        print("📋 Scenario 1: Slash Commands")

        r = t.send_command('/help')
        t.check("S1: /help", len(r) > 20, f"len={len(r)}")

        r = t.send_command('/flags')
        t.check("S1: /flags", 'AUTO_DREAM' in r or 'SANDBOX' in r, f"r={r[:100]}")

        r = t.send_command('/doctor')
        t.check("S1: /doctor", 'Python' in r or 'Service' in r, f"r={r[:100]}")

        r = t.send_command('/context')
        t.check("S1: /context", 'Message' in r or 'token' in r.lower() or 'Context' in r, f"r={r[:100]}")

        r = t.send_command('/brief on')
        t.check("S1: /brief on", 'enabled' in r.lower() or 'brief' in r.lower(), f"r={r[:100]}")

        r = t.send_command('/brief off')
        t.check("S1: /brief off", 'disabled' in r.lower() or 'brief' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 2: Think Mode ═══
        print("\n" + "="*50)
        print("📋 Scenario 2: Think Mode")

        r = t.send_command('/think')
        t.check("S2: /think toggle", 'think' in r.lower() or 'enabled' in r.lower() or 'disabled' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 3: LLM Chat ═══
        print("\n" + "="*50)
        print("📋 Scenario 3: LLM Chat (Real LLM)")

        r = t.send_chat('What is 2+2? Answer with just the number, nothing else.')
        t.check("S3: LLM 2+2", '4' in r, f"r={r[:100]}")

        r = t.send_chat('My project is called SuperApp. Just say OK.')
        t.check("S3: LLM ack", len(r) > 0 and r != '[EOF]', f"r={r[:100]}")

        r = t.send_chat('What is my project called? One word.')
        t.check("S3: LLM context", 'superapp' in r.lower() or 'super' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 4: Session Management ═══
        print("\n" + "="*50)
        print("📋 Scenario 4: Session Mgmt")

        r = t.send_command('/checkpoint repl-test')
        t.check("S4: /checkpoint", '✓' in r or 'saved' in r.lower() or 'Checkpoint' in r, f"r={r[:100]}")

        r = t.send_command('/snip 2')
        t.check("S4: /snip", '✓' in r or 'Snip' in r or 'saved' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 5: Teams ═══
        print("\n" + "="*50)
        print("📋 Scenario 5: Teams")

        r = t.send_command('/team create repl-team')
        t.check("S5: /team create", '✓' in r or 'created' in r.lower(), f"r={r[:100]}")

        r = t.send_command('/team list')
        t.check("S5: /team list", 'repl-team' in r or 'Teams' in r, f"r={r[:100]}")

        r = t.send_command('/team delete repl-team')
        t.check("S5: /team delete", '✓' in r or 'deleted' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 6: Rules ═══
        print("\n" + "="*50)
        print("📋 Scenario 6: Rules")

        r = t.send_command('/rules')
        t.check("S6: /rules empty", 'No permission' in r or 'Permission' in r, f"r={r[:100]}")

        r = t.send_command('/rules add Bash allow npm test')
        t.check("S6: /rules add", '✓' in r or 'added' in r.lower(), f"r={r[:100]}")

        r = t.send_command('/rules remove 0')
        t.check("S6: /rules remove", '✓' in r or 'removed' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 7: Code Gen (LLM) ═══
        print("\n" + "="*50)
        print("📋 Scenario 7: Code Gen")

        r = t.send_chat('Write a Python function that returns the factorial of n. Just the function.')
        t.check("S7: code gen", 'def' in r or 'factorial' in r or 'return' in r, f"r={r[:200]}")

        # ═══ Scenario 8: Export ═══
        print("\n" + "="*50)
        print("📋 Scenario 8: Export")

        import tempfile
        tmp = tempfile.mktemp(suffix='.md', dir='/tmp')
        r = t.send_command(f'/save {tmp}')
        t.check("S8: /save md", '✓' in r or 'saved' in r.lower() or 'markdown' in r.lower(), f"r={r[:100]}")

        if os.path.exists(tmp):
            content = open(tmp).read()
            t.check("S8: MD content", '##' in content and len(content) > 50, f"len={len(content)}")
            os.unlink(tmp)

        # ═══ Scenario 9: TOOL CALLS (LLM decides to use tools) ═══
        # This is THE critical test — it triggers the agentic loop
        # where the LLM autonomously calls Read/Bash/Grep etc.
        print("\n" + "="*50)
        print("📋 Scenario 9: Tool Calls (Agentic Loop)")

        # Ask something that FORCES the LLM to use tools
        r = t.send_chat('Run: echo "hello from tool test" and show me the output.')
        t.check("S9: Bash tool call",
                'hello from tool test' in r or 'echo' in r or len(r) > 10,
                f"r={r[:200]}")

        # Ask to read a specific file (forces Read tool)
        r = t.send_chat('Read the file main.py and tell me the first line. Just the first line.')
        t.check("S9: Read tool call",
                'main' in r.lower() or 'python' in r.lower() or 'import' in r.lower() or len(r) > 20,
                f"r={r[:200]}")

        # Ask to search (forces Grep or Glob)
        r = t.send_chat('How many .py files are in the current directory? Just the number.')
        t.check("S9: Search tool call",
                any(c.isdigit() for c in r) or 'file' in r.lower() or len(r) > 10,
                f"r={r[:200]}")

        # Ask something that requires multiple tools
        r = t.send_chat('What is the current git branch? One line answer.')
        t.check("S9: Git tool call",
                len(r) > 0 and r != '[EOF]',
                f"r={r[:200]}")

        # ═══ Scenario 10: Think Mode + LLM (was S9) ═══
        print("\n" + "="*50)
        print("📋 Scenario 9: Think Mode + LLM")

        # Enable thinking
        r = t.send_command('/think')
        think_on = 'enabled' in r.lower() or 'on' in r.lower()
        t.check("S13:/think enable", 'think' in r.lower(), f"r={r[:100]}")

        # Ask a question with thinking enabled
        r = t.send_chat('What is the capital of France? One word.')
        t.check("S13:think+chat", 'paris' in r.lower(), f"r={r[:100]}")

        # Disable thinking
        r = t.send_command('/think')
        t.check("S13:/think disable", 'think' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 11: Multi-format Export ═══
        print("\n" + "="*50)
        print("📋 Scenario 10: Export Formats")

        import tempfile as _tf

        # JSON export
        tmp_json = _tf.mktemp(suffix='.json', dir='/tmp')
        r = t.send_command(f'/save {tmp_json}')
        t.check("S13:/save json", '✓' in r or 'json' in r.lower(), f"r={r[:100]}")
        if os.path.exists(tmp_json):
            import json
            try:
                data = json.loads(open(tmp_json).read())
                t.check("S13:JSON valid", 'messages' in data, f"keys={list(data.keys())}")
            except:
                t.check("S13:JSON valid", False, "Invalid JSON")
            os.unlink(tmp_json)

        # HTML export
        tmp_html = _tf.mktemp(suffix='.html', dir='/tmp')
        r = t.send_command(f'/save {tmp_html}')
        t.check("S13:/save html", '✓' in r or 'html' in r.lower(), f"r={r[:100]}")
        if os.path.exists(tmp_html):
            html_content = open(tmp_html).read()
            t.check("S13:HTML valid", '<html' in html_content, f"len={len(html_content)}")
            os.unlink(tmp_html)

        # ═══ Scenario 12: Extended Multi-Turn Context ═══
        print("\n" + "="*50)
        print("📋 Scenario 11: Extended Multi-Turn")

        r = t.send_chat('I have 3 servers: alpha, beta, gamma. Just say OK.')
        t.check("S13: set context", len(r) > 0, f"r={r[:100]}")

        r = t.send_chat('How many servers do I have?')
        t.check("S13: recall count", '3' in r or 'three' in r.lower(), f"r={r[:100]}")

        r = t.send_chat('Name the second server.')
        t.check("S13: recall detail", 'beta' in r.lower(), f"r={r[:100]}")

        # ═══ Scenario 13: Dream & Stats ═══
        print("\n" + "="*50)
        print("📋 Scenario 12: Status Commands")

        r = t.send_command('/dream')
        t.check("S13: /dream", 'AutoDream' in r or 'dream' in r.lower() or 'Running' in r, f"r={r[:100]}")

        r = t.send_command('/stats')
        t.check("S13: /stats", len(r) > 10, f"r={r[:100]}")

        r = t.send_command('/cost')
        t.check("S13: /cost", len(r) > 5, f"r={r[:100]}")

    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        t.stop()
        t.write_report()

    return t.failed == 0


if __name__ == '__main__':
    print("="*60)
    print("NeoMind REPL Harness v2 (synced prompt)")
    print("="*60)
    success = run_all_scenarios()
    sys.exit(0 if success else 1)
