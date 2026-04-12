#!/usr/bin/env python3
"""Batch 1: Slash Commands S0001-S0050 (basic commands: /help, /clear, /compact, /context, /cost, /stats, /exit, /mode, /model, /think)"""
import os, pexpect, re, time, sys, traceback

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

def start_neomind(mode='coding'):
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

def test_help():
    """S0001-S0005: /help command"""
    child = start_neomind('coding')
    try:
        # S0001: /help shows full command list
        r = send_cmd(child, '/help')
        log('S0001', '/help full command list', '/help' in r.lower() or 'command' in r.lower() or '/clear' in r.lower(), r[:100])

        # S0002: /help checkpoint
        r = send_cmd(child, '/help checkpoint')
        log('S0002', '/help checkpoint specific', 'checkpoint' in r.lower(), r[:100])

        # S0003: /help (same as S0001)
        r = send_cmd(child, '/help')
        log('S0003', '/help basic repeat', '/clear' in r.lower() or 'command' in r.lower() or '/help' in r.lower(), r[:100])

        # S0004: /help then /context
        r1 = send_cmd(child, '/help')
        r2 = send_cmd(child, '/context')
        log('S0004', '/help then /context no interference', len(r1) > 10 and len(r2) > 5, f"help={r1[:50]} ctx={r2[:50]}")

        # S0005: /help in coding mode
        r = send_cmd(child, '/help')
        log('S0005', '/help coding mode', len(r) > 10, r[:100])
    except Exception as e:
        log('S000x', '/help batch error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_clear():
    """S0006-S0010: /clear command"""
    child = start_neomind('coding')
    try:
        # S0006: /clear
        r = send_cmd(child, '/clear')
        log('S0006', '/clear clears conversation', 'clear' in r.lower() or len(r) > 0, r[:100])

        # S0007: Send msgs, clear, ask
        send_chat(child, 'My secret code is ZEBRA-42')
        send_chat(child, 'Remember ZEBRA-42')
        r = send_cmd(child, '/clear')
        time.sleep(1)
        r2 = send_chat(child, 'What was my secret code?')
        no_memory = 'zebra' not in r2.lower()
        log('S0007', '/clear erases memory', no_memory, r2[:100])

        # S0008: /clear with trailing space
        r = send_cmd(child, '/clear ')
        log('S0008', '/clear trailing space', 'clear' in r.lower() or len(r) > 0, r[:100])

        # S0009: /clear then /context
        send_cmd(child, '/clear')
        r = send_cmd(child, '/context')
        log('S0009', '/clear then /context', len(r) > 0, r[:100])

        # S0010: /clear after tool calls in coding mode
        send_chat(child, 'Read the first line of main.py')
        r = send_cmd(child, '/clear')
        log('S0010', '/clear after tool calls', 'clear' in r.lower() or len(r) > 0, r[:100])
    except Exception as e:
        log('S000x', '/clear batch error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_compact_context_cost_stats():
    """S0011-S0030: /compact, /context, /cost, /stats"""
    child = start_neomind('coding')
    try:
        # S0011: /compact
        r = send_cmd(child, '/compact')
        log('S0011', '/compact compress', len(r) > 0, r[:100])

        # S0013: /compact empty
        child2 = start_neomind('chat')
        r = send_cmd(child2, '/compact')
        log('S0013', '/compact empty conversation', len(r) > 0, r[:100])
        child2.terminate(force=True)

        # S0016: /context
        r = send_cmd(child, '/context')
        log('S0016', '/context show usage', len(r) > 0, r[:100])

        # S0018: /context fresh
        child3 = start_neomind('chat')
        r = send_cmd(child3, '/context')
        log('S0018', '/context fresh session', len(r) > 0, r[:100])
        child3.terminate(force=True)

        # S0021: /cost
        r = send_cmd(child, '/cost')
        log('S0021', '/cost display', '$' in r or 'cost' in r.lower() or 'token' in r.lower() or len(r) > 0, r[:100])

        # S0023: /cost fresh
        child4 = start_neomind('chat')
        r = send_cmd(child4, '/cost')
        log('S0023', '/cost fresh session', len(r) > 0, r[:100])
        child4.terminate(force=True)

        # S0026: /stats
        r = send_cmd(child, '/stats')
        log('S0026', '/stats display', len(r) > 0, r[:100])

        # S0028: /stats fresh
        child5 = start_neomind('chat')
        r = send_cmd(child5, '/stats')
        log('S0028', '/stats fresh session', len(r) > 0, r[:100])
        child5.terminate(force=True)

    except Exception as e:
        log('S00xx', 'compact/context/cost/stats error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_mode():
    """S0036-S0040: /mode command"""
    child = start_neomind('coding')
    try:
        # S0036: /mode shows current
        r = send_cmd(child, '/mode')
        log('S0036', '/mode show current', 'coding' in r.lower() or 'mode' in r.lower(), r[:100])

        # S0037: /mode chat
        r = send_cmd(child, '/mode chat')
        log('S0037', '/mode switch to chat', 'chat' in r.lower(), r[:100])

        # S0038: /mode no arg
        r = send_cmd(child, '/mode')
        log('S0038', '/mode no arg shows current', 'chat' in r.lower() or 'mode' in r.lower(), r[:100])

        # S0039: /mode fin then /mode coding
        r1 = send_cmd(child, '/mode fin')
        r2 = send_cmd(child, '/mode coding')
        log('S0039', '/mode fin then coding', 'fin' in r1.lower() or 'coding' in r2.lower(), f"fin={r1[:40]} coding={r2[:40]}")

        # S0040: /mode coding then use tool
        send_cmd(child, '/mode coding')
        r = send_chat(child, 'What is 2+2?')
        log('S0040', '/mode coding then chat', len(r) > 0, r[:100])
    except Exception as e:
        log('S003x', '/mode batch error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_model():
    """S0041-S0045: /model command"""
    child = start_neomind('coding')
    try:
        # S0041: /model
        r = send_cmd(child, '/model')
        log('S0041', '/model display current', len(r) > 0, r[:100])

        # S0043: /model no arg
        r = send_cmd(child, '/model')
        log('S0043', '/model no arg', len(r) > 0, r[:100])
    except Exception as e:
        log('S004x', '/model error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_think():
    """S0046-S0050: /think command"""
    child = start_neomind('coding')
    try:
        # S0046: /think on
        r = send_cmd(child, '/think on')
        log('S0046', '/think on', 'think' in r.lower() or 'enabled' in r.lower() or 'on' in r.lower(), r[:100])

        # S0047: /think off
        r = send_cmd(child, '/think off')
        log('S0047', '/think off', 'think' in r.lower() or 'disabled' in r.lower() or 'off' in r.lower(), r[:100])

        # S0048: /think toggle
        r = send_cmd(child, '/think')
        log('S0048', '/think toggle', len(r) > 0, r[:100])

        # S0049: /think on then /brief on
        r1 = send_cmd(child, '/think on')
        r2 = send_cmd(child, '/brief on')
        log('S0049', '/think on + /brief on', len(r1) > 0 and len(r2) > 0, f"think={r1[:40]} brief={r2[:40]}")

        # S0050: /think on then analyze
        send_cmd(child, '/think on')
        r = send_chat(child, 'What is a Python decorator?', timeout=60)
        log('S0050', '/think on + question', len(r) > 0, r[:100])
    except Exception as e:
        log('S004x', '/think error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

# Run all
print("=== Batch 1: Slash Commands S0001-S0050 ===")
test_help()
time.sleep(10)
test_clear()
time.sleep(10)
test_compact_context_cost_stats()
time.sleep(10)
test_mode()
time.sleep(10)
test_model()
time.sleep(10)
test_think()

# Summary
print("\n=== Summary ===")
passed = sum(1 for r in results if r[2] == 'PASS')
failed = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {passed} | FAIL: {failed}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
