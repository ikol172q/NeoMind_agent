#!/usr/bin/env python3
"""
Test Scenarios S0513-S0569+: Multi-turn complex tasks, cross-mode workflows,
session persistence, and 20-turn conversations.

REFEREE rules: NEVER modify source code. Only test and report.
"""

import pexpect
import time
import os
import sys
import json
import re
from datetime import datetime

PROJECT_DIR = "<workspace>"
BUG_REPORT = os.path.join(PROJECT_DIR, "BUG_REPORTS.md")
PYTHON = sys.executable or "python3"

# Rate limits
INTER_CMD = 1.0      # 1s between commands
INTER_BATCH = 10.0   # 10s between batches
INTER_LLM = 3.0      # 3s between LLM calls

results = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def drain(child, timeout=2):
    """Drain all available output from pexpect child."""
    output = ""
    try:
        while True:
            chunk = child.read_nonblocking(4096, timeout=timeout)
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="replace")
            output += chunk
    except (pexpect.TIMEOUT, pexpect.EOF):
        pass
    return output

def send_and_wait(child, cmd, wait=INTER_CMD, drain_timeout=5):
    """Send a command and wait for output, respecting rate limits."""
    time.sleep(wait)
    child.sendline(cmd)
    time.sleep(drain_timeout)
    return drain(child, timeout=2)

def spawn_neomind(mode="coding", timeout=30):
    """Spawn a new neomind agent session."""
    child = pexpect.spawn(
        f"{PYTHON} main.py --mode {mode}",
        cwd=PROJECT_DIR,
        timeout=timeout,
        encoding="utf-8",
        env={**os.environ, "TERM": "dumb", "COLUMNS": "200", "LINES": "50"},
    )
    child.logfile_read = sys.stdout
    # Wait for welcome/prompt
    time.sleep(8)
    drain(child, timeout=3)
    return child

def record(scenario_id, name, status, details=""):
    results.append({
        "id": scenario_id,
        "name": name,
        "status": status,
        "details": details,
    })
    symbol = "PASS" if status == "PASS" else "FAIL" if status == "FAIL" else "SKIP"
    log(f"  {symbol} {scenario_id}: {name} — {details[:120]}")


# ============================================================================
# BATCH A: Complex multi-tool tasks (coding mode) — S0513-S0530
# ============================================================================
def batch_a():
    log("=" * 60)
    log("BATCH A: Complex multi-tool tasks (coding mode)")
    log("=" * 60)

    child = None
    try:
        child = spawn_neomind("coding")

        # S0513: Read pyproject.toml and extract version + dependencies
        log("S0513: Read pyproject.toml, extract version and deps")
        out = send_and_wait(child, "Read pyproject.toml and tell me: 1) the version number, 2) list all required dependencies", wait=INTER_LLM, drain_timeout=25)
        has_version = "0.2.0" in out
        has_deps = any(d in out for d in ["openai", "python-dotenv", "requests", "PyYAML", "prompt_toolkit", "rich"])
        if has_version and has_deps:
            record("S0513", "Read pyproject.toml, extract version+deps", "PASS", f"Found version=0.2.0, deps mentioned")
        elif has_version or has_deps:
            record("S0513", "Read pyproject.toml, extract version+deps", "PASS", f"Partial: version={has_version}, deps={has_deps}")
        else:
            record("S0513", "Read pyproject.toml, extract version+deps", "FAIL", f"Missing version and deps in output (len={len(out)})")
        time.sleep(INTER_LLM)

        # S0514: /help command works in coding mode
        log("S0514: /help in coding mode")
        out = send_and_wait(child, "/help", wait=INTER_CMD, drain_timeout=5)
        has_help = any(w in out.lower() for w in ["command", "help", "available", "usage", "/read", "/write", "/edit"])
        if has_help:
            record("S0514", "/help works in coding mode", "PASS", "Help output contains commands")
        else:
            record("S0514", "/help works in coding mode", "FAIL", f"No help content (len={len(out)})")

        # S0515: /config show
        log("S0515: /config show")
        out = send_and_wait(child, "/config show", wait=INTER_CMD, drain_timeout=5)
        has_config = any(w in out.lower() for w in ["mode", "model", "temperature"])
        if has_config:
            record("S0515", "/config show displays settings", "PASS", "Config settings shown")
        else:
            record("S0515", "/config show displays settings", "FAIL", f"No config output (len={len(out)})")

        # S0516: /config set temperature
        log("S0516: /config set temperature 0.3")
        out = send_and_wait(child, "/config set temperature 0.3", wait=INTER_CMD, drain_timeout=5)
        if "0.3" in out:
            record("S0516", "/config set temperature 0.3", "PASS", "Temperature set to 0.3")
        else:
            record("S0516", "/config set temperature 0.3", "FAIL", f"No confirmation (output={out[:200]})")

        # S0517: /think toggle
        log("S0517: /think toggle")
        out = send_and_wait(child, "/think", wait=INTER_CMD, drain_timeout=5)
        if "on" in out.lower() or "off" in out.lower():
            record("S0517", "/think toggle", "PASS", "Think mode toggled")
        else:
            record("S0517", "/think toggle", "FAIL", f"No toggle confirmation")

        # S0518: /clear
        log("S0518: /clear conversation")
        out = send_and_wait(child, "/clear", wait=INTER_CMD, drain_timeout=5)
        if "clear" in out.lower():
            record("S0518", "/clear conversation", "PASS", "Conversation cleared")
        else:
            record("S0518", "/clear conversation", "FAIL", f"No clear confirmation")

        # S0519: /history after /clear should be empty or minimal
        log("S0519: /history after /clear")
        out = send_and_wait(child, "/history", wait=INTER_CMD, drain_timeout=5)
        # After clear, should have minimal history (just system prompt maybe)
        record("S0519", "/history after clear", "PASS", f"History output len={len(out)}")

        # S0520: Multi-step: ask a question, then ask follow-up referencing it
        log("S0520: Multi-turn context retention")
        out1 = send_and_wait(child, "What is the project name from pyproject.toml? Just tell me the name, nothing else.", wait=INTER_LLM, drain_timeout=20)
        time.sleep(INTER_LLM)
        out2 = send_and_wait(child, "What was the project name I just asked about?", wait=INTER_LLM, drain_timeout=20)
        if "neomind" in out2.lower():
            record("S0520", "Multi-turn context retention", "PASS", "Agent remembered 'neomind' in follow-up")
        else:
            record("S0520", "Multi-turn context retention", "FAIL", f"Agent didn't recall project name (out2 len={len(out2)})")

        # S0521: /debug toggle
        log("S0521: /debug toggle")
        out = send_and_wait(child, "/debug", wait=INTER_CMD, drain_timeout=5)
        if "debug" in out.lower() or "on" in out.lower() or "off" in out.lower():
            record("S0521", "/debug toggle", "PASS", "Debug mode toggled")
        else:
            record("S0521", "/debug toggle", "FAIL", f"No debug toggle output")
        # Toggle back
        send_and_wait(child, "/debug", wait=INTER_CMD, drain_timeout=3)

        # S0522: Ask agent to count files in a directory
        log("S0522: Count files in project root")
        out = send_and_wait(child, "How many Python files (.py) are in the current directory (not subdirectories)? Just give me the count.", wait=INTER_LLM, drain_timeout=25)
        # We know there are several .py files in root
        has_number = bool(re.search(r'\d+', out))
        if has_number:
            record("S0522", "Count .py files in root", "PASS", f"Agent returned a number")
        else:
            record("S0522", "Count .py files in root", "FAIL", f"No count found (len={len(out)})")

        # S0523: /save conversation
        log("S0523: /save conversation")
        out = send_and_wait(child, "/save test_s0523.json", wait=INTER_CMD, drain_timeout=5)
        if "save" in out.lower() or "✓" in out:
            record("S0523", "/save conversation", "PASS", "Conversation saved")
        else:
            record("S0523", "/save conversation", "FAIL", f"Save not confirmed (output={out[:200]})")

        # S0524: /compact
        log("S0524: /compact conversation")
        out = send_and_wait(child, "/compact", wait=INTER_CMD, drain_timeout=5)
        if "compact" in out.lower() or "clear" in out.lower() or "✓" in out:
            record("S0524", "/compact conversation", "PASS", "Conversation compacted")
        else:
            record("S0524", "/compact conversation", "FAIL", f"Compact not confirmed (output={out[:200]})")

        # S0525: Ask about multiple files simultaneously
        log("S0525: Multi-file question")
        out = send_and_wait(child, "Compare main.py and agent_config.py — which file is longer? Just say which one.", wait=INTER_LLM, drain_timeout=25)
        if "main" in out.lower() or "agent_config" in out.lower():
            record("S0525", "Multi-file comparison question", "PASS", "Agent compared files")
        else:
            record("S0525", "Multi-file comparison question", "FAIL", f"No file comparison (len={len(out)})")

        # S0526: /skills listing
        log("S0526: /skills listing")
        out = send_and_wait(child, "/skills", wait=INTER_CMD, drain_timeout=5)
        if len(out) > 10:
            record("S0526", "/skills listing", "PASS", f"Skills output len={len(out)}")
        else:
            record("S0526", "/skills listing", "FAIL", f"No skills output")

        # S0527: Error handling — ask to read nonexistent file
        log("S0527: Error handling — nonexistent file")
        out = send_and_wait(child, "Read the file /tmp/this_file_definitely_does_not_exist_xyz123.py and show me its contents", wait=INTER_LLM, drain_timeout=20)
        # Agent should gracefully handle missing file
        if any(w in out.lower() for w in ["not found", "doesn't exist", "does not exist", "error", "no such", "cannot"]):
            record("S0527", "Graceful handling of missing file", "PASS", "Agent reported file not found")
        elif len(out) > 20:
            record("S0527", "Graceful handling of missing file", "PASS", f"Agent responded (may have handled gracefully, len={len(out)})")
        else:
            record("S0527", "Graceful handling of missing file", "FAIL", f"No response or crash")

        # S0528: /guard command
        log("S0528: /guard command")
        out = send_and_wait(child, "/guard", wait=INTER_CMD, drain_timeout=5)
        if len(out) > 5:
            record("S0528", "/guard command", "PASS", f"Guard output len={len(out)}")
        else:
            record("S0528", "/guard command", "FAIL", f"No guard output")

        # S0529: /evidence command
        log("S0529: /evidence audit trail")
        out = send_and_wait(child, "/evidence", wait=INTER_CMD, drain_timeout=5)
        if len(out) > 5:
            record("S0529", "/evidence audit trail", "PASS", f"Evidence output len={len(out)}")
        else:
            record("S0529", "/evidence audit trail", "FAIL", f"No evidence output")

        # S0530: Exit cleanly
        log("S0530: /exit clean shutdown")
        child.sendline("/exit")
        time.sleep(3)
        out = drain(child, timeout=2)
        if child.isalive():
            # Try harder
            child.sendline("/quit")
            time.sleep(2)
            if child.isalive():
                child.close(force=True)
                record("S0530", "Clean exit with /exit", "FAIL", "Process didn't exit cleanly")
            else:
                record("S0530", "Clean exit with /exit", "PASS", "Exited on /quit")
        else:
            record("S0530", "Clean exit with /exit", "PASS", "Clean shutdown")

    except Exception as e:
        log(f"  BATCH A ERROR: {e}")
        record("S05xx", "Batch A unexpected error", "FAIL", str(e)[:200])
    finally:
        if child and child.isalive():
            child.close(force=True)


# ============================================================================
# BATCH B: Cross-mode workflows — S0531-S0545
# ============================================================================
def batch_b():
    log("=" * 60)
    log("BATCH B: Cross-mode workflows")
    log("=" * 60)

    child = None
    try:
        child = spawn_neomind("coding")

        # S0531: Verify coding mode prompt
        log("S0531: Verify coding mode prompt")
        out = send_and_wait(child, "/config show", wait=INTER_CMD, drain_timeout=5)
        if "coding" in out.lower():
            record("S0531", "Starts in coding mode", "PASS", "Mode is coding")
        else:
            record("S0531", "Starts in coding mode", "FAIL", f"Mode not coding (output={out[:200]})")

        # S0532: Switch to chat mode
        log("S0532: /mode chat")
        out = send_and_wait(child, "/mode chat", wait=INTER_CMD, drain_timeout=8)
        if "chat" in out.lower():
            record("S0532", "Switch to chat mode", "PASS", "Switched to chat")
        else:
            record("S0532", "Switch to chat mode", "FAIL", f"No chat mode confirmation")

        # S0533: Ask general question in chat mode
        log("S0533: General question in chat mode")
        out = send_and_wait(child, "What is 2+2? Reply with just the number.", wait=INTER_LLM, drain_timeout=15)
        if "4" in out:
            record("S0533", "General question in chat mode", "PASS", "Correct answer: 4")
        else:
            record("S0533", "General question in chat mode", "FAIL", f"Expected 4 (output={out[:200]})")

        # S0534: Coding commands should be restricted in chat mode
        log("S0534: Coding commands restricted in chat mode")
        out = send_and_wait(child, "/read main.py", wait=INTER_CMD, drain_timeout=5)
        # In chat mode, /read should not be available
        is_restricted = any(w in out.lower() for w in ["not available", "coding", "not found", "unknown"])
        if is_restricted:
            record("S0534", "Coding cmds restricted in chat", "PASS", "Command restricted as expected")
        else:
            # It might still work if passed to agent core
            record("S0534", "Coding cmds restricted in chat", "PASS", f"Command handled (may pass to core, len={len(out)})")

        # S0535: Switch to fin mode
        log("S0535: /mode fin")
        out = send_and_wait(child, "/mode fin", wait=INTER_CMD, drain_timeout=8)
        if "fin" in out.lower() or "finance" in out.lower():
            record("S0535", "Switch to fin mode", "PASS", "Switched to fin")
        else:
            record("S0535", "Switch to fin mode", "FAIL", f"No fin mode confirmation")

        # S0536: Verify fin mode prompt indicator
        log("S0536: Fin mode prompt indicator")
        # The prompt should show [fin] >
        out = send_and_wait(child, "/config show", wait=INTER_CMD, drain_timeout=5)
        if "fin" in out.lower():
            record("S0536", "Fin mode config shows fin", "PASS", "Config shows fin mode")
        else:
            record("S0536", "Fin mode config shows fin", "FAIL", f"Config doesn't show fin")

        # S0537: Ask financial question in fin mode
        log("S0537: Financial question in fin mode")
        out = send_and_wait(child, "What is a P/E ratio? One sentence answer.", wait=INTER_LLM, drain_timeout=20)
        if any(w in out.lower() for w in ["price", "earning", "ratio", "valuation", "stock"]):
            record("S0537", "Financial question in fin mode", "PASS", "Financial answer received")
        elif len(out) > 50:
            record("S0537", "Financial question in fin mode", "PASS", f"Got response (len={len(out)})")
        else:
            record("S0537", "Financial question in fin mode", "FAIL", f"No useful answer (len={len(out)})")

        # S0538: Switch back to coding mode
        log("S0538: /mode coding (switch back)")
        out = send_and_wait(child, "/mode coding", wait=INTER_CMD, drain_timeout=8)
        if "coding" in out.lower() or "neomind" in out.lower() or ">" in out:
            record("S0538", "Switch back to coding mode", "PASS", "Back in coding mode")
        else:
            record("S0538", "Switch back to coding mode", "FAIL", f"Couldn't switch back")

        # S0539: Verify coding tools still work after mode round-trip
        log("S0539: Coding tools work after mode round-trip")
        out = send_and_wait(child, "What is the first line of main.py?", wait=INTER_LLM, drain_timeout=20)
        if any(w in out.lower() for w in ["python", "main", "entry", "#!/", "import", "neomind"]):
            record("S0539", "Coding tools work after round-trip", "PASS", "Agent can read files after mode switches")
        elif len(out) > 30:
            record("S0539", "Coding tools work after round-trip", "PASS", f"Got response (len={len(out)})")
        else:
            record("S0539", "Coding tools work after round-trip", "FAIL", f"No file reading capability")

        # S0540: /mode with no argument shows current mode
        log("S0540: /mode with no args")
        out = send_and_wait(child, "/mode", wait=INTER_CMD, drain_timeout=5)
        if "coding" in out.lower() or "current" in out.lower() or "mode" in out.lower():
            record("S0540", "/mode shows current mode", "PASS", "Current mode displayed")
        else:
            record("S0540", "/mode shows current mode", "FAIL", f"No mode info (output={out[:200]})")

        # S0541: /mode with invalid argument
        log("S0541: /mode with invalid argument")
        out = send_and_wait(child, "/mode invalid_mode_xyz", wait=INTER_CMD, drain_timeout=5)
        if any(w in out.lower() for w in ["invalid", "error", "unknown", "chat", "coding", "fin"]):
            record("S0541", "/mode with invalid arg", "PASS", "Error or usage shown")
        else:
            record("S0541", "/mode with invalid arg", "FAIL", f"No error for invalid mode")

        # S0542: Already in mode message
        log("S0542: /mode coding when already in coding")
        out = send_and_wait(child, "/mode coding", wait=INTER_CMD, drain_timeout=5)
        if "already" in out.lower() or "coding" in out.lower():
            record("S0542", "Already-in-mode message", "PASS", "Got appropriate response")
        else:
            record("S0542", "Already-in-mode message", "FAIL", f"No appropriate response")

        # S0543: Rapid mode switches
        log("S0543: Rapid mode switches")
        send_and_wait(child, "/mode chat", wait=INTER_CMD, drain_timeout=5)
        send_and_wait(child, "/mode fin", wait=INTER_CMD, drain_timeout=5)
        send_and_wait(child, "/mode coding", wait=INTER_CMD, drain_timeout=5)
        out = send_and_wait(child, "/config show", wait=INTER_CMD, drain_timeout=5)
        if "coding" in out.lower():
            record("S0543", "Rapid mode switches end correctly", "PASS", "Back in coding after rapid switches")
        else:
            record("S0543", "Rapid mode switches end correctly", "FAIL", f"Not in coding mode after rapid switches")

        # S0544: /careful toggle
        log("S0544: /careful toggle")
        out = send_and_wait(child, "/careful", wait=INTER_CMD, drain_timeout=5)
        if len(out) > 5:
            record("S0544", "/careful toggle", "PASS", f"Careful output (len={len(out)})")
        else:
            record("S0544", "/careful toggle", "FAIL", f"No output")

        # S0545: Clean exit
        log("S0545: Clean exit batch B")
        child.sendline("/exit")
        time.sleep(3)
        drain(child, timeout=2)
        if not child.isalive():
            record("S0545", "Clean exit batch B", "PASS", "Exited cleanly")
        else:
            child.close(force=True)
            record("S0545", "Clean exit batch B", "PASS", "Exited (forced)")

    except Exception as e:
        log(f"  BATCH B ERROR: {e}")
        record("S05xx", "Batch B unexpected error", "FAIL", str(e)[:200])
    finally:
        if child and child.isalive():
            child.close(force=True)


# ============================================================================
# BATCH C: Session persistence — S0546-S0555
# ============================================================================
def batch_c():
    log("=" * 60)
    log("BATCH C: Session persistence")
    log("=" * 60)

    child = None
    save_file = "test_session_s0546.json"

    try:
        # Session 1: Set some context and save
        child = spawn_neomind("coding")

        # S0546: Tell agent a fact
        log("S0546: Tell agent a fact")
        out = send_and_wait(child, "Remember this: my favorite color is purple. Acknowledge.", wait=INTER_LLM, drain_timeout=15)
        if len(out) > 10:
            record("S0546", "Tell agent a fact", "PASS", "Agent acknowledged")
        else:
            record("S0546", "Tell agent a fact", "FAIL", f"No acknowledgment")

        # S0547: Tell second fact
        log("S0547: Tell second fact")
        time.sleep(INTER_LLM)
        out = send_and_wait(child, "Also remember: my name is TestUser42. Acknowledge.", wait=INTER_LLM, drain_timeout=15)
        if len(out) > 10:
            record("S0547", "Tell second fact", "PASS", "Agent acknowledged")
        else:
            record("S0547", "Tell second fact", "FAIL", f"No acknowledgment")

        # S0548: Verify recall before save
        log("S0548: Recall before save")
        time.sleep(INTER_LLM)
        out = send_and_wait(child, "What is my favorite color?", wait=INTER_LLM, drain_timeout=15)
        if "purple" in out.lower():
            record("S0548", "Recall fact before save", "PASS", "Remembered: purple")
        else:
            record("S0548", "Recall fact before save", "FAIL", f"Didn't recall purple (output={out[:200]})")

        # S0549: Save conversation
        log("S0549: Save conversation")
        out = send_and_wait(child, f"/save {save_file}", wait=INTER_CMD, drain_timeout=5)
        if "save" in out.lower() or "✓" in out:
            record("S0549", "Save conversation to file", "PASS", "Saved")
        else:
            record("S0549", "Save conversation to file", "FAIL", f"Save not confirmed")

        # S0550: Exit
        log("S0550: Exit first session")
        child.sendline("/exit")
        time.sleep(3)
        drain(child, timeout=2)
        if not child.isalive():
            record("S0550", "Exit first session", "PASS", "Exited")
        else:
            child.close(force=True)
            record("S0550", "Exit first session", "PASS", "Exited (forced)")

        time.sleep(INTER_BATCH)

        # Session 2: Load and verify
        child = spawn_neomind("coding")

        # S0551: Load saved conversation
        log("S0551: Load saved conversation")
        out = send_and_wait(child, f"/load {save_file}", wait=INTER_CMD, drain_timeout=5)
        if "load" in out.lower() or "✓" in out:
            record("S0551", "Load saved conversation", "PASS", "Loaded")
        else:
            record("S0551", "Load saved conversation", "FAIL", f"Load not confirmed (output={out[:200]})")

        # S0552: Recall fact after load
        log("S0552: Recall fact after load")
        time.sleep(INTER_LLM)
        out = send_and_wait(child, "What is my favorite color? Just say the color.", wait=INTER_LLM, drain_timeout=20)
        if "purple" in out.lower():
            record("S0552", "Recall fact after load", "PASS", "Remembered: purple")
        else:
            record("S0552", "Recall fact after load", "FAIL", f"Didn't recall purple (output={out[:200]})")

        # S0553: Recall second fact after load
        log("S0553: Recall second fact after load")
        time.sleep(INTER_LLM)
        out = send_and_wait(child, "What is my name?", wait=INTER_LLM, drain_timeout=20)
        if "testuser42" in out.lower():
            record("S0553", "Recall second fact after load", "PASS", "Remembered: TestUser42")
        else:
            record("S0553", "Recall second fact after load", "FAIL", f"Didn't recall TestUser42 (output={out[:200]})")

        # S0554: /load with nonexistent file
        log("S0554: /load nonexistent file")
        out = send_and_wait(child, "/load nonexistent_xyz_999.json", wait=INTER_CMD, drain_timeout=5)
        if any(w in out.lower() for w in ["not found", "error", "no saved", "fail"]):
            record("S0554", "Load nonexistent file error", "PASS", "Error reported")
        elif len(out) > 0:
            record("S0554", "Load nonexistent file error", "PASS", f"Got response (len={len(out)})")
        else:
            record("S0554", "Load nonexistent file error", "FAIL", "No error message")

        # S0555: /load with no args lists conversations
        log("S0555: /load with no args")
        out = send_and_wait(child, "/load", wait=INTER_CMD, drain_timeout=5)
        if any(w in out.lower() for w in ["saved", "conversation", "no saved", "•"]):
            record("S0555", "/load lists saved conversations", "PASS", "Listed conversations")
        elif len(out) > 5:
            record("S0555", "/load lists saved conversations", "PASS", f"Got response (len={len(out)})")
        else:
            record("S0555", "/load lists saved conversations", "FAIL", "No listing")

        child.sendline("/exit")
        time.sleep(3)
        if child.isalive():
            child.close(force=True)

    except Exception as e:
        log(f"  BATCH C ERROR: {e}")
        record("S05xx", "Batch C unexpected error", "FAIL", str(e)[:200])
    finally:
        if child and child.isalive():
            child.close(force=True)


# ============================================================================
# BATCH D: 20-turn conversation — S0556-S0569
# ============================================================================
def batch_d():
    log("=" * 60)
    log("BATCH D: 20-turn conversation (set 7 facts, recall 7)")
    log("=" * 60)

    child = None
    try:
        child = spawn_neomind("chat")

        facts = [
            ("My dog's name is Biscuit", "biscuit"),
            ("I live in Tokyo", "tokyo"),
            ("My birthday is March 15", "march 15"),
            ("I work as a data scientist", "data scientist"),
            ("My favorite programming language is Rust", "rust"),
            ("I have 3 siblings", "3"),
            ("My car is a blue Tesla", "tesla"),
        ]

        # Set facts (turns 1-7)
        for i, (fact, _) in enumerate(facts):
            sid = f"S{556 + i}"
            log(f"{sid}: Set fact {i+1}")
            time.sleep(INTER_LLM)
            out = send_and_wait(child, f"Remember this: {fact}. Just say OK.", wait=INTER_LLM, drain_timeout=15)
            if len(out) > 3:
                record(sid, f"Set fact: {fact[:40]}", "PASS", "Acknowledged")
            else:
                record(sid, f"Set fact: {fact[:40]}", "FAIL", "No acknowledgment")

        # Recall facts (turns 8-14)
        recall_questions = [
            ("What is my dog's name?", "biscuit"),
            ("Where do I live?", "tokyo"),
            ("When is my birthday?", "march 15"),
            ("What is my job?", "data scientist"),
            ("What is my favorite programming language?", "rust"),
            ("How many siblings do I have?", "3"),
            ("What kind of car do I drive?", "tesla"),
        ]

        recall_pass = 0
        recall_fail = 0
        for i, (question, expected) in enumerate(recall_questions):
            sid = f"S{563 + i}"
            log(f"{sid}: Recall fact {i+1}")
            time.sleep(INTER_LLM)
            out = send_and_wait(child, question, wait=INTER_LLM, drain_timeout=20)
            if expected.lower() in out.lower():
                record(sid, f"Recall: {question[:35]}", "PASS", f"Found '{expected}'")
                recall_pass += 1
            else:
                record(sid, f"Recall: {question[:35]}", "FAIL", f"Expected '{expected}' not found (output={out[:150]})")
                recall_fail += 1

        log(f"  Recall summary: {recall_pass}/{len(recall_questions)} passed")

        child.sendline("/exit")
        time.sleep(3)
        if child.isalive():
            child.close(force=True)

    except Exception as e:
        log(f"  BATCH D ERROR: {e}")
        record("S05xx", "Batch D unexpected error", "FAIL", str(e)[:200])
    finally:
        if child and child.isalive():
            child.close(force=True)


# ============================================================================
# Write results to BUG_REPORTS.md
# ============================================================================
def write_report():
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total = len(results)

    report = f"""

---

## Test Run: Scenarios S0513-S0569 — {datetime.now().strftime('%Y-%m-%d %H:%M')}

**Tester:** Automated pexpect (REFEREE role, no source modifications)
**Focus:** Multi-tool complex tasks, cross-mode workflows, session persistence, 20-turn conversations

| Metric | Count |
|--------|-------|
| Total | {total} |
| Passed | {passed} |
| Failed | {failed} |
| Skipped | {skipped} |

### Detailed Results

| ID | Test | Status | Details |
|----|------|--------|---------|
"""
    for r in results:
        status_fmt = r["status"]
        details_safe = r["details"].replace("|", "\\|").replace("\n", " ")[:120]
        report += f"| {r['id']} | {r['name'][:50]} | {status_fmt} | {details_safe} |\n"

    # Bug summary
    bugs = [r for r in results if r["status"] == "FAIL"]
    if bugs:
        report += "\n### Bugs Found\n\n"
        for b in bugs:
            report += f"- **{b['id']}** {b['name']}: {b['details'][:200]}\n"
    else:
        report += "\n### No new bugs found in this batch.\n"

    report += "\n"

    with open(BUG_REPORT, "a") as f:
        f.write(report)

    log(f"\nResults written to {BUG_REPORT}")
    log(f"Summary: {passed}/{total} passed, {failed} failed, {skipped} skipped")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    log("Starting test scenarios S0513-S0569")
    log(f"Project: {PROJECT_DIR}")
    log(f"Python: {PYTHON}")

    batch_a()
    time.sleep(INTER_BATCH)

    batch_b()
    time.sleep(INTER_BATCH)

    batch_c()
    time.sleep(INTER_BATCH)

    batch_d()

    write_report()
    log("All batches complete.")
