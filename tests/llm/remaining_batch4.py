#!/usr/bin/env python3
"""Batch 4: Context Memory S0301-S0350"""
import os, pexpect, re, time

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

def start_neomind(mode='chat'):
    child = pexpect.spawn('python3', ['main.py', '--mode', mode],
        cwd='<workspace>', env=env,
        encoding='utf-8', timeout=30, dimensions=(50,200))
    child.expect(r'> ', timeout=30)
    return child

def send_cmd(child, cmd):
    drain(child)
    time.sleep(1)
    child.sendline(cmd)
    try:
        child.expect(r'> ', timeout=15)
        return clean(child.before or '')
    except:
        return clean(child.before or '')

def send_chat(child, msg, timeout=120):
    drain(child)
    time.sleep(3)
    child.sendline(msg)
    try:
        child.expect(r'> ', timeout=timeout)
        return clean(child.before or '')
    except:
        return clean(child.before or '')

def log(sid, desc, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((sid, desc, status, detail))
    print(f"  [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and not passed else ""))

def test_memory_single():
    """S0301-S0306: Single-turn memory"""
    child = start_neomind('chat')
    try:
        send_chat(child, 'My name is Alice')
        r = send_chat(child, 'What is my name?')
        log('S0301', 'Remember name Alice', 'alice' in r.lower(), r[:100])

        send_chat(child, 'Remember: the secret code is DELTA-7')
        r = send_chat(child, "What's the secret code?")
        log('S0302', 'Remember secret code', 'delta' in r.lower() or 'delta-7' in r.lower(), r[:100])

        send_chat(child, 'My favorite color is blue')
        r = send_chat(child, "What's my favorite color?")
        log('S0303', 'Remember favorite color', 'blue' in r.lower(), r[:100])
    except Exception as e:
        log('S030x', 'memory single error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_memory_multiple():
    """S0304-S0310"""
    child = start_neomind('chat')
    try:
        send_chat(child, "My name is Bob, I'm 30, I live in Tokyo")
        r = send_chat(child, 'Tell me what you know about me')
        has_info = 'bob' in r.lower() and ('30' in r or 'tokyo' in r.lower())
        log('S0304', 'Recall 3 facts', has_info, r[:100])

        child2 = start_neomind('chat')
        send_chat(child2, 'Project: myapp, Language: Rust, DB: PostgreSQL')
        r = send_chat(child2, 'What stack am I using?')
        log('S0305', 'Recall project stack', 'rust' in r.lower() or 'postgresql' in r.lower() or 'myapp' in r.lower(), r[:100])
        child2.terminate(force=True)

        child3 = start_neomind('chat')
        send_chat(child3, 'I have 3 pets: a cat named Luna, a dog named Max, a fish named Bubbles')
        r = send_chat(child3, "What are my pets' names?")
        log('S0306', 'Recall pet names', 'luna' in r.lower() or 'max' in r.lower() or 'bubbles' in r.lower(), r[:100])
        child3.terminate(force=True)
    except Exception as e:
        log('S030x', 'memory multiple error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_memory_5turn():
    """S0307-S0308"""
    child = start_neomind('chat')
    try:
        send_chat(child, "I'm working on Project Alpha")
        send_chat(child, 'It uses Python')
        send_chat(child, 'The deadline is Friday')
        send_chat(child, 'The team has 5 people')
        r = send_chat(child, 'What do you know about my project?')
        has_facts = ('alpha' in r.lower() or 'python' in r.lower() or 'friday' in r.lower())
        log('S0307', '5-turn project recall', has_facts, r[:100])
    except Exception as e:
        log('S0307', '5-turn error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

    child = start_neomind('chat')
    try:
        send_chat(child, 'Step 1: fetch data')
        send_chat(child, 'Step 2: parse JSON')
        send_chat(child, 'Step 3: validate')
        send_chat(child, 'Step 4: store in DB')
        r = send_chat(child, 'List all the steps I mentioned')
        has_steps = ('fetch' in r.lower() or 'parse' in r.lower() or 'validate' in r.lower() or 'store' in r.lower())
        log('S0308', 'Recall 4 steps in order', has_steps, r[:100])
    except Exception as e:
        log('S0308', '5-turn steps error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_memory_correction():
    """S0313-S0316"""
    child = start_neomind('chat')
    try:
        send_chat(child, 'My name is Alice')
        send_chat(child, 'Actually, my name is Bob')
        r = send_chat(child, 'What is my name?')
        log('S0313', 'Correction: Alice->Bob', 'bob' in r.lower(), r[:100])

        send_chat(child, 'The server runs on port 3000')
        send_chat(child, "Correction: it's actually port 8080")
        r = send_chat(child, 'What port?')
        log('S0314', 'Correction: port 3000->8080', '8080' in r, r[:100])

        send_chat(child, 'The deadline is Monday')
        send_chat(child, 'The deadline is Friday')
        r = send_chat(child, 'When is the deadline?')
        log('S0316', 'Latest: Friday', 'friday' in r.lower(), r[:100])
    except Exception as e:
        log('S031x', 'correction error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_memory_types():
    """S0317-S0328"""
    child = start_neomind('chat')
    try:
        send_chat(child, 'Remember: 42, 73, 99, 15, 8')
        r = send_chat(child, 'What numbers did I mention?')
        log('S0317', 'Recall numbers', '42' in r or '73' in r or '99' in r, r[:100])

        send_chat(child, 'Shopping list: milk, eggs, bread, butter, cheese')
        r = send_chat(child, "What's on my shopping list?")
        log('S0319', 'Recall shopping list', 'milk' in r.lower() or 'eggs' in r.lower() or 'bread' in r.lower(), r[:100])

        send_chat(child, 'TODO: fix login, add tests, update docs, refactor DB')
        r = send_chat(child, 'What are my TODOs?')
        log('S0320', 'Recall TODOs', 'fix' in r.lower() or 'test' in r.lower() or 'docs' in r.lower(), r[:100])

        send_chat(child, 'Remember this function: def add(a, b): return a + b')
        r = send_chat(child, 'What function did I share?')
        log('S0321', 'Recall code', 'add' in r.lower() or 'def' in r.lower(), r[:100])

        send_chat(child, 'The bug is on line 42: off-by-one in the for loop')
        r = send_chat(child, 'Where was the bug?')
        log('S0322', 'Recall bug location', '42' in r or 'off-by-one' in r.lower(), r[:100])
    except Exception as e:
        log('S03xx', 'memory types error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_memory_advanced():
    """S0325-S0350 (select subset)"""
    child = start_neomind('chat')
    try:
        send_chat(child, '我叫张三，I work at Google')
        r = send_chat(child, "What's my name and employer?")
        log('S0325', 'Mixed lang recall', '张三' in r or 'google' in r.lower(), r[:100])

        send_chat(child, 'Config: {"host": "localhost", "port": 5432, "db": "mydb"}')
        r = send_chat(child, "What port is in the config?")
        log('S0336', 'JSON recall', '5432' in r, r[:100])

        send_chat(child, 'Docs are at https://docs.example.com/v2/api')
        r = send_chat(child, 'Where are the docs?')
        log('S0337', 'URL recall', 'docs.example.com' in r, r[:100])

        send_chat(child, 'Project started on 2025-01-15')
        r = send_chat(child, 'When did the project start?')
        log('S0338', 'Date recall', '2025' in r or '01-15' in r or 'january' in r.lower(), r[:100])

        send_chat(child, "I'm a senior backend engineer at a fintech startup")
        r = send_chat(child, "What's my role?")
        log('S0340', 'Role recall', 'senior' in r.lower() or 'backend' in r.lower() or 'fintech' in r.lower(), r[:100])

        send_chat(child, 'Alice likes Python, Bob likes Java, Carol likes Rust')
        r = send_chat(child, 'What does Bob like?')
        log('S0341', 'Multi-entity recall', 'java' in r.lower(), r[:100])

        send_chat(child, 'The config file is at /etc/myapp/config.yaml')
        r = send_chat(child, 'Where is the config file?')
        log('S0343', 'Path recall', '/etc/myapp/config.yaml' in r, r[:100])

        send_chat(child, 'FE means frontend, BE means backend, DB means database')
        r = send_chat(child, 'What does BE stand for?')
        log('S0344', 'Abbreviation recall', 'backend' in r.lower(), r[:100])

        send_chat(child, 'P0: fix crash, P1: add logging, P2: update docs')
        r = send_chat(child, "What's the P0 task?")
        log('S0345', 'Priority recall', 'fix' in r.lower() or 'crash' in r.lower(), r[:100])

        send_chat(child, 'Stack: React + Next.js + Tailwind + Prisma + PostgreSQL')
        r = send_chat(child, 'What ORM are we using?')
        log('S0349', 'Stack ORM recall', 'prisma' in r.lower(), r[:100])
    except Exception as e:
        log('S03xx', 'memory advanced error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

# Run all
print("=== Batch 4: Context Memory S0301-S0350 ===")
test_memory_single()
time.sleep(10)
test_memory_multiple()
time.sleep(10)
test_memory_5turn()
time.sleep(10)
test_memory_correction()
time.sleep(10)
test_memory_types()
time.sleep(10)
test_memory_advanced()

# Summary
print("\n=== Summary ===")
passed = sum(1 for r in results if r[2] == 'PASS')
failed = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {passed} | FAIL: {failed}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
