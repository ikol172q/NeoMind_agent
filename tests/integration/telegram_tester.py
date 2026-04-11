#!/usr/bin/env python3
"""
NeoMind Telegram Bot Tester — sends real messages as YOU and reads bot replies.

Uses Telethon (a real Telegram MTProto client). The first run prompts for an
SMS code; subsequent runs reuse the auth session file.

This is the canonical Telegram tester driver. It is imported by:

  - tester subagents during per-commit validation gates
  - comprehensive validation scenarios under tests/qa_archive/plans/
  - the NeoMind runtime `telegram-selftest` skill (via Mailbox workers)

Role contract (non-negotiable):
  - This module is a TESTER. It NEVER modifies source code.
  - It only sends real messages to @neomindagent_bot and reports verdicts.
  - Subagents using this module must have "read-only under agent/ and tests/"
    enforcement via their prompt; fixer agents never touch this driver.

Setup:
  1. Get api_id + api_hash from https://my.telegram.org
  2. Save to ~/.config/neomind-tester/telethon.env with:
        TG_API_ID=...
        TG_API_HASH=...
        TG_PHONE=+1...
        TG_BOT_USERNAME=@neomindagent_bot
  3. .venv/bin/pip install telethon (already installed in neo venv)
  4. .venv/bin/python -m tests.integration.telegram_tester
     .venv/bin/python -m tests.integration.telegram_tester --plan smoke

Built-in plans (small quick-tests only; the authoritative
comprehensive suite lives in tests/qa_archive/plans/
2026-04-10_telegram_validation_v1.py):
  smoke   — 8 quick scenarios, ~2 min
  models  — test /model command + every router model
  modes   — test /mode chat/coding/fin switches
  long    — 50-turn endurance run
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# ── Load credentials ──────────────────────────────────────────────
ENV_FILE = Path.home() / ".config" / "neomind-tester" / "telethon.env"
if not ENV_FILE.exists():
    print(f"❌ {ENV_FILE} not found.", file=sys.stderr)
    print("   See header of this script for setup instructions.", file=sys.stderr)
    sys.exit(2)

env = {}
for line in ENV_FILE.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

API_ID = int(env.get("TG_API_ID", "0"))
API_HASH = env.get("TG_API_HASH", "")
PHONE = env.get("TG_PHONE", "")
BOT_USERNAME = env.get("TG_BOT_USERNAME", "")

if not (API_ID and API_HASH and PHONE and BOT_USERNAME):
    print("❌ Missing required keys in env file. Need: TG_API_ID, TG_API_HASH, TG_PHONE, TG_BOT_USERNAME", file=sys.stderr)
    sys.exit(2)

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import Message
except ImportError:
    print("❌ telethon not installed. Run: pip3 install telethon", file=sys.stderr)
    sys.exit(2)

SESSION_FILE = str(Path.home() / ".config" / "neomind-tester" / "session")


# ── Test plans ────────────────────────────────────────────────────

SMOKE_PLAN = [
    {"send": "/start", "wait": 10, "expect_any": ["NeoMind", "neomind", "你好", "ready"]},
    {"send": "你好", "wait": 60, "expect_any": ["你好", "Hello", "NeoMind"]},
    {"send": "/status", "wait": 15, "expect_any": ["mode", "Router", "router", "状态", "🤖", "model"]},
    {"send": "/model", "wait": 15, "expect_any": ["deepseek", "kimi", "glm", "model"]},
    {"send": "Reply with just the number: 17*23=?", "wait": 90, "expect_any": ["391"]},
    {"send": "/mode fin", "wait": 10, "expect_any": ["fin"]},
    {"send": "什么是ETF? 不要搜索, 直接告诉我.", "wait": 90, "expect_any": ["ETF", "基金", "fund", "exchange"]},
    {"send": "/clear", "wait": 15, "expect_any": ["清空", "clear", "✓", "已"]},
]

MODELS_PLAN = [
    {"send": "/model", "wait": 5, "expect_any": ["deepseek-chat"]},
    {"send": "/model deepseek-chat", "wait": 5, "expect_any": ["deepseek-chat", "✅"]},
    {"send": "What is 2+2? One word.", "wait": 25, "expect_any": ["4"]},
    {"send": "/model glm-5", "wait": 5, "expect_any": ["glm-5", "✅"]},
    {"send": "What is 3+3? One word.", "wait": 25, "expect_any": ["6"]},
    {"send": "/model kimi-k2.5", "wait": 5, "expect_any": ["kimi-k2.5", "✅"]},
    {"send": "What is 5+5? One word.", "wait": 30, "expect_any": ["10"]},
    {"send": "/model deepseek-reasoner", "wait": 5, "expect_any": ["deepseek-reasoner", "✅"]},
    {"send": "What is 7+7?", "wait": 40, "expect_any": ["14"]},
    {"send": "/model deepseek-chat", "wait": 5, "expect_any": ["deepseek-chat", "✅"]},
]

MODES_PLAN = [
    {"send": "/mode chat", "wait": 5, "expect_any": ["chat"]},
    {"send": "Tell me a one-line joke", "wait": 30, "expect_any": [""]},
    {"send": "/mode coding", "wait": 5, "expect_any": ["coding"]},
    {"send": "Write a Python one-liner to reverse a string", "wait": 30, "expect_any": ["[::-1]", "reverse"]},
    {"send": "/mode fin", "wait": 5, "expect_any": ["fin"]},
    {"send": "什么是市盈率?", "wait": 30, "expect_any": ["市盈率", "PE"]},
]


# ── Tester ────────────────────────────────────────────────────────

class TelegramBotTester:
    def __init__(self, client: TelegramClient, bot_username: str):
        self.client = client
        self.bot_username = bot_username
        self._last_msg_id = 0

    async def warmup(self):
        """Resolve the bot entity and snapshot last message id."""
        self.bot = await self.client.get_entity(self.bot_username)
        # Get the most recent message id so we know what's "new"
        async for m in self.client.iter_messages(self.bot, limit=1):
            self._last_msg_id = m.id
            break

    async def drain_until_quiet(self, quiet_seconds: float = 6.0, max_wait: float = 60.0):
        """Wait until the bot stops sending us anything for `quiet_seconds`.

        Used between test steps to ensure late replies from a slow previous
        handler don't bleed into the next step's reply window. Caller should
        snapshot _last_msg_id BEFORE sending the next message.
        """
        deadline = time.time() + max_wait
        last_id_seen = self._last_msg_id
        last_change = time.time()
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            async for m in self.client.iter_messages(self.bot, limit=1):
                if m.id > last_id_seen:
                    last_id_seen = m.id
                    last_change = time.time()
                break
            if (time.time() - last_change) >= quiet_seconds:
                self._last_msg_id = last_id_seen
                return
        self._last_msg_id = last_id_seen

    async def send(self, text: str) -> int:
        msg = await self.client.send_message(self.bot, text)
        return msg.id

    async def wait_for_reply(self, after_id: int, timeout: float = 30) -> list:
        """Collect every NEW message from the bot after `after_id`.

        Two stop conditions:
          1. timeout reached (hard cap)
          2. no new message for `quiet_window` seconds AND last message looks
             "complete" (not a thinking indicator like '💭 ...')

        Thinking indicators that we DON'T treat as final:
            '💭', '⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏', 'Thinking'
        Telegram bots often EDIT a message to replace these with the real reply,
        so we also re-fetch the latest version of each tracked message.
        """
        deadline = time.time() + timeout
        quiet_window = 8.0   # was 3 — too short for streaming LLMs
        last_received = time.time()
        replies = []
        tracked_ids = set()

        THINKING_MARKERS = ("💭", "Thinking", "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

        def looks_thinking(text: str) -> bool:
            t = (text or "").strip()
            if not t:
                return True
            # Strict: only treat as "still thinking" if message is short AND
            # contains a marker. Long answers may also use 💭 as decoration.
            if len(t) < 50 and any(m in t for m in THINKING_MARKERS):
                return True
            return False

        prior_text = {}  # id → last seen text (for edit-detection)
        while time.time() < deadline:
            await asyncio.sleep(0.7)
            # Fetch ALL messages since after_id (not just new ones — also get
            # edits to existing tracked messages)
            current_msgs = []
            async for m in self.client.iter_messages(self.bot, min_id=after_id, limit=20):
                if m.sender_id != self.bot.id:
                    continue
                current_msgs.append(m)

            current_msgs.reverse()  # chronological

            # If we already have tracked ids, also explicitly refetch them by
            # id. iter_messages can return slightly-stale text after the bot
            # edits a message in place; get_messages(ids=...) hits the server
            # fresh and returns the current state.
            if tracked_ids:
                try:
                    refreshed = await self.client.get_messages(
                        self.bot, ids=list(tracked_ids)
                    )
                    refreshed_by_id = {r.id: r for r in refreshed if r is not None}
                    # Replace any current_msgs entries with refreshed versions
                    for i, m in enumerate(current_msgs):
                        if m.id in refreshed_by_id:
                            current_msgs[i] = refreshed_by_id[m.id]
                    # Also include any tracked ids not in current_msgs
                    seen_ids = {m.id for m in current_msgs}
                    for mid, m in refreshed_by_id.items():
                        if mid not in seen_ids:
                            current_msgs.append(m)
                    current_msgs.sort(key=lambda x: x.id)
                except Exception:
                    pass

            # Detect new messages OR edits to existing tracked messages
            saw_change = False
            new_replies_snapshot = []
            for m in current_msgs:
                txt = m.text or ""
                if m.id not in tracked_ids:
                    tracked_ids.add(m.id)
                    saw_change = True
                elif prior_text.get(m.id) != txt:
                    # Text edited in place — also counts as activity
                    saw_change = True
                prior_text[m.id] = txt
                new_replies_snapshot.append(m)

            if saw_change:
                last_received = time.time()
                replies = new_replies_snapshot
            elif new_replies_snapshot:
                # Refresh references even if nothing changed, so the latest
                # text is returned when we eventually break out.
                replies = new_replies_snapshot

            # Stop condition: have replies, none of them looks thinking,
            # and quiet_window has elapsed
            if replies:
                last_text = replies[-1].text or ""
                if not looks_thinking(last_text) and (time.time() - last_received) > quiet_window:
                    break

        return replies

    async def run_step(self, step: dict, idx: int, total: int) -> dict:
        send_text = step["send"]
        wait = step.get("wait", 15)
        expect_any = step.get("expect_any", [])

        print(f"\n[{idx:02d}/{total:02d}] → {send_text}")
        sent_id = await self.send(send_text)
        replies = await self.wait_for_reply(after_id=sent_id, timeout=wait)

        if not replies:
            print(f"        ⚠ NO REPLY")
            return {"step": idx, "sent": send_text, "verdict": "FAIL", "reason": "no reply", "replies": []}

        combined = "\n".join((m.text or "") for m in replies)
        snippet = combined[:300].replace("\n", " ⏎ ")
        print(f"        ← {snippet}")

        if expect_any and not any(e in combined for e in expect_any if e):
            return {"step": idx, "sent": send_text, "verdict": "FAIL",
                    "reason": f"none of {expect_any} found", "replies": [m.text for m in replies]}

        # Error pattern check
        ERRORS = ["PARSE FAILED", "Traceback", "parser returned None", "⛔", "⚠️ LLM 调用失败"]
        for e in ERRORS:
            if e in combined:
                return {"step": idx, "sent": send_text, "verdict": "FAIL",
                        "reason": f"error pattern: {e}", "replies": [m.text for m in replies]}

        return {"step": idx, "sent": send_text, "verdict": "PASS", "replies": [m.text for m in replies]}


# ── Main ──────────────────────────────────────────────────────────

PLANS = {
    "smoke": SMOKE_PLAN,
    "models": MODELS_PLAN,
    "modes": MODES_PLAN,
}


async def run_plan(plan_name: str):
    plan = PLANS[plan_name]
    print(f"=" * 60)
    print(f"  NeoMind Telegram Bot Tester — plan: {plan_name}")
    print(f"  Bot: {BOT_USERNAME}")
    print(f"  Steps: {len(plan)}")
    print(f"=" * 60)

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start(phone=PHONE)

    tester = TelegramBotTester(client, BOT_USERNAME)
    await tester.warmup()

    results = []
    for i, step in enumerate(plan, 1):
        r = await tester.run_step(step, i, len(plan))
        results.append(r)
        await asyncio.sleep(2)

    await client.disconnect()

    # Summary
    print(f"\n{'=' * 60}")
    pass_n = sum(1 for r in results if r["verdict"] == "PASS")
    fail_n = sum(1 for r in results if r["verdict"] == "FAIL")
    print(f"  Results: {pass_n} PASS / {fail_n} FAIL")
    print(f"{'=' * 60}")
    if fail_n:
        print("\nFailures:")
        for r in results:
            if r["verdict"] == "FAIL":
                print(f"  [{r['step']:02d}] {r['sent'][:50]}")
                print(f"       reason: {r['reason']}")
    return 0 if fail_n == 0 else 1


async def interactive():
    """Interactive REPL — type messages, see bot replies live."""
    print(f"=" * 60)
    print(f"  Interactive Telegram bot REPL")
    print(f"  Bot: {BOT_USERNAME}")
    print(f"  Type messages, see bot replies. Ctrl+D to quit.")
    print(f"=" * 60)

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start(phone=PHONE)

    tester = TelegramBotTester(client, BOT_USERNAME)
    await tester.warmup()

    loop = asyncio.get_event_loop()
    while True:
        try:
            text = await loop.run_in_executor(None, lambda: input("you> "))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text.strip():
            continue
        sent_id = await tester.send(text)
        replies = await tester.wait_for_reply(after_id=sent_id, timeout=60)
        if not replies:
            print("bot> (no reply, timeout)")
        for m in replies:
            txt = m.text or "(no text)"
            print(f"bot> {txt}")

    await client.disconnect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=list(PLANS), help="Run a scripted test plan")
    args = ap.parse_args()

    if args.plan:
        sys.exit(asyncio.run(run_plan(args.plan)))
    else:
        asyncio.run(interactive())


if __name__ == "__main__":
    main()
