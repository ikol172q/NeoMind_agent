"""Manual reflect CLI for C1 evolve loop.

Reads last N episodes captured by ``episode_capture.record_episode``,
sends them to a cheap LLM, prints suggestions to stdout. **Never
auto-injects** into prompts — user copies what they want and edits the
yaml themselves.

Usage:
    .venv/bin/python -m agent.evolution.reflect_cli --last 30
    .venv/bin/python -m agent.evolution.reflect_cli --last 50 --mode fin

Exit non-zero only on hard errors (no episodes / LLM failure). Empty
output (e.g. "no patterns detected") is exit 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable

import httpx

from agent.evolution.episode_capture import iter_recent_episodes

REFLECT_MODEL = os.getenv("NEOMIND_REFLECT_MODEL", "deepseek-v4-flash")
LLM_BASE = os.getenv("LLM_ROUTER_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_KEY = os.getenv("LLM_ROUTER_API_KEY", "dummy")

REFLECT_PROMPT = """You are a self-reflection critic for the NeoMind agent.
You will see {n} recent episodes from mode `{mode}`. Each episode is one
turn: a user query, the agent's reply, the tool calls it made, and
signals (latency / token usage / finish reason).

Your job: find **recurring patterns** that suggest the agent's prompt or
behavior could be improved. Be concrete and selective — surface only the
top 3-5 most actionable patterns, not every quirk.

For each pattern, output:
- **Pattern**: 1-line description
- **Evidence**: episode req_ids that exhibit it (2-3 example req_ids max)
- **Suggested change**: specific edit to base.yaml/<mode>.yaml prompt or
  a new GATE check, in 1-2 sentences. Skip "improve X generally" — be
  concrete.

If no clear patterns emerge (small sample, healthy agent, etc.) say so
plainly. Don't invent patterns to fill space.

Output plain markdown, no preamble, no closing summary.

═══ EPISODES ═══

{episodes}
"""


def format_episode(rec: dict) -> str:
    sig = rec.get("signals") or {}
    tools = rec.get("tool_calls") or []
    tool_str = ", ".join(t.get("name", "?") for t in tools) if tools else "(none)"
    return (
        f"--- req_id={rec.get('req_id') or '?'} ts={rec.get('ts','')} ---\n"
        f"  query: {rec.get('query','')[:300]}\n"
        f"  reply: {rec.get('reply','')[:600]}\n"
        f"  tools: {tool_str}\n"
        f"  signals: dur={sig.get('duration_ms')}ms "
        f"prompt_tok={sig.get('prompt_tokens')} "
        f"finish={sig.get('finish_reason')} "
        f"compacted={sig.get('compacted')}"
    )


def call_llm(prompt: str) -> str:
    resp = httpx.post(
        f"{LLM_BASE.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
        json={
            "model": REFLECT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2500,
        },
        timeout=httpx.Timeout(120.0, read=120.0),
    )
    resp.raise_for_status()
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reflect_cli")
    p.add_argument("--last", type=int, default=30, help="N most-recent episodes")
    p.add_argument("--mode", default=None, help="filter by mode (fin/chat/coding)")
    p.add_argument("--days", type=int, default=14, help="walk back this many daily files")
    p.add_argument("--dry-run", action="store_true",
                   help="print formatted episodes without calling LLM")
    args = p.parse_args(argv)

    episodes = list(iter_recent_episodes(
        limit=args.last, mode_filter=args.mode, days_back=args.days,
    ))
    if not episodes:
        print("No episodes found. Use the agent for a few turns first.", file=sys.stderr)
        return 1

    formatted = "\n\n".join(format_episode(r) for r in episodes)
    mode_label = args.mode or "all modes"
    full_prompt = REFLECT_PROMPT.format(
        n=len(episodes), mode=mode_label, episodes=formatted,
    )

    if args.dry_run:
        print(full_prompt)
        return 0

    print(f"# Reflecting on {len(episodes)} episodes (mode={mode_label})\n", file=sys.stderr)
    try:
        out = call_llm(full_prompt)
    except Exception as exc:
        print(f"LLM call failed: {exc}", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
