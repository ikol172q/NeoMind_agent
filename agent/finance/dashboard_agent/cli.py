"""CLI REPL test harness for the dashboard agent.

Usage:
    python -m agent.finance.dashboard_agent.cli

Streams every tool call inline so you can see what the agent is
thinking. Persists to agent_chat_history under chat_id='cli:<USER>'.
"""
from __future__ import annotations

import asyncio
import os
import sys

from agent.finance.dashboard_agent.agent import answer


def _banner() -> None:
    print()
    print("─" * 60)
    print(" NeoMind dashboard agent · CLI REPL")
    print("─" * 60)
    print(" 输 /reset 清空 chat, /quit 退出, 否则你说啥它就答啥")
    print(f" model: {os.getenv('DASHBOARD_AGENT_MODEL', 'deepseek-v4-flash')}")
    print(f" data:  {os.getenv('NEOMIND_FIN_DASHBOARD_URL', 'http://127.0.0.1:8001')}")
    print("─" * 60)
    print()


async def _repl() -> None:
    chat_id = f"cli:{os.getenv('USER', 'anon')}"
    _banner()
    while True:
        try:
            user_msg = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user_msg:
            continue
        if user_msg == "/quit":
            return
        if user_msg == "/reset":
            from agent.finance.dashboard_agent.agent import _agent_connect
            with _agent_connect() as conn:
                conn.execute(
                    "DELETE FROM agent_chat_history WHERE chat_id = ?",
                    (chat_id,),
                )
            print("(chat 已清空)")
            continue

        reply = await answer(chat_id, user_msg)
        print()
        print(f"🤖 {reply.text}")
        if reply.proposals:
            print()
            print("─ 可一键执行的行动 (telegram 里是 inline button) ─")
            for i, p in enumerate(reply.proposals, 1):
                print(f"  [{i}] {p.label}   (kind={p.kind} args={p.args})")
        print()


def main() -> int:
    try:
        asyncio.run(_repl())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
