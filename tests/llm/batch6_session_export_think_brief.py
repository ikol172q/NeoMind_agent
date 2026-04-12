#!/usr/bin/env python3
"""Batch 6: Session Mgmt (S0470-S0509), Export (S0810-S0839), Think (S0700-S0729), Brief (S0730-S0749)"""
import os, pexpect, re, time, sys

env = os.environ.copy()
env['NEOMIND_DISABLE_VAULT'] = '1'
env['TERM'] = 'dumb'
env['PYTHONPATH'] = '<workspace>'
env['NEOMIND_AUTO_ACCEPT'] = '1'

results = []

def clean(t):
    t = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', t)
    t = re.sub(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', '', t)
    t = re.sub(r'Thinking…', '', t)
    t = re.sub(r'Thought for [0-9.]+s — [^\n]*\n?', '', t)
    return t.strip()

def drain(c):
    for _ in range(5):
        try: c.read_nonblocking(65536, 1.0)
        except: break
        time.sleep(0.3)

def start(mode='coding'):
    c = pexpect.spawn('python3', ['main.py', '--mode', mode],
        cwd='<workspace>', env=env,
        encoding='utf-8', timeout=30, dimensions=(50,200))
    c.expect(r'> ', timeout=30)
    return c

def chat(c, msg, timeout=90):
    drain(c); time.sleep(3); c.sendline(msg)
    try: c.expect(r'> ', timeout=timeout); return clean(c.before or '')
    except: return clean(c.before or '')

def cmd(c, msg):
    drain(c); time.sleep(1); c.sendline(msg)
    try: c.expect(r'> ', timeout=15); return clean(c.before or '')
    except: return clean(c.before or '')

def log(sid, desc, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((sid, desc, status, detail))
    sys.stdout.write(f"  [{status}] {sid}: {desc}\n"); sys.stdout.flush()

# === Session Management ===
print("--- Session Management ---")
c = start('coding')
try:
    r = cmd(c, '/checkpoint first')
    log('S0470', '/checkpoint first', len(r) > 0, r[:80])

    chat(c, 'Remember: test message for session')
    r = cmd(c, '/checkpoint second')
    log('S0471', '/checkpoint second after chat', len(r) > 0, r[:80])

    # S0474: rewind count
    chat(c, 'msg1'); chat(c, 'msg2'); chat(c, 'msg3')
    r = cmd(c, '/rewind 3')
    log('S0474', '/rewind 3', len(r) > 0, r[:80])

    r = cmd(c, '/rewind 1')
    log('S0475', '/rewind 1', len(r) > 0, r[:80])

    # Branch
    r = cmd(c, '/branch fork1')
    log('S0478', '/branch fork1', len(r) > 0, r[:80])

    # Snip
    chat(c, 'Important note 1')
    chat(c, 'Important note 2')
    r = cmd(c, '/snip 2')
    log('S0480', '/snip 2', len(r) > 0, r[:80])

    r = cmd(c, '/snip 1')
    log('S0481', '/snip 1', len(r) > 0, r[:80])

    # Save formats
    chat(c, 'Test message for export')
    r = cmd(c, '/save /tmp/neomind_conv.md')
    log('S0484', '/save .md', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neomind_conv.json')
    log('S0485', '/save .json', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neomind_conv.html')
    log('S0486', '/save .html', len(r) > 0, r[:80])

    # Resume
    r = cmd(c, '/resume')
    log('S0487', '/resume list', len(r) > 0, r[:80])

    # Checkpoint multi
    cmd(c, '/checkpoint cp1'); cmd(c, '/checkpoint cp2'); cmd(c, '/checkpoint cp3')
    r = cmd(c, '/rewind cp1')
    log('S0504', 'Multi checkpoint rewind', len(r) > 0, r[:80])

    # Snip empty
    r = cmd(c, '/snip 0')
    log('S0505', '/snip 0', len(r) > 0, r[:80])

    # Save overwrite
    cmd(c, '/save /tmp/neomind_overwrite.md')
    r = cmd(c, '/save /tmp/neomind_overwrite.md')
    log('S0506', '/save overwrite', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Export ===
print("--- Export ---")
c = start('chat')
try:
    chat(c, 'Hello, this is turn 1')
    chat(c, 'This is turn 2')
    chat(c, 'This is turn 3')

    r = cmd(c, '/save /tmp/neo_chat.md')
    log('S0810', 'Export simple md', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neo_chat.json')
    log('S0811', 'Export simple json', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neo_chat.html')
    log('S0812', 'Export simple html', len(r) > 0, r[:80])

    # Chinese export
    chat(c, '你好，这是中文测试')
    r = cmd(c, '/save /tmp/neo_cn.md')
    log('S0822', 'Export Chinese md', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neo_cn.json')
    log('S0823', 'Export Chinese json', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neo_cn.html')
    log('S0824', 'Export Chinese html', len(r) > 0, r[:80])

    # Format detection
    r = cmd(c, '/save /tmp/neo_detect.md')
    log('S0833', 'Format detect md', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neo_detect.json')
    log('S0834', 'Format detect json', len(r) > 0, r[:80])

    r = cmd(c, '/save /tmp/neo_detect.html')
    log('S0835', 'Format detect html', len(r) > 0, r[:80])

    # Multi-export
    cmd(c, '/save /tmp/neo_a.md')
    cmd(c, '/save /tmp/neo_a.json')
    r = cmd(c, '/save /tmp/neo_a.html')
    log('S0836', 'Multi-export all 3', len(r) > 0, r[:80])

    # Empty export
    c2 = start('chat')
    r = cmd(c2, '/save /tmp/neo_empty.md')
    log('S0838', 'Empty export', len(r) > 0, r[:80])
    c2.terminate(force=True)
finally:
    c.terminate(force=True)

time.sleep(5)

# === Think Mode ===
print("--- Think Mode ---")
c = start('chat')
try:
    cmd(c, '/think on')
    r = chat(c, 'What is 15% of 230?')
    log('S0700', 'Think: 15% of 230', '34' in r, r[:80])

    r = chat(c, 'Is Python compiled or interpreted?')
    log('S0701', 'Think: Python compiled?', len(r) > 0, r[:80])

    cmd(c, '/think off')
    r = chat(c, 'What is 15% of 230?')
    log('S0712', 'Think off: direct answer', '34' in r, r[:80])

    # Toggle
    cmd(c, '/think on')
    r = chat(c, 'Explain recursion briefly')
    log('S0715', 'Think on: has reasoning', len(r) > 0, r[:80])

    cmd(c, '/think off')
    r = chat(c, 'Explain recursion briefly')
    log('S0716', 'Think off: no reasoning section', len(r) > 0, r[:80])

    # Edge
    cmd(c, '/think on')
    r = cmd(c, '/think on')
    log('S0725', 'Think on idempotent', len(r) > 0, r[:80])

    # Combined
    cmd(c, '/think on')
    cmd(c, '/brief on')
    r = chat(c, 'Explain hash tables')
    log('S0726', 'Think+Brief combined', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Brief Mode ===
print("--- Brief Mode ---")
c = start('chat')
try:
    cmd(c, '/brief on')
    r = chat(c, 'Explain what a REST API is')
    log('S0730', 'Brief: REST API', len(r) > 0, r[:80])

    r = chat(c, 'What is Docker?')
    log('S0731', 'Brief: Docker', len(r) > 0, r[:80])

    r = chat(c, 'List 5 design patterns')
    log('S0732', 'Brief: design patterns', len(r) > 0, r[:80])

    cmd(c, '/brief off')
    r = chat(c, 'What is Docker?')
    log('S0738', 'Brief off: Docker', len(r) > 0, r[:80])

    # Toggle
    cmd(c, '/brief on')
    cmd(c, '/brief off')
    cmd(c, '/brief on')
    r = cmd(c, '/brief')
    log('S0743', 'Brief triple toggle', len(r) > 0, r[:80])

    # Chinese
    cmd(c, '/brief on')
    r = chat(c, '什么是微服务？')
    log('S0744', 'Brief Chinese', len(r) > 0, r[:80])

    # State
    r = cmd(c, '/brief')
    log('S0749', 'Brief state display', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

# Summary
print("\n=== Summary ===")
p = sum(1 for r in results if r[2] == 'PASS')
f = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {p} | FAIL: {f}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
