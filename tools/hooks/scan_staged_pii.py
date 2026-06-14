#!/usr/bin/env python3
"""Personal-data / PII guard for git hooks.

Blocks a commit / push when the *added* lines contain the owner's private
data: real holdings, identity, home-dir username, Telegram bot handle, or
specific financial situation.

The real match patterns live OUTSIDE any repo, in
    ~/.neomind/fin/pii_patterns.txt   (gitignored — never committed)
so this committed hook code stays PII-free. A small generic BASELINE below
catches the obvious shapes even on a fresh clone without that file.

Modes:
    scan_staged_pii.py staged          # scan `git diff --cached`  (pre-commit)
    scan_staged_pii.py diff <A>..<B>   # scan `git diff <A>..<B>`  (pre-push)

Bypass once (only if you are SURE it's a false positive):
    NEOMIND_ALLOW_PERSONAL=1 git commit ...
    NEOMIND_ALLOW_PERSONAL=1 git push ...
"""
import os
import re
import subprocess
import sys

LOCAL_PATTERNS = os.path.expanduser("~/.neomind/fin/pii_patterns.txt")

# Generic, high-signal SHAPES only — safe in this public file because they are
# regexes, not actual personal values (so this file never self-flags). The
# specific values (real tickers, bot handle, email, etc.) live ONLY in the
# gitignored local file above, which persists in the home dir across clones.
BASELINE = [
    r"/Users/[A-Za-z0-9._-]*kong",     # personal home path (OS username)
    r"[0-9]+ ?股 ?@ ?\$[0-9]",     # real position notation: "N 股 @ $X"
]


def load_patterns():
    pats = list(BASELINE)
    try:
        with open(LOCAL_PATTERNS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line)
    except FileNotFoundError:
        pass
    return pats


def diff_text(mode, args):
    if mode == "staged":
        cmd = ["git", "diff", "--cached", "-U0"]
    elif mode == "diff" and args:
        cmd = ["git", "diff", "-U0", args[0]]
    else:
        return ""
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def main():
    if os.environ.get("NEOMIND_ALLOW_PERSONAL"):
        sys.stderr.write("[pii-guard] BYPASS (NEOMIND_ALLOW_PERSONAL=1) — not scanning.\n")
        return 0

    mode = sys.argv[1] if len(sys.argv) > 1 else "staged"
    text = diff_text(mode, sys.argv[2:])

    # only newly-added content (lines starting with a single '+')
    added = [ln[1:] for ln in text.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    body = "\n".join(added)

    hits = []
    for raw in load_patterns():
        try:
            rx = re.compile(raw, re.IGNORECASE)
        except re.error:
            continue
        m = rx.search(body)
        if m:
            hits.append((raw, m.group(0)[:70]))

    if hits:
        sys.stderr.write(
            "\n\U0001f6ab [pii-guard] BLOCKED — private/financial data detected in this change:\n")
        seen = set()
        for raw, sample in hits:
            if (raw, sample) in seen:
                continue
            seen.add((raw, sample))
            sys.stderr.write(f"     /{raw}/   ->   {sample!r}\n")
        sys.stderr.write(
            "\n  This guard keeps your real holdings / identity / financial info out of\n"
            "  a (public) remote. Move the personal bits to a local-only file\n"
            "  (e.g. ~/neomind-local-plans/), or scrub them, then re-commit.\n"
            "  Sure it's a false positive? bypass once:\n"
            "     NEOMIND_ALLOW_PERSONAL=1 git commit ...   (or git push ...)\n\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
