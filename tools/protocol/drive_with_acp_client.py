"""Spawn NeoMind's ACP entry point and drive it as a real client would.

Mirrors what DeepSeek Harness's `subagent-acp` does: spawn the configured
command, speak ACP over its stdio, initialize, open a session, prompt, collect
streamed agent_message_chunk text, then close stdin to shut it down.
"""
import asyncio, os, sys

import acp
from acp import schema


class Recording(acp.Client):
    def __init__(self):
        self.chunks, self.thoughts, self.tools, self.permissions = [], [], [], []

    async def session_update(self, session_id, update, **kw):
        name = type(update).__name__
        if name == "AgentMessageChunk":
            self.chunks.append(update.content.text)
        elif name == "AgentThoughtChunk":
            self.thoughts.append(update.content.text)
        elif name in ("ToolCallStart", "ToolCallProgress"):
            self.tools.append(f"{name}:{getattr(update, 'status', '?')}")

    async def request_permission(self, session_id, tool_call, options, **kw):
        self.permissions.append(tool_call.title)
        return schema.RequestPermissionResponse(
            outcome=schema.DeniedOutcome(outcome="cancelled")
        )


async def main():
    repo = os.path.dirname(os.path.abspath(__file__))
    proc = await asyncio.create_subprocess_exec(
        sys.argv[1], "-m", "agent.integration.acp_stdio", "--mode", "chat",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=sys.argv[2],
    )
    client = Recording()
    conn = acp.connect_to_agent(client, proc.stdin, proc.stdout)

    init = await conn.initialize(protocol_version=1)
    print("  initialize   → protocol", init.protocol_version)

    ns = await conn.new_session(cwd=sys.argv[2])
    print("  new_session  →", ns.session_id)

    resp = await conn.prompt(
        session_id=ns.session_id,
        prompt=[schema.TextContentBlock(type="text", text="Reply with exactly: ACP_STDIO_OK")],
    )
    print("  prompt       → stop_reason:", resp.stop_reason)
    print("  streamed     →", repr("".join(client.chunks))[:90])
    print("  usage        →", resp.usage.total_tokens if resp.usage else None)

    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
        print("  shutdown     → exit", proc.returncode)
    except asyncio.TimeoutError:
        proc.kill(); print("  shutdown     → 超时被杀")
    err = (await proc.stderr.read())[:400].decode(errors="replace").strip()
    if err:
        print("  stderr       →", err[:200])

asyncio.run(main())
