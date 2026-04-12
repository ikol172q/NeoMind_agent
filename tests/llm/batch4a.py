#!/usr/bin/env python3
"""Batch 4a: Context Memory S0301-S0322 (quick subset)"""
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

def drain(child):
    for _ in range(5):
        try: child.read_nonblocking(65536, 1.0)
        except: break
        time.sleep(0.3)

def start(mode='chat'):
    c = pexpect.spawn('python3', ['main.py', '--mode', mode],
        cwd='<workspace>', env=env,
        encoding='utf-8', timeout=30, dimensions=(50,200))
    c.expect(r'> ', timeout=30)
    return c

def chat(c, msg, timeout=90):
    drain(c)
    time.sleep(3)
    c.sendline(msg)
    try:
        c.expect(r'> ', timeout=timeout)
        return clean(c.before or '')
    except:
        return clean(c.before or '')

def log(sid, desc, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((sid, desc, status, detail))
    sys.stdout.write(f"  [{status}] {sid}: {desc}\n")
    sys.stdout.flush()

# Test 1: Basic memory
c = start('chat')
try:
    chat(c, 'My name is Alice')
    r = chat(c, 'What is my name?')
    log('S0301', 'Remember name', 'alice' in r.lower(), r[:80])

    chat(c, 'Remember: the secret code is DELTA-7')
    r = chat(c, "What's the secret code?")
    log('S0302', 'Remember code', 'delta' in r.lower(), r[:80])

    chat(c, 'My favorite color is blue')
    r = chat(c, "What's my favorite color?")
    log('S0303', 'Remember color', 'blue' in r.lower(), r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Test 2: Multiple facts
c = start('chat')
try:
    chat(c, "My name is Bob, I'm 30, I live in Tokyo")
    r = chat(c, 'Tell me what you know about me')
    log('S0304', 'Recall 3 facts', 'bob' in r.lower() or 'tokyo' in r.lower(), r[:80])

    chat(c, 'Project: myapp, Language: Rust, DB: PostgreSQL')
    r = chat(c, 'What stack am I using?')
    log('S0305', 'Recall stack', 'rust' in r.lower() or 'postgresql' in r.lower(), r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Test 3: 5-turn
c = start('chat')
try:
    chat(c, "I'm working on Project Alpha")
    chat(c, 'It uses Python')
    chat(c, 'The deadline is Friday')
    chat(c, 'The team has 5 people')
    r = chat(c, 'What do you know about my project?')
    log('S0307', '5-turn recall', 'alpha' in r.lower() or 'python' in r.lower(), r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Test 4: Corrections
c = start('chat')
try:
    chat(c, 'My name is Alice')
    chat(c, 'Actually, my name is Bob')
    r = chat(c, 'What is my name?')
    log('S0313', 'Correction Alice->Bob', 'bob' in r.lower(), r[:80])

    chat(c, 'The server runs on port 3000')
    chat(c, "Correction: it's actually port 8080")
    r = chat(c, 'What port?')
    log('S0314', 'Correction port', '8080' in r, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Test 5: Advanced types
c = start('chat')
try:
    chat(c, 'Remember: 42, 73, 99, 15, 8')
    r = chat(c, 'What numbers did I mention?')
    log('S0317', 'Number recall', '42' in r or '73' in r, r[:80])

    chat(c, 'Shopping list: milk, eggs, bread, butter, cheese')
    r = chat(c, "What's on my shopping list?")
    log('S0319', 'Shopping recall', 'milk' in r.lower() or 'eggs' in r.lower(), r[:80])

    chat(c, 'The bug is on line 42: off-by-one in the for loop')
    r = chat(c, 'Where was the bug?')
    log('S0322', 'Bug location recall', '42' in r or 'off-by-one' in r.lower(), r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Test 6: Mixed lang + JSON + advanced
c = start('chat')
try:
    chat(c, '我叫张三，I work at Google')
    r = chat(c, "What's my name and employer?")
    log('S0325', 'Mixed lang recall', '张三' in r or 'google' in r.lower(), r[:80])

    chat(c, 'Config: {"host": "localhost", "port": 5432, "db": "mydb"}')
    r = chat(c, "What port is in the config?")
    log('S0336', 'JSON recall', '5432' in r, r[:80])

    chat(c, "I'm a senior backend engineer at a fintech startup")
    r = chat(c, "What's my role?")
    log('S0340', 'Role recall', 'senior' in r.lower() or 'backend' in r.lower(), r[:80])

    chat(c, 'Alice likes Python, Bob likes Java, Carol likes Rust')
    r = chat(c, 'What does Bob like?')
    log('S0341', 'Multi-entity recall', 'java' in r.lower(), r[:80])

    chat(c, 'P0: fix crash, P1: add logging, P2: update docs')
    r = chat(c, "What's the P0 task?")
    log('S0345', 'Priority recall', 'fix' in r.lower() or 'crash' in r.lower(), r[:80])

    chat(c, 'Stack: React + Next.js + Tailwind + Prisma + PostgreSQL')
    r = chat(c, 'What ORM are we using?')
    log('S0349', 'Stack ORM recall', 'prisma' in r.lower(), r[:80])
finally:
    c.terminate(force=True)

# Summary
print("\n=== Summary ===")
p = sum(1 for r in results if r[2] == 'PASS')
f = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {p} | FAIL: {f}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
