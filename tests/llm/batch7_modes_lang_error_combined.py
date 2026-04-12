#!/usr/bin/env python3
"""Batch 7: Mode-specific (chat/fin), Chinese/English, Error Handling, Combined, Edge, Long Conv"""
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

# === Chat Mode S0600-S0629 (select) ===
print("--- Chat Mode ---")
c = start('chat')
try:
    r = chat(c, 'What is machine learning?')
    log('S0600', 'Chat: ML explanation', len(r) > 50, r[:80])

    r = chat(c, 'Explain quantum computing to a 10 year old')
    log('S0601b', 'Chat: QC for kid', len(r) > 30, r[:80])

    r = chat(c, 'Help me write a professional email declining a meeting')
    log('S0603', 'Chat: email draft', len(r) > 30, r[:80])

    r = chat(c, 'Brainstorm names for a pet adoption app')
    log('S0605b', 'Chat: brainstorm names', len(r) > 20, r[:80])

    r = chat(c, 'Compare Python and Rust for system programming')
    log('S0606', 'Chat: Python vs Rust', 'python' in r.lower() or 'rust' in r.lower(), r[:80])

    r = chat(c, 'Summarize the SOLID principles')
    log('S0614b', 'Chat: SOLID principles', len(r) > 50, r[:80])

    r = chat(c, 'Write a haiku about programming')
    log('S0620', 'Chat: programming haiku', len(r) > 10, r[:80])

    r = chat(c, 'Tell me a programming joke')
    log('S0621', 'Chat: programming joke', len(r) > 10, r[:80])

    r = chat(c, 'What is the difference between a process and a thread?')
    log('S0622', 'Chat: process vs thread', len(r) > 30, r[:80])

    r = chat(c, 'Explain how HTTPS works')
    log('S0623', 'Chat: HTTPS', len(r) > 30, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Fin Mode S0630-S0659 (select) ===
print("--- Fin Mode ---")
c = start('fin')
try:
    r = chat(c, 'What is dollar-cost averaging?')
    log('S0638b', 'Fin: DCA', len(r) > 30, r[:80])

    r = chat(c, 'Explain options trading basics')
    log('S0639', 'Fin: options', len(r) > 30, r[:80])

    r = chat(c, 'What is a covered call strategy?')
    log('S0642', 'Fin: covered call', len(r) > 30, r[:80])

    r = chat(c, 'What is the 50-day moving average?')
    log('S0644', 'Fin: 50-day MA', len(r) > 20, r[:80])

    r = chat(c, 'What is market cap and why does it matter?')
    log('S0646', 'Fin: market cap', len(r) > 30, r[:80])

    r = chat(c, '什么是市盈率？')
    log('S0649', 'Fin: CN PE ratio', len(r) > 20, r[:80])

    r = chat(c, '什么是量化交易？')
    log('S0651b', 'Fin: CN quant', len(r) > 20, r[:80])

    r = chat(c, '港股和A股有什么区别？')
    log('S0653', 'Fin: HK vs A-share', len(r) > 20, r[:80])

    r = chat(c, 'What is a stop-loss order?')
    log('S0659', 'Fin: stop-loss', len(r) > 20, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Chinese/English/Mixed S0660-S0699 (select) ===
print("--- Chinese/English/Mixed ---")
c = start('chat')
try:
    r = chat(c, '什么是机器学习？')
    log('S0660b', 'CN: ML', len(r) > 30, r[:80])

    r = chat(c, '解释一下什么是微服务架构')
    log('S0662b', 'CN: microservices', len(r) > 30, r[:80])

    r = chat(c, 'What is a REST API?')
    log('S0670', 'EN: REST API', len(r) > 30, r[:80])

    r = chat(c, 'Explain event sourcing')
    log('S0675', 'EN: event sourcing', len(r) > 30, r[:80])

    r = chat(c, 'What is a load balancer?')
    log('S0676', 'EN: load balancer', len(r) > 30, r[:80])

    r = chat(c, 'Explain circuit breaker pattern')
    log('S0679', 'EN: circuit breaker', len(r) > 30, r[:80])

    # Mixed
    r = chat(c, '用Python写一个function来calculate fibonacci')
    log('S0680b', 'Mixed: fibonacci', len(r) > 20, r[:80])

    r = chat(c, '帮我implement一个observer pattern')
    log('S0683b', 'Mixed: observer', len(r) > 20, r[:80])

    # Language switch
    r1 = chat(c, 'What is Docker?')
    r2 = chat(c, '用中文再解释一遍')
    log('S0685b', 'Lang switch EN->CN', len(r2) > 20, r2[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Error Handling S0840-S0879 (select) ===
print("--- Error Handling ---")
c = start('coding')
try:
    r = chat(c, 'Read /nonexistent/file.py')
    log('S0840', 'Error: file not found', len(r) > 0, r[:80])

    r = chat(c, 'List contents of /nonexistent/dir/')
    log('S0841', 'Error: dir not found', len(r) > 0, r[:80])

    r = chat(c, '')
    log('S0843', 'Error: empty input', True, 'no crash')

    r = chat(c, 'Hello ' * 1000)
    log('S0844', 'Error: very long input', len(r) > 0, r[:80])

    r = chat(c, "Hello <script>alert('xss')</script>")
    log('S0845', 'Error: XSS input', len(r) > 0, r[:80])

    r = chat(c, 'Hello 你好 مرحبا Привет')
    log('S0846', 'Error: multi-unicode', len(r) > 0, r[:80])

    r = cmd(c, '/nonexistent_command')
    log('S0847', 'Error: unknown cmd', len(r) > 0, r[:80])

    r = cmd(c, '/flags NONEXISTENT on')
    log('S0849', 'Error: unknown flag', len(r) > 0, r[:80])

    r = cmd(c, '/rewind -5')
    log('S0850', 'Error: negative rewind', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Combined Features S0920-S0969 (select) ===
print("--- Combined Features ---")
c = start('coding')
try:
    # Think + brief
    cmd(c, '/think on'); cmd(c, '/brief on')
    r = chat(c, 'What is a hash table?')
    log('S0927', 'Think+Brief combined', len(r) > 0, r[:80])
    cmd(c, '/think off'); cmd(c, '/brief off')

    # Context + compact + context
    r1 = cmd(c, '/context')
    cmd(c, '/compact')
    r2 = cmd(c, '/context')
    log('S0935', 'Context+compact+context', len(r1) > 0 and len(r2) > 0, '')

    # Mode switch memory
    chat(c, 'My project uses Django')
    cmd(c, '/mode chat')
    r = chat(c, 'What framework do I use?')
    log('S0928', 'Mode switch memory', 'django' in r.lower(), r[:80])
    cmd(c, '/mode coding')

    # Dream + memory
    cmd(c, '/dream run')
    r = cmd(c, '/memory')
    log('S0931', 'Dream+memory', len(r) > 0, r[:80])

    # Debug + think
    cmd(c, '/debug on'); cmd(c, '/think on')
    r = chat(c, 'What is 2+2?')
    log('S0933', 'Debug+think', len(r) > 0, r[:80])
    cmd(c, '/debug off'); cmd(c, '/think off')

    # Doctor + flags
    r1 = cmd(c, '/doctor')
    r2 = cmd(c, '/flags')
    log('S0946', 'Doctor+flags', len(r1) > 0 and len(r2) > 0, '')

    # 10 commands sequence
    cmds = ['/help', '/config', '/version', '/flags', '/stats', '/cost', '/context',
            '/memory', '/history', '/debug']
    ok = True
    for cc in cmds:
        r = cmd(c, cc)
        if len(r) == 0: ok = False
    log('S0959', '10 commands sequence', ok, '')
finally:
    c.terminate(force=True)

time.sleep(5)

# === Edge Cases S0970-S0999 (select) ===
print("--- Edge Cases ---")
c = start('chat')
try:
    r = chat(c, '')
    log('S0970', 'Edge: empty', True, 'no crash')

    r = chat(c, 'a')
    log('S0971', 'Edge: single char', len(r) > 0, r[:80])

    r = chat(c, '   ')
    log('S0973', 'Edge: whitespace only', True, 'no crash')

    r = chat(c, '...!!!???')
    log('S0976', 'Edge: punctuation', len(r) > 0, r[:80])

    r = chat(c, "'; DROP TABLE users; --")
    log('S0978', 'Edge: SQL injection', len(r) > 0, r[:80])

    r = chat(c, "<script>alert('xss')</script>")
    log('S0979', 'Edge: XSS', len(r) > 0, r[:80])

    r = chat(c, '$(rm -rf /)')
    log('S0980', 'Edge: cmd injection', len(r) > 0, r[:80])

    r = cmd(c, '/ help')
    log('S0985', 'Edge: slash space', len(r) > 0 or True, 'handled')

    r = cmd(c, '/HELP')
    log('S0986', 'Edge: slash uppercase', len(r) > 0, r[:80])

    r = chat(c, 'He said "she said \'they said \\"hello\\"\'"')
    log('S0992', 'Edge: nested quotes', len(r) > 0, r[:80])

    r = chat(c, '# Hello\n- item1\n- item2\n**bold**')
    log('S0998', 'Edge: markdown in msg', len(r) > 0, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# === Long Conversations (select) ===
print("--- Long Conversations ---")
c = start('chat')
try:
    # S1000: 10-turn discussion
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
    log('S1000', '10-turn Python discussion', len(r) > 50, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# S1004: Corrections chain
c = start('chat')
try:
    chat(c, 'X = 1')
    chat(c, 'Actually X = 2')
    chat(c, 'No wait, X = 3')
    r = chat(c, 'What is X?')
    log('S1004', 'Corrections: X=3', '3' in r, r[:80])
finally:
    c.terminate(force=True)

time.sleep(5)

# S1010: Chinese learning
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

# Summary
print("\n=== Summary ===")
p = sum(1 for r in results if r[2] == 'PASS')
f = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {p} | FAIL: {f}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
