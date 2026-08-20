"""Run NeoMind as an ACP agent over stdio.

The entry point a client spawns. DeepSeek Harness's `subagent-acp` provider is
configured with a `command` and `args`, launches that process per run, and
speaks ACP over its stdin/stdout — `spawn` → `initialize` → `session/new` →
prompt, then collects streamed `agent_message_chunk` text. Zed and any other
ACP client work the same way.

Thin on purpose. `acp_server.py` is the agent and `acp_translate.py` is the
mapping; the SDK owns the JSON-RPC framing. What is left here is the one thing
neither can do: **keep stdout clean**.

That is the whole risk of a stdio protocol. Stdout *is* the wire, so a stray
`print`, a logging handler defaulting to `sys.stdout`, or a library banner
lands in the middle of a JSON-RPC frame and the client sees a parse error with
no clue where the text came from. Logging is pinned to stderr before the agent
is built, not after — an import that prints during construction is already too
late.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional


def _silence_stdout() -> None:
    """Send every log to stderr and leave stdout to the protocol.

    Done before anything else imports: `logging.basicConfig` is a no-op once a
    handler exists, so a module that configured logging at import time would
    otherwise keep its stdout handler and corrupt the stream.
    """
    import os

    level = logging.DEBUG if os.getenv("NEOMIND_ACP_DEBUG") else logging.WARNING
    root = logging.getLogger()
    for handler in list(root.handlers):
        stream = getattr(handler, "stream", None)
        if stream is sys.stdout:
            root.removeHandler(handler)
    if not root.handlers:
        logging.basicConfig(
            stream=sys.stderr,
            level=level,
            format="%(levelname)s %(name)s: %(message)s",
        )
    else:
        root.setLevel(level)
        for handler in root.handlers:
            if getattr(handler, "stream", None) is sys.stdout:
                handler.setStream(sys.stderr)  # type: ignore[attr-defined]


async def serve(default_mode: str = "coding") -> None:
    """Serve one client over stdio until it closes the connection."""
    _silence_stdout()

    import acp

    from agent.integration.acp_server import NeoMindACPAgent

    agent = NeoMindACPAgent(default_mode=default_mode)
    await acp.run_agent(agent)


def main(argv: Optional[list] = None) -> int:
    """`python -m agent.integration.acp_stdio [--mode coding]`.

    The command a client's config points at. Kept runnable as a module rather
    than only as a console script so it works from a checkout with no install
    step — which is what a `command: python` + `args: [-m, ...]` config needs.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="neomind-acp",
        description="Serve NeoMind over the Agent Client Protocol on stdio.",
    )
    parser.add_argument(
        "--mode", default="coding", choices=("chat", "coding", "fin"),
        help="Personality a new session starts in.",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(serve(default_mode=args.mode))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # The client closed stdin. That is how `subagent-acp` asks a child to
        # quit — it closes stdin and waits out a grace period before SIGTERM —
        # so it is an ordinary shutdown, not a failure.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
