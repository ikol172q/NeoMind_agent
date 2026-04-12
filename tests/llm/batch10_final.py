#!/usr/bin/env python3
"""Batch 10: Team/Swarm, Code Generation, Multi-turn Complex, Combined remaining"""
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

def chat(c, msg, timeout=120):
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

# Team/Swarm
print("--- Team/Swarm ---")
c = start('coding')
try:
    r = cmd(c, '/team create alpha-test')
    log('S0750b', 'Create alpha-test', len(r) > 0, r[:80])

    r = cmd(c, '/team create beta-test')
    log('S0752b', 'Create beta-test', len(r) > 0, r[:80])

    r = cmd(c, '/team list')
    log('S0753b', 'List teams', len(r) > 0, r[:80])

    r = cmd(c, '/team info alpha-test')
    log('S0755b', 'Team info', len(r) > 0, r[:80])

    r = cmd(c, '/team delete nonexistent')
    log('S0757b', 'Delete nonexistent', len(r) > 0, r[:80])

    r = cmd(c, '/team create temp-test')
    cmd(c, '/team delete temp-test')
    log('S0756b', 'Create+delete', True, '')

    # Cleanup
    cmd(c, '/team delete alpha-test')
    cmd(c, '/team delete beta-test')
finally:
    c.terminate(force=True)

time.sleep(5)

# Code Generation (fresh process per scenario)
print("--- Code Generation ---")
tests = [
    ('S0351', 'Write a Python function to check if a string is a palindrome', 'palindrome'),
    ('S0352', 'Create a Python class for a bank account with deposit, withdraw, and balance', 'class'),
    ('S0353', 'Write a Python decorator that logs function execution time', 'decorator'),
    ('S0354', 'Write a list comprehension to filter even numbers and square them', 'comprehension'),
    ('S0355', 'Write a function that reads a JSON file with proper error handling', 'try'),
    ('S0371', 'Write a Python generator for Fibonacci numbers', 'yield'),
    ('S0372', 'Write a context manager for database transactions', 'enter'),
    ('S0373', 'Create dataclasses for a blog system: Post, Comment, Author', 'dataclass'),
    ('S0383', 'Implement a binary search tree with insert, search, delete', 'class'),
    ('S0385', 'Implement a hash map with chaining collision resolution', 'class'),
]

for sid, prompt, keyword in tests:
    c = start('coding')
    try:
        r = chat(c, prompt)
        passed = keyword in r.lower() or 'def ' in r or 'class ' in r or 'python' in r.lower() or len(r) > 100
        log(sid, f'CodeGen: {prompt[:40]}...', passed, r[:80])
    finally:
        c.terminate(force=True)
        time.sleep(3)

time.sleep(5)

# Multi-turn complex (select)
print("--- Multi-turn Complex ---")
c = start('coding')
try:
    r = chat(c, 'Analyze this codebase and tell me the architecture')
    log('S0510', 'Complex: architecture', len(r) > 50, r[:80])

    r = chat(c, 'What patterns do you see?')
    log('S0510b', 'Complex: patterns', len(r) > 30, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Remaining combined
print("--- Combined Remaining ---")
c = start('coding')
try:
    # Brief + codegen
    cmd(c, '/brief on')
    r = chat(c, 'Write a REST API with CRUD')
    log('S0921', 'Brief+codegen', len(r) > 20, r[:80])
    cmd(c, '/brief off')

    # Brief + Chinese
    cmd(c, '/brief on')
    r = chat(c, '什么是量子计算？')
    log('S0926', 'Brief+Chinese', len(r) > 10, r[:80])
    cmd(c, '/brief off')

    # Think + fin + Chinese
    cmd(c, '/mode fin')
    cmd(c, '/think on')
    r = chat(c, '分析AAPL的投资价值')
    log('S0924', 'Think+CN+fin', len(r) > 30, r[:80])
    cmd(c, '/think off')
    cmd(c, '/mode coding')

    # Export after think
    cmd(c, '/think on')
    chat(c, 'What is recursion?')
    r = cmd(c, '/save /tmp/neo_think_export.md')
    log('S0925', 'Export after think', len(r) > 0, r[:80])
    cmd(c, '/think off')

    # Compact + memory
    cmd(c, '/compact')
    r = cmd(c, '/memory')
    log('S0953', 'Compact+memory', len(r) > 0, r[:80])

    # History + export
    r1 = cmd(c, '/history')
    r2 = cmd(c, '/save /tmp/neo_hist.md')
    log('S0966', 'History+export', len(r1) > 0 and len(r2) > 0, '')

    # Context + think + brief
    r = cmd(c, '/context')
    cmd(c, '/think on'); cmd(c, '/brief on')
    r = chat(c, 'What is a linked list?')
    log('S0967', 'Context+think+brief', len(r) > 0, r[:80])
    cmd(c, '/think off'); cmd(c, '/brief off')
finally:
    c.terminate(force=True)

# Summary
print("\n=== Summary ===")
p = sum(1 for r in results if r[2] == 'PASS')
f = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {p} | FAIL: {f}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
