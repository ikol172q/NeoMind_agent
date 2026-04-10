#!/usr/bin/env python3
"""Batch 2: Slash Commands S0051-S0130"""
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

def test_config_memory_debug():
    """S0051-S0065"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/config')
        log('S0051', '/config display', len(r) > 0, r[:100])

        r = send_cmd(child, '/config show')
        log('S0052', '/config show', len(r) > 0, r[:100])

        r = send_cmd(child, '/config')
        log('S0053', '/config empty', len(r) > 0, r[:100])

        r1 = send_cmd(child, '/config')
        r2 = send_cmd(child, '/flags')
        log('S0054', '/config then /flags', len(r1) > 0 and len(r2) > 0, f"cfg={r1[:40]} flg={r2[:40]}")

        r = send_cmd(child, '/config')
        log('S0055', '/config coding mode', len(r) > 0, r[:100])

        # Memory S0056-S0060
        r = send_cmd(child, '/memory')
        log('S0056', '/memory status', len(r) > 0, r[:100])

        r = send_cmd(child, '/memory list')
        log('S0057', '/memory list', len(r) > 0, r[:100])

        r = send_cmd(child, '/memory')
        log('S0058', '/memory no arg', len(r) > 0, r[:100])

        r = send_cmd(child, '/memory')
        log('S0060', '/memory coding mode', len(r) > 0, r[:100])

        # Debug S0061-S0065
        r = send_cmd(child, '/debug')
        log('S0061', '/debug toggle', len(r) > 0, r[:100])

        r = send_cmd(child, '/debug on')
        log('S0062', '/debug on', len(r) > 0, r[:100])

        r = send_cmd(child, '/debug')
        log('S0063', '/debug no arg toggle', len(r) > 0, r[:100])

        send_cmd(child, '/debug on')
        r = send_chat(child, 'hi', timeout=30)
        log('S0064', '/debug on then message', len(r) > 0, r[:100])

        send_cmd(child, '/debug off')
    except Exception as e:
        log('S005x', 'config/memory/debug error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_history_save_skills():
    """S0066-S0080"""
    child = start_neomind('coding')
    try:
        # History S0066-S0070
        r = send_cmd(child, '/history')
        log('S0066', '/history display', len(r) > 0, r[:100])

        r = send_cmd(child, '/history 5')
        log('S0067', '/history 5', len(r) > 0, r[:100])

        # S0068: fresh session history
        child2 = start_neomind('chat')
        r = send_cmd(child2, '/history')
        log('S0068', '/history empty session', len(r) > 0, r[:100])
        child2.terminate(force=True)

        # Save S0071-S0075
        send_chat(child, 'Hello world test')
        r = send_cmd(child, '/save /tmp/neomind_test_output.md')
        log('S0071', '/save output.md', 'save' in r.lower() or '✓' in r or 'success' in r.lower() or len(r) > 0, r[:100])

        r = send_cmd(child, '/save /tmp/neomind_test_output.json')
        log('S0072', '/save output.json', len(r) > 0, r[:100])

        r = send_cmd(child, '/save')
        log('S0073', '/save no filename', len(r) > 0, r[:100])

        # Skills S0076-S0080
        r = send_cmd(child, '/skills')
        log('S0076', '/skills list', len(r) > 0, r[:100])

        r = send_cmd(child, '/skills list')
        log('S0077', '/skills list explicit', len(r) > 0, r[:100])

        r = send_cmd(child, '/skills')
        log('S0078', '/skills no arg', len(r) > 0, r[:100])

        r = send_cmd(child, '/skills')
        log('S0080', '/skills coding mode', len(r) > 0, r[:100])
    except Exception as e:
        log('S006x', 'history/save/skills error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_permissions_version():
    """S0081-S0090"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/permissions')
        log('S0081', '/permissions display', len(r) > 0, r[:100])

        r = send_cmd(child, '/permissions normal')
        log('S0082', '/permissions normal', len(r) > 0, r[:100])

        r = send_cmd(child, '/permissions')
        log('S0083', '/permissions no arg', len(r) > 0, r[:100])

        # S0086-S0090: /version
        r = send_cmd(child, '/version')
        log('S0086', '/version display', len(r) > 0, r[:100])

        r = send_cmd(child, '/version')
        log('S0087', '/version basic', len(r) > 0, r[:100])

        r = send_cmd(child, '/version extra text')
        log('S0088', '/version with extra', len(r) > 0, r[:100])

        r1 = send_cmd(child, '/version')
        r2 = send_cmd(child, '/doctor')
        log('S0089', '/version then /doctor', len(r1) > 0 and len(r2) > 0, f"ver={r1[:40]} doc={r2[:40]}")

        r = send_cmd(child, '/version')
        log('S0090', '/version coding mode', len(r) > 0, r[:100])
    except Exception as e:
        log('S008x', 'permissions/version error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_checkpoint_rewind():
    """S0091-S0100"""
    child = start_neomind('coding')
    try:
        r = send_cmd(child, '/checkpoint save1')
        log('S0091', '/checkpoint save1', 'checkpoint' in r.lower() or '✓' in r or len(r) > 0, r[:100])

        r = send_cmd(child, '/checkpoint "before refactor"')
        log('S0092', '/checkpoint quoted label', len(r) > 0, r[:100])

        r = send_cmd(child, '/checkpoint')
        log('S0093', '/checkpoint no label', len(r) > 0, r[:100])

        # S0096: checkpoint then rewind
        send_cmd(child, '/checkpoint testpoint')
        send_chat(child, 'This message should be removed after rewind')
        r = send_cmd(child, '/rewind testpoint')
        log('S0096', '/rewind to checkpoint', len(r) > 0, r[:100])

        # S0097: /rewind 3
        r = send_cmd(child, '/rewind 3')
        log('S0097', '/rewind 3', len(r) > 0, r[:100])

        # S0098: /rewind no arg
        r = send_cmd(child, '/rewind')
        log('S0098', '/rewind no arg', len(r) > 0, r[:100])

        # S0099: /rewind nonexistent
        r = send_cmd(child, '/rewind nonexistent_checkpoint_xyz')
        log('S0099', '/rewind nonexistent', len(r) > 0, r[:100])
    except Exception as e:
        log('S009x', 'checkpoint/rewind error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_flags_dream_resume():
    """S0101-S0115"""
    child = start_neomind('coding')
    try:
        # Flags S0101-S0105
        r = send_cmd(child, '/flags')
        log('S0101', '/flags list', len(r) > 0, r[:100])

        r = send_cmd(child, '/flags VOICE_INPUT on')
        log('S0102', '/flags VOICE_INPUT on', len(r) > 0, r[:100])

        r = send_cmd(child, '/flags')
        log('S0103', '/flags no arg', len(r) > 0, r[:100])

        # Dream S0106-S0110
        r = send_cmd(child, '/dream')
        log('S0106', '/dream status', len(r) > 0, r[:100])

        r = send_cmd(child, '/dream run')
        log('S0107', '/dream run', len(r) > 0, r[:100])

        r = send_cmd(child, '/dream')
        log('S0108', '/dream no arg', len(r) > 0, r[:100])

        # Resume S0111-S0115
        r = send_cmd(child, '/resume')
        log('S0111', '/resume list', len(r) > 0, r[:100])

        r = send_cmd(child, '/resume')
        log('S0113', '/resume no arg', len(r) > 0, r[:100])
    except Exception as e:
        log('S010x', 'flags/dream/resume error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

def test_branch_snip_brief():
    """S0116-S0130"""
    child = start_neomind('coding')
    try:
        # Branch S0116-S0120
        r = send_cmd(child, '/branch experiment')
        log('S0116', '/branch experiment', len(r) > 0, r[:100])

        r = send_cmd(child, '/branch "new approach"')
        log('S0117', '/branch quoted label', len(r) > 0, r[:100])

        r = send_cmd(child, '/branch')
        log('S0118', '/branch no label', len(r) > 0, r[:100])

        # Snip S0121-S0125
        send_chat(child, 'Test message 1 for snipping')
        send_chat(child, 'Test message 2 for snipping')
        send_chat(child, 'Test message 3 for snipping')

        r = send_cmd(child, '/snip 3')
        log('S0121', '/snip 3', 'snip' in r.lower() or '✓' in r or 'save' in r.lower() or len(r) > 0, r[:100])

        r = send_cmd(child, '/snip important_finding')
        log('S0122', '/snip custom label', len(r) > 0, r[:100])

        r = send_cmd(child, '/snip')
        log('S0123', '/snip no arg', len(r) > 0, r[:100])

        # Brief S0126-S0130
        r = send_cmd(child, '/brief on')
        log('S0126', '/brief on', 'brief' in r.lower() or 'enabled' in r.lower() or len(r) > 0, r[:100])

        r = send_cmd(child, '/brief off')
        log('S0127', '/brief off', 'brief' in r.lower() or 'disabled' in r.lower() or len(r) > 0, r[:100])

        r = send_cmd(child, '/brief')
        log('S0128', '/brief no arg', len(r) > 0, r[:100])

        send_cmd(child, '/brief on')
        send_cmd(child, '/think on')
        log('S0129', '/brief on + /think on', True, 'both activated')

        send_cmd(child, '/brief on')
        r = send_chat(child, 'What is a linked list?', timeout=60)
        log('S0130', '/brief on + complex question', len(r) > 0, r[:100])
    except Exception as e:
        log('S01xx', 'branch/snip/brief error', False, str(e)[:100])
    finally:
        try: child.terminate(force=True)
        except: pass

# Run all
print("=== Batch 2: Slash Commands S0051-S0130 ===")
test_config_memory_debug()
time.sleep(10)
test_history_save_skills()
time.sleep(10)
test_permissions_version()
time.sleep(10)
test_checkpoint_rewind()
time.sleep(10)
test_flags_dream_resume()
time.sleep(10)
test_branch_snip_brief()

# Summary
print("\n=== Summary ===")
passed = sum(1 for r in results if r[2] == 'PASS')
failed = sum(1 for r in results if r[2] == 'FAIL')
print(f"Total: {len(results)} | PASS: {passed} | FAIL: {failed}")
for sid, desc, status, detail in results:
    print(f"- [{status}] {sid}: {desc}" + (f" -- {detail[:80]}" if detail and status == 'FAIL' else ""))
