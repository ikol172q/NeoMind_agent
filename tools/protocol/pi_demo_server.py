"""Run NeoMind's pi server on a port, with a scripted turn (no provider)."""
import asyncio, sys
# Run from the repo root, or with the repo on PYTHONPATH.
from agent.integration.pi_server import PiProtocolServer
from agent.integration.pi_transport import PiTransportServer
from agent.runtime.events import TextDelta, ThinkingDelta, ToolProposed, ToolFinished, TurnFinished

def ev(cls, **kw):
    return cls(session_id="s", turn_id="t1", sequence=0, **kw)

class ScriptedSession:
    def run_turn(self, text):
        async def gen():
            yield ev(ThinkingDelta, text="considering")
            for word in ("你好 ", "from ", "NeoMind"):
                await asyncio.sleep(0.05)
                yield ev(TextDelta, text=word)
            yield ev(ToolProposed, call_id="c1", tool_name="Read", preview="a.txt")
            yield ev(ToolFinished, call_id="c1", tool_name="Read", success=True, preview="data")
            yield ev(TurnFinished, response="你好 from NeoMind")
        return gen()
    async def cancel(self, turn_id): pass

def make():
    return PiProtocolServer(server_id="neomind", session_factory=lambda s: ScriptedSession())

async def main():
    srv = await PiTransportServer(make, port=int(sys.argv[1])).start()
    print(f"listening on {srv.bound_port}", flush=True)
    await asyncio.Event().wait()

asyncio.run(main())
