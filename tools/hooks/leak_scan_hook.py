#!/usr/bin/env python3
"""Claude Code PreToolUse hook — block git commit/push if gitleaks finds secrets.

Background: 2026-04-24 incident — a shallow pre-push leak scan reported clean
but a deep agent-driven scan turned up 250 commits with the user's email +
home hostname in author metadata, plus an email leaked in a feature branch
and `/Users/<user>/` paths in working-tree files. All would have gone public.
The user's standing rule: personal data safety is top priority, run a full-
repo + full-history scan before any commit/push/upload.

This hook intercepts Bash tool calls running `git commit` or `git push` and
runs gitleaks before letting the operation proceed. Findings → exit 2 (block).

Behavior:
- `git commit ...`     → `gitleaks protect --staged` on the index
- `git push ...`       → `gitleaks detect` on full history + author metadata check
                         on the commits about to be pushed (origin/<branch>..HEAD)

Bypass for emergencies:
  NEOMIND_ALLOW_LEAKS=1 git push ...

If gitleaks isn't installed, the hook blocks and tells the user how to
install it. Fail-closed because that's the whole point of the hook.
"""
from __future__ import annotations
import json
import os
import re
import shlex
import shutil
import subprocess
import sys


# Sensitive author identifiers — reported by user 2026-04-24. Updated when
# new identifiers come up. These are checked against `git log --pretty='%ae|%ce'`
# of commits about to be pushed.
LEAKY_AUTHOR_PATTERNS = [
    r"ikol1729@gmail\.com",
    r"irenez202021@gmail\.com",
    r"paomian_kong@",                  # mac username + hostname
    r"paomian-kongdeMac",              # hostname literal
    r"@paomian-kongdeMac",             # full author@host form
]

# .gitleaks.toml config in the repo root if present, else use defaults
GITLEAKS_CONFIG = os.path.join(
    os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    ".gitleaks.toml",
)


def _git_invocations(cmd: str) -> list[list[str]]:
    """Return every actual `git <subcommand> ...` invocation in the command.

    Uses shlex so text inside single/double quotes (echo "git push", grep
    'git commit', JSON payloads, etc.) is NOT counted as an invocation.
    Returns a list of token-lists, one per `git` invocation found.
    """
    try:
        tokens = shlex.posix_split(cmd) if hasattr(shlex, "posix_split") else shlex.split(cmd, posix=True)
    except ValueError:
        # Unbalanced quotes — fall back to permissive substring scan
        return [["git"] + cmd.split()] if "git " in cmd else []
    # Strip leading `cd path &&` / `cd path; ` prefixes by splitting on
    # bash separators (which shlex preserves as their own tokens).
    SEPARATORS = {"&&", "||", ";", "|", "&"}
    runs = []
    current = []
    for tok in tokens:
        if tok in SEPARATORS:
            if current:
                runs.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        runs.append(current)
    invocations = []
    for run in runs:
        # First token of each run is the executable. We only count `git`
        # itself — `cd /tmp && git push` becomes two runs, the second
        # starting with `git`.
        if run and run[0] == "git" and len(run) >= 2:
            invocations.append(run)
    return invocations


def is_git_commit(cmd: str) -> bool:
    """True when an actual `git commit` invocation is present (no false
    positives from `echo 'git commit'` or `git commit-tree`)."""
    for inv in _git_invocations(cmd):
        sub = inv[1] if len(inv) > 1 else ""
        if sub == "commit":
            return True
    return False


def is_git_push(cmd: str) -> bool:
    """True when an actual `git push` invocation is present."""
    for inv in _git_invocations(cmd):
        sub = inv[1] if len(inv) > 1 else ""
        if sub == "push":
            return True
    return False


def is_force_push_to_main(cmd: str) -> bool:
    """True when an actual `git push` invocation includes --force AND main/master."""
    for inv in _git_invocations(cmd):
        if len(inv) < 2 or inv[1] != "push":
            continue
        rest = inv[2:]
        has_force = any(tok in ("-f", "--force", "--force-with-lease") for tok in rest)
        targets_main = any(tok in ("main", "master") for tok in rest)
        if has_force and targets_main:
            return True
    return False


def run(cmd_list, **kwargs) -> tuple[int, str, str]:
    """Run subprocess, return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=120, **kwargs,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def have_gitleaks() -> bool:
    return shutil.which("gitleaks") is not None


def scan_staged() -> tuple[bool, str]:
    """Run gitleaks on the staged index. Return (clean?, message)."""
    args = ["gitleaks", "protect", "--staged", "--no-banner", "--redact"]
    if os.path.exists(GITLEAKS_CONFIG):
        args.extend(["--config", GITLEAKS_CONFIG])
    rc, out, err = run(args)
    if rc == 0:
        return True, ""
    # gitleaks exits 1 when leaks found
    return False, (out + err)[:2000]


def scan_full_history() -> tuple[bool, str]:
    """Run gitleaks on the full repo history. Return (clean?, message)."""
    args = ["gitleaks", "detect", "--no-banner", "--redact"]
    if os.path.exists(GITLEAKS_CONFIG):
        args.extend(["--config", GITLEAKS_CONFIG])
    rc, out, err = run(args)
    if rc == 0:
        return True, ""
    return False, (out + err)[:2000]


def scan_push_authors(cmd: str) -> tuple[bool, str]:
    """Check author + committer emails on the commits about to be pushed.

    Uses `git log @{u}..HEAD --pretty='%ae|%ce'` for the upstream's perspective.
    Falls back to `git log -50` if no upstream is set.
    """
    rc, out, _ = run(["git", "log", "@{u}..HEAD", "--pretty=%ae|%ce"])
    if rc != 0:
        # No upstream tracked — scan recent 50 commits as a safety floor
        rc, out, _ = run(["git", "log", "-50", "--pretty=%ae|%ce"])
        if rc != 0:
            return True, ""  # Can't introspect; let it through (gitleaks already ran)
    leaky = []
    for line in out.splitlines():
        for pat in LEAKY_AUTHOR_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                leaky.append(f"  - {line.strip()}  (matched: {pat})")
                break
    if leaky:
        return False, "Leaky author/committer metadata in pending commits:\n" + "\n".join(leaky[:20])
    return True, ""


def emit_block(reason: str, details: str = "", cmd: str = "") -> int:
    msg = (
        f"\n🔒 BLOCKED: pre-{reason} leak scan failed\n"
        f"\n"
        f"{details}\n"
        f"\n"
        f"Memory rule (feedback_personal_data_safety_first.md): personal "
        f"data safety is top priority — every commit/push must clear a full-"
        f"repo + full-history scan before going through.\n"
        f"\n"
        f"Bypass (only after manual verification):\n"
        f"  NEOMIND_ALLOW_LEAKS=1 {cmd[:200]}\n"
        f"\n"
        f"If a finding is a known false positive, add it to .gitleaks.toml's\n"
        f"[allowlist] section instead of bypassing.\n"
    )
    print(msg, file=sys.stderr)
    return 2


def main() -> int:
    if os.environ.get("NEOMIND_ALLOW_LEAKS"):
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    is_commit = is_git_commit(cmd)
    is_push = is_git_push(cmd)
    if not (is_commit or is_push):
        return 0

    # Refuse force-push to main outright unless bypassed
    if is_force_push_to_main(cmd):
        return emit_block(
            "push",
            "🚨 force-push to main/master detected. This rewrites public "
            "history and cannot be undone. If you genuinely need to do this, "
            "set NEOMIND_ALLOW_LEAKS=1 explicitly.",
            cmd,
        )

    if not have_gitleaks():
        return emit_block(
            "commit/push" if is_commit else "push",
            "gitleaks not installed. Run:\n  brew install gitleaks\nThen retry.",
            cmd,
        )

    # 1. Staged-content scan (commits) or full-history scan (pushes).
    if is_commit:
        clean, finding = scan_staged()
        if not clean:
            return emit_block("commit", finding, cmd)
    else:  # is_push
        clean, finding = scan_full_history()
        if not clean:
            return emit_block("push", finding, cmd)

    # 2. Author metadata check on pushes (this is what the 2026-04-24 incident missed).
    if is_push:
        clean, finding = scan_push_authors(cmd)
        if not clean:
            return emit_block("push", finding, cmd)

    return 0


if __name__ == "__main__":
    sys.exit(main())
