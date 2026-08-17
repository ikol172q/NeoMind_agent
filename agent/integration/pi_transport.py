"""Carry pi's protocol over a socket.

`pi_server.py` takes decoded messages and returns messages; this is the part
that puts them on a wire. Split that way on purpose: the command surface is
testable without a socket, and the socket is testable without a model.

pi's own client (`@earendil-works/pi-client`) is transport-neutral — it asks
for a `ByteTransport` with `send` and `close`, and hands back `onData`,
`onClose`, `onError`. So anything that moves bytes in order will do, and a TCP
socket on loopback is the simplest thing that lets pi's real client drive this
server rather than a client we wrote ourselves to agree with us.

One connection, one client. pi's `attach`/`detach` model means several clients
can watch one *session*, which is a different thing from several clients
sharing one socket, and this serves each connection independently.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from agent.integration.pi_framing import (
    DEFAULT_MAX_FRAME_LENGTH,
    FrameDecoder,
    FrameError,
    encode_message,
)

logger = logging.getLogger(__name__)

#: Loopback only. This speaks an unauthenticated protocol — pi's own hello
#: carries no credential — so binding it to anything reachable would expose an
#: agent that can read files and run commands to whoever connects.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8791

#: pi's CLI accepts **only** `unix:///path` for `--connect`; its
#: `parseTransportAddress` rejects every other scheme outright. So a TCP
#: listener is reachable from its client *library* but not from `pi` itself,
#: which is the difference between "the protocol works" and "the user can use
#: it". A Unix socket is also the safer default: filesystem permissions gate
#: it, where a loopback port is open to every process on the machine.
DEFAULT_SOCKET_PATH = "/tmp/neomind-pi.sock"


class PiTransportServer:
    """Serve `PiProtocolServer` over TCP.

    `server_factory` is called once per connection rather than shared: pi's
    session ids are minted per server instance, and two clients handed the same
    counter would collide on `neomind-1`.
    """

    def __init__(
        self,
        server_factory: Callable[[], Any],
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        socket_path: Optional[str] = None,
        max_frame_length: int = DEFAULT_MAX_FRAME_LENGTH,
    ) -> None:
        self.server_factory = server_factory
        self.host = host
        self.port = port
        #: When set, listen on a Unix socket instead of TCP. Required for
        #: `pi --connect`, which accepts no other scheme.
        self.socket_path = socket_path
        self.max_frame_length = max_frame_length
        self._server: Optional[asyncio.AbstractServer] = None

    @property
    def sockets(self):
        return self._server.sockets if self._server else ()

    @property
    def bound_port(self) -> int:
        """The port actually bound, which differs from `port` when it was 0.

        Tests bind port 0 so they cannot collide with a real server or with
        each other; without this they would have no way to find out where.
        """
        socks = self.sockets
        return socks[0].getsockname()[1] if socks else self.port

    async def start(self) -> "PiTransportServer":
        if self.socket_path:
            # A stale socket file from a crashed run makes bind fail with
            # EADDRINUSE even though nothing is listening.
            import os

            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
            self._server = await asyncio.start_unix_server(
                self._handle_client, path=self.socket_path
            )
            os.chmod(self.socket_path, 0o600)
        else:
            self._server = await asyncio.start_server(
                self._handle_client, self.host, self.port
            )
        return self

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        try:
            await self._server.wait_closed()
        finally:
            self._server = None
            if self.socket_path:
                import os

                try:
                    os.unlink(self.socket_path)
                except FileNotFoundError:
                    pass

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    # ── one connection ────────────────────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        protocol = self.server_factory()
        decoder = FrameDecoder(max_frame_length=self.max_frame_length)
        peer = writer.get_extra_info("peername")
        logger.info("pi client connected: %s", peer)

        async def send(message: Any) -> None:
            writer.write(encode_message(message, max_frame_length=self.max_frame_length))
            await writer.drain()

        try:
            while True:
                chunk = await reader.read(64 * 1024)
                if not chunk:
                    break
                try:
                    frames = decoder.feed(chunk)
                except FrameError as exc:
                    # An over-long announcement is refused before allocating,
                    # and the connection ends: a peer that sends one is either
                    # broken or hostile, and there is no useful way to resync.
                    logger.warning("pi framing error from %s: %s", peer, exc)
                    break

                for frame in frames:
                    await self._dispatch(protocol, frame, send)
        except (ConnectionResetError, BrokenPipeError):
            logger.info("pi client %s disconnected abruptly", peer)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("pi client closed: %s", peer)

    async def _dispatch(self, protocol: Any, frame: bytes, send) -> None:
        import cbor2

        try:
            message = cbor2.loads(frame)
        except Exception as exc:
            logger.warning("undecodable pi frame: %s", exc)
            return

        for reply in protocol.handle(message):
            await send(reply)

        # A prompt is acknowledged synchronously and then streamed. Driving the
        # turn here rather than inside `handle()` keeps the command surface
        # free of the event loop, and lets the acknowledgement reach the client
        # before the first token.
        request = (message or {}).get("request") or {}
        if request.get("command") == "prompt":
            session_id = str(request.get("sessionId", ""))
            text = str(request.get("text", ""))
            if session_id and text.strip():
                asyncio.ensure_future(self._run_turn(protocol, session_id, text, send))

    @staticmethod
    async def _run_turn(protocol: Any, session_id: str, text: str, send) -> None:
        try:
            async for message in protocol.run_turn(session_id, text):
                await send(message)
        except Exception:
            logger.exception("pi turn failed for session %s", session_id)


async def serve(
    server_factory: Callable[[], Any],
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    socket_path: Optional[str] = None,
) -> None:
    """Run until cancelled. The entry point a `neomind pi-serve` would call.

    Pass `socket_path` to be reachable from `pi --connect unix:///...`; TCP is
    for tests and for anything driving `PiClient` directly.
    """
    await PiTransportServer(
        server_factory, host=host, port=port, socket_path=socket_path,
    ).serve_forever()
