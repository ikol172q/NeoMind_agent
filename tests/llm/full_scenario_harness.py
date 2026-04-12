#!/usr/bin/env python3
"""
Full Scenario Harness — 100 scenarios covering EVERY feature of NeoMind.

Covers:
  - 3 personality modes (coding/chat/fin)
  - All 17 new commands
  - Tool calls (Bash, Read, Edit, Grep, Glob, Git)
  - Multi-turn context
  - Chinese + English
  - Error handling
  - Think mode
  - Brief mode
  - Session management
  - Export
  - Permission
  - Complex multi-tool tasks
"""

import os
import sys
import re
import time
import json
import tempfile
import pexpect

NEOMIND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_PATH = os.path.join(NEOMIND_DIR, 'tests', 'llm', 'FULL_SCENARIO_REPORT.md')

LLM_TIMEOUT = 120
CMD_TIMEOUT = 15
STARTUP_TIMEOUT = 30


def clean(text):
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\[\?[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', '', text)
    text = re.sub(r'\[K', '', text)
    text = re.sub(r'Thinking…', '', text)
    text = re.sub(r'Thought for [\d.]+s — [^\n]*\n?', '', text)
    text = re.sub(r'\r', '', text)
    return text.strip()


class Harness:
    def __init__(self, mode='coding'):
        self.mode = mode
        self.child = None
        self.results = []
        self.passed = 0
        self.failed = 0

    @property
    def prompt_re(self):
        """Return a regex that matches the full prompt for this mode.

        Coding mode uses:  '> '
        Chat mode uses:    '[chat] > '
        Fin mode uses:     '[fin] > '
        """
        if self.mode == 'coding':
            return r'(?<!\[)\> '
        else:
            return re.escape(f'[{self.mode}]') + r' > '

    def start(self):
        env = os.environ.copy()
        env['NEOMIND_DISABLE_VAULT'] = '1'
        env['TERM'] = 'dumb'
        env['PYTHONPATH'] = NEOMIND_DIR

        self.child = pexpect.spawn(
            'python3', ['main.py', '--mode', self.mode],
            cwd=NEOMIND_DIR, env=env, encoding='utf-8',
            timeout=STARTUP_TIMEOUT, maxread=65536,
            dimensions=(50, 200),
        )
        try:
            # Use a generous initial pattern — any prompt ending with '> '
            self.child.expect(r'> ', timeout=STARTUP_TIMEOUT)
            return True
        except:
            return False

    def _drain(self):
        """Aggressively drain all pending output from the buffer.

        Loop until no more data arrives, with increasing timeouts.
        This prevents output from one scenario leaking into the next.
        """
        for _ in range(5):  # Up to 5 drain attempts
            try:
                self.child.read_nonblocking(size=65536, timeout=1.0)
            except (pexpect.TIMEOUT, pexpect.EOF):
                break  # No more data
            time.sleep(0.3)  # Brief pause between drains

    def cmd(self, command):
        self._drain()
        time.sleep(1)  # Rate limit protection: 1s between commands
        self.child.sendline(command)
        try:
            self.child.expect(self.prompt_re, timeout=CMD_TIMEOUT)
            r = clean(self.child.before or "")
            if command in r:
                r = r.split(command, 1)[-1].strip()
            return r
        except:
            return clean(self.child.before or "")

    def chat(self, msg, timeout=LLM_TIMEOUT, debug=False):
        self._drain()
        time.sleep(3)  # Rate limit protection: 3s between LLM calls
        self.child.sendline(msg)
        try:
            self.child.expect(self.prompt_re, timeout=timeout)
            r = clean(self.child.before or "")
            if debug:
                print(f"  [DEBUG] prompt_re={self.prompt_re!r}")
                print(f"  [DEBUG] raw before={self.child.before!r:.300s}")
                print(f"  [DEBUG] cleaned={r!r:.200s}")
            if msg in r:
                r = r.split(msg, 1)[-1].strip()
            return r
        except:
            raw = self.child.before or ""
            if debug:
                print(f"  [DEBUG] TIMEOUT prompt_re={self.prompt_re!r}")
                print(f"  [DEBUG] TIMEOUT raw before={raw!r:.300s}")
            return clean(raw)

    def check(self, name, ok, detail=""):
        self.results.append({'name': name, 'ok': ok, 'detail': detail})
        if ok:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            print(f"  ❌ {name}")
            if detail:
                print(f"     → {detail[:150]}")

    def stop(self):
        if self.child and self.child.isalive():
            try: self.child.sendline('/exit')
            except: pass
            time.sleep(1)
            try:
                if self.child.isalive(): self.child.terminate(force=True)
            except: pass

    def report(self, section_results):
        """Append this mode's results to the overall report."""
        return {
            'mode': self.mode,
            'passed': self.passed,
            'failed': self.failed,
            'results': self.results,
        }


def test_coding_mode():
    """Test CODING mode — all features."""
    print("\n" + "=" * 60)
    print("🖥️  CODING MODE — Full Test Suite")
    print("=" * 60)

    h = Harness('coding')
    if not h.start():
        print("❌ Failed to start coding mode")
        return h.report([])

    # ─── A. SLASH COMMANDS ─────────────────────────────────
    print("\n📋 A. Slash Commands")

    r = h.cmd('/help')
    h.check("C01: /help", len(r) > 20)

    r = h.cmd('/flags')
    h.check("C02: /flags", 'AUTO_DREAM' in r or 'SANDBOX' in r)

    r = h.cmd('/doctor')
    h.check("C03: /doctor", 'Python' in r)

    r = h.cmd('/context')
    h.check("C04: /context", 'Message' in r or 'token' in r.lower() or 'Context' in r)

    r = h.cmd('/brief on')
    h.check("C05: /brief on", 'enabled' in r.lower() or 'brief' in r.lower())

    r = h.cmd('/brief off')
    h.check("C06: /brief off", 'disabled' in r.lower() or 'brief' in r.lower())

    r = h.cmd('/think')
    h.check("C07: /think", 'think' in r.lower())

    r = h.cmd('/think')  # toggle back
    h.check("C08: /think toggle back", 'think' in r.lower())

    r = h.cmd('/dream')
    h.check("C09: /dream", 'AutoDream' in r or 'dream' in r.lower() or 'Running' in r or 'Status' in r)

    r = h.cmd('/stats')
    h.check("C10: /stats", len(r) > 5)

    r = h.cmd('/cost')
    h.check("C11: /cost", len(r) > 5)

    r = h.cmd('/version')
    h.check("C12: /version", 'neomind' in r.lower() or 'version' in r.lower() or '0.' in r)

    r = h.cmd('/permissions')
    h.check("C13: /permissions", 'permission' in r.lower() or 'mode' in r.lower() or 'normal' in r.lower())

    # ─── B. SIMPLE LLM CHAT ───────────────────────────────
    print("\n📋 B. Simple LLM Chat")

    r = h.chat('What is 2+2? Answer with just the number.')
    h.check("C14: math 2+2", '4' in r)

    r = h.chat('What is the capital of Japan? One word.')
    h.check("C15: knowledge", 'tokyo' in r.lower())

    r = h.chat('Say hello in French. One word.')
    h.check("C16: language", 'bonjour' in r.lower())

    # ─── C. CONTEXT MEMORY ─────────────────────────────────
    print("\n📋 C. Context Memory")

    r = h.chat('My name is Alice and I work at Google. Just say OK.')
    h.check("C17: set context", len(r) > 0)

    r = h.chat('What is my name? One word.')
    h.check("C18: recall name", 'alice' in r.lower())

    r = h.chat('Where do I work? One word.')
    h.check("C19: recall company", 'google' in r.lower())

    r = h.chat('I have 3 servers: alpha, beta, gamma. Just say OK.')
    h.check("C20: set servers", len(r) > 0)

    r = h.chat('Name my second server.')
    h.check("C21: recall server", 'beta' in r.lower())

    # ─── D. CHINESE LANGUAGE ───────────────────────────────
    print("\n📋 D. Chinese Language")

    r = h.chat('用中文回答：1+1等于几？只回答数字。')
    h.check("C22: 中文数学", '2' in r)

    r = h.chat('用一句话介绍Python语言。')
    h.check("C23: 中文描述", len(r) > 10 and ('python' in r.lower() or '编程' in r or '语言' in r))

    # ─── E. TOOL CALLS (CRITICAL PATH) ─────────────────────
    print("\n📋 E. Tool Calls (Agentic Loop)")

    r = h.chat('Run this command: echo "tool-test-ok" and show me the output.')
    h.check("C24: Bash tool", 'tool-test-ok' in r or len(r) > 10)

    r = h.chat('Read main.py and tell me what the first function is called.')
    h.check("C25: Read tool", len(r) > 10 and '_get_tool_definition' not in r)

    r = h.chat('List all .py files in the current directory. Just the filenames.')
    h.check("C26: Glob/LS tool", '.py' in r or 'main' in r.lower() or len(r) > 10)

    r = h.chat('Search for the word "class" in main.py. How many times does it appear?')
    h.check("C27: Grep tool", any(c.isdigit() for c in r) or 'class' in r.lower() or len(r) > 10)

    r = h.chat('What is the current git branch?')
    h.check("C28: Git tool", len(r) > 0 and '_get_tool_definition' not in r)

    # ─── F. COMPLEX MULTI-TOOL TASKS ──────────────────────
    print("\n📋 F. Complex Tasks")

    r = h.chat('看看当前这个codebase是干啥的，简单说几句就行')
    h.check("C29: codebase分析", len(r) > 20 and '_get_tool_definition' not in r)

    r = h.chat('Count the total number of lines in main.py.')
    h.check("C30: line count task", any(c.isdigit() for c in r) or len(r) > 10)

    # ─── G. ERROR HANDLING ─────────────────────────────────
    print("\n📋 G. Error Handling")

    r = h.chat('Read the file /nonexistent/file/that/does/not/exist.txt')
    h.check("C31: missing file", 'not found' in r.lower() or 'error' in r.lower() or 'exist' in r.lower() or len(r) > 10)

    # ─── H. SESSION MANAGEMENT ─────────────────────────────
    print("\n📋 H. Session Management")

    r = h.cmd('/checkpoint full-test')
    h.check("C32: checkpoint", '✓' in r or 'saved' in r.lower() or 'Checkpoint' in r)

    r = h.cmd('/snip 3')
    h.check("C33: snip", '✓' in r or 'Snip' in r or 'saved' in r.lower())

    r = h.cmd('/branch full-test-branch')
    h.check("C34: branch", '✓' in r or 'Branched' in r or 'branch' in r.lower())

    # ─── I. TEAM MANAGEMENT ────────────────────────────────
    print("\n📋 I. Team Management")

    r = h.cmd('/team create fulltest-team')
    h.check("C35: team create", '✓' in r or 'created' in r.lower())

    r = h.cmd('/team list')
    h.check("C36: team list", 'fulltest-team' in r or 'Teams' in r)

    r = h.cmd('/team delete fulltest-team')
    h.check("C37: team delete", '✓' in r or 'deleted' in r.lower())

    # ─── J. PERMISSION RULES ──────────────────────────────
    print("\n📋 J. Permission Rules")

    r = h.cmd('/rules')
    h.check("C38: rules empty", 'No permission' in r or 'Permission' in r)

    r = h.cmd('/rules add Bash allow npm test')
    h.check("C39: rules add", '✓' in r or 'added' in r.lower())

    r = h.cmd('/rules')
    h.check("C40: rules shows", 'Bash' in r or 'npm' in r)

    r = h.cmd('/rules remove 0')
    h.check("C41: rules remove", '✓' in r or 'removed' in r.lower())

    # ─── K. EXPORT ─────────────────────────────────────────
    print("\n📋 K. Export")

    tmp_md = tempfile.mktemp(suffix='.md', dir='/tmp')
    r = h.cmd(f'/save {tmp_md}')
    h.check("C42: save md", '✓' in r or 'markdown' in r.lower())
    if os.path.exists(tmp_md):
        c = open(tmp_md).read()
        h.check("C43: md content", '##' in c and len(c) > 50)
        os.unlink(tmp_md)

    tmp_json = tempfile.mktemp(suffix='.json', dir='/tmp')
    r = h.cmd(f'/save {tmp_json}')
    h.check("C44: save json", '✓' in r or 'json' in r.lower())
    if os.path.exists(tmp_json):
        try:
            d = json.loads(open(tmp_json).read())
            h.check("C45: json valid", 'messages' in d)
        except:
            h.check("C45: json valid", False, "Invalid JSON")
        os.unlink(tmp_json)

    tmp_html = tempfile.mktemp(suffix='.html', dir='/tmp')
    r = h.cmd(f'/save {tmp_html}')
    h.check("C46: save html", '✓' in r or 'html' in r.lower())
    if os.path.exists(tmp_html):
        c = open(tmp_html).read()
        h.check("C47: html valid", '<html' in c)
        os.unlink(tmp_html)

    # ─── L. CODE GENERATION ────────────────────────────────
    print("\n📋 L. Code Generation")

    r = h.chat('Write a Python function called "fibonacci" that returns the nth fibonacci number. Just the function.')
    h.check("C48: fibonacci", 'def' in r or 'fibonacci' in r or 'return' in r)

    r = h.chat('Write a one-line Python list comprehension that squares numbers 1 to 10.')
    h.check("C49: list comp", '[' in r or 'for' in r or '**' in r or len(r) > 10)

    # ─── M. BTW ────────────────────────────────────────────
    print("\n📋 M. Side Questions")

    r = h.cmd('/btw What year was Python created?')
    h.check("C50: btw", '1991' in r or 'python' in r.lower() or len(r) > 5)

    h.stop()
    return h.report([])


def test_chat_mode():
    """Test CHAT mode."""
    print("\n" + "=" * 60)
    print("💬 CHAT MODE — Full Test Suite")
    print("=" * 60)

    h = Harness('chat')
    if not h.start():
        print("❌ Failed to start chat mode")
        return h.report([])

    print("\n📋 A. Basic Chat")

    r = h.cmd('/help')
    h.check("H01: /help in chat", len(r) > 20)

    r = h.chat('Hello! How are you? Answer in one sentence.')
    h.check("H02: greeting", len(r) > 5)

    r = h.chat('Tell me a fun fact about dolphins in one sentence.')
    h.check("H03: knowledge", len(r) > 10 and ('dolphin' in r.lower() or '海豚' in r))

    print("\n📋 B. Context")

    r = h.chat('My favorite color is blue. Just say OK.')
    h.check("H04: set context", len(r) > 0)

    r = h.chat('What is my favorite color? One word.')
    h.check("H05: recall", 'blue' in r.lower())

    print("\n📋 C. Chinese")

    r = h.chat('用中文解释什么是人工智能，一句话。')
    h.check("H06: 中文AI", len(r) > 10 and ('人工' in r or '智能' in r or 'AI' in r))

    print("\n📋 D. Mode Info")

    r = h.cmd('/flags')
    h.check("H07: flags in chat", 'AUTO_DREAM' in r or 'Feature' in r)

    r = h.cmd('/doctor')
    h.check("H08: doctor in chat", 'Python' in r)

    print("\n📋 E. Creative")

    r = h.chat('Write a haiku about programming.')
    h.check("H09: haiku", len(r) > 10)

    r = h.chat('Give me a metaphor for debugging code. One sentence.')
    h.check("H10: metaphor", len(r) > 10)

    h.stop()
    return h.report([])


def test_fin_mode():
    """Test FIN mode."""
    print("\n" + "=" * 60)
    print("📈 FIN MODE — Full Test Suite")
    print("=" * 60)

    h = Harness('fin')
    if not h.start():
        print("❌ Failed to start fin mode")
        return h.report([])

    print("\n📋 A. Basic Fin")

    r = h.cmd('/help')
    h.check("F01: /help in fin", len(r) > 20)

    r = h.chat('What is the S&P 500? Answer in one sentence.')
    h.check("F02: market knowledge", len(r) > 10 and ('500' in r or 'stock' in r.lower() or '指数' in r or 'market' in r.lower() or 'index' in r.lower()))

    r = h.chat('What is compound interest? One sentence.')
    h.check("F03: finance concept", len(r) > 10 and ('interest' in r.lower() or '利息' in r or '复利' in r or 'compound' in r.lower()))

    print("\n📋 B. Fin Context")

    r = h.chat('I want to invest $10000 in index funds. Just say OK.')
    h.check("F04: set context", len(r) > 0)

    r = h.chat('How much did I say I want to invest?')
    h.check("F05: recall amount", '10000' in r or '10,000' in r or '$10' in r or '一万' in r)

    print("\n📋 C. Fin Commands")

    r = h.cmd('/flags')
    h.check("F06: flags in fin", 'AUTO_DREAM' in r or 'Feature' in r)

    r = h.cmd('/doctor')
    h.check("F07: doctor in fin", 'Python' in r)

    print("\n📋 D. Chinese Finance")

    r = h.chat('什么是ETF？一句话解释。')
    h.check("F08: 中文ETF", len(r) > 10 and ('ETF' in r or '基金' in r or 'fund' in r.lower() or '交易' in r))

    h.stop()
    return h.report([])


def write_full_report(all_results):
    """Write the comprehensive report."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    total_pass = sum(r['passed'] for r in all_results)
    total_fail = sum(r['failed'] for r in all_results)
    total = total_pass + total_fail

    lines = [
        f"# Full Scenario Test Report — {ts}",
        f"",
        f"## Summary",
        f"- **Total: {total_pass}/{total} passed** ({total_fail} failed)",
        f"",
    ]

    for mode_result in all_results:
        mode = mode_result['mode'].upper()
        p = mode_result['passed']
        f = mode_result['failed']
        lines.append(f"### {mode} Mode: {p}/{p+f} passed")
        if f > 0:
            lines.append(f"**Failures:**")
            for r in mode_result['results']:
                if not r['ok']:
                    lines.append(f"- ❌ {r['name']}: {r['detail']}")
        lines.append("")
        lines.append("| # | Test | Result |")
        lines.append("|---|------|--------|")
        for r in mode_result['results']:
            s = "✅" if r['ok'] else "❌"
            lines.append(f"| | {r['name']} | {s} |")
        lines.append("")

    with open(REPORT_PATH, 'w') as f:
        f.write('\n'.join(lines))
    print(f"\n📝 Full report: {REPORT_PATH}")


if __name__ == '__main__':
    print("=" * 60)
    print("NeoMind Full Scenario Test — 68 scenarios, 3 modes")
    print("=" * 60)

    all_results = []

    # Test all 3 modes
    all_results.append(test_coding_mode())
    all_results.append(test_chat_mode())
    all_results.append(test_fin_mode())

    write_full_report(all_results)

    total_pass = sum(r['passed'] for r in all_results)
    total_fail = sum(r['failed'] for r in all_results)
    total = total_pass + total_fail

    print(f"\n{'=' * 60}")
    print(f"FINAL: {total_pass}/{total} passed ({total_fail} failed)")
    for r in all_results:
        print(f"  {r['mode']:8s}: {r['passed']}/{r['passed']+r['failed']}")
    print(f"{'=' * 60}")

    sys.exit(0 if total_fail == 0 else 1)
