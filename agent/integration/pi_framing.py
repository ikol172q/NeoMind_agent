"""Length-prefixed CBOR framing, as pi speaks it.

Phase 7, second adapter. pi does not speak ACP — a fresh clone on 2026-08-16
contains zero references to it — so being drivable from pi's TUI means speaking
its own protocol: a 4-byte big-endian unsigned length followed by that many
bytes of CBOR.

pi implements CBOR itself rather than using a library, which raised the
question of whether it is a dialect. It is not: its encoder makes no canonical
or tag choices, its decoder covers all eight major types, and bytes produced by
it parse exactly under a decoder written only from RFC 8949 — verified on a
104-byte sample carrying CJK text, integers, booleans, null, arrays and nested
maps, with every byte consumed. So `cbor2` is enough on this side and there is
no codec to hand-write.

This module is only the frame. Nothing here knows what a message means, which
is what lets a malformed-length test run without a session, a socket or pi.
"""

from __future__ import annotations

import struct
from typing import Any, Iterator, List, Optional, Tuple

#: Bytes of length prefix, unsigned big-endian. pi's `framing.ts`.
HEADER_LENGTH = 4

#: pi's own default ceiling for one payload (16 MiB). Enforced on both sides:
#: a peer that announces more than this is either broken or hostile, and
#: allocating first to find out is the bug.
DEFAULT_MAX_FRAME_LENGTH = 16 * 1024 * 1024

MAX_UINT32 = 0xFFFF_FFFF


class FrameError(Exception):
    """A frame that cannot be trusted: over-long, or a truncated header."""


def encode_frame(payload: bytes, *, max_frame_length: int = DEFAULT_MAX_FRAME_LENGTH) -> bytes:
    """Prefix `payload` with its unsigned 32-bit big-endian length."""
    if len(payload) > max_frame_length:
        raise FrameError(
            f"payload is {len(payload)} bytes, over the {max_frame_length} limit"
        )
    if len(payload) > MAX_UINT32:
        raise FrameError("payload length does not fit in a uint32")
    return struct.pack(">I", len(payload)) + payload


def encode_message(message: Any, **kw: Any) -> bytes:
    """One protocol message → one framed CBOR blob."""
    import cbor2

    return encode_frame(cbor2.dumps(message), **kw)


class FrameDecoder:
    """Accumulates bytes and yields complete frames.

    Stream-oriented on purpose: a socket hands over arbitrary slices, and the
    common bug in a hand-rolled reader is assuming one read is one frame. Feed
    it whatever arrives; it emits only what is complete.
    """

    def __init__(self, *, max_frame_length: int = DEFAULT_MAX_FRAME_LENGTH) -> None:
        if not (0 <= max_frame_length <= MAX_UINT32):
            raise ValueError("max_frame_length must fit in a uint32")
        self.max_frame_length = max_frame_length
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> List[bytes]:
        """Add bytes, return every frame that is now complete."""
        self._buffer.extend(chunk)
        return list(self._drain())

    def _drain(self) -> Iterator[bytes]:
        while True:
            if len(self._buffer) < HEADER_LENGTH:
                return
            (length,) = struct.unpack(">I", self._buffer[:HEADER_LENGTH])
            if length > self.max_frame_length:
                # Refused before allocating. A 4-gigabyte announcement costs
                # nothing to send and everything to believe.
                raise FrameError(
                    f"frame announces {length} bytes, over the "
                    f"{self.max_frame_length} limit"
                )
            end = HEADER_LENGTH + length
            if len(self._buffer) < end:
                return
            frame = bytes(self._buffer[HEADER_LENGTH:end])
            del self._buffer[:end]
            yield frame

    @property
    def pending(self) -> int:
        """Bytes held back waiting for the rest of a frame."""
        return len(self._buffer)


def decode_messages(decoder: FrameDecoder, chunk: bytes) -> List[Any]:
    """Feed bytes, get decoded CBOR messages."""
    import cbor2

    return [cbor2.loads(frame) for frame in decoder.feed(chunk)]
