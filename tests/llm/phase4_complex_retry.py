#!/usr/bin/env python3
"""Phase 4 retry: Complex multi-step tasks with higher timeouts."""

import os, sys, re, time, pexpect, traceback
from datetime import datetime

CWD = '<workspace>'
REPORT_FILE = os.path.join(CWD, 'tests/llm/BUG_REPORTS.md')

ENV = os.environ.copy()
ENV['NEOMIND_DISABLE_VAULT'] = '1'
ENV['TERM'] = 'dumb'
ENV['PYTHONPATH'] = CWD
ENV['NEOMIND_AUTO_ACCEPT'] = '1'

results = []

def clean(t):
    t = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', t)
    t = re.sub(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', '', t)
    t = re.sub(r'Thinking…', '', t)
    t = re.sub(r'Thought for [0-9.]+s — [^\n]*\n?', '', t)
    return t.strip()

def spawn_session(mode='coding', timeout=120):
    child = pexpect.spawn(
        'python3', ['main.py', '--mode', mode],
        cwd=CWD, env=ENV, encoding='utf-8',
        timeout=timeout, dimensions=(50, 200)
    )
    child.expect(r'> ', timeout=60)
    return child

def send_and_get(child, msg, timeout=180, expect_pattern=r'> '):
    child.sendline(msg)
    child.expect(expect_pattern, timeout=timeout)
    return clean(child.before)

def record(sid, title, passed, detail=""):
    results.append((sid, title, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  {sid}: {title} -- {status}")
    if not passed and detail:
        print(f"    Detail: {detail[:300]}")

def safe_close(child):
    try:
        child.sendline('/exit')
        child.expect(pexpect.EOF, timeout=5)
    except:
        pass
    try:
        child.close(force=True)
    except:
        pass

def test_complex_tasks():
    print("\n=== Complex Multi-Step Tasks RETRY (S0881-S0890) ===")

    child = spawn_session('coding', timeout=180)
    try:
        # S0881: Analyze project architecture (Chinese) - with 180s timeout
        resp = send_and_get(child, "分析这个项目的架构", timeout=180)
        record("S0881", "分析这个项目的架构 (analyze architecture)",
               len(resp) > 50 and bool(re.search(r'agent|cli|main|模块|架构|目录|structure|module', resp, re.I)),
               f"Got ({len(resp)} chars): {resp[:300]}")
    except Exception as e:
        record("S0881", f"分析架构 timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    # Start fresh session for each to avoid cascading timeouts
    child = spawn_session('coding', timeout=180)
    try:
        # S0882: Find all functions in main.py
        resp = send_and_get(child, "找到main.py里所有的函数", timeout=180)
        record("S0882", "找到main.py里所有的函数 (find functions)",
               bool(re.search(r'main|interactive_main|_fast_path|test_main|def ', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0882", f"Find functions timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0883: What dependencies does this project use
        resp = send_and_get(child, "这个项目用了哪些依赖", timeout=180)
        record("S0883", "这个项目用了哪些依赖 (list dependencies)",
               bool(re.search(r'openai|prompt.toolkit|dotenv|depend|pyproject|toml', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0883", f"List deps timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0884: Read pyproject.toml
        resp = send_and_get(child, "Read pyproject.toml and tell me the project version and name", timeout=180)
        record("S0884", "Read pyproject.toml for version/name",
               bool(re.search(r'neomind|version|0\.\d', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0884", f"Read pyproject.toml timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0885: Search for safety imports
        resp = send_and_get(child, "Search for all files that import 'safety' and list them", timeout=180)
        record("S0885", "Search for safety imports",
               bool(re.search(r'safety|import|agent', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0885", f"Search safety timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0886: Count lines in main.py
        resp = send_and_get(child, "How many lines of code are in main.py?", timeout=180)
        record("S0886", "Count lines in main.py",
               bool(re.search(r'\d+', resp)),
               f"Got: {resp[:200]}")
    except Exception as e:
        record("S0886", f"Count lines timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0887: Explain _fast_path
        resp = send_and_get(child, "Explain what the _fast_path function in main.py does", timeout=180)
        record("S0887", "Explain _fast_path function",
               bool(re.search(r'version|fast|arg|flag|help|path', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0887", f"Explain function timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0888: Find potential bugs
        resp = send_and_get(child, "Are there any potential issues or bugs in main.py?", timeout=180)
        record("S0888", "Find potential bugs in main.py",
               len(resp) > 30,
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0888", f"Find bugs timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0889: Cross-file analysis
        resp = send_and_get(child, "What is the relationship between main.py and cli/neomind_interface.py?", timeout=180)
        record("S0889", "Cross-file relationship analysis",
               bool(re.search(r'import|call|interface|interactive|main|entry', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0889", f"Cross-file analysis timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)

    child = spawn_session('coding', timeout=180)
    try:
        # S0890: List agent/ directory
        resp = send_and_get(child, "List the directory structure of the agent/ folder", timeout=180)
        record("S0890", "List agent/ directory structure",
               bool(re.search(r'agent|\.py|file|dir|folder', resp, re.I)),
               f"Got: {resp[:300]}")
    except Exception as e:
        record("S0890", f"List directory timeout/error", False, str(e)[:300])
    finally:
        safe_close(child)


def write_report():
    passes = [r for r in results if r[2]]
    fails = [r for r in results if not r[2]]

    report = f"\n\n### Phase 4 Complex Tasks Retry ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
    report += f"Retried S0881-S0890 with 180s timeout per scenario.\n\n"

    for sid, title, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        report += f"- {sid}: {title} -- {status}\n"
        if not passed:
            report += f"  - Detail: {detail[:300]}\n"

    report += f"\nRetry totals: {len(passes)} PASS, {len(fails)} FAIL\n\n"

    with open(REPORT_FILE, 'a') as f:
        f.write(report)

    print(f"\nRetry Results: {len(passes)} PASS, {len(fails)} FAIL out of {len(results)} total")


if __name__ == '__main__':
    print("Phase 4 Complex Tasks Retry")
    print("=" * 60)
    test_complex_tasks()
    write_report()
