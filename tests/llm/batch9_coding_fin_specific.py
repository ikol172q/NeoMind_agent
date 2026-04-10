#!/usr/bin/env python3
"""Batch 9: Coding mode specific S0580-S0599, Fin mode specific S0642-S0659, Frustration S0904-S0919"""
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

# Coding mode specific
print("--- Coding Mode Specific ---")
c = start('coding')
try:
    r = chat(c, 'Generate a requirements.txt from the project')
    log('S0580', 'Generate requirements.txt', len(r) > 0, r[:80])

    r = chat(c, 'Find unused imports')
    log('S0582', 'Find unused imports', len(r) > 0, r[:80])

    r = chat(c, 'Find all API endpoints')
    log('S0594', 'Find API endpoints', len(r) > 0, r[:80])

    r = chat(c, 'Explain the inheritance hierarchy')
    log('S0593', 'Explain inheritance', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Fin mode Chinese/specific
print("--- Fin Mode Chinese ---")
c = start('fin')
try:
    r = chat(c, '分析贵州茅台的财务状况')
    log('S0647', 'CN: Maotai analysis', len(r) > 30, r[:80])

    r = chat(c, '什么是涨停和跌停？')
    log('S0694', 'CN: price limits', len(r) > 20, r[:80])

    r = chat(c, '解释K线图的基本形态')
    log('S0695', 'CN: candlestick', len(r) > 20, r[:80])

    r = chat(c, 'Explain value investing vs growth investing')
    log('S0656', 'Fin: value vs growth', len(r) > 30, r[:80])

    r = chat(c, 'What are ETFs and how do they work?')
    log('S0657', 'Fin: ETFs', len(r) > 30, r[:80])

    r = chat(c, 'Calculate compound interest on $10,000 at 7% for 20 years')
    log('S0658', 'Fin: compound interest', len(r) > 20, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Frustration/Correction additional
print("--- Frustration Additional ---")
c = start('chat')
try:
    r = chat(c, "No, that's not what I asked for")
    log('S0901', 'Frustration: not asked', len(r) > 0, r[:80])

    r = chat(c, '你理解错了，我要的不是这个')
    log('S0903', 'CN: misunderstanding', len(r) > 0, r[:80])

    r = chat(c, "Can you try a completely different approach?")
    log('S0910', 'Different approach', len(r) > 0, r[:80])

    r = chat(c, "hmm, that doesn't seem right")
    log('S0918', 'Subtle correction', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Chinese/English remaining
print("--- Chinese/English Remaining ---")
c = start('chat')
try:
    r = chat(c, 'What is a message queue?')
    log('S0678', 'EN: message queue', len(r) > 30, r[:80])

    r = chat(c, 'What is CQRS pattern?')
    log('S0673', 'EN: CQRS', len(r) > 30, r[:80])

    r = chat(c, '如何优化SQL查询性能？')
    log('S0667', 'CN: SQL optimization', len(r) > 30, r[:80])

    r = chat(c, '解释CAP定理')
    log('S0668', 'CN: CAP theorem', len(r) > 30, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Feature flags remaining
print("--- Feature Flags ---")
c = start('coding')
try:
    r = cmd(c, '/flags')
    log('S0880', 'Flags list', len(r) > 0, r[:80])

    r = cmd(c, '/flags VOICE_INPUT on')
    log('S0881', 'Flags VOICE on', len(r) > 0, r[:80])

    r = cmd(c, '/flags VOICE_INPUT off')
    log('S0882', 'Flags VOICE off', len(r) > 0, r[:80])

    r = cmd(c, '/flags AUTO_DREAM off')
    r2 = cmd(c, '/dream')
    log('S0883', 'Flags AUTO_DREAM off+dream', len(r) > 0, r[:80])

    r = cmd(c, '/flags AUTO_DREAM on')
    r2 = cmd(c, '/dream')
    log('S0884', 'Flags AUTO_DREAM on+dream', len(r) > 0, r[:80])

    r = cmd(c, '/flags SESSION_CHECKPOINT on')
    r2 = cmd(c, '/checkpoint flagtest')
    log('S0899', 'Flags checkpoint+test', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Permission rules remaining
print("--- Permission Rules ---")
c = start('coding')
try:
    r = cmd(c, '/rules add Bash allow npm test')
    log('S0780b', 'Rules add allow', len(r) > 0, r[:80])

    r = cmd(c, '/rules add Read allow *.py')
    log('S0781b', 'Rules add Read allow', len(r) > 0, r[:80])

    r = cmd(c, '/rules add Bash deny rm -rf')
    log('S0782b', 'Rules add deny rm', len(r) > 0, r[:80])

    r = cmd(c, '/rules add Write deny ~/.env')
    log('S0783b', 'Rules add deny .env', len(r) > 0, r[:80])

    r = cmd(c, '/rules')
    log('S0799b', 'Rules list all', len(r) > 0, r[:80])

    r = cmd(c, '/rules add')
    log('S0803', 'Rules add empty', len(r) > 0, r[:80])

    # Clean up
    for i in range(5, -1, -1):
        cmd(c, f'/rules remove {i}')
finally:
    c.terminate(force=True)

# Summary
print("\n=== Summary ===")
p = sum(1 for r in results if r[2] == 'PASS')
f = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {p} | FAIL: {f}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
