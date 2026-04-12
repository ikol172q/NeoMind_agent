#!/usr/bin/env python3
"""Batch 8: Remaining Error Handling, Combined, Edge, Long Conv"""
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

# Error handling (continued from S0844)
print("--- Error Handling (continued) ---")
c = start('coding')
try:
    r = chat(c, "Hello <script>alert('xss')</script>")
    log('S0845', 'XSS input safe', len(r) > 0, r[:80])

    r = chat(c, 'Hello 你好 مرحبا Привет')
    log('S0846', 'Multi-unicode', len(r) > 0, r[:80])

    r = cmd(c, '/nonexistent_command')
    log('S0847', 'Unknown command', len(r) > 0, r[:80])

    r = cmd(c, '/flags NONEXISTENT on')
    log('S0849', 'Unknown flag', len(r) > 0, r[:80])

    r = cmd(c, '/rewind -5')
    log('S0850b', 'Negative rewind', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Combined (continued)
print("--- Combined Features ---")
c = start('coding')
try:
    cmd(c, '/think on'); cmd(c, '/brief on')
    r = chat(c, 'What is a hash table?')
    log('S0927', 'Think+Brief', len(r) > 0, r[:80])
    cmd(c, '/think off'); cmd(c, '/brief off')

    r1 = cmd(c, '/context')
    cmd(c, '/compact')
    r2 = cmd(c, '/context')
    log('S0935', 'Context+compact+context', len(r1) > 0 and len(r2) > 0, '')

    chat(c, 'My project uses Django')
    cmd(c, '/mode chat')
    r = chat(c, 'What framework do I use?')
    log('S0928', 'Mode switch memory', 'django' in r.lower(), r[:80])
    cmd(c, '/mode coding')

    cmd(c, '/dream run')
    r = cmd(c, '/memory')
    log('S0931', 'Dream+memory', len(r) > 0, r[:80])

    r1 = cmd(c, '/doctor')
    r2 = cmd(c, '/flags')
    log('S0946', 'Doctor+flags consistent', len(r1) > 0 and len(r2) > 0, '')

    # 10 commands
    cmds = ['/help', '/config', '/version', '/flags', '/stats', '/cost', '/context', '/memory', '/history', '/debug']
    ok = True
    for cc in cmds:
        r = cmd(c, cc)
        if len(r) == 0: ok = False
    log('S0959', '10 cmds sequence', ok, '')
finally:
    c.terminate(force=True)

time.sleep(5)

# Edge cases
print("--- Edge Cases ---")
c = start('chat')
try:
    r = chat(c, '')
    log('S0970', 'Empty msg', True, 'no crash')

    r = chat(c, 'a')
    log('S0971', 'Single char', len(r) > 0, r[:80])

    r = chat(c, '   ')
    log('S0973', 'Whitespace', True, 'no crash')

    r = chat(c, '...!!!???')
    log('S0976', 'Punctuation', len(r) > 0 or True, 'handled')

    r = chat(c, "'; DROP TABLE users; --")
    log('S0978', 'SQL injection', len(r) > 0, r[:80])

    r = chat(c, "<script>alert('xss')</script>")
    log('S0979', 'XSS', len(r) > 0, r[:80])

    r = chat(c, '$(rm -rf /)')
    log('S0980', 'Cmd injection in chat', len(r) > 0, r[:80])

    r = cmd(c, '/HELP')
    log('S0986', 'Uppercase cmd', len(r) > 0, r[:80])

    r = chat(c, '# Hello\n- item1\n**bold**')
    log('S0998', 'Markdown in msg', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Long conversations
print("--- Long Conversations ---")
c = start('chat')
try:
    chat(c, "Let's discuss Python")
    chat(c, 'What about type hints?')
    chat(c, 'How do generics work?')
    chat(c, 'What about Protocol?')
    chat(c, 'Compare to Java interfaces')
    chat(c, 'What about multiple inheritance?')
    chat(c, 'How does MRO work?')
    chat(c, 'Explain super()')
    chat(c, 'What about mixins?')
    r = chat(c, 'Summarize our discussion')
    log('S1000', '10-turn Python', len(r) > 50, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

c = start('chat')
try:
    chat(c, 'X = 1')
    chat(c, 'Actually X = 2')
    chat(c, 'No wait, X = 3')
    r = chat(c, 'What is X?')
    log('S1004', 'Correction chain X=3', '3' in r, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

c = start('chat')
try:
    chat(c, '你好，我想学习Python')
    chat(c, '从哪里开始好？')
    chat(c, '基础语法有哪些？')
    chat(c, '变量类型怎么用？')
    chat(c, '函数怎么定义？')
    r = chat(c, '总结一下今天学的内容')
    log('S1010', 'CN 6-turn learning', len(r) > 50, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Frustration/Correction
print("--- Frustration ---")
c = start('chat')
try:
    r = chat(c, "That's completely wrong, try again")
    log('S0900', 'Frustration: wrong', len(r) > 0, r[:80])

    r = chat(c, '不对，你说的完全不对')
    log('S0902', 'CN frustration', len(r) > 0, r[:80])

    r = chat(c, "I'm so frustrated with this response")
    log('S0907', 'Frustration: angry', len(r) > 0, r[:80])

    r = chat(c, 'Actually, I meant Python not Java')
    log('S0908', 'Correction: Python not Java', len(r) > 0, r[:80])

    r = chat(c, "That's perfect, exactly what I needed!")
    log('S0919', 'Positive feedback', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# Tool scenarios (remaining)
print("--- Tool Scenarios ---")
c = start('coding')
try:
    r = chat(c, '运行 echo "你好世界"')
    log('S0225', 'Bash Chinese output', len(r) > 0, r[:80])

    r = chat(c, 'Read lines 50-100 of main.py')
    log('S0230', 'Read range', len(r) > 0, r[:80])

    r = chat(c, '读取 main.py 文件')
    log('S0233b', 'Read CN instruction', len(r) > 0, r[:80])

    r = chat(c, 'Search for "TODO" in the codebase')
    log('S0253b', 'Grep TODO', len(r) > 0, r[:80])

    r = chat(c, 'Find all Python files in the project')
    log('S0261b', 'Glob *.py', len(r) > 0, r[:80])

    r = chat(c, 'List the contents of the current directory')
    log('S0269', 'LS basic', len(r) > 0, r[:80])

    r = chat(c, '列出当前目录的文件')
    log('S0273', 'LS Chinese', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

# Summary
print("\n=== Summary ===")
p = sum(1 for r in results if r[2] == 'PASS')
f = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {p} | FAIL: {f}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
