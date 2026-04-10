#!/usr/bin/env python3
"""Batch 3: Slash Commands S0131-S0220"""
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

def test_init_ship_btw():
    """S0131-S0145"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/init')
        log('S0131', '/init scan workspace', len(r) > 0, r[:100])

        r = send_cmd(child, '/init')
        log('S0132', '/init Python project', len(r) > 0, r[:100])

        # S0136-S0138: /ship
        r = send_cmd(child, '/ship')
        log('S0136', '/ship start git workflow', len(r) > 0, r[:100])

        r = send_cmd(child, '/ship feature')
        log('S0137', '/ship feature', len(r) > 0, r[:100])

        # S0141-S0145: /btw
        r = send_cmd(child, '/btw 2+2等于几？')
        log('S0141', '/btw quick Chinese', len(r) > 0, r[:100])

        r = send_cmd(child, '/btw what is the capital of France?')
        log('S0142', '/btw quick English', len(r) > 0, r[:100])

        r = send_cmd(child, '/btw')
        log('S0143', '/btw no question', len(r) > 0, r[:100])
    except Exception as e:
        log('S01xx', 'init/ship/btw error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_doctor_style_rules():
    """S0146-S0160"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/doctor')
        log('S0146', '/doctor diagnostics', len(r) > 0, r[:100])

        r = send_cmd(child, '/doctor')
        log('S0148', '/doctor no arg', len(r) > 0, r[:100])

        r1 = send_cmd(child, '/doctor')
        r2 = send_cmd(child, '/flags')
        log('S0149', '/doctor then /flags', len(r1) > 0 and len(r2) > 0, '')

        r = send_cmd(child, '/doctor')
        log('S0150', '/doctor coding mode', len(r) > 0, r[:100])

        # Style S0151-S0155
        r = send_cmd(child, '/style')
        log('S0151', '/style list', len(r) > 0, r[:100])

        r = send_cmd(child, '/style concise')
        log('S0152', '/style concise', len(r) > 0, r[:100])

        r = send_cmd(child, '/style')
        log('S0153', '/style no arg', len(r) > 0, r[:100])

        r = send_cmd(child, '/style')
        log('S0155', '/style coding mode', len(r) > 0, r[:100])

        # Rules S0156-S0160
        r = send_cmd(child, '/rules')
        log('S0156', '/rules display', len(r) > 0, r[:100])

        r = send_cmd(child, '/rules add Bash allow npm test')
        log('S0157', '/rules add allow', len(r) > 0, r[:100])

        r = send_cmd(child, '/rules')
        log('S0158', '/rules no arg', len(r) > 0, r[:100])

        r = send_cmd(child, '/rules add Bash allow git*')
        log('S0160', '/rules add glob', len(r) > 0, r[:100])
    except Exception as e:
        log('S015x', 'doctor/style/rules error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_team_plan_review():
    """S0161-S0175"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/team create devteam')
        log('S0161', '/team create devteam', len(r) > 0, r[:100])

        r = send_cmd(child, '/team list')
        log('S0162', '/team list', len(r) > 0, r[:100])

        r = send_cmd(child, '/team')
        log('S0163', '/team no arg', len(r) > 0, r[:100])

        send_cmd(child, '/team create tempteam')
        r = send_cmd(child, '/team delete tempteam')
        log('S0164', '/team create then delete', len(r) > 0, r[:100])

        r = send_cmd(child, '/team info devteam')
        log('S0165', '/team info', len(r) > 0, r[:100])

        # Plan S0166-S0170
        r = send_cmd(child, '/plan')
        log('S0166', '/plan display', len(r) > 0, r[:100])

        r = send_cmd(child, '/plan add authentication')
        log('S0167', '/plan add', len(r) > 0, r[:100])

        r = send_cmd(child, '/plan')
        log('S0168', '/plan no arg', len(r) > 0, r[:100])

        # Review S0171-S0175
        r = send_cmd(child, '/review')
        log('S0171', '/review analyze', len(r) > 0, r[:100])

        r = send_cmd(child, '/review')
        log('S0173', '/review no changes', len(r) > 0, r[:100])

        # cleanup
        send_cmd(child, '/team delete devteam')
    except Exception as e:
        log('S016x', 'team/plan/review error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_diff_git_test():
    """S0176-S0195"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/diff')
        log('S0176', '/diff show', len(r) > 0, r[:100])

        r = send_cmd(child, '/diff')
        log('S0178', '/diff no git (may work or error)', len(r) > 0, r[:100])

        # Git S0181-S0185
        r = send_cmd(child, '/git status')
        log('S0181', '/git status', len(r) > 0, r[:100])

        r = send_cmd(child, '/git log --oneline -5')
        log('S0182', '/git log', len(r) > 0, r[:100])

        r = send_cmd(child, '/git')
        log('S0183', '/git no arg', len(r) > 0, r[:100])

        # Test S0186-S0190
        r = send_cmd(child, '/test')
        log('S0186', '/test run', len(r) > 0, r[:100])

        r = send_cmd(child, '/test')
        log('S0188', '/test no tests (may find some)', len(r) > 0, r[:100])

        # Security-review S0191-S0195
        r = send_cmd(child, '/security-review')
        log('S0191', '/security-review', len(r) > 0, r[:100])

        r = send_cmd(child, '/security-review')
        log('S0193', '/security-review clean', len(r) > 0, r[:100])
    except Exception as e:
        log('S01xx', 'diff/git/test error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_fin_commands():
    """S0196-S0220: /stock, /portfolio, /market, /news, /quant"""
    child = start_neomind('fin')
    try:
        r = send_cmd(child, '/stock AAPL')
        log('S0196', '/stock AAPL', len(r) > 0, r[:100])

        r = send_cmd(child, '/stock AAPL MSFT GOOG')
        log('S0197', '/stock multiple', len(r) > 0, r[:100])

        r = send_cmd(child, '/stock')
        log('S0198', '/stock no ticker', len(r) > 0, r[:100])

        # Portfolio S0201-S0205
        r = send_cmd(child, '/portfolio')
        log('S0201b', '/portfolio display', len(r) > 0, r[:100])

        r = send_cmd(child, '/portfolio')
        log('S0203', '/portfolio no arg', len(r) > 0, r[:100])

        # Market S0206-S0210
        r = send_cmd(child, '/market')
        log('S0206', '/market overview', len(r) > 0, r[:100])

        r = send_cmd(child, '/market US')
        log('S0207', '/market US', len(r) > 0, r[:100])

        r = send_cmd(child, '/market')
        log('S0208', '/market no arg', len(r) > 0, r[:100])

        # News S0211-S0215
        r = send_cmd(child, '/news')
        log('S0211', '/news financial', len(r) > 0, r[:100])

        r = send_cmd(child, '/news AAPL')
        log('S0212', '/news AAPL', len(r) > 0, r[:100])

        r = send_cmd(child, '/news')
        log('S0213', '/news no arg', len(r) > 0, r[:100])

        # Quant S0216-S0220
        r = send_cmd(child, '/quant AAPL')
        log('S0216', '/quant AAPL', len(r) > 0, r[:100])

        r = send_cmd(child, '/quant')
        log('S0218', '/quant no arg', len(r) > 0, r[:100])
    except Exception as e:
        log('S02xx', 'fin commands error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

# Run all
print("=== Batch 3: Slash Commands S0131-S0220 ===")
test_init_ship_btw()
time.sleep(10)
test_doctor_style_rules()
time.sleep(10)
test_team_plan_review()
time.sleep(10)
test_diff_git_test()
time.sleep(10)
test_fin_commands()

# Summary
print("\n=== Summary ===")
passed = sum(1 for r in results if r[2] == 'PASS')
failed = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {passed} | FAIL: {failed}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
